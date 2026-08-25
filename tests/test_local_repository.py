from __future__ import annotations

import pandas as pd
import pytest

from collector.local_repository import LocalPostgresRepository


# -- Threat matrix: SQL composition (task 3.1, RED before local_repository.py existed) --


def test_ticker_with_sql_injection_payload_round_trips_as_literal_data(
    repository: LocalPostgresRepository,
    db_connection,
) -> None:
    malicious_ticker = "'; drop table assets; --"

    asset_id = repository.get_or_create_asset(malicious_ticker)
    fetched = repository.get_asset(malicious_ticker)

    assert fetched["id"] == asset_id
    assert fetched["ticker"] == malicious_ticker.upper()

    with db_connection.cursor() as cur:
        cur.execute("SELECT to_regclass('assets') IS NOT NULL")
        (still_exists,) = cur.fetchone()
    assert still_exists is True


# -- Assets ------------------------------------------------------------------


def test_get_or_create_asset_is_idempotent(repository: LocalPostgresRepository) -> None:
    first_id = repository.get_or_create_asset("aapl", name="Apple", asset_class="stock")
    second_id = repository.get_or_create_asset("aapl")

    assert first_id == second_id
    matches = [asset for asset in repository.get_assets() if asset["ticker"] == "AAPL"]
    assert len(matches) == 1


def test_get_asset_id_raises_when_missing(repository: LocalPostgresRepository) -> None:
    with pytest.raises(ValueError, match="Asset not found: MISSING"):
        repository.get_asset_id("missing")


def test_get_asset_returns_metadata(repository: LocalPostgresRepository) -> None:
    repository.get_or_create_asset("aapl", name="Apple", asset_class="stock")

    asset = repository.get_asset("aapl")

    assert asset["ticker"] == "AAPL"
    assert asset["asset_class"] == "stock"


def test_get_assets_orders_by_ticker_ascending(repository: LocalPostgresRepository) -> None:
    repository.get_or_create_asset("msft", asset_class="stock")
    repository.get_or_create_asset("aapl", asset_class="stock")

    tickers = [asset["ticker"] for asset in repository.get_assets()]

    assert tickers == sorted(tickers)
    assert {"AAPL", "MSFT"}.issubset(set(tickers))


# -- Prices / features / labels ------------------------------------------------


def test_upsert_prices_resolves_conflicts_and_returns_batch_size(
    repository: LocalPostgresRepository,
) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    first_batch = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
            "open": [10, 11],
            "high": [12, 13],
            "low": [9, 10],
            "close": [11, 12],
            "volume": [1000, 1100],
        }
    )
    assert repository.upsert_prices(asset_id, first_batch) == 2

    second_batch = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"),
            "open": [99, 88, 77],
            "high": [100, 90, 80],
            "low": [95, 85, 75],
            "close": [98.0, 87.0, 76.0],
            "volume": [5000, 6000, 7000],
        }
    )
    assert repository.upsert_prices(asset_id, second_batch) == 3

    prices = repository.get_prices(asset_id)
    assert len(prices) == 3
    # 2024-01-01 exists in both batches; the second (last-written) value wins.
    assert prices.loc[0, "close"] == 98.0
    assert isinstance(prices.loc[0, "close"], float)


def test_get_prices_respects_limit_and_order(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    prices = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"),
            "open": [10, 11, 12],
            "high": [12, 13, 14],
            "low": [9, 10, 11],
            "close": [11, 12, 13],
            "volume": [1000, 1100, 1200],
        }
    )
    repository.upsert_prices(asset_id, prices)

    latest = repository.get_prices(asset_id, limit=1, ascending=False)

    assert len(latest) == 1
    assert latest.loc[0, "close"] == 13.0


def test_upsert_and_get_features(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    features = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
            "return_1d": [0.01, 0.02],
            "rsi_14": [55.5, 60.0],
        }
    )

    inserted = repository.upsert_features(asset_id, features, ["return_1d", "rsi_14"], "technical_test")

    assert inserted == 2
    stored = repository.get_features(asset_id, "technical_test")
    assert len(stored) == 2
    assert stored.loc[0, "features"] == {"return_1d": 0.01, "rsi_14": 55.5}


def test_upsert_and_get_labels(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    labels = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
            "label": ["BUY", "SELL"],
            "outcome_return": [0.03, -0.01],
        }
    )

    inserted = repository.upsert_labels(asset_id, labels, "triple_barrier", 5)

    assert inserted == 2
    stored = repository.get_labels(asset_id, "triple_barrier", 5)
    assert len(stored) == 2
    assert stored.loc[0, "label"] == "BUY"
    assert stored.loc[0, "outcome_return"] == 0.03


# -- Model runs / predictions ----------------------------------------------------


def test_create_model_run_is_idempotent(repository: LocalPostgresRepository) -> None:
    first_id = repository.create_model_run(
        model_name="baseline",
        model_version="v1",
        feature_set="technical_v1",
        label_method="triple_barrier",
        horizon=5,
    )
    second_id = repository.create_model_run(
        model_name="baseline",
        model_version="v1",
        feature_set="technical_v1",
        label_method="triple_barrier",
        horizon=5,
    )

    assert first_id == second_id


def test_get_model_run_returns_stored_run(repository: LocalPostgresRepository) -> None:
    repository.create_model_run(
        model_name="baseline",
        model_version="v2",
        feature_set="technical_v1",
        label_method="fixed_horizon",
        horizon=10,
        params={"splits": 3},
        metrics={"summary": {"mean_f1_macro": 0.5}},
    )

    run = repository.get_model_run("baseline", "v2")

    assert run["model_name"] == "baseline"
    assert run["metrics"]["summary"]["mean_f1_macro"] == 0.5


def test_get_model_run_raises_when_missing(repository: LocalPostgresRepository) -> None:
    with pytest.raises(ValueError, match="Model run not found"):
        repository.get_model_run("missing", "v1")


def test_get_model_runs_filters_by_model_name(repository: LocalPostgresRepository) -> None:
    repository.create_model_run(model_name="a", model_version="v1", feature_set="f", label_method="l", horizon=1)
    repository.create_model_run(model_name="b", model_version="v1", feature_set="f", label_method="l", horizon=1)

    runs = repository.get_model_runs(model_name="a")

    assert len(runs) == 1
    assert runs[0]["model_name"] == "a"


def test_update_model_run_artifact_uri(repository: LocalPostgresRepository) -> None:
    run_id = repository.create_model_run(
        model_name="baseline", model_version="v3", feature_set="f", label_method="l", horizon=1
    )

    updated = repository.update_model_run_artifact_uri(run_id, "models/baseline.joblib")

    assert updated["artifact_uri"] == "models/baseline.joblib"


def test_update_model_run_artifact_uri_raises_when_missing(repository: LocalPostgresRepository) -> None:
    with pytest.raises(RuntimeError, match="Model run not found"):
        repository.update_model_run_artifact_uri("00000000-0000-0000-0000-000000000000", "models/x.joblib")


def test_upsert_predictions_and_prediction_feedback(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    run_id = repository.create_model_run(
        model_name="baseline", model_version="v1", feature_set="f", label_method="triple_barrier", horizon=5
    )
    predictions = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC"),
            "action": ["BUY"],
            "confidence": [0.72],
            "expected_return": [None],
            "expected_risk": [None],
            "probabilities": [{"BUY": 0.72, "HOLD": 0.2, "SELL": 0.08}],
            "metadata": [{"raw_action": "BUY"}],
        }
    )
    assert repository.upsert_predictions(asset_id, run_id, predictions) == 1

    labels = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC"),
            "label": ["BUY"],
            "outcome_return": [0.05],
        }
    )
    repository.upsert_labels(asset_id, labels, "triple_barrier", 5)

    feedback = repository.get_prediction_feedback(model_name="baseline", model_version="v1")
    assert len(feedback) == 1
    assert feedback.loc[0, "actual_label"] == "BUY"
    assert bool(feedback.loc[0, "is_correct"]) is True

    latest = repository.get_latest_prediction(asset_id, model_name="baseline")
    assert latest is not None
    assert latest["predicted_action"] == "BUY"


def test_get_latest_prediction_returns_none_without_data(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")

    assert repository.get_latest_prediction(asset_id) is None


# -- Backtests / paper trading ------------------------------------------------


def test_create_and_get_backtests_embeds_model_run(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    run_id = repository.create_model_run(
        model_name="baseline", model_version="v1", feature_set="f", label_method="l", horizon=1
    )

    backtest_id = repository.create_backtest(
        name="baseline:v1:AAPL",
        model_run_id=run_id,
        asset_id=asset_id,
        metrics={"total_return": 0.12},
        params={"fee_bps": 5},
    )

    backtests = repository.get_backtests(asset_id=asset_id)
    assert len(backtests) == 1
    assert backtests.loc[0, "id"] == backtest_id
    assert backtests.loc[0, "model_runs"]["model_name"] == "baseline"


def test_get_backtests_model_runs_is_none_without_linked_run(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    repository.create_backtest(name="no-model", model_run_id=None, asset_id=asset_id, metrics={})

    backtests = repository.get_backtests(asset_id=asset_id)

    assert backtests.loc[0, "model_runs"] is None


def test_insert_backtest_trades(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    backtest_id = repository.create_backtest(name="bt", model_run_id=None, asset_id=asset_id, metrics={})
    trades = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC"),
            "action": ["BUY"],
            "confidence": [0.8],
            "gross_return": [0.03],
            "net_return": [0.028],
            "cost": [0.002],
            "equity": [1028],
            "metadata": [{"actual_label": "BUY"}],
        }
    )

    assert repository.insert_backtest_trades(backtest_id, asset_id, trades) == 1


def test_create_and_get_paper_trading_runs_embeds_model_run(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    run_id = repository.create_model_run(
        model_name="extra_trees", model_version="v1", feature_set="f", label_method="l", horizon=1
    )

    paper_run_id = repository.create_paper_trading_run(
        name="extra_trees:v1:AAPL:paper",
        model_run_id=run_id,
        asset_id=asset_id,
        metrics={"total_return": 0.12},
    )

    runs = repository.get_paper_trading_runs(asset_id=asset_id)
    assert len(runs) == 1
    assert runs.loc[0, "id"] == paper_run_id
    assert runs.loc[0, "model_runs"]["model_name"] == "extra_trees"


def test_insert_paper_trading_events(repository: LocalPostgresRepository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    run_id = repository.create_paper_trading_run(
        name="paper-run", model_run_id=None, asset_id=asset_id, metrics={}
    )
    timeline = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC"),
            "action": ["BUY"],
            "confidence": [0.8],
            "price": [100],
            "mark_return": [0.0],
            "exposure": [0.5],
            "exposure_delta": [0.5],
            "cost": [0.001],
            "equity": [999],
            "position_state": ["LONG"],
            "metadata": [{"risk": {"position_size": 0.5}}],
        }
    )

    assert repository.insert_paper_trading_events(run_id, asset_id, timeline) == 1


# -- Risk profiles (scope-only: no user_id, start empty) -----------------------


def test_fresh_risk_profile_table_is_empty(db_connection) -> None:
    with db_connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM risk_profiles")
        (count,) = cur.fetchone()

    assert count == 0


def test_get_default_risk_profile_returns_none_when_empty(repository: LocalPostgresRepository) -> None:
    assert repository.get_default_risk_profile() is None


def test_upsert_and_get_default_risk_profile(repository: LocalPostgresRepository) -> None:
    saved = repository.upsert_default_risk_profile({"max_position_size": 0.04, "allow_short": False})

    assert saved["scope_type"] == "default"
    assert saved["scope_value"] == ""
    assert saved["max_position_size"] == 0.04

    fetched = repository.get_default_risk_profile()
    assert fetched is not None
    assert fetched["id"] == saved["id"]


def test_upsert_risk_profile_scoped_by_ticker(repository: LocalPostgresRepository) -> None:
    saved = repository.upsert_risk_profile(
        {"name": "btc", "max_position_size": 0.04}, scope_type="ticker", scope_value="BTC-USD"
    )

    assert saved["scope_type"] == "ticker"
    assert saved["scope_value"] == "BTC-USD"

    fetched = repository.get_scoped_risk_profile("ticker", "BTC-USD")
    assert fetched is not None
    assert fetched["id"] == saved["id"]


def test_upsert_risk_profile_updates_all_payload_columns_on_conflict(
    repository: LocalPostgresRepository,
) -> None:
    repository.upsert_risk_profile(
        {"max_position_size": 0.10, "allow_short": True}, scope_type="ticker", scope_value="AAPL"
    )

    updated = repository.upsert_risk_profile(
        {"max_position_size": 0.20, "allow_short": False}, scope_type="ticker", scope_value="AAPL"
    )

    assert updated["max_position_size"] == 0.20
    assert updated["allow_short"] is False
    refetched = repository.get_scoped_risk_profile("ticker", "AAPL")
    assert refetched["max_position_size"] == 0.20


def test_get_risk_profile_for_asset_prefers_ticker_then_asset_class_then_default(
    repository: LocalPostgresRepository,
) -> None:
    repository.upsert_default_risk_profile({"max_position_size": 0.10})
    repository.upsert_risk_profile({"max_position_size": 0.05}, scope_type="asset_class", scope_value="crypto")
    repository.upsert_risk_profile({"max_position_size": 0.02}, scope_type="ticker", scope_value="BTC-USD")

    ticker_profile = repository.get_risk_profile_for_asset(ticker="btc-usd", asset_class="crypto")
    assert ticker_profile["scope_value"] == "BTC-USD"

    class_profile = repository.get_risk_profile_for_asset(ticker="eth-usd", asset_class="crypto")
    assert class_profile["scope_type"] == "asset_class"

    default_profile = repository.get_risk_profile_for_asset(ticker="aapl", asset_class="stock")
    assert default_profile["scope_type"] == "default"


# -- Schema introspection --------------------------------------------------------


def test_relation_exists_true_for_known_table(repository: LocalPostgresRepository) -> None:
    assert repository.relation_exists("assets") is True


def test_relation_exists_false_for_unknown_table(repository: LocalPostgresRepository) -> None:
    assert repository.relation_exists("not_a_real_table") is False
