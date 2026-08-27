from __future__ import annotations

import numpy as np
import pandas as pd

from brain.backtesting import BacktestConfig, run_prediction_backtest
from brain.backtesting import run_confidence_threshold_sweep, run_walk_forward_model_backtest
from brain.candidate_matrix import run_candidate_matrix
from brain.datasets import build_dataset_from_materialized, build_supervised_dataset
from brain.feedback import analyze_prediction_feedback
from brain.features import FEATURE_COLUMNS, FEATURE_COLUMNS_TECHNICAL_V2, build_features, feature_columns_for_set
from brain.inference import PredictionPolicy, predict_actions
from brain.inference_job import (
    is_promoted_model_run,
    load_promoted_model_runs,
    min_confidence_for_model_run,
    run_latest_inference_job,
    target_ticker_for_model_run,
)
from brain.labeling import BUY, HOLD, SELL, fixed_horizon_labels, triple_barrier_labels
from brain.models import available_model_names, create_model, walk_forward_evaluate
from brain.promotion import build_promoted_training_frame, select_candidate
from brain.risk import RiskPolicy, apply_risk_policy
from brain.retraining_job import RetrainingJobConfig, compare_candidate_to_incumbent, run_retraining_job
from brain.scoped_evaluation import AssetDataset, run_scoped_walk_forward_backtest
from brain.selection import PromotionCriteria, evaluate_promotion, rank_candidate_summaries, score_candidate


def make_prices(rows: int = 120) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=rows, freq="D", tz="UTC")
    wave = np.sin(np.arange(rows) / 3) * 2.5
    trend = np.arange(rows) * 0.03
    close = 100 + wave + trend
    open_ = close + np.cos(np.arange(rows)) * 0.2
    high = np.maximum(open_, close) + 1.0
    low = np.minimum(open_, close) - 1.0
    volume = 1_000_000 + (np.arange(rows) % 9) * 10_000

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def test_features_do_not_change_when_future_price_changes() -> None:
    prices = make_prices(80)
    changed = prices.copy()
    changed.loc[79, "close"] = changed.loc[79, "close"] * 10
    changed.loc[79, "high"] = changed.loc[79, "high"] * 10

    original_features = build_features(prices).loc[:78, FEATURE_COLUMNS]
    changed_features = build_features(changed).loc[:78, FEATURE_COLUMNS]

    pd.testing.assert_frame_equal(original_features, changed_features)


def test_technical_v2_features_do_not_change_when_future_price_changes() -> None:
    prices = make_prices(100)
    changed = prices.copy()
    changed.loc[99, "close"] = changed.loc[99, "close"] * 10
    changed.loc[99, "high"] = changed.loc[99, "high"] * 10
    columns = feature_columns_for_set("technical_v2")

    original_features = build_features(prices).loc[:98, columns]
    changed_features = build_features(changed).loc[:98, columns]

    pd.testing.assert_frame_equal(original_features, changed_features)


def test_fixed_horizon_labels_create_expected_classes() -> None:
    labels = fixed_horizon_labels(
        make_prices(80),
        horizon=3,
        buy_threshold=0.005,
        sell_threshold=-0.005,
    )

    assert {BUY, SELL, HOLD}.intersection(set(labels["label"]))
    assert labels["future_return"].notna().sum() == 77
    assert labels["label"].isna().sum() == 3


def test_triple_barrier_labels_include_exit_metadata() -> None:
    labels = triple_barrier_labels(
        make_prices(60),
        horizon=4,
        profit_take=0.01,
        stop_loss=0.01,
    )

    assert {"label", "outcome_return", "label_exit_timestamp"}.issubset(labels.columns)
    assert set(labels["label"].dropna()).issubset({BUY, SELL, HOLD})
    assert labels["label"].isna().sum() == 4


def test_build_supervised_dataset_has_training_columns() -> None:
    dataset = build_supervised_dataset(
        make_prices(100),
        label_method="fixed_horizon",
        horizon=3,
        buy_threshold=0.005,
        sell_threshold=-0.005,
    )

    assert set(FEATURE_COLUMNS + ["label"]).issubset(dataset.columns)
    assert dataset[FEATURE_COLUMNS + ["label"]].isna().sum().sum() == 0


def test_build_supervised_dataset_supports_technical_v2_columns() -> None:
    dataset = build_supervised_dataset(
        make_prices(120),
        label_method="fixed_horizon",
        horizon=3,
        buy_threshold=0.005,
        sell_threshold=-0.005,
        feature_set="technical_v2",
    )

    assert set(FEATURE_COLUMNS_TECHNICAL_V2 + ["label"]).issubset(dataset.columns)
    assert dataset[FEATURE_COLUMNS_TECHNICAL_V2 + ["label"]].isna().sum().sum() == 0


def test_walk_forward_evaluate_returns_fold_metrics() -> None:
    dataset = build_supervised_dataset(
        make_prices(140),
        label_method="fixed_horizon",
        horizon=3,
        buy_threshold=0.003,
        sell_threshold=-0.003,
    )

    result = walk_forward_evaluate(dataset, n_splits=3)

    assert len(result.fold_metrics) == 3
    assert result.summary["rows"] == len(dataset)
    assert 0 <= result.summary["mean_f1_macro"] <= 1


def test_model_registry_exposes_comparable_candidates() -> None:
    names = available_model_names()

    assert "baseline_hist_gradient_boosting" in names
    assert "logistic_regression" in names
    assert "random_forest" in names
    assert create_model("extra_trees").named_steps["classifier"].__class__.__name__ == "ExtraTreesClassifier"


def test_walk_forward_evaluate_accepts_registered_model_name() -> None:
    dataset = build_supervised_dataset(
        make_prices(140),
        label_method="fixed_horizon",
        horizon=3,
        buy_threshold=0.003,
        sell_threshold=-0.003,
    )

    result = walk_forward_evaluate(dataset, n_splits=3, model_name="logistic_regression")

    assert result.summary["model_name"] == "logistic_regression"
    assert result.summary["estimator"] == "LogisticRegression"


def test_build_dataset_from_materialized_expands_feature_json() -> None:
    feature_rows = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
            "features": [
                {column: 0.1 for column in FEATURE_COLUMNS},
                {column: 0.2 for column in FEATURE_COLUMNS},
            ],
        }
    )
    label_rows = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
            "label": ["BUY", "HOLD"],
            "outcome_return": [0.03, 0.0],
        }
    )

    dataset = build_dataset_from_materialized(feature_rows, label_rows)

    assert list(dataset[FEATURE_COLUMNS].iloc[0]) == [0.1] * len(FEATURE_COLUMNS)
    assert dataset["label"].tolist() == ["BUY", "HOLD"]


class FakeClassifier:
    classes_ = ["BUY", "HOLD", "SELL"]

    def predict_proba(self, X):
        return [
            [0.7, 0.2, 0.1],
            [0.4, 0.45, 0.15],
        ]


def test_predict_actions_uses_confidence_threshold() -> None:
    feature_frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
            **{column: [0.1, 0.2] for column in FEATURE_COLUMNS},
        }
    )

    predictions = predict_actions(
        FakeClassifier(),
        feature_frame,
        policy=PredictionPolicy(min_confidence=0.6),
    )

    assert predictions["action"].tolist() == ["BUY", "HOLD"]
    assert predictions.loc[0, "confidence"] == 0.7
    assert predictions.loc[1, "metadata"]["raw_action"] == "HOLD"


def test_analyze_prediction_feedback_summarizes_errors_and_returns() -> None:
    feedback = pd.DataFrame(
        {
            "predicted_action": ["BUY", "BUY", "SELL", "HOLD"],
            "actual_label": ["BUY", "SELL", "SELL", "HOLD"],
            "is_correct": [True, False, True, True],
            "confidence": [0.8, 0.6, 0.7, 0.5],
            "outcome_return": [0.03, -0.02, 0.01, 0.0],
        }
    )

    report = analyze_prediction_feedback(feedback)

    assert report.summary["evaluated_predictions"] == 4
    assert report.summary["accuracy"] == 0.75
    assert np.isclose(report.summary["total_outcome_return"], 0.02)
    assert {row["predicted_action"] for row in report.by_action} == {"BUY", "SELL", "HOLD"}
    assert report.by_confidence_bucket


def test_analyze_prediction_feedback_handles_empty_data() -> None:
    report = analyze_prediction_feedback(pd.DataFrame())

    assert report.summary["evaluated_predictions"] == 0
    assert report.summary["accuracy"] is None


def test_run_prediction_backtest_applies_costs_and_equity_curve() -> None:
    feedback = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"),
            "predicted_action": ["BUY", "SELL", "HOLD"],
            "actual_label": ["BUY", "SELL", "HOLD"],
            "confidence": [0.8, 0.7, 0.6],
            "outcome_return": [0.03, -0.02, 0.01],
            "model_name": ["baseline", "baseline", "baseline"],
            "model_version": ["v1", "v1", "v1"],
        }
    )

    result = run_prediction_backtest(
        feedback,
        BacktestConfig(initial_capital=1000, fee_bps=5, slippage_bps=5),
    )

    assert result.metrics["trade_count"] == 3
    assert result.metrics["active_trade_count"] == 2
    assert result.metrics["final_equity"] > 1000
    assert np.isclose(result.trades.loc[0, "net_return"], 0.028)
    assert result.trades.loc[1, "gross_return"] == 0.02


def test_run_prediction_backtest_handles_empty_feedback() -> None:
    result = run_prediction_backtest(pd.DataFrame(), BacktestConfig(initial_capital=5000))

    assert result.metrics["final_equity"] == 5000
    assert result.metrics["trade_count"] == 0
    assert result.trades.empty


def test_run_walk_forward_model_backtest_compares_baselines() -> None:
    dataset = build_supervised_dataset(
        make_prices(180),
        label_method="triple_barrier",
        horizon=3,
        profit_take=0.01,
        stop_loss=0.01,
    )

    result = run_walk_forward_model_backtest(
        dataset,
        n_splits=3,
        model_name="random_forest",
        config=BacktestConfig(initial_capital=1000, fee_bps=5, slippage_bps=5),
    )

    assert result.summary["evaluated_rows"] == len(result.predictions)
    assert result.summary["model_name"] == "random_forest"
    assert result.summary["embargo_rows"] == 0
    assert result.summary["trade_stride"] == 1
    assert len(result.folds) == 3
    assert "model" in result.summary
    assert {"no_trade", "always_buy", "always_sell"}.issubset(result.baselines)
    assert result.model_backtest.metrics["trade_count"] == len(result.predictions)
    assert result.baselines["no_trade"].metrics["final_equity"] == 1000


def test_run_walk_forward_model_backtest_supports_embargo_and_trade_stride() -> None:
    dataset = build_supervised_dataset(
        make_prices(180),
        label_method="triple_barrier",
        horizon=3,
        profit_take=0.01,
        stop_loss=0.01,
    )

    result = run_walk_forward_model_backtest(dataset, n_splits=3, embargo_rows=3, trade_stride=3)

    assert result.summary["embargo_rows"] == 3
    assert result.summary["trade_stride"] == 3
    assert result.summary["evaluated_rows"] < len(dataset)


def test_run_confidence_threshold_sweep_sorts_by_return() -> None:
    dataset = build_supervised_dataset(
        make_prices(180),
        label_method="triple_barrier",
        horizon=3,
        profit_take=0.01,
        stop_loss=0.01,
    )

    rows = run_confidence_threshold_sweep(
        dataset,
        thresholds=[0.55, 0.70],
        n_splits=3,
        trade_stride=3,
    )

    assert [row["min_confidence"] for row in rows] == [
        row["min_confidence"] for row in sorted(rows, key=lambda item: item["total_return"], reverse=True)
    ]
    assert {"total_return", "max_drawdown", "active_trade_count"}.issubset(rows[0])


def test_run_scoped_walk_forward_backtest_compares_training_scopes() -> None:
    target = AssetDataset(
        asset_id="btc-id",
        ticker="BTC-USD",
        asset_class="crypto",
        dataset=build_supervised_dataset(
            make_prices(180),
            label_method="triple_barrier",
            horizon=3,
            profit_take=0.01,
            stop_loss=0.01,
        ).assign(asset_id="btc-id", ticker="BTC-USD", asset_class="crypto"),
    )
    peer_crypto = AssetDataset(
        asset_id="eth-id",
        ticker="ETH-USD",
        asset_class="crypto",
        dataset=build_supervised_dataset(
            make_prices(180).assign(close=lambda frame: frame["close"] * 0.8),
            label_method="triple_barrier",
            horizon=3,
            profit_take=0.01,
            stop_loss=0.01,
        ).assign(asset_id="eth-id", ticker="ETH-USD", asset_class="crypto"),
    )
    stock = AssetDataset(
        asset_id="aapl-id",
        ticker="AAPL",
        asset_class="stock",
        dataset=build_supervised_dataset(
            make_prices(180).assign(close=lambda frame: frame["close"] * 1.2),
            label_method="triple_barrier",
            horizon=3,
            profit_take=0.01,
            stop_loss=0.01,
        ).assign(asset_id="aapl-id", ticker="AAPL", asset_class="stock"),
    )

    local = run_scoped_walk_forward_backtest(
        [target, peer_crypto, stock],
        target_ticker="BTC-USD",
        scope="local",
        n_splits=3,
        trade_stride=3,
        model_name="logistic_regression",
    )
    asset_class = run_scoped_walk_forward_backtest(
        [target, peer_crypto, stock],
        target_ticker="BTC-USD",
        scope="asset_class",
        n_splits=3,
        trade_stride=3,
        model_name="logistic_regression",
    )
    global_result = run_scoped_walk_forward_backtest(
        [target, peer_crypto, stock],
        target_ticker="BTC-USD",
        scope="global",
        n_splits=3,
        trade_stride=3,
        model_name="logistic_regression",
    )

    assert local.summary["participating_asset_count"] == 1
    assert asset_class.summary["participating_asset_count"] == 2
    assert global_result.summary["participating_asset_count"] == 3
    assert asset_class.folds[0]["train_rows"] > asset_class.folds[0]["target_train_rows"]
    assert global_result.summary["evaluated_rows"] == local.summary["evaluated_rows"]
    assert set(global_result.predictions["scope"]) == {"global"}


def test_candidate_selection_scores_return_after_risk() -> None:
    strong = {
        "scope": "global",
        "model_name": "extra_trees",
        "min_confidence": 0.65,
        "participating_asset_count": 3,
        "model": {
            "total_return": 0.30,
            "max_drawdown": -0.08,
            "profit_factor": 1.8,
            "active_trade_count": 30,
            "win_rate": 0.55,
            "exposure": 0.40,
        },
        "baselines": {"no_trade": {"total_return": 0.0}},
    }
    fragile = {
        "scope": "local",
        "model_name": "extra_trees",
        "min_confidence": 0.65,
        "participating_asset_count": 1,
        "model": {
            "total_return": 0.32,
            "max_drawdown": -0.22,
            "profit_factor": 1.1,
            "active_trade_count": 30,
            "win_rate": 0.52,
            "exposure": 0.40,
        },
        "baselines": {"no_trade": {"total_return": 0.0}},
    }

    assert score_candidate(strong) > score_candidate(fragile)

    ranking = rank_candidate_summaries([fragile, strong])

    assert ranking[0]["scope"] == "global"
    assert ranking[0]["promotion"]["status"] == "pass"
    assert ranking[1]["promotion"]["status"] == "pass"


def test_candidate_selection_fails_when_sample_is_too_small() -> None:
    summary = {
        "scope": "local",
        "model_name": "extra_trees",
        "min_confidence": 0.75,
        "participating_asset_count": 1,
        "model": {
            "total_return": 0.20,
            "max_drawdown": -0.03,
            "profit_factor": 2.0,
            "active_trade_count": 5,
            "win_rate": 0.80,
            "exposure": 0.10,
        },
        "baselines": {"no_trade": {"total_return": 0.0}},
    }

    promotion = evaluate_promotion(summary, PromotionCriteria(min_active_trades=20))

    assert promotion["status"] == "fail"
    assert "active_trades_below_20" in promotion["failed"]


def test_candidate_selection_allows_positive_no_loss_candidate() -> None:
    summary = {
        "scope": "local",
        "model_name": "extra_trees",
        "min_confidence": 0.75,
        "participating_asset_count": 1,
        "model": {
            "total_return": 0.08,
            "max_drawdown": 0.0,
            "profit_factor": None,
            "active_trade_count": 20,
            "win_rate": 1.0,
            "exposure": 0.20,
        },
        "baselines": {"no_trade": {"total_return": 0.0}},
    }

    promotion = evaluate_promotion(summary, PromotionCriteria(min_active_trades=20))

    assert promotion["status"] == "pass"


def test_run_candidate_matrix_compares_scopes_and_thresholds() -> None:
    target = AssetDataset(
        asset_id="btc-id",
        ticker="BTC-USD",
        asset_class="crypto",
        dataset=build_supervised_dataset(
            make_prices(180),
            label_method="triple_barrier",
            horizon=3,
            profit_take=0.01,
            stop_loss=0.01,
        ).assign(asset_id="btc-id", ticker="BTC-USD", asset_class="crypto"),
    )
    peer_crypto = AssetDataset(
        asset_id="eth-id",
        ticker="ETH-USD",
        asset_class="crypto",
        dataset=build_supervised_dataset(
            make_prices(180).assign(close=lambda frame: frame["close"] * 0.8),
            label_method="triple_barrier",
            horizon=3,
            profit_take=0.01,
            stop_loss=0.01,
        ).assign(asset_id="eth-id", ticker="ETH-USD", asset_class="crypto"),
    )

    matrix = run_candidate_matrix(
        [target, peer_crypto],
        target_ticker="BTC-USD",
        scopes=["local", "global"],
        model_names=["logistic_regression"],
        confidence_thresholds=[0.55, 0.65],
        n_splits=3,
        trade_stride=3,
        promotion_criteria=PromotionCriteria(min_active_trades=1),
    )

    assert len(matrix["results"]) == 4
    assert matrix["errors"] == []
    assert len(matrix["ranking"]) == 4
    assert {row["scope"] for row in matrix["ranking"]} == {"local", "global"}
    assert {row["min_confidence"] for row in matrix["ranking"]} == {0.55, 0.65}
    assert all(row["candidate_id"].startswith("BTC-USD::logistic_regression") for row in matrix["ranking"])


class FakeModelRunRepository:
    def __init__(self, model_runs: list[dict]) -> None:
        self.model_runs = model_runs

    def get_model_runs(self, **kwargs):
        self.kwargs = kwargs
        return self.model_runs


def test_load_promoted_model_runs_filters_unpromoted_runs() -> None:
    promoted = {
        "id": "run-1",
        "model_name": "extra_trees",
        "model_version": "v1",
        "params": {"source": "candidate_matrix_promotion", "target_ticker": "BTC-USD", "min_confidence": 0.65},
    }
    unpromoted = {
        "id": "run-2",
        "model_name": "random_forest",
        "model_version": "v1",
        "params": {"source": "manual"},
    }
    repository = FakeModelRunRepository([promoted, unpromoted])

    selected, skipped = load_promoted_model_runs(repository, limit=10)

    assert selected == [promoted]
    assert skipped[0]["reason"] == "not_promoted"
    assert repository.kwargs["limit"] == 10
    assert is_promoted_model_run(promoted)
    assert target_ticker_for_model_run(promoted) == "BTC-USD"
    assert min_confidence_for_model_run(promoted) == 0.65


class FakeInferenceRepository:
    """Minimal repository stub for `run_latest_inference_job`'s previous-action
    read (Req: Signal Alerts Fire Only on Action Transition)."""

    def __init__(self, previous_predictions: dict[str, dict | None] | None = None) -> None:
        self.previous_predictions = previous_predictions or {}
        self.get_latest_prediction_calls: list[tuple] = []

    def get_asset_id(self, ticker: str) -> str:
        return f"asset-{ticker}"

    def get_latest_prediction(self, asset_id, model_name=None, model_version=None):
        self.get_latest_prediction_calls.append((asset_id, model_name, model_version))
        return self.previous_predictions.get(asset_id)


def test_run_latest_inference_job_records_success_and_errors(monkeypatch, tmp_path) -> None:
    good_artifact = tmp_path / "good.joblib"
    good_artifact.write_text("placeholder", encoding="utf-8")
    model_runs = [
        {
            "id": "run-1",
            "model_name": "extra_trees",
            "model_version": "v1",
            "feature_set": "technical_v2",
            "artifact_uri": str(good_artifact),
            "params": {"source": "candidate_matrix_promotion", "target_ticker": "BTC-USD", "min_confidence": 0.65},
        },
        {
            "id": "run-2",
            "model_name": "extra_trees",
            "model_version": "v2",
            "feature_set": "technical_v2",
            "artifact_uri": str(tmp_path / "missing.joblib"),
            "params": {"source": "candidate_matrix_promotion", "target_ticker": "ETH-USD"},
        },
    ]

    monkeypatch.setattr("brain.inference_job.joblib.load", lambda path: object())

    def fake_generate_latest_prediction(**kwargs):
        return {
            "predictions_loaded": 1,
            "predictions": [{"action": "HOLD", "confidence": kwargs["min_confidence"]}],
        }

    monkeypatch.setattr("brain.inference_job.generate_latest_prediction", fake_generate_latest_prediction)

    repository = FakeInferenceRepository(previous_predictions={"asset-BTC-USD": {"predicted_action": "HOLD"}})
    result = run_latest_inference_job(repository, model_runs)

    assert result["attempted"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["results"][0]["ticker"] == "BTC-USD"
    assert result["results"][0]["latest_prediction"]["confidence"] == 0.65
    assert result["results"][0]["previous_action"] == "HOLD"
    assert "artifact_not_found" in result["errors"][0]["error"]
    assert repository.get_latest_prediction_calls == [("asset-BTC-USD", "extra_trees", None)]


def test_run_latest_inference_job_first_ever_prediction_has_no_previous_action(monkeypatch, tmp_path) -> None:
    good_artifact = tmp_path / "good.joblib"
    good_artifact.write_text("placeholder", encoding="utf-8")
    model_runs = [
        {
            "id": "run-1",
            "model_name": "extra_trees",
            "model_version": "v1",
            "feature_set": "technical_v2",
            "artifact_uri": str(good_artifact),
            "params": {"source": "candidate_matrix_promotion", "target_ticker": "BTC-USD", "min_confidence": 0.65},
        },
    ]

    monkeypatch.setattr("brain.inference_job.joblib.load", lambda path: object())

    def fake_generate_latest_prediction(**kwargs):
        return {
            "predictions_loaded": 1,
            "predictions": [{"action": "BUY", "confidence": kwargs["min_confidence"]}],
        }

    monkeypatch.setattr("brain.inference_job.generate_latest_prediction", fake_generate_latest_prediction)

    repository = FakeInferenceRepository(previous_predictions={})
    result = run_latest_inference_job(repository, model_runs)

    assert result["results"][0]["previous_action"] is None


def test_select_candidate_uses_top_promotable_rank() -> None:
    report = {
        "ranking": [
            {"candidate_id": "failed", "promotion": {"status": "fail"}, "objective_score": 0.9},
            {"candidate_id": "winner", "promotion": {"status": "pass"}, "objective_score": 0.8},
            {"candidate_id": "runner-up", "promotion": {"status": "pass"}, "objective_score": 0.7},
        ]
    }

    selected = select_candidate(report)
    second = select_candidate(report, rank=2)

    assert selected["candidate_id"] == "winner"
    assert second["candidate_id"] == "runner-up"


def test_select_candidate_blocks_failed_candidate_by_default() -> None:
    report = {"ranking": [{"candidate_id": "failed", "promotion": {"status": "fail"}}]}

    try:
        select_candidate(report, candidate_id="failed")
    except ValueError as error:
        assert "not promotable" in str(error)
    else:
        raise AssertionError("Expected failed candidate to be blocked")


def test_build_promoted_training_frame_uses_candidate_scope() -> None:
    target = AssetDataset(
        asset_id="btc-id",
        ticker="BTC-USD",
        asset_class="crypto",
        dataset=build_supervised_dataset(
            make_prices(150),
            label_method="triple_barrier",
            horizon=3,
            profit_take=0.01,
            stop_loss=0.01,
        ).assign(asset_id="btc-id", ticker="BTC-USD", asset_class="crypto"),
    )
    peer_crypto = AssetDataset(
        asset_id="eth-id",
        ticker="ETH-USD",
        asset_class="crypto",
        dataset=build_supervised_dataset(
            make_prices(150).assign(close=lambda frame: frame["close"] * 0.8),
            label_method="triple_barrier",
            horizon=3,
            profit_take=0.01,
            stop_loss=0.01,
        ).assign(asset_id="eth-id", ticker="ETH-USD", asset_class="crypto"),
    )
    stock = AssetDataset(
        asset_id="aapl-id",
        ticker="AAPL",
        asset_class="stock",
        dataset=build_supervised_dataset(
            make_prices(150).assign(close=lambda frame: frame["close"] * 1.2),
            label_method="triple_barrier",
            horizon=3,
            profit_take=0.01,
            stop_loss=0.01,
        ).assign(asset_id="aapl-id", ticker="AAPL", asset_class="stock"),
    )

    frame, assets = build_promoted_training_frame([target, peer_crypto, stock], "BTC-USD", "asset_class")

    assert set(frame["ticker"]) == {"BTC-USD", "ETH-USD"}
    assert {asset["ticker"] for asset in assets} == {"BTC-USD", "ETH-USD"}


class FakeRetrainingRepository:
    def __init__(self, model_runs: list[dict] | None = None) -> None:
        self.updated_artifacts: list[tuple[str, str]] = []
        self.model_runs = model_runs or []

    def update_model_run_artifact_uri(self, model_run_id: str, artifact_uri: str) -> dict:
        self.updated_artifacts.append((model_run_id, artifact_uri))
        return {"id": model_run_id, "artifact_uri": artifact_uri}

    def get_model_runs(self, **kwargs):
        self.model_run_kwargs = kwargs
        return self.model_runs


def test_run_retraining_job_promotes_and_uploads_candidate(monkeypatch, tmp_path) -> None:
    target = AssetDataset(
        asset_id="btc-id",
        ticker="BTC-USD",
        asset_class="crypto",
        dataset=pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")}),
    )
    candidate = {
        "candidate_id": "BTC-USD::extra_trees::confidence_0.6500::local",
        "promotion": {"status": "pass"},
        "model_name": "extra_trees",
        "scope": "local",
        "target_ticker": "BTC-USD",
        "min_confidence": 0.65,
        "objective_score": 0.42,
    }
    artifact_path = tmp_path / "model.joblib"

    monkeypatch.setattr("brain.retraining_job.load_candidate_datasets", lambda *args, **kwargs: ([target], []))
    monkeypatch.setattr(
        "brain.retraining_job.run_candidate_matrix",
        lambda *args, **kwargs: {"results": [], "ranking": [candidate], "errors": []},
    )

    def fake_promote_candidate_from_report(**kwargs):
        artifact_path.write_bytes(b"model")
        from brain.promotion import PromotionResult

        return PromotionResult(
            candidate=kwargs["candidate"],
            model_run_id="run-1",
            artifact_uri=str(artifact_path),
            metrics={},
            prediction={"predictions_loaded": 1},
        )

    monkeypatch.setattr("brain.retraining_job.promote_candidate_from_report", fake_promote_candidate_from_report)
    monkeypatch.setattr(
        "brain.retraining_job.store_model_artifact",
        lambda *args, **kwargs: "models/model.joblib",
    )
    repository = FakeRetrainingRepository()

    result = run_retraining_job(
        repository=repository,
        tickers=["BTC-USD"],
        config=RetrainingJobConfig(
            model_names=["extra_trees"],
            confidence_thresholds=[0.65],
            scopes=["local"],
            upload_artifacts=True,
            min_active_trades=1,
        ),
    )

    assert result["attempted"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["model_run_id"] == "run-1"
    assert result["results"][0]["artifact_uri"] == "models/model.joblib"
    assert result["results"][0]["incumbent_comparison"]["reason"] == "no_incumbent"
    assert repository.updated_artifacts == [("run-1", "models/model.joblib")]


def test_run_retraining_job_skips_candidate_that_does_not_improve_incumbent(monkeypatch) -> None:
    target = AssetDataset(
        asset_id="btc-id",
        ticker="BTC-USD",
        asset_class="crypto",
        dataset=pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")}),
    )
    candidate = {
        "candidate_id": "BTC-USD::extra_trees::confidence_0.6500::local",
        "promotion": {"status": "pass"},
        "model_name": "extra_trees",
        "scope": "local",
        "target_ticker": "BTC-USD",
        "min_confidence": 0.65,
        "objective_score": 0.42,
    }
    incumbent = {
        "id": "run-incumbent",
        "model_name": "extra_trees",
        "model_version": "v1",
        "feature_set": "technical_v2",
        "label_method": "triple_barrier",
        "horizon": 5,
        "params": {"source": "candidate_matrix_promotion", "target_ticker": "BTC-USD"},
        "metrics": {"promotion": {"candidate": {"candidate_id": "old", "objective_score": 0.50}}},
    }

    monkeypatch.setattr("brain.retraining_job.load_candidate_datasets", lambda *args, **kwargs: ([target], []))
    monkeypatch.setattr(
        "brain.retraining_job.run_candidate_matrix",
        lambda *args, **kwargs: {"results": [], "ranking": [candidate], "errors": []},
    )

    def fail_if_promoted(**kwargs):
        raise AssertionError("Candidate should not be promoted")

    monkeypatch.setattr("brain.retraining_job.promote_candidate_from_report", fail_if_promoted)

    result = run_retraining_job(
        repository=FakeRetrainingRepository([incumbent]),
        tickers=["BTC-USD"],
        config=RetrainingJobConfig(
            model_names=["extra_trees"],
            confidence_thresholds=[0.65],
            scopes=["local"],
            upload_artifacts=False,
            min_active_trades=1,
        ),
    )

    assert result["attempted"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["skipped"][0]["reason"] == "candidate_not_better_than_incumbent"
    assert result["skipped"][0]["incumbent_model_run_id"] == "run-incumbent"


def test_compare_candidate_to_incumbent_allows_real_improvement() -> None:
    candidate = {"candidate_id": "new", "objective_score": 0.56}
    incumbent = {
        "id": "run-old",
        "model_name": "extra_trees",
        "model_version": "v1",
        "metrics": {"promotion": {"candidate": {"candidate_id": "old", "objective_score": 0.50}}},
    }

    comparison = compare_candidate_to_incumbent(candidate, incumbent, min_objective_improvement=0.01)

    assert comparison["status"] == "pass"
    assert comparison["reason"] == "candidate_improves_incumbent"


def test_run_retraining_job_skips_when_no_candidate_passes(monkeypatch) -> None:
    target = AssetDataset(
        asset_id="btc-id",
        ticker="BTC-USD",
        asset_class="crypto",
        dataset=pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")}),
    )

    monkeypatch.setattr("brain.retraining_job.load_candidate_datasets", lambda *args, **kwargs: ([target], []))
    monkeypatch.setattr(
        "brain.retraining_job.run_candidate_matrix",
        lambda *args, **kwargs: {
            "results": [],
            "ranking": [{"candidate_id": "weak", "promotion": {"status": "fail"}, "objective_score": 0.1}],
            "errors": [],
        },
    )

    result = run_retraining_job(
        repository=FakeRetrainingRepository(),
        tickers=["BTC-USD"],
        config=RetrainingJobConfig(
            model_names=["extra_trees"],
            confidence_thresholds=[0.65],
            scopes=["local"],
            upload_artifacts=False,
        ),
    )

    assert result["attempted"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["skipped"][0]["reason"] == "no_promotable_candidate"


def test_apply_risk_policy_sizes_confident_trade() -> None:
    predictions = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC"),
            "action": ["BUY"],
            "confidence": [0.8],
            "expected_risk": [0.02],
            "metadata": [{}],
        }
    )

    adjusted = apply_risk_policy(predictions, RiskPolicy(max_position_size=0.2, min_confidence_to_trade=0.6))

    assert adjusted.loc[0, "action"] == "BUY"
    assert adjusted.loc[0, "metadata"]["risk"]["position_size"] == 0.1
    assert adjusted.loc[0, "metadata"]["risk"]["blocked_reasons"] == []


def test_apply_risk_policy_blocks_low_confidence_trade() -> None:
    predictions = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC"),
            "action": ["BUY"],
            "confidence": [0.55],
            "expected_risk": [0.02],
            "metadata": [{}],
        }
    )

    adjusted = apply_risk_policy(predictions, RiskPolicy(min_confidence_to_trade=0.6))

    assert adjusted.loc[0, "action"] == "HOLD"
    assert "confidence_below_trade_threshold" in adjusted.loc[0, "metadata"]["risk"]["blocked_reasons"]


def test_apply_risk_policy_blocks_short_when_disabled() -> None:
    predictions = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC"),
            "action": ["SELL"],
            "confidence": [0.9],
            "expected_risk": [0.02],
            "metadata": [{}],
        }
    )

    adjusted = apply_risk_policy(predictions, RiskPolicy(allow_short=False))

    assert adjusted.loc[0, "action"] == "HOLD"
    assert "short_disabled" in adjusted.loc[0, "metadata"]["risk"]["blocked_reasons"]
