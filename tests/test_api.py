from __future__ import annotations

import inspect

import pandas as pd
from fastapi.testclient import TestClient

from app_config import AppConfig
from api.main import app, get_app_config, get_operational_alerts, get_repository
from collector.local_repository import LocalPostgresRepository
from ops.notification_rules import (
    DEFAULT_MAX_PRICE_AGE_HOURS,
    DEFAULT_MIN_ACCURACY,
    DEFAULT_MIN_FEEDBACK_SAMPLES,
    DEFAULT_MIN_MEAN_OUTCOME_RETURN,
)


class FakeRepository:
    def __init__(
        self,
        prediction: dict | None = None,
        prices: pd.DataFrame | None = None,
        prediction_feedback: pd.DataFrame | None = None,
        risk_profile: dict | None = None,
    ) -> None:
        self.prediction = prediction
        self.prices = prices if prices is not None else make_prices()
        self.prediction_feedback = prediction_feedback
        self.risk_profile = risk_profile
        self.feedback_kwargs: dict | None = None
        self.backtest_kwargs: dict | None = None
        self.paper_run_kwargs: dict | None = None
        self.paper_events_kwargs: dict | None = None
        self.paper_runs_kwargs: dict | None = None
        self.upserted_risk_profile: dict | None = None
        self.profile_lookup_kwargs: dict | None = None

    def get_assets(self) -> list[dict]:
        return [{"id": "asset-1", "ticker": "AAPL", "name": "Apple Inc.", "asset_class": "stock"}]

    def get_asset_id(self, ticker: str) -> str:
        if ticker.upper() == "MISSING":
            raise ValueError("missing")
        return "asset-1"

    def get_asset(self, ticker: str) -> dict:
        if ticker.upper() == "MISSING":
            raise ValueError("missing")
        return {"id": "asset-1", "ticker": ticker.upper(), "name": "Apple Inc.", "asset_class": "stock"}

    def get_prices(self, asset_id: str, limit: int | None = None, ascending: bool = True) -> pd.DataFrame:
        prices = self.prices.head(limit) if limit else self.prices
        return prices.sort_values("timestamp", ascending=ascending).reset_index(drop=True)

    def get_latest_prediction(
        self,
        asset_id: str,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> dict | None:
        return self.prediction

    def get_prediction_feedback(
        self,
        model_name: str | None = None,
        model_version: str | None = None,
        asset_id: str | None = None,
        only_evaluated: bool = True,
        limit: int | None = None,
        ascending: bool = True,
    ) -> pd.DataFrame:
        self.feedback_kwargs = {
            "model_name": model_name,
            "model_version": model_version,
            "asset_id": asset_id,
            "only_evaluated": only_evaluated,
            "limit": limit,
            "ascending": ascending,
        }
        if self.prediction_feedback is not None:
            return self.prediction_feedback
        return pd.DataFrame(
            [
                {
                    "prediction_id": 1,
                    "timestamp": "2026-07-05T00:00:00+00:00",
                    "predicted_action": "HOLD",
                    "confidence": 0.45,
                    "probabilities": {"BUY": 0.3, "HOLD": 0.45, "SELL": 0.25},
                    "model_name": "extra_trees",
                    "model_version": "promoted",
                    "model_run_id": "run-1",
                    "feature_set": "technical_v2",
                    "label_method": "triple_barrier",
                    "horizon": 5,
                    "metadata": {"risk": {"position_size": 0, "blocked_reasons": ["confidence_below_trade_threshold"]}},
                    "actual_label": None,
                    "is_correct": None,
                    "outcome_return": None,
                    "prediction_created_at": "2026-07-05T00:01:00+00:00",
                }
            ]
        )

    def get_backtests(
        self,
        asset_id: str | None = None,
        model_run_id: str | None = None,
        limit: int | None = None,
        ascending: bool = False,
    ) -> pd.DataFrame:
        self.backtest_kwargs = {
            "asset_id": asset_id,
            "model_run_id": model_run_id,
            "limit": limit,
            "ascending": ascending,
        }
        return pd.DataFrame(
            [
                {
                    "id": "backtest-1",
                    "name": "extra_trees:promoted:BTC-USD",
                    "model_run_id": "run-1",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "ended_at": "2026-07-01T00:00:00+00:00",
                    "created_at": "2026-07-06T00:00:00+00:00",
                    "metrics": {
                        "total_return": 0.25,
                        "max_drawdown": -0.04,
                        "profit_factor": 2.1,
                        "active_trade_count": 20,
                        "trade_count": 40,
                        "win_rate": 0.58,
                        "exposure": 0.5,
                        "final_equity": 12500,
                    },
                    "params": {"fee_bps": 5},
                    "model_runs": {
                        "model_name": "extra_trees",
                        "model_version": "promoted",
                        "feature_set": "technical_v2",
                        "label_method": "triple_barrier",
                        "horizon": 5,
                    },
                }
            ]
        )

    def create_paper_trading_run(
        self,
        name: str,
        model_run_id: str | None,
        asset_id: str | None,
        metrics: dict,
        params: dict | None = None,
        started_at=None,
        ended_at=None,
    ) -> str:
        self.paper_run_kwargs = {
            "name": name,
            "model_run_id": model_run_id,
            "asset_id": asset_id,
            "metrics": metrics,
            "params": params,
            "started_at": started_at,
            "ended_at": ended_at,
        }
        return "paper-run-1"

    def insert_paper_trading_events(self, paper_trading_run_id: str, asset_id: str | None, timeline: pd.DataFrame) -> int:
        self.paper_events_kwargs = {
            "paper_trading_run_id": paper_trading_run_id,
            "asset_id": asset_id,
            "rows": len(timeline),
        }
        return len(timeline)

    def get_paper_trading_runs(
        self,
        asset_id: str | None = None,
        model_run_id: str | None = None,
        limit: int | None = None,
        ascending: bool = False,
    ) -> pd.DataFrame:
        self.paper_runs_kwargs = {
            "asset_id": asset_id,
            "model_run_id": model_run_id,
            "limit": limit,
            "ascending": ascending,
        }
        return pd.DataFrame(
            [
                {
                    "id": "paper-run-1",
                    "name": "extra_trees:promoted:AAPL:paper",
                    "model_run_id": "run-1",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "ended_at": "2026-01-03T00:00:00+00:00",
                    "created_at": "2026-07-07T00:00:00+00:00",
                    "metrics": {
                        "initial_capital": 1000,
                        "final_equity": 1102.5,
                        "total_return": 0.1025,
                        "max_drawdown": 0,
                        "signal_count": 3,
                        "trade_count": 1,
                        "active_signal_count": 1,
                        "average_abs_exposure": 0.5,
                        "open_exposure": 0.5,
                        "open_position": "LONG",
                        "last_price": 121,
                        "profit_factor": None,
                        "fee_bps": 0,
                        "slippage_bps": 0,
                        "allow_short": True,
                    },
                    "params": {"fee_bps": 0},
                    "model_runs": {
                        "model_name": "extra_trees",
                        "model_version": "promoted",
                        "feature_set": "technical_v2",
                        "label_method": "triple_barrier",
                        "horizon": 5,
                    },
                }
            ]
        )

    def get_scoped_risk_profile(self, scope_type: str, scope_value: str = "") -> dict | None:
        self.profile_lookup_kwargs = {"scope_type": scope_type, "scope_value": scope_value}
        if self.risk_profile and self.risk_profile.get("scope_type", "default") == scope_type:
            if self.risk_profile.get("scope_value", "") == scope_value:
                return self.risk_profile
        return None

    def get_risk_profile_for_asset(
        self,
        ticker: str | None = None,
        asset_class: str | None = None,
    ) -> dict | None:
        self.profile_lookup_kwargs = {"ticker": ticker, "asset_class": asset_class}
        return self.risk_profile

    def upsert_risk_profile(
        self,
        profile: dict,
        scope_type: str = "default",
        scope_value: str = "",
    ) -> dict:
        self.upserted_risk_profile = {
            "scope_type": scope_type,
            "scope_value": scope_value,
            **profile,
        }
        return self.upserted_risk_profile


class PredictionUnavailableRepository(FakeRepository):
    def get_latest_prediction(
        self,
        asset_id: str,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> dict | None:
        raise RuntimeError("prediction feedback unavailable")


def make_prices(rows: int = 120) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=rows, freq="D", tz="UTC")
    close = pd.Series(range(rows), dtype=float) + 100
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": 1000,
        }
    )


def override_repository(repository: FakeRepository) -> None:
    app.dependency_overrides[get_repository] = lambda: repository


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def override_config(config: AppConfig) -> None:
    app.dependency_overrides[get_app_config] = lambda: config


def test_assets_endpoint_returns_repository_assets() -> None:
    override_repository(FakeRepository())
    client = TestClient(app)

    response = client.get("/api/assets")

    clear_overrides()
    assert response.status_code == 200
    assert response.json()[0]["ticker"] == "AAPL"


def test_health_endpoint_reports_ready_api_without_schema_check() -> None:
    override_repository(FakeRepository())
    client = TestClient(app)

    response = client.get("/api/health?include_schema=false")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["api"]["status"] == "ok"
    assert payload["checks"]["database"]["status"] == "ok"
    assert "schema" not in payload["checks"]


def test_health_endpoint_reports_degraded_without_database() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    response = client.get("/api/health")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["database"]["status"] == "unavailable"
    assert payload["checks"]["schema"]["reason"] == "database_unavailable"


def test_analysis_endpoint_prefers_latest_prediction() -> None:
    override_repository(
        FakeRepository(
            prediction={
                "predicted_action": "BUY",
                "confidence": 0.72,
                "probabilities": {"BUY": 0.72, "HOLD": 0.2, "SELL": 0.08},
                "model_name": "baseline",
                "model_version": "v1",
                "model_run_id": "run-1",
                "feature_set": "technical_v1",
                "label_method": "triple_barrier",
                "horizon": 5,
                "metadata": {
                    "risk": {
                        "position_size": 0.05,
                        "stop_loss": 0.02,
                        "take_profit": 0.04,
                        "blocked_reasons": [],
                    }
                },
            }
        )
    )
    client = TestClient(app)

    response = client.get("/api/analysis/AAPL")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "prediction"
    assert payload["analysis"]["signal"] == "BUY"
    assert payload["analysis"]["model"]["version"] == "v1"
    assert payload["analysis"]["risk"]["position_size"] == 0.05


def test_analysis_endpoint_applies_authenticated_risk_profile() -> None:
    repository = FakeRepository(
        risk_profile={
            "name": "conservador",
            "max_position_size": 0.02,
            "min_confidence_to_trade": 0.80,
            "max_expected_risk": 0.01,
            "stop_loss": 0.01,
            "take_profit": 0.02,
            "allow_short": True,
        },
        prediction={
            "predicted_action": "BUY",
            "confidence": 0.72,
            "expected_risk": 0.02,
            "probabilities": {"BUY": 0.72, "HOLD": 0.2, "SELL": 0.08},
            "model_name": "baseline",
            "model_version": "v1",
            "model_run_id": "run-1",
            "feature_set": "technical_v1",
            "label_method": "triple_barrier",
            "horizon": 5,
            "metadata": {"risk": {"position_size": 0.05, "blocked_reasons": [], "pre_risk_action": "BUY"}},
        },
    )
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/analysis/AAPL")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "prediction"
    assert payload["analysis"]["signal"] == "HOLD"
    assert payload["analysis"]["risk"]["position_size"] == 0
    assert payload["analysis"]["risk"]["pre_risk_action"] == "BUY"
    assert payload["analysis"]["risk"]["profile_source"] == "user"
    assert payload["analysis"]["risk"]["profile_name"] == "conservador"
    assert payload["analysis"]["risk"]["profile_scope"] == "default"
    assert payload["analysis"]["risk"]["profile_scope_value"] == ""
    assert repository.profile_lookup_kwargs == {"ticker": "AAPL", "asset_class": "stock"}
    assert set(payload["analysis"]["risk"]["blocked_reasons"]) == {
        "confidence_below_trade_threshold",
        "expected_risk_above_limit",
    }


def test_analysis_endpoint_reuses_pre_risk_action_for_user_policy() -> None:
    override_repository(
        FakeRepository(
            risk_profile={
                "name": "long-only",
                "max_position_size": 0.05,
                "min_confidence_to_trade": 0.60,
                "max_expected_risk": 0.05,
                "stop_loss": 0.02,
                "take_profit": 0.04,
                "allow_short": False,
            },
            prediction={
                "predicted_action": "HOLD",
                "confidence": 0.91,
                "expected_risk": 0.02,
                "probabilities": {"BUY": 0.03, "HOLD": 0.06, "SELL": 0.91},
                "model_name": "baseline",
                "model_version": "v1",
                "model_run_id": "run-1",
                "feature_set": "technical_v1",
                "label_method": "triple_barrier",
                "horizon": 5,
                "metadata": {
                    "risk": {
                        "position_size": 0,
                        "blocked_reasons": ["short_disabled"],
                        "pre_risk_action": "SELL",
                    }
                },
            },
        )
    )
    client = TestClient(app)

    response = client.get("/api/analysis/AAPL", headers={"Authorization": "Bearer good-token"})

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis"]["signal"] == "HOLD"
    assert payload["analysis"]["risk"]["pre_risk_action"] == "SELL"
    assert payload["analysis"]["risk"]["blocked_reasons"] == ["short_disabled"]
    assert payload["analysis"]["risk"]["profile_name"] == "long-only"


def test_analysis_endpoint_falls_back_to_indicator_logic() -> None:
    override_repository(FakeRepository(prediction=None))
    client = TestClient(app)

    response = client.get("/api/analysis/AAPL")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "fallback_indicators"
    assert payload["analysis"]["signal"] in {"BUY", "SELL", "HOLD"}


def test_analysis_endpoint_uses_real_prices_when_prediction_feedback_is_unavailable() -> None:
    override_repository(PredictionUnavailableRepository())
    client = TestClient(app)

    response = client.get("/api/analysis/AAPL")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "fallback_indicators"
    assert payload["analysis"]["signal"] in {"BUY", "SELL", "HOLD"}


def test_prediction_history_endpoint_returns_audit_rows() -> None:
    repository = FakeRepository()
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/predictions/AAPL?limit=5&only_evaluated=false")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["action"] == "HOLD"
    assert payload[0]["model"]["name"] == "extra_trees"
    assert payload[0]["risk"]["blocked_reasons"] == ["confidence_below_trade_threshold"]
    assert repository.feedback_kwargs == {
        "model_name": None,
        "model_version": None,
        "asset_id": "asset-1",
        "only_evaluated": False,
        "limit": 5,
        "ascending": False,
    }


def test_prediction_history_endpoint_returns_empty_demo_history() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    response = client.get("/api/predictions/BTC-USD")

    clear_overrides()
    assert response.status_code == 200
    assert response.json() == []


def test_feedback_summary_endpoint_returns_model_quality() -> None:
    repository = FakeRepository(
        prediction_feedback=pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC"),
                "predicted_action": ["BUY", "SELL", "BUY"],
                "actual_label": ["BUY", "HOLD", "SELL"],
                "is_correct": [True, False, False],
                "confidence": [0.8, 0.7, 0.6],
                "outcome_return": [0.04, -0.01, -0.02],
            }
        )
    )
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/feedback/AAPL?limit=3")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["evaluated_predictions"] == 3
    assert payload["summary"]["accuracy"] == 1 / 3
    assert payload["by_action"][0]["action"] in {"BUY", "SELL"}
    assert repository.feedback_kwargs == {
        "model_name": None,
        "model_version": None,
        "asset_id": "asset-1",
        "only_evaluated": True,
        "limit": 3,
        "ascending": False,
    }


def test_feedback_summary_endpoint_returns_empty_demo_report() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    response = client.get("/api/feedback/BTC-USD")

    clear_overrides()
    assert response.status_code == 200
    assert response.json()["summary"]["evaluated_predictions"] == 0


def test_operational_alerts_endpoint_defaults_match_notification_rules_constants() -> None:
    """Req: Degradation Thresholds Share One Default Source. The endpoint's
    `Query(default=...)` values must be the exact `ops.notification_rules`
    constants (a compile-time import), never a duplicated literal, so the two
    can never silently drift."""
    parameters = inspect.signature(get_operational_alerts).parameters
    assert parameters["max_price_age_hours"].default.default == DEFAULT_MAX_PRICE_AGE_HOURS
    assert parameters["min_feedback_samples"].default.default == DEFAULT_MIN_FEEDBACK_SAMPLES
    assert parameters["min_accuracy"].default.default == DEFAULT_MIN_ACCURACY
    assert parameters["min_mean_outcome_return"].default.default == DEFAULT_MIN_MEAN_OUTCOME_RETURN


def test_operational_alerts_endpoint_returns_ok_when_thresholds_pass() -> None:
    repository = FakeRepository(
        prediction={
            "predicted_action": "BUY",
            "confidence": 0.72,
            "model_name": "extra_trees",
            "model_version": "promoted",
        },
        prices=pd.DataFrame(
            {
                "timestamp": [pd.Timestamp.now(tz="UTC")],
                "open": [100],
                "high": [102],
                "low": [99],
                "close": [101],
                "volume": [1000],
            }
        ),
        prediction_feedback=pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC"),
                "predicted_action": ["BUY", "SELL", "HOLD"],
                "actual_label": ["BUY", "SELL", "HOLD"],
                "is_correct": [True, True, True],
                "confidence": [0.8, 0.7, 0.6],
                "outcome_return": [0.03, 0.01, 0.0],
            }
        ),
    )
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/alerts/AAPL?min_feedback_samples=3&min_accuracy=0.5")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["alerts"] == []
    assert repository.feedback_kwargs == {
        "model_name": None,
        "model_version": None,
        "asset_id": "asset-1",
        "only_evaluated": True,
        "limit": 250,
        "ascending": False,
    }


def test_operational_alerts_endpoint_reports_stale_prices_and_low_accuracy() -> None:
    repository = FakeRepository(
        prediction=None,
        prices=pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2026-01-01T00:00:00Z")],
                "open": [100],
                "high": [101],
                "low": [99],
                "close": [100],
                "volume": [1000],
            }
        ),
        prediction_feedback=pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC"),
                "predicted_action": ["BUY", "BUY", "SELL", "SELL"],
                "actual_label": ["SELL", "HOLD", "BUY", "BUY"],
                "is_correct": [False, False, False, False],
                "confidence": [0.8, 0.7, 0.6, 0.65],
                "outcome_return": [-0.03, -0.02, -0.01, -0.04],
            }
        ),
    )
    override_repository(repository)
    client = TestClient(app)

    response = client.get(
        "/api/alerts/AAPL?max_price_age_hours=1&min_feedback_samples=4&min_accuracy=0.5&min_mean_outcome_return=0"
    )

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "warning"
    codes = {alert["code"] for alert in payload["alerts"]}
    assert {"stale_prices", "no_prediction", "low_accuracy", "negative_edge"}.issubset(codes)


def test_operational_alerts_endpoint_reports_demo_mode() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    response = client.get("/api/alerts/BTC-USD")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "info"
    assert payload["alerts"][0]["code"] == "demo_data"


def test_backtest_history_endpoint_returns_model_metrics() -> None:
    repository = FakeRepository()
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/backtests/AAPL?limit=3")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == "backtest-1"
    assert payload[0]["model"]["name"] == "extra_trees"
    assert payload[0]["metrics"]["total_return"] == 0.25
    assert repository.backtest_kwargs == {
        "asset_id": "asset-1",
        "model_run_id": None,
        "limit": 3,
        "ascending": False,
    }


def test_backtest_history_endpoint_returns_empty_demo_history() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    response = client.get("/api/backtests/BTC-USD")

    clear_overrides()
    assert response.status_code == 200
    assert response.json() == []


def test_paper_trading_endpoint_simulates_prediction_stream() -> None:
    timestamps = pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC")
    repository = FakeRepository(
        prices=pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100, 110, 121],
                "high": [101, 111, 122],
                "low": [99, 109, 120],
                "close": [100, 110, 121],
                "volume": [1000, 1000, 1000],
            }
        ),
        prediction_feedback=pd.DataFrame(
            {
                "timestamp": timestamps,
                "predicted_action": ["BUY", "HOLD", "HOLD"],
                "confidence": [0.8, 0.5, 0.5],
                "metadata": [{"risk": {"position_size": 0.5}}, {}, {}],
            }
        ),
    )
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/paper-trading/AAPL?initial_capital=1000&fee_bps=0&slippage_bps=0")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AAPL"
    assert payload["metrics"]["trade_count"] == 1
    assert payload["metrics"]["open_position"] == "LONG"
    assert round(payload["metrics"]["final_equity"], 2) == 1102.5
    assert len(payload["timeline"]) == 3
    assert repository.feedback_kwargs == {
        "model_name": None,
        "model_version": None,
        "asset_id": "asset-1",
        "only_evaluated": False,
        "limit": 100,
        "ascending": True,
    }


def test_paper_trading_endpoint_persists_run_when_requested() -> None:
    timestamps = pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC")
    repository = FakeRepository(
        prices=pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100, 110, 121],
                "high": [101, 111, 122],
                "low": [99, 109, 120],
                "close": [100, 110, 121],
                "volume": [1000, 1000, 1000],
            }
        ),
        prediction_feedback=pd.DataFrame(
            {
                "timestamp": timestamps,
                "predicted_action": ["BUY", "HOLD", "HOLD"],
                "confidence": [0.8, 0.5, 0.5],
                "model_name": ["extra_trees", "extra_trees", "extra_trees"],
                "model_version": ["promoted", "promoted", "promoted"],
                "model_run_id": ["run-1", "run-1", "run-1"],
                "metadata": [{"risk": {"position_size": 0.5}}, {}, {}],
            }
        ),
    )
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/paper-trading/AAPL?initial_capital=1000&fee_bps=0&slippage_bps=0&persist=true")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["persisted_run_id"] == "paper-run-1"
    assert repository.paper_run_kwargs is not None
    assert repository.paper_run_kwargs["name"] == "extra_trees:promoted:AAPL:paper"
    assert repository.paper_run_kwargs["model_run_id"] == "run-1"
    assert repository.paper_run_kwargs["metrics"]["trade_count"] == 1
    assert "persist" not in repository.paper_run_kwargs["params"]
    assert repository.paper_events_kwargs == {
        "paper_trading_run_id": "paper-run-1",
        "asset_id": "asset-1",
        "rows": 3,
    }


def test_paper_trading_runs_endpoint_returns_persisted_summaries() -> None:
    repository = FakeRepository()
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/paper-trading-runs/AAPL?limit=5&model_run_id=run-1")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == "paper-run-1"
    assert payload[0]["metrics"]["final_equity"] == 1102.5
    assert payload[0]["model"]["name"] == "extra_trees"
    assert repository.paper_runs_kwargs == {
        "asset_id": "asset-1",
        "model_run_id": "run-1",
        "limit": 5,
        "ascending": False,
    }


def test_paper_trading_endpoint_returns_flat_demo_result() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    response = client.get("/api/paper-trading/BTC-USD")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["open_position"] == "FLAT"
    assert payload["timeline"] == []


def test_prices_endpoint_returns_descending_prices() -> None:
    override_repository(FakeRepository())
    client = TestClient(app)

    response = client.get("/api/prices/AAPL?limit=3")

    clear_overrides()
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 3
    assert rows[0]["timestamp"] > rows[-1]["timestamp"]


def test_demo_mode_identifies_demo_source_and_varies_price_shape() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    btc_prices = client.get("/api/prices/BTC-USD?limit=5")
    eth_prices = client.get("/api/prices/ETH-USD?limit=5")
    analysis = client.get("/api/analysis/BTC-USD")

    clear_overrides()
    assert btc_prices.status_code == 200
    assert eth_prices.status_code == 200
    assert analysis.status_code == 200
    assert analysis.json()["source"] == "demo_indicators"
    assert [row["close"] for row in btc_prices.json()] != [row["close"] for row in eth_prices.json()]


def test_assets_endpoint_returns_unavailable_when_demo_is_disabled() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    override_config(AppConfig(environment="production", allow_demo_fallback=False))
    client = TestClient(app)

    response = client.get("/api/assets")

    clear_overrides()
    assert response.status_code == 503
    assert response.json()["detail"] == "Fuente de datos no disponible y modo demo desactivado"


def test_prices_endpoint_returns_unavailable_when_demo_is_disabled() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    override_config(AppConfig(environment="production", allow_demo_fallback=False))
    client = TestClient(app)

    response = client.get("/api/prices/BTC-USD?limit=5")

    clear_overrides()
    assert response.status_code == 503
    assert response.json()["detail"] == "Fuente de datos no disponible y modo demo desactivado"


def test_risk_profile_endpoint_returns_default_without_auth() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    response = client.get("/api/risk-profile")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "default"
    assert payload["profile"]["max_position_size"] == 0.1
    assert payload["profile"]["allow_short"] is True


def test_risk_profile_endpoint_returns_scoped_profile() -> None:
    repository = FakeRepository(
        risk_profile={
            "name": "crypto",
            "scope_type": "asset_class",
            "scope_value": "crypto",
            "max_position_size": 0.02,
            "min_confidence_to_trade": 0.75,
            "max_expected_risk": 0.025,
            "stop_loss": 0.01,
            "take_profit": 0.03,
            "allow_short": False,
        }
    )
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/risk-profile?scope_type=asset_class&scope_value=Crypto")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "user"
    assert payload["profile"]["scope_type"] == "asset_class"
    assert payload["profile"]["scope_value"] == "crypto"
    assert repository.profile_lookup_kwargs == {
        "scope_type": "asset_class",
        "scope_value": "crypto",
    }


def test_risk_profile_endpoint_rejects_invalid_scope_type() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    response = client.get("/api/risk-profile?scope_type=bogus")

    clear_overrides()
    assert response.status_code == 422


def test_risk_profile_update_persists_authenticated_profile() -> None:
    repository = FakeRepository()
    override_repository(repository)
    client = TestClient(app)

    response = client.put(
        "/api/risk-profile",
        json={
            "name": "agresivo",
            "max_position_size": 0.15,
            "min_confidence_to_trade": 0.68,
            "max_expected_risk": 0.08,
            "stop_loss": 0.03,
            "take_profit": 0.06,
            "allow_short": True,
        },
    )

    clear_overrides()
    assert response.status_code == 200
    assert repository.upserted_risk_profile == {
        "scope_type": "default",
        "scope_value": "",
        "name": "agresivo",
        "max_position_size": 0.15,
        "min_confidence_to_trade": 0.68,
        "max_expected_risk": 0.08,
        "stop_loss": 0.03,
        "take_profit": 0.06,
        "allow_short": True,
    }
    assert response.json()["profile"]["take_profit"] == 0.06


def test_risk_profile_update_persists_ticker_scope() -> None:
    repository = FakeRepository()
    override_repository(repository)
    client = TestClient(app)

    response = client.put(
        "/api/risk-profile",
        json={
            "name": "btc",
            "scope_type": "ticker",
            "scope_value": "btc-usd",
            "max_position_size": 0.04,
            "min_confidence_to_trade": 0.70,
            "max_expected_risk": 0.03,
            "stop_loss": 0.02,
            "take_profit": 0.05,
            "allow_short": False,
        },
    )

    clear_overrides()
    assert response.status_code == 200
    assert repository.upserted_risk_profile == {
        "scope_type": "ticker",
        "scope_value": "BTC-USD",
        "name": "btc",
        "max_position_size": 0.04,
        "min_confidence_to_trade": 0.70,
        "max_expected_risk": 0.03,
        "stop_loss": 0.02,
        "take_profit": 0.05,
        "allow_short": False,
    }
    assert response.json()["profile"]["scope_value"] == "BTC-USD"


def test_health_endpoint_schema_check_succeeds_against_real_database(
    repository: LocalPostgresRepository,
) -> None:
    """End-to-end regression for the interim gap flagged in apply-progress.md:
    `/api/health?include_schema=true` must call `check_relations` with a real
    `LocalPostgresRepository` (not a Fake) so `relation_exists` actually runs
    against a migrated database, with no `AttributeError`."""
    override_repository(repository)
    client = TestClient(app)

    response = client.get("/api/health?include_schema=true")

    clear_overrides()
    assert response.status_code == 200
    payload = response.json()
    assert payload["checks"]["database"]["status"] == "ok"
    assert payload["checks"]["schema"]["status"] == "ok"
    assert payload["checks"]["schema"]["missing"] == []
