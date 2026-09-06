from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import joblib

from brain.artifacts import resolve_model_artifact
from brain.features import feature_columns_for_set
from brain.promotion import generate_latest_prediction
from brain.risk import RiskPolicy
from collector.local_repository import LocalPostgresRepository


PROMOTION_SOURCE = "candidate_matrix_promotion"


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
