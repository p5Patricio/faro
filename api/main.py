from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from math import cos, sin

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from app_config import AppConfig
from brain.feedback import analyze_prediction_feedback
from brain.logic import generate_signals
from brain.paper_trading import PaperTradingConfig, run_paper_trading
from brain.risk import RiskPolicy, apply_risk_policy
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from collector.schema_check import check_relations


APP_CONFIG = AppConfig.from_env()

_POOL: ConnectionPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _POOL
    try:
        dsn = LocalPostgresConfig.from_env().dsn
        _POOL = ConnectionPool(conninfo=dsn, configure=LocalPostgresRepository._configure, open=False)
        _POOL.open()
    except RuntimeError:
        _POOL = None
    yield
    if _POOL is not None:
        _POOL.close()


app = FastAPI(title="Plataforma IA Inversiones API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(APP_CONFIG.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RiskProfilePayload(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=80)
    scope_type: str = Field(default="default", min_length=1, max_length=40)
    scope_value: str | None = Field(default=None, max_length=80)
    max_position_size: float = Field(default=0.10, ge=0, le=1)
    min_confidence_to_trade: float = Field(default=0.60, ge=0, le=1)
    max_expected_risk: float = Field(default=0.05, ge=0, le=1)
    stop_loss: float = Field(default=0.02, ge=0, le=1)
    take_profit: float = Field(default=0.04, ge=0, le=5)
    allow_short: bool = True

def get_repository() -> LocalPostgresRepository | None:
    if _POOL is None:
        return None
    return LocalPostgresRepository(pool=_POOL)


def get_app_config() -> AppConfig:
    return APP_CONFIG


@app.get("/")
def read_root():
    return {"message": "API de Plataforma IA Inversiones funcionando"}


@app.get("/api/health")
def get_health(
    include_schema: bool = Query(default=True),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    checks = {
        "api": {"status": "ok"},
        "database": {"status": "ok" if repository is not None else "unavailable"},
    }
    status = "ok" if repository is not None else "degraded"

    if include_schema and repository is not None:
        relation_statuses = check_relations(repository)
        missing = [item for item in relation_statuses if not item.available]
        checks["schema"] = {
            "status": "ok" if not missing else "missing_relations",
            "missing": [item.name for item in missing],
            "relations": {item.name: item.available for item in relation_statuses},
        }
        if missing:
            status = "degraded"
    elif include_schema:
        checks["schema"] = {"status": "skipped", "reason": "database_unavailable"}

    return {
        "status": status,
        "environment": config.environment,
        "allow_demo_fallback": config.allow_demo_fallback,
        "checks": checks,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }


@app.get("/api/assets")
def get_assets(
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    if repository is None:
        require_demo_fallback(config)
        return demo_assets()

    try:
        return repository.get_assets()
    except RuntimeError:
        require_demo_fallback(config)
        return demo_assets()


@app.get("/api/prices/{ticker}")
def get_prices(
    ticker: str,
    limit: int = 100,
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    if repository is None:
        require_demo_ticker(ticker, config)
        return demo_prices(ticker, limit=limit)

    try:
        asset_id = repository.get_asset_id(ticker)
        prices = repository.get_prices(asset_id, limit=limit, ascending=False)
        return prices.to_dict(orient="records")
    except ValueError:
        if not should_use_demo_ticker(ticker, config):
            raise HTTPException(status_code=404, detail="Activo no encontrado") from None
    except RuntimeError:
        require_demo_ticker(ticker, config)

    return demo_prices(ticker, limit=limit)


@app.get("/api/analysis/{ticker}")
def analyze_ticker(
    ticker: str,
    model_name: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    if repository is None:
        require_demo_ticker(ticker, config)
        prices = demo_prices(ticker, limit=100)
        return {
            "ticker": ticker.upper(),
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "source": "demo_indicators",
            "analysis": generate_signals(prices),
        }

    try:
        asset = repository.get_asset(ticker)
        asset_id = asset["id"]
        try:
            prediction = repository.get_latest_prediction(
                asset_id=asset_id,
                model_name=model_name,
                model_version=model_version,
            )
        except RuntimeError:
            prediction = None

        if prediction:
            profile = repository.get_risk_profile_for_asset(
                ticker=asset.get("ticker") or ticker,
                asset_class=asset.get("asset_class"),
            )
            if profile:
                prediction = apply_user_risk_profile_to_prediction(prediction, profile)
            return {
                "ticker": ticker.upper(),
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "source": "prediction",
                "analysis": format_prediction_analysis(prediction),
            }

        prices = repository.get_prices(asset_id, limit=100, ascending=False)
        if prices.empty:
            raise HTTPException(status_code=404, detail="No hay precios para analizar")

        return {
            "ticker": ticker.upper(),
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "source": "fallback_indicators",
            "analysis": generate_signals(prices.to_dict(orient="records")),
        }
    except ValueError:
        if not should_use_demo_ticker(ticker, config):
            raise HTTPException(status_code=404, detail="Activo no encontrado") from None
    except RuntimeError:
        require_demo_ticker(ticker, config)

    prices = demo_prices(ticker, limit=100)
    return {
        "ticker": ticker.upper(),
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "source": "demo_indicators",
        "analysis": generate_signals(prices),
    }


@app.get("/api/predictions/{ticker}")
def get_prediction_history(
    ticker: str,
    limit: int = Query(default=20, ge=1, le=100),
    model_name: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    only_evaluated: bool = Query(default=False),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    if repository is None:
        require_demo_ticker(ticker, config)
        return []

    try:
        asset_id = repository.get_asset_id(ticker)
        feedback = repository.get_prediction_feedback(
            asset_id=asset_id,
            model_name=model_name,
            model_version=model_version,
            only_evaluated=only_evaluated,
            limit=limit,
            ascending=False,
        )
        return [format_prediction_history_row(row) for row in feedback.to_dict(orient="records")]
    except ValueError:
        if not should_use_demo_ticker(ticker, config):
            raise HTTPException(status_code=404, detail="Activo no encontrado") from None
    except RuntimeError:
        require_demo_ticker(ticker, config)

    return []


@app.get("/api/feedback/{ticker}")
def get_feedback_summary(
    ticker: str,
    limit: int = Query(default=250, ge=1, le=1000),
    model_name: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    if repository is None:
        require_demo_ticker(ticker, config)
        return format_feedback_report(analyze_prediction_feedback(pd.DataFrame()))

    try:
        asset_id = repository.get_asset_id(ticker)
        feedback = repository.get_prediction_feedback(
            asset_id=asset_id,
            model_name=model_name,
            model_version=model_version,
            only_evaluated=True,
            limit=limit,
            ascending=False,
        )
        return format_feedback_report(analyze_prediction_feedback(feedback))
    except ValueError:
        if not should_use_demo_ticker(ticker, config):
            raise HTTPException(status_code=404, detail="Activo no encontrado") from None
    except RuntimeError:
        require_demo_ticker(ticker, config)

    return format_feedback_report(analyze_prediction_feedback(pd.DataFrame()))


@app.get("/api/alerts/{ticker}")
def get_operational_alerts(
    ticker: str,
    max_price_age_hours: float = Query(default=72.0, gt=0),
    min_feedback_samples: int = Query(default=20, ge=1, le=1000),
    min_accuracy: float = Query(default=0.45, ge=0, le=1),
    min_mean_outcome_return: float = Query(default=0.0, ge=-1, le=1),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    if repository is None:
        require_demo_ticker(ticker, config)
        return format_operational_alerts(
            ticker,
            [
                {
                    "severity": "info",
                    "code": "demo_data",
                    "message": "Modo demo activo; las alertas no representan datos reales de mercado.",
                    "details": {},
                }
            ],
        )

    try:
        asset_id = repository.get_asset_id(ticker)
        prices = repository.get_prices(asset_id, limit=1, ascending=False)
        prediction = repository.get_latest_prediction(asset_id=asset_id)
        feedback = repository.get_prediction_feedback(
            asset_id=asset_id,
            only_evaluated=True,
            limit=max(min_feedback_samples, 250),
            ascending=False,
        )
        feedback_report = analyze_prediction_feedback(feedback)
        alerts = build_operational_alerts(
            ticker=ticker,
            prices=prices,
            latest_prediction=prediction,
            feedback_report=feedback_report,
            max_price_age_hours=max_price_age_hours,
            min_feedback_samples=min_feedback_samples,
            min_accuracy=min_accuracy,
            min_mean_outcome_return=min_mean_outcome_return,
        )
        return format_operational_alerts(ticker, alerts)
    except ValueError:
        if not should_use_demo_ticker(ticker, config):
            raise HTTPException(status_code=404, detail="Activo no encontrado") from None
    except RuntimeError:
        require_demo_ticker(ticker, config)

    return format_operational_alerts(ticker, [])


@app.get("/api/backtests/{ticker}")
def get_backtest_history(
    ticker: str,
    limit: int = Query(default=10, ge=1, le=50),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    if repository is None:
        require_demo_ticker(ticker, config)
        return []

    try:
        asset_id = repository.get_asset_id(ticker)
        backtests = repository.get_backtests(asset_id=asset_id, limit=limit, ascending=False)
        return [format_backtest_history_row(row) for row in backtests.to_dict(orient="records")]
    except ValueError:
        if not should_use_demo_ticker(ticker, config):
            raise HTTPException(status_code=404, detail="Activo no encontrado") from None
    except RuntimeError:
        require_demo_ticker(ticker, config)

    return []


@app.get("/api/paper-trading/{ticker}")
def get_paper_trading(
    ticker: str,
    limit: int = Query(default=100, ge=1, le=500),
    model_name: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    initial_capital: float = Query(default=10_000.0, gt=0),
    default_position_size: float = Query(default=0.10, ge=0, le=1),
    fee_bps: float = Query(default=5.0, ge=0),
    slippage_bps: float = Query(default=5.0, ge=0),
    allow_short: bool = Query(default=True),
    persist: bool = Query(default=False),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    if repository is None:
        require_demo_ticker(ticker, config)
        result = run_paper_trading(
            pd.DataFrame(),
            pd.DataFrame(demo_prices(ticker, limit=limit)),
            PaperTradingConfig(
                initial_capital=initial_capital,
                default_position_size=default_position_size,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                allow_short=allow_short,
            ),
        )
        return format_paper_trading_response(ticker, result)

    try:
        asset_id = repository.get_asset_id(ticker)
        predictions = repository.get_prediction_feedback(
            asset_id=asset_id,
            model_name=model_name,
            model_version=model_version,
            only_evaluated=False,
            limit=limit,
            ascending=True,
        )
        prices = repository.get_prices(asset_id, limit=max(limit * 3, limit), ascending=True)
        result = run_paper_trading(
            predictions,
            prices,
            PaperTradingConfig(
                initial_capital=initial_capital,
                default_position_size=default_position_size,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                allow_short=allow_short,
            ),
        )
        persisted_run_id = None
        if persist:
            try:
                persisted_run_id = persist_paper_trading_run(
                    repository=repository,
                    ticker=ticker,
                    asset_id=asset_id,
                    predictions=predictions,
                    result=result,
                    params={
                        "limit": limit,
                        "model_name": model_name,
                        "model_version": model_version,
                        "initial_capital": initial_capital,
                        "default_position_size": default_position_size,
                        "fee_bps": fee_bps,
                        "slippage_bps": slippage_bps,
                        "allow_short": allow_short,
                    },
                )
            except RuntimeError:
                raise HTTPException(status_code=503, detail="No se pudo guardar la simulacion de paper trading") from None
        return format_paper_trading_response(ticker, result, persisted_run_id=persisted_run_id)
    except ValueError:
        if not should_use_demo_ticker(ticker, config):
            raise HTTPException(status_code=404, detail="Activo no encontrado") from None
    except RuntimeError:
        require_demo_ticker(ticker, config)

    result = run_paper_trading(
        pd.DataFrame(),
        pd.DataFrame(demo_prices(ticker, limit=limit)),
        PaperTradingConfig(
            initial_capital=initial_capital,
            default_position_size=default_position_size,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            allow_short=allow_short,
        ),
    )
    return format_paper_trading_response(ticker, result)


@app.get("/api/paper-trading-runs/{ticker}")
def get_paper_trading_runs(
    ticker: str,
    limit: int = Query(default=10, ge=1, le=100),
    model_run_id: str | None = Query(default=None),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    if repository is None:
        require_demo_ticker(ticker, config)
        return []

    try:
        asset_id = repository.get_asset_id(ticker)
        runs = repository.get_paper_trading_runs(
            asset_id=asset_id,
            model_run_id=model_run_id,
            limit=limit,
            ascending=False,
        )
        return [format_paper_trading_run_row(row) for row in runs.to_dict(orient="records")]
    except ValueError:
        if not should_use_demo_ticker(ticker, config):
            raise HTTPException(status_code=404, detail="Activo no encontrado") from None
    except RuntimeError:
        require_demo_ticker(ticker, config)

    return []


@app.get("/api/risk-profile")
def get_risk_profile(
    scope_type: str = Query(default="default"),
    scope_value: str | None = Query(default=None),
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    scope_type, scope_value = normalize_risk_profile_scope(scope_type, scope_value)
    if repository is None:
        return format_risk_profile(None, source="default")

    try:
        profile = repository.get_scoped_risk_profile(scope_type, scope_value)
    except RuntimeError:
        profile = None
    return format_risk_profile(profile, source="user" if profile else "default")


@app.put("/api/risk-profile")
def update_risk_profile(
    payload: RiskProfilePayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    if repository is None:
        raise HTTPException(status_code=503, detail="Base de datos no disponible para guardar perfil de riesgo")

    profile_payload = payload.model_dump()
    scope_type, scope_value = normalize_risk_profile_scope(
        str(profile_payload.pop("scope_type", "default")),
        profile_payload.pop("scope_value", None),
    )
    try:
        profile = repository.upsert_risk_profile(
            profile_payload,
            scope_type=scope_type,
            scope_value=scope_value,
        )
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar el perfil de riesgo") from None
    return format_risk_profile(profile, source="user")


def require_demo_fallback(config: AppConfig) -> None:
    if not config.allow_demo_fallback:
        raise HTTPException(
            status_code=503,
            detail="Fuente de datos no disponible y modo demo desactivado",
        )


def require_demo_ticker(ticker: str, config: AppConfig) -> None:
    require_demo_fallback(config)
    if not is_demo_ticker(ticker):
        raise HTTPException(status_code=404, detail="Activo no encontrado") from None


def should_use_demo_ticker(ticker: str, config: AppConfig) -> bool:
    return config.allow_demo_fallback and is_demo_ticker(ticker)


def format_risk_profile(profile: dict | None, source: str) -> dict:
    policy = risk_policy_from_profile(profile)
    return {
        "source": source,
        "profile": {
            "name": (profile or {}).get("name", "default"),
            "scope_type": (profile or {}).get("scope_type", "default"),
            "scope_value": (profile or {}).get("scope_value", ""),
            "max_position_size": policy.max_position_size,
            "min_confidence_to_trade": policy.min_confidence_to_trade,
            "max_expected_risk": policy.max_expected_risk,
            "stop_loss": policy.stop_loss,
            "take_profit": policy.take_profit,
            "allow_short": policy.allow_short,
        },
    }


def risk_policy_from_profile(profile: dict | None) -> RiskPolicy:
    default_policy = RiskPolicy()
    if not profile:
        return default_policy
    return RiskPolicy(
        max_position_size=float(profile.get("max_position_size", default_policy.max_position_size)),
        min_confidence_to_trade=float(profile.get("min_confidence_to_trade", default_policy.min_confidence_to_trade)),
        max_expected_risk=float(profile.get("max_expected_risk", default_policy.max_expected_risk)),
        stop_loss=float(profile.get("stop_loss", default_policy.stop_loss)),
        take_profit=float(profile.get("take_profit", default_policy.take_profit)),
        allow_short=bool(profile.get("allow_short", default_policy.allow_short)),
    )


def normalize_risk_profile_scope(scope_type: str, scope_value: str | None) -> tuple[str, str]:
    normalized_type = scope_type.strip().lower()
    if normalized_type not in {"default", "asset_class", "ticker"}:
        raise HTTPException(status_code=422, detail="scope_type debe ser default, asset_class o ticker")
    if normalized_type == "default":
        return normalized_type, ""

    normalized_value = (scope_value or "").strip()
    if not normalized_value:
        raise HTTPException(status_code=422, detail="scope_value es requerido para perfiles por scope")
    if normalized_type == "ticker":
        normalized_value = normalized_value.upper()
    else:
        normalized_value = normalized_value.lower()
    return normalized_type, normalized_value


def apply_user_risk_profile_to_prediction(prediction: dict, profile: dict) -> dict:
    metadata = dict(prediction.get("metadata") or {})
    current_risk = dict(metadata.get("risk") or {})
    base_action = current_risk.get("pre_risk_action") or prediction.get("predicted_action") or prediction.get("action") or "HOLD"
    prediction_frame = pd.DataFrame(
        [
            {
                "action": base_action,
                "confidence": prediction.get("confidence") or 0,
                "expected_risk": prediction.get("expected_risk"),
                "metadata": metadata,
            }
        ]
    )
    adjusted = apply_risk_policy(prediction_frame, risk_policy_from_profile(profile)).iloc[0]
    adjusted_prediction = dict(prediction)
    adjusted_prediction["predicted_action"] = adjusted["action"]
    adjusted_prediction["metadata"] = adjusted["metadata"]
    adjusted_prediction["metadata"]["risk"]["profile_source"] = "user"
    adjusted_prediction["metadata"]["risk"]["profile_name"] = profile.get("name", "default")
    adjusted_prediction["metadata"]["risk"]["profile_scope"] = profile.get("scope_type", "default")
    adjusted_prediction["metadata"]["risk"]["profile_scope_value"] = profile.get("scope_value", "")
    return adjusted_prediction


def format_prediction_analysis(prediction: dict) -> dict:
    metadata = prediction.get("metadata") or {}
    risk = metadata.get("risk") or {}
    probabilities = prediction.get("probabilities") or {}
    action = prediction.get("predicted_action") or prediction.get("action") or "HOLD"
    confidence = prediction.get("confidence") or 0

    reasons = [
        f"Modelo {prediction.get('model_name')}:{prediction.get('model_version')}",
        f"Feature set {prediction.get('feature_set')}",
    ]
    blocked = risk.get("blocked_reasons") or []
    if blocked:
        reasons.append(f"Bloqueada por riesgo: {', '.join(blocked)}")

    return {
        "signal": action,
        "confidence": float(confidence),
        "reason": "Prediccion versionada del modelo",
        "reasons": reasons,
        "probabilities": probabilities,
        "model": {
            "name": prediction.get("model_name"),
            "version": prediction.get("model_version"),
            "run_id": prediction.get("model_run_id"),
            "feature_set": prediction.get("feature_set"),
            "label_method": prediction.get("label_method"),
            "horizon": prediction.get("horizon"),
        },
        "risk": {
            "position_size": risk.get("position_size", 0),
            "stop_loss": risk.get("stop_loss"),
            "take_profit": risk.get("take_profit"),
            "blocked_reasons": blocked,
            "pre_risk_action": risk.get("pre_risk_action"),
            "profile_source": risk.get("profile_source"),
            "profile_name": risk.get("profile_name"),
            "profile_scope": risk.get("profile_scope"),
            "profile_scope_value": risk.get("profile_scope_value"),
        },
        "feedback": {
            "actual_label": prediction.get("actual_label"),
            "is_correct": prediction.get("is_correct"),
            "outcome_return": prediction.get("outcome_return"),
        },
        "indicators": {
            "rsi": None,
            "close": None,
            "sma_20": None,
        },
        "prediction_timestamp": prediction.get("timestamp"),
        "expected_return": prediction.get("expected_return"),
        "expected_risk": prediction.get("expected_risk"),
    }


def format_backtest_history_row(backtest: dict) -> dict:
    metrics = backtest.get("metrics") or {}
    params = backtest.get("params") or {}
    model = backtest.get("model_runs") or {}
    return {
        "id": backtest.get("id"),
        "name": backtest.get("name"),
        "started_at": backtest.get("started_at"),
        "ended_at": backtest.get("ended_at"),
        "created_at": backtest.get("created_at"),
        "metrics": {
            "total_return": metrics.get("total_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "profit_factor": metrics.get("profit_factor"),
            "active_trade_count": metrics.get("active_trade_count"),
            "trade_count": metrics.get("trade_count"),
            "win_rate": metrics.get("win_rate"),
            "exposure": metrics.get("exposure"),
            "final_equity": metrics.get("final_equity"),
        },
        "params": params,
        "model": {
            "name": model.get("model_name"),
            "version": model.get("model_version"),
            "run_id": backtest.get("model_run_id"),
            "feature_set": model.get("feature_set"),
            "label_method": model.get("label_method"),
            "horizon": model.get("horizon"),
        },
    }


def format_feedback_report(report) -> dict:
    return {
        "summary": report.summary,
        "by_action": [
            {
                "action": row.get("predicted_action"),
                "count": row.get("count"),
                "accuracy": row.get("accuracy"),
                "mean_confidence": row.get("mean_confidence"),
                "mean_outcome_return": row.get("mean_outcome_return"),
                "total_outcome_return": row.get("total_outcome_return"),
            }
            for row in report.by_action
        ],
        "by_confidence_bucket": [
            {
                "bucket": row.get("confidence_bucket"),
                "count": row.get("count"),
                "accuracy": row.get("accuracy"),
                "mean_confidence": row.get("mean_confidence"),
                "mean_outcome_return": row.get("mean_outcome_return"),
                "total_outcome_return": row.get("total_outcome_return"),
            }
            for row in report.by_confidence_bucket
        ],
    }


def build_operational_alerts(
    ticker: str,
    prices: pd.DataFrame,
    latest_prediction: dict | None,
    feedback_report,
    max_price_age_hours: float,
    min_feedback_samples: int,
    min_accuracy: float,
    min_mean_outcome_return: float,
    now: datetime | None = None,
) -> list[dict]:
    alerts: list[dict] = []
    now = now or datetime.now(tz=UTC)

    if prices.empty:
        alerts.append(
            {
                "severity": "critical",
                "code": "no_prices",
                "message": f"{ticker.upper()} no tiene precios disponibles para analisis.",
                "details": {},
            }
        )
    elif "timestamp" not in prices.columns:
        alerts.append(
            {
                "severity": "warning",
                "code": "missing_price_timestamp",
                "message": "La ultima lectura de precios no incluye timestamp.",
                "details": {},
            }
        )
    else:
        latest_price_at = pd.to_datetime(prices["timestamp"], utc=True, errors="coerce").max()
        if pd.isna(latest_price_at):
            alerts.append(
                {
                    "severity": "warning",
                    "code": "invalid_price_timestamp",
                    "message": "No se pudo interpretar la fecha de la ultima lectura de precios.",
                    "details": {},
                }
            )
        else:
            latest_price_dt = latest_price_at.to_pydatetime()
            age_hours = max((now - latest_price_dt).total_seconds() / 3600, 0)
            if age_hours > max_price_age_hours:
                alerts.append(
                    {
                        "severity": "warning",
                        "code": "stale_prices",
                        "message": "La ultima lectura de precios esta atrasada.",
                        "details": {
                            "latest_price_at": latest_price_dt.isoformat(),
                            "age_hours": round(age_hours, 2),
                            "max_price_age_hours": max_price_age_hours,
                        },
                    }
                )

    if not latest_prediction:
        alerts.append(
            {
                "severity": "warning",
                "code": "no_prediction",
                "message": "No hay una prediccion versionada reciente para este activo.",
                "details": {},
            }
        )

    summary = feedback_report.summary
    evaluated = int(summary.get("evaluated_predictions") or 0)
    accuracy = summary.get("accuracy")
    mean_outcome_return = summary.get("mean_outcome_return")

    if evaluated < min_feedback_samples:
        alerts.append(
            {
                "severity": "info",
                "code": "insufficient_feedback",
                "message": "Aun hay pocas predicciones evaluadas para juzgar estabilidad.",
                "details": {
                    "evaluated_predictions": evaluated,
                    "min_feedback_samples": min_feedback_samples,
                },
            }
        )
    else:
        if accuracy is not None and float(accuracy) < min_accuracy:
            alerts.append(
                {
                    "severity": "warning",
                    "code": "low_accuracy",
                    "message": "El acierto observado esta por debajo del umbral operativo.",
                    "details": {"accuracy": float(accuracy), "min_accuracy": min_accuracy},
                }
            )
        if mean_outcome_return is not None and float(mean_outcome_return) < min_mean_outcome_return:
            alerts.append(
                {
                    "severity": "warning",
                    "code": "negative_edge",
                    "message": "El retorno medio observado no supera el umbral minimo.",
                    "details": {
                        "mean_outcome_return": float(mean_outcome_return),
                        "min_mean_outcome_return": min_mean_outcome_return,
                    },
                }
            )

    return alerts


def format_operational_alerts(ticker: str, alerts: list[dict]) -> dict:
    return {
        "ticker": ticker.upper(),
        "status": alert_status(alerts),
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "alerts": alerts,
    }


def alert_status(alerts: list[dict]) -> str:
    severities = {str(alert.get("severity", "info")) for alert in alerts}
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    if "info" in severities:
        return "info"
    return "ok"


def persist_paper_trading_run(
    repository: LocalPostgresRepository,
    ticker: str,
    asset_id: str,
    predictions: pd.DataFrame,
    result,
    params: dict,
) -> str:
    model_run_id = _single_non_null_value(predictions, "model_run_id")
    started_at = result.timeline["timestamp"].min() if not result.timeline.empty else None
    ended_at = result.timeline["timestamp"].max() if not result.timeline.empty else None
    model_name = params.get("model_name") or _single_non_null_value(predictions, "model_name") or "model"
    model_version = params.get("model_version") or _single_non_null_value(predictions, "model_version") or "latest"
    name = f"{model_name}:{model_version}:{ticker.upper()}:paper"
    run_id = repository.create_paper_trading_run(
        name=name,
        model_run_id=model_run_id,
        asset_id=asset_id,
        metrics=result.metrics,
        params=params,
        started_at=started_at,
        ended_at=ended_at,
    )
    repository.insert_paper_trading_events(run_id, asset_id, result.timeline)
    return run_id


def format_paper_trading_response(ticker: str, result, persisted_run_id: str | None = None) -> dict:
    payload = {
        "ticker": ticker.upper(),
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "persisted_run_id": persisted_run_id,
        "metrics": result.metrics,
        "timeline": [
            {
                "timestamp": _isoformat_value(row.get("timestamp")),
                "action": row.get("action"),
                "confidence": row.get("confidence"),
                "price": row.get("price"),
                "mark_return": row.get("mark_return"),
                "exposure": row.get("exposure"),
                "exposure_delta": row.get("exposure_delta"),
                "cost": row.get("cost"),
                "equity": row.get("equity"),
                "position_state": row.get("position_state"),
                "metadata": row.get("metadata") or {},
            }
            for row in result.timeline.to_dict(orient="records")
        ],
    }
    return payload


def format_paper_trading_run_row(run: dict) -> dict:
    metrics = run.get("metrics") or {}
    params = run.get("params") or {}
    model = run.get("model_runs") or {}
    return {
        "id": run.get("id"),
        "name": run.get("name"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "created_at": run.get("created_at"),
        "metrics": {
            "initial_capital": metrics.get("initial_capital"),
            "final_equity": metrics.get("final_equity"),
            "total_return": metrics.get("total_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "signal_count": metrics.get("signal_count"),
            "trade_count": metrics.get("trade_count"),
            "active_signal_count": metrics.get("active_signal_count"),
            "average_abs_exposure": metrics.get("average_abs_exposure"),
            "open_exposure": metrics.get("open_exposure"),
            "open_position": metrics.get("open_position"),
            "last_price": metrics.get("last_price"),
            "profit_factor": metrics.get("profit_factor"),
            "fee_bps": metrics.get("fee_bps"),
            "slippage_bps": metrics.get("slippage_bps"),
            "allow_short": metrics.get("allow_short"),
        },
        "params": params,
        "model": {
            "name": model.get("model_name"),
            "version": model.get("model_version"),
            "run_id": run.get("model_run_id"),
            "feature_set": model.get("feature_set"),
            "label_method": model.get("label_method"),
            "horizon": model.get("horizon"),
        },
    }


def format_prediction_history_row(prediction: dict) -> dict:
    metadata = prediction.get("metadata") or {}
    risk = metadata.get("risk") or {}
    blocked = risk.get("blocked_reasons") or []
    return {
        "prediction_id": prediction.get("prediction_id"),
        "ticker": prediction.get("ticker"),
        "timestamp": prediction.get("timestamp"),
        "created_at": prediction.get("prediction_created_at"),
        "action": prediction.get("predicted_action") or prediction.get("action") or "HOLD",
        "confidence": prediction.get("confidence"),
        "probabilities": prediction.get("probabilities") or {},
        "expected_return": prediction.get("expected_return"),
        "expected_risk": prediction.get("expected_risk"),
        "model": {
            "name": prediction.get("model_name"),
            "version": prediction.get("model_version"),
            "run_id": prediction.get("model_run_id"),
            "feature_set": prediction.get("feature_set"),
            "label_method": prediction.get("label_method"),
            "horizon": prediction.get("horizon"),
        },
        "risk": {
            "position_size": risk.get("position_size", 0),
            "stop_loss": risk.get("stop_loss"),
            "take_profit": risk.get("take_profit"),
            "blocked_reasons": blocked,
        },
        "feedback": {
            "actual_label": prediction.get("actual_label"),
            "is_correct": prediction.get("is_correct"),
            "outcome_return": prediction.get("outcome_return"),
        },
    }


def _single_non_null_value(frame: pd.DataFrame, column: str) -> str | None:
    if frame.empty or column not in frame.columns:
        return None
    values = [value for value in frame[column].dropna().unique().tolist() if value]
    return str(values[0]) if len(values) == 1 else None


def _isoformat_value(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def demo_assets() -> list[dict]:
    return [
        {"id": "demo-btc-usd", "ticker": "BTC-USD", "name": "Bitcoin", "asset_class": "crypto"},
        {"id": "demo-eth-usd", "ticker": "ETH-USD", "name": "Ethereum", "asset_class": "crypto"},
        {"id": "demo-aapl", "ticker": "AAPL", "name": "Apple Inc.", "asset_class": "stock"},
        {"id": "demo-msft", "ticker": "MSFT", "name": "Microsoft Corp.", "asset_class": "stock"},
    ]


def is_demo_ticker(ticker: str) -> bool:
    return ticker.upper() in {asset["ticker"] for asset in demo_assets()}


def demo_prices(ticker: str, limit: int = 100) -> list[dict]:
    normalized = ticker.upper()
    profiles = {
        "BTC-USD": {"base": 106000.0, "trend": 0.0018, "cycle": 0.035, "period": 6.0, "phase": 0.0, "noise": 0.014},
        "ETH-USD": {"base": 5200.0, "trend": 0.0012, "cycle": 0.052, "period": 4.2, "phase": 1.4, "noise": 0.019},
        "AAPL": {"base": 225.0, "trend": 0.0007, "cycle": 0.018, "period": 9.0, "phase": 2.2, "noise": 0.006},
        "MSFT": {"base": 495.0, "trend": 0.0010, "cycle": 0.024, "period": 7.4, "phase": 3.1, "noise": 0.008},
    }
    profile = profiles.get(
        normalized,
        {"base": 100.0, "trend": 0.001, "cycle": 0.02, "period": 8.0, "phase": 0.8, "noise": 0.007},
    )
    rows = []
    today = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    for index in range(max(limit, 30)):
        age = max(limit, 30) - index
        trend = 1 + (index * profile["trend"])
        cycle = sin((index / profile["period"]) + profile["phase"]) * profile["cycle"]
        noise = cos((index * 1.7) + profile["phase"]) * profile["noise"]
        close = profile["base"] * trend * (1 + cycle + noise)
        rows.append(
            {
                "timestamp": (today - timedelta(days=age)).isoformat(),
                "open": round(close * 0.992, 2),
                "high": round(close * 1.018, 2),
                "low": round(close * 0.982, 2),
                "close": round(close, 2),
                "volume": int(1_000_000 + index * 7_500),
            }
        )

    return list(reversed(rows[-limit:]))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
