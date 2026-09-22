from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import joblib
import pandas as pd

from brain.artifacts import resolve_model_artifact
from brain.features import feature_columns_for_set
from brain.portfolio_risk import PortfolioRiskPolicy, apply_portfolio_risk_policy
from brain.promotion import generate_latest_prediction
from brain.risk import RiskPolicy
from collector.local_repository import LocalPostgresRepository


PROMOTION_SOURCE = "candidate_matrix_promotion"

# Trading-day lookback for the correlation-estimation return history: long
# enough for Ledoit-Wolf shrinkage to be meaningful (see
# `PortfolioRiskPolicy.min_returns_observations`), short enough that a
# ticker's regime shift a year ago does not dominate today's cluster call.
PORTFOLIO_RISK_PRICE_HISTORY_LIMIT = 252


def load_promoted_model_runs(
    repository: LocalPostgresRepository,
    model_name: str | None = None,
    model_version: str | None = None,
    limit: int | None = None,
    include_unpromoted: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    model_runs = repository.get_model_runs(
        model_name=model_name,
        model_version=model_version,
        limit=limit,
        ascending=False,
    )
    selected = []
    skipped = []
    # model_runs arrives newest-first (ascending=False). Only the most
    # recent promoted run per ticker serves predictions -- a later
    # promotion supersedes an earlier one regardless of feature set, so a
    # freshly adopted fundamental_v1 model replaces the technical_v2 one it
    # beat instead of both writing competing predictions (see
    # find_incumbent_model_run: adoption is already gated on objective_score).
    seen_tickers: set[str] = set()
    for model_run in model_runs:
        if not (include_unpromoted or is_promoted_model_run(model_run)):
            skipped.append(
                {
                    "model_run_id": model_run.get("id"),
                    "model_name": model_run.get("model_name"),
                    "model_version": model_run.get("model_version"),
                    "reason": "not_promoted",
                }
            )
            continue

        ticker = target_ticker_for_model_run(model_run, required=False)
        if ticker is not None:
            if ticker in seen_tickers:
                skipped.append(
                    {
                        "model_run_id": model_run.get("id"),
                        "model_name": model_run.get("model_name"),
                        "model_version": model_run.get("model_version"),
                        "reason": "superseded_by_newer_promotion",
                    }
                )
                continue
            seen_tickers.add(ticker)

        selected.append(model_run)
    return selected, skipped


def run_latest_inference_job(
    repository: LocalPostgresRepository,
    model_runs: list[dict[str, Any]],
    latest_feature_limit: int = 1,
    min_confidence: float | None = None,
    risk_policy: RiskPolicy | None = None,
    portfolio_risk_policy: PortfolioRiskPolicy | None = None,
    batch_size: int = 500,
    continue_on_error: bool = True,
) -> dict[str, Any]:
    started_at = datetime.now(tz=UTC)
    results = []
    errors = []

    for model_run in model_runs:
        context = {
            "model_run_id": model_run.get("id"),
            "model_name": model_run.get("model_name"),
            "model_version": model_run.get("model_version"),
        }
        try:
            ticker = target_ticker_for_model_run(model_run)
            artifact_uri = model_run.get("artifact_uri")
            if not artifact_uri:
                raise ValueError("model_run_missing_artifact_uri")
            artifact_path = resolve_model_artifact(str(artifact_uri))

            model = joblib.load(artifact_path)
            feature_columns = feature_columns_for_set(model_run["feature_set"])

            # Read the previously stored prediction for this ticker/model
            # BEFORE generate_latest_prediction upserts the new one, otherwise
            # this read would return the row we are about to write (Req:
            # Signal Alerts Fire Only on Action Transition).
            asset_id = repository.get_asset_id(ticker)
            previous = repository.get_latest_prediction(asset_id, model_name=model_run["model_name"])

            prediction = generate_latest_prediction(
                repository=repository,
                ticker=ticker,
                model=model,
                model_run_id=model_run["id"],
                feature_set=model_run["feature_set"],
                feature_columns=feature_columns,
                min_confidence=min_confidence
                if min_confidence is not None
                else min_confidence_for_model_run(model_run),
                latest_feature_limit=latest_feature_limit,
                risk_policy=risk_policy,
                batch_size=batch_size,
            )
            results.append(
                {
                    **context,
                    "ticker": ticker,
                    "predictions_loaded": prediction["predictions_loaded"],
                    "latest_prediction": prediction["predictions"][0] if prediction["predictions"] else None,
                    "previous_action": previous.get("predicted_action") if previous else None,
                }
            )
        except Exception as error:
            errors.append({**context, "error": str(error)})
            if not continue_on_error:
                raise

    # Every per-ticker `apply_risk_policy` call above (inside
    # `generate_latest_prediction`) already sized this ticker's signal in
    # isolation -- it has no view of what every *other* ticker in this same
    # run is about to trade. Now that `results` holds the whole run's
    # BUY/SELL batch, cap combined exposure across tickers whose historical
    # returns are highly correlated, without touching any `action` the
    # model + single-signal risk policy already decided.
    #
    # Wrapped like every per-ticker step above: a portfolio-risk failure
    # (a transient DB error, a numerical issue in the covariance estimate)
    # must not discard the results already collected for every ticker that
    # DID succeed -- that would violate `continue_on_error`'s contract for
    # the whole run, not just a single ticker.
    try:
        _apply_portfolio_risk_to_results(repository, results, portfolio_risk_policy or PortfolioRiskPolicy())
    except Exception as error:
        errors.append({"model_run_id": None, "step": "portfolio_risk", "error": str(error)})
        if not continue_on_error:
            raise

    ended_at = datetime.now(tz=UTC)
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "attempted": len(model_runs),
        "succeeded": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


def _apply_portfolio_risk_to_results(
    repository: LocalPostgresRepository,
    results: list[dict[str, Any]],
    policy: PortfolioRiskPolicy,
) -> None:
    """Mutate `results` in place: scale down `latest_prediction`s for
    tickers whose combined correlated exposure exceeds the policy cap, and
    re-persist the adjusted rows. A run with fewer than two sized BUY/SELL
    signals has nothing to correlate, so it returns without touching the
    repository at all -- this keeps single-ticker runs (and the minimal
    repository stubs used by their tests) unaffected."""
    candidates = [result for result in results if _prediction_position_size(result.get("latest_prediction")) > 0.0]
    if len(candidates) < 2:
        return

    returns = _historical_returns(repository, [result["ticker"] for result in candidates])
    predictions = pd.DataFrame(
        [
            {
                "ticker": result["ticker"],
                "action": result["latest_prediction"]["action"],
                "position_size": _prediction_position_size(result["latest_prediction"]),
                "metadata": dict(result["latest_prediction"].get("metadata") or {}),
            }
            for result in candidates
        ]
    )

    adjusted = apply_portfolio_risk_policy(predictions, returns, policy)

    for result, (_, adjusted_row) in zip(candidates, adjusted.iterrows(), strict=True):
        prediction = result["latest_prediction"]
        metadata = adjusted_row["metadata"]
        prediction["metadata"] = metadata
        risk = metadata.get("risk")
        if isinstance(risk, dict):
            risk["position_size"] = adjusted_row["position_size"]
        _persist_adjusted_prediction(repository, result, prediction)


def _persist_adjusted_prediction(
    repository: LocalPostgresRepository,
    result: dict[str, Any],
    prediction: dict[str, Any],
) -> None:
    """Re-upsert this ticker's prediction row so the portfolio-adjusted
    `position_size` actually reaches downstream readers of stored
    predictions (e.g. `brain.paper_trading._position_size`, which reads
    `metadata.risk.position_size` straight off the row) instead of only
    existing in this run's in-memory report. `generate_latest_prediction`
    already upserted this exact row (per ticker, single-signal-sized)
    earlier in this same run; `upsert_predictions` conflicts on
    `(asset_id, model_run_id, timestamp)`, so this updates it in place
    rather than inserting a duplicate."""
    if "timestamp" not in prediction:
        return
    asset_id = repository.get_asset_id(result["ticker"])
    repository.upsert_predictions(
        asset_id=asset_id,
        model_run_id=result["model_run_id"],
        predictions=pd.DataFrame([prediction]),
    )


def _historical_returns(repository: LocalPostgresRepository, tickers: list[str]) -> pd.DataFrame:
    """Build a tickers-by-dates simple-return frame from stored daily
    closes. `collector.local_repository.LocalPostgresRepository` has no
    multi-ticker batch price read, so this loops the same
    `get_asset_id`/`get_prices` primitives `brain.materialize_technical_alpha`
    uses for one ticker at a time and pivots the per-ticker close series into
    one wide frame for `brain.portfolio_risk`'s correlation estimate."""
    closes: dict[str, pd.Series] = {}
    for ticker in tickers:
        asset_id = repository.get_asset_id(ticker)
        prices = repository.get_prices(asset_id, limit=PORTFOLIO_RISK_PRICE_HISTORY_LIMIT, ascending=True)
        if prices.empty or "close" not in prices.columns:
            continue
        closes[ticker] = prices.set_index("timestamp")["close"].astype(float)

    if len(closes) < 2:
        return pd.DataFrame()
    return pd.DataFrame(closes).pct_change().dropna(how="all")


def _prediction_position_size(prediction: dict[str, Any] | None) -> float:
    if not prediction:
        return 0.0
    metadata = prediction.get("metadata") or {}
    risk = metadata.get("risk") or {}
    value = risk.get("position_size")
    if value is None:
        return 0.0
    return float(value)


def is_promoted_model_run(model_run: dict[str, Any]) -> bool:
    params = model_run.get("params") or {}
    return params.get("source") == PROMOTION_SOURCE and bool(target_ticker_for_model_run(model_run, required=False))


def target_ticker_for_model_run(model_run: dict[str, Any], required: bool = True) -> str | None:
    params = model_run.get("params") or {}
    metrics = model_run.get("metrics") or {}
    candidate = (metrics.get("promotion") or {}).get("candidate") or {}
    ticker = params.get("target_ticker") or candidate.get("target_ticker")
    if ticker:
        return str(ticker).upper()
    if required:
        raise ValueError("model_run_missing_target_ticker")
    return None


def min_confidence_for_model_run(model_run: dict[str, Any], default: float = 0.55) -> float:
    params = model_run.get("params") or {}
    metrics = model_run.get("metrics") or {}
    candidate = (metrics.get("promotion") or {}).get("candidate") or {}
    value = params.get("min_confidence", candidate.get("min_confidence", default))
    return float(value)
