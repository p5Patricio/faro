from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

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
from brain.materialize_fundamentals import FundamentalMaterializationConfig, materialize_asset_fundamentals
from brain.models import available_model_names, create_model, walk_forward_evaluate
from brain.promotion import build_promoted_training_frame, select_candidate
from brain.risk import RiskPolicy, apply_risk_policy
from brain.retraining_job import (
    RetrainingJobConfig,
    compare_candidate_to_incumbent,
    resolve_target_tickers,
    run_retraining_job,
)
from brain.run_retraining_job import DEFAULT_UNIVERSE_FILE, load_universe_disclosure
from brain.scoped_evaluation import AssetDataset, run_scoped_walk_forward_backtest, select_scope_datasets
from brain.selection import PromotionCriteria, evaluate_promotion, rank_candidate_summaries, score_candidate
from collector.fundamentals import CONCEPT_CHAINS
from collector.universe import load_universe_document, universe_disclosure


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


def make_fake_dataset(ticker: str, rows: int, asset_class: str = "stock") -> AssetDataset:
    return AssetDataset(
        asset_id=f"asset-{ticker.lower()}",
        ticker=ticker,
        asset_class=asset_class,
        dataset=pd.DataFrame({"value": range(rows)}),
    )


def test_select_scope_datasets_caps_global_scope_deterministically() -> None:
    target = make_fake_dataset("AAA", rows=50)
    peers = [make_fake_dataset(f"PEER{index:02d}", rows=100 + index) for index in range(39)]
    datasets = [target, *peers]
    assert len(datasets) == 40

    first_run = select_scope_datasets(datasets, "AAA", "global", max_scope_assets=12)
    second_run = select_scope_datasets(list(reversed(datasets)), "AAA", "global", max_scope_assets=12)

    assert len(first_run) == 12
    assert first_run[0].ticker == "AAA"
    assert [item.ticker for item in first_run] == [item.ticker for item in second_run]

    expected_rest = sorted(peers, key=lambda item: (-len(item.dataset), item.ticker))[:11]
    assert [item.ticker for item in first_run[1:]] == [item.ticker for item in expected_rest]


def test_select_scope_datasets_below_cap_is_unaffected() -> None:
    target = make_fake_dataset("AAA", rows=50)
    peers = [make_fake_dataset(f"PEER{index:02d}", rows=10) for index in range(3)]
    datasets = [target, *peers]

    selected = select_scope_datasets(datasets, "AAA", "global", max_scope_assets=12)

    assert selected == datasets


def test_resolve_target_tickers_raises_over_cap_with_no_tickers_or_default_targets() -> None:
    datasets = [make_fake_dataset(f"TKR{index:03d}", rows=1) for index in range(100)]

    with pytest.raises(ValueError, match="max_auto_targets"):
        resolve_target_tickers(datasets, None, max_auto_targets=8)


def test_resolve_target_tickers_uses_default_targets_when_no_tickers_given() -> None:
    datasets = [make_fake_dataset(f"TKR{index:03d}", rows=1) for index in range(100)]

    resolved = resolve_target_tickers(
        datasets, None, default_targets=["TKR001", "TKR050", "MISSING"], max_auto_targets=8
    )

    assert resolved == ["TKR001", "TKR050"]


def test_resolve_target_tickers_explicit_tickers_override_policy() -> None:
    datasets = [make_fake_dataset(f"TKR{index:03d}", rows=1) for index in range(100)]

    resolved = resolve_target_tickers(
        datasets, ["tkr002", "missing"], default_targets=["TKR001"], max_auto_targets=8
    )

    assert resolved == ["TKR002"]


def test_resolve_target_tickers_within_cap_falls_back_to_sorted_available() -> None:
    datasets = [make_fake_dataset(ticker, rows=1) for ticker in ["MSFT", "AAPL", "BTC-USD", "ETH-USD"]]

    resolved = resolve_target_tickers(datasets, None, max_auto_targets=8)

    assert resolved == ["AAPL", "BTC-USD", "ETH-USD", "MSFT"]


def test_resolve_target_tickers_uncapped_preserves_two_positional_arg_behavior() -> None:
    datasets = [make_fake_dataset(f"TKR{index:03d}", rows=1) for index in range(100)]

    # existing 2-positional-arg call sites never pass max_auto_targets/default_targets --
    # behavior must stay exactly today's `sorted(available)`, no matter the count.
    resolved = resolve_target_tickers(datasets, None)

    assert resolved == sorted(item.ticker for item in datasets)


def test_load_universe_disclosure_embeds_universe_disclosure_for_real_snapshot() -> None:
    """Req: Survivorship Bias Disclosure -- confirms `brain/run_retraining_job.py`'s
    `main()` (`payload["universe"] = load_universe_disclosure(DEFAULT_UNIVERSE_FILE)`)
    embeds `universe_disclosure(doc)` verbatim under the JSON report's `"universe"`
    key for the real checked-in `config/universe.sp100.json` snapshot (spec
    "Backtest report discloses snapshot bias")."""
    disclosure = load_universe_disclosure(DEFAULT_UNIVERSE_FILE)

    assert disclosure == universe_disclosure(load_universe_document(DEFAULT_UNIVERSE_FILE))
    assert disclosure["snapshot_date"] == "2025-09-22"
    assert disclosure["member_count"] == 101


def test_load_universe_disclosure_degrades_to_incomplete_marker_when_missing(tmp_path) -> None:
    """Spec "Missing snapshot date blocks disclosure-bearing output" -- a missing
    universe file must never silently omit the `"universe"` key."""
    disclosure = load_universe_disclosure(str(tmp_path / "does-not-exist.json"))

    assert disclosure == {"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}


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


def test_load_promoted_model_runs_keeps_only_newest_per_ticker() -> None:
    # get_model_runs returns newest-first; the older AAPL run is a different
    # feature set but the same ticker, so only the newest one serves.
    newer_aapl = {
        "id": "run-new",
        "model_name": "extra_trees",
        "model_version": "v2",
        "feature_set": "fundamental_v1",
        "params": {"source": "candidate_matrix_promotion", "target_ticker": "AAPL"},
    }
    older_aapl = {
        "id": "run-old",
        "model_name": "extra_trees",
        "model_version": "v1",
        "feature_set": "technical_v2",
        "params": {"source": "candidate_matrix_promotion", "target_ticker": "AAPL"},
    }
    msft = {
        "id": "run-msft",
        "model_name": "random_forest",
        "model_version": "v1",
        "feature_set": "technical_v2",
        "params": {"source": "candidate_matrix_promotion", "target_ticker": "MSFT"},
    }
    repository = FakeModelRunRepository([newer_aapl, older_aapl, msft])

    selected, skipped = load_promoted_model_runs(repository, limit=50)

    assert [run["id"] for run in selected] == ["run-new", "run-msft"]
    superseded = [entry["model_run_id"] for entry in skipped if entry["reason"] == "superseded_by_newer_promotion"]
    assert superseded == ["run-old"]


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


def test_incumbent_lookup_compares_across_feature_sets(monkeypatch) -> None:
    """A fundamental_v1 candidate is measured against the technical_v2 model
    already serving the ticker, not only against a prior fundamental_v1 run
    (proposal.md, fundamental-analysis, Product Decision 2)."""
    target = AssetDataset(
        asset_id="aapl-id",
        ticker="AAPL",
        asset_class="stock",
        dataset=pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")}),
    )
    candidate = {
        "candidate_id": "AAPL::extra_trees::confidence_0.6500::local",
        "promotion": {"status": "pass"},
        "model_name": "extra_trees",
        "scope": "local",
        "target_ticker": "AAPL",
        "min_confidence": 0.65,
        "objective_score": 0.30,
    }
    technical_incumbent = {
        "id": "run-technical",
        "model_name": "extra_trees",
        "model_version": "v1",
        "feature_set": "technical_v2",
        "label_method": "triple_barrier",
        "horizon": 5,
        "params": {"source": "candidate_matrix_promotion", "target_ticker": "AAPL"},
        "metrics": {"promotion": {"candidate": {"candidate_id": "old", "objective_score": 0.55}}},
    }

    monkeypatch.setattr("brain.retraining_job.load_candidate_datasets", lambda *args, **kwargs: ([target], []))
    monkeypatch.setattr(
        "brain.retraining_job.run_candidate_matrix",
        lambda *args, **kwargs: {"results": [], "ranking": [candidate], "errors": []},
    )

    def fail_if_promoted(**kwargs):
        raise AssertionError("A worse cross-feature-set candidate must not be promoted")

    monkeypatch.setattr("brain.retraining_job.promote_candidate_from_report", fail_if_promoted)

    result = run_retraining_job(
        repository=FakeRetrainingRepository([technical_incumbent]),
        tickers=["AAPL"],
        config=RetrainingJobConfig(
            model_names=["extra_trees"],
            confidence_thresholds=[0.65],
            scopes=["local"],
            feature_set="fundamental_v1",
            upload_artifacts=False,
            min_active_trades=1,
        ),
    )

    assert result["succeeded"] == 0
    assert result["skipped"][0]["reason"] == "candidate_not_better_than_incumbent"
    assert result["skipped"][0]["incumbent_model_run_id"] == "run-technical"


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


def _fundamental_fact_row(
    logical_concept: str,
    *,
    period_end: str,
    filed_date: str,
    value: float,
    fiscal_period: str = "FY",
    accession: str = "acc-1",
) -> dict:
    """Build one raw `fundamental_facts` row via the real `CONCEPT_CHAINS`
    (the same map `collector.fundamentals.parse_company_facts` and
    `brain.fundamental_factors._select_as_of` read), so this fixture's tags
    stay in sync with the production chains instead of duplicating them."""
    expected_unit, chain = CONCEPT_CHAINS[logical_concept]
    taxonomy, concept = chain[0]
    return {
        "taxonomy": taxonomy,
        "concept": concept,
        "unit": expected_unit,
        "period_end": period_end,
        "fiscal_year": None,
        "fiscal_period": fiscal_period,
        "filed_date": filed_date,
        "accession": accession,
        "value": value,
    }


def _two_fiscal_years_of_fundamental_facts() -> list[dict]:
    """A stock with two clean fiscal years -- all 9 Piotroski signals TRUE,
    Altman/Novy-Marx both finite. Same hand-built values
    `tests/test_fundamental_factors.py::_two_year_facts` and
    `tests/test_fundamental_lookahead.py::_two_year_facts` use (already
    proven correct at the unit level). `year_one` is filed well before
    `make_prices`' spine starts -- harmless, since Piotroski is NaN for
    every row that only has one fiscal year available, so `upsert_features`
    drops that whole warm-up window anyway regardless of `year_one`'s own
    Altman resolution. `year_two` is filed ON a date inside the spine (past
    the 50-day technical warm-up) so Altman's exact-date price lookup
    (`_price_close_on`, never interpolated) actually resolves once both
    fiscal years are visible -- this test proves the pipeline WIRING
    end-to-end (materialize -> retrain), not the C1 lag itself, which
    Phase 4's dedicated look-ahead suite already covers."""
    year_one = dict(period_end="2021-12-31", filed_date="2022-02-10")
    year_two = dict(period_end="2022-12-31", filed_date="2024-03-01")
    return [
        _fundamental_fact_row("assets", value=1000.0, **year_one),
        _fundamental_fact_row("assets_current", value=400.0, **year_one),
        _fundamental_fact_row("liabilities", value=600.0, **year_one),
        _fundamental_fact_row("liabilities_current", value=200.0, **year_one),
        _fundamental_fact_row("equity", value=400.0, **year_one),
        _fundamental_fact_row("long_term_debt", value=300.0, **year_one),
        _fundamental_fact_row("net_income", value=50.0, **year_one),
        _fundamental_fact_row("cfo", value=40.0, **year_one),
        _fundamental_fact_row("retained_earnings", value=150.0, **year_one),
        _fundamental_fact_row("operating_income", value=80.0, **year_one),
        _fundamental_fact_row("revenue", value=900.0, **year_one),
        _fundamental_fact_row("cost_of_revenue", value=600.0, **year_one),
        _fundamental_fact_row("shares_outstanding_wavg", value=100.0, **year_one),
        _fundamental_fact_row("shares_outstanding_mve", value=101.0, **year_one),
        _fundamental_fact_row("assets", value=1200.0, **year_two),
        _fundamental_fact_row("assets_current", value=500.0, **year_two),
        _fundamental_fact_row("liabilities", value=650.0, **year_two),
        _fundamental_fact_row("liabilities_current", value=220.0, **year_two),
        _fundamental_fact_row("equity", value=550.0, **year_two),
        _fundamental_fact_row("long_term_debt", value=280.0, **year_two),
        _fundamental_fact_row("net_income", value=90.0, **year_two),
        _fundamental_fact_row("cfo", value=110.0, **year_two),
        _fundamental_fact_row("retained_earnings", value=200.0, **year_two),
        _fundamental_fact_row("operating_income", value=130.0, **year_two),
        _fundamental_fact_row("revenue", value=1100.0, **year_two),
        _fundamental_fact_row("cost_of_revenue", value=650.0, **year_two),
        _fundamental_fact_row("shares_outstanding_wavg", value=98.0, **year_two),
        _fundamental_fact_row("shares_outstanding_mve", value=99.0, **year_two),
    ]


def test_retraining_job_runs_on_fundamental_v1_feature_set(repository, tmp_path) -> None:
    """Phase 5 acceptance (proposal.md Success Criteria / design.md slice 5):
    `--feature-set fundamental_v1` materializes and retrains end-to-end on a
    stock fixture, and a crypto asset in the same run appears in
    `skipped_assets`, never as an error. Wires `materialize_asset_fundamentals`
    (Phase 4) into `run_retraining_job` (pre-existing, feature-set-agnostic)
    for real against the real `repository` fixture -- the first genuinely
    end-to-end, no-monkeypatch retraining test in this file."""
    stock_asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    repository.get_or_create_asset("btc-usd", asset_class="crypto")

    prices = make_prices(250)
    repository.upsert_prices(stock_asset_id, prices)
    repository.upsert_fundamental_facts(
        [{**row, "asset_id": stock_asset_id} for row in _two_fiscal_years_of_fundamental_facts()]
    )
    labels = triple_barrier_labels(prices, horizon=5, profit_take=0.01, stop_loss=0.01)
    repository.upsert_labels(stock_asset_id, labels, label_method="triple_barrier", horizon=5)

    materialization = materialize_asset_fundamentals(
        repository, FundamentalMaterializationConfig(ticker="aapl")
    )
    assert materialization.skipped_assets == []
    assert materialization.feature_rows_loaded > 0

    result = run_retraining_job(
        repository=repository,
        tickers=["AAPL", "BTC-USD"],
        config=RetrainingJobConfig(
            feature_set="fundamental_v1",
            label_method="triple_barrier",
            horizon=5,
            model_names=["logistic_regression"],
            confidence_thresholds=[0.55],
            scopes=["local"],
            splits=3,
            min_rows=30,
            min_total_return=-1.0,
            min_profit_factor=0.0,
            max_drawdown_floor=-1.0,
            min_active_trades=1,
            upload_artifacts=False,
            model_dir=str(tmp_path),
        ),
    )

    # A crypto asset materializes zero fundamental_v1 rows (Phase 4's
    # stock-only scope gate) and is therefore never even a candidate
    # dataset -- it surfaces in skipped_assets, never in errors, and is
    # never resolved as a retraining target.
    assert result["failed"] == 0
    assert result["errors"] == []
    assert result["attempted"] == 1
    assert result["succeeded"] == 1
    assert result["results"][0]["ticker"] == "AAPL"
    assert result["results"][0]["prediction_loaded"] is True

    skipped_tickers = {item["ticker"] for item in result["skipped_assets"]}
    assert skipped_tickers == {"BTC-USD"}
    assert result["skipped_assets"][0]["reason"] == "no_materialized_dataset"


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
