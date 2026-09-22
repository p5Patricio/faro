from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from brain.candidate_matrix import load_candidate_datasets
from brain.datasets import build_feature_frame_from_materialized
from brain.features import feature_columns_for_set
from brain.inference import PredictionPolicy, predict_actions
from brain.models import get_model_spec, train_final_model
from brain.risk import RiskPolicy, apply_risk_policy
from brain.scoped_evaluation import AssetDataset, asset_summaries, find_target_dataset, select_scope_datasets
from collector.local_repository import LocalPostgresRepository


@dataclass(frozen=True)
class PromotionResult:
    candidate: dict[str, Any]
    model_run_id: str | None
    artifact_uri: str
    metrics: dict[str, Any]
    prediction: dict[str, Any] | None = None


def default_promotion_version() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")


def load_candidate_report(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def select_candidate(
    report: dict[str, Any],
    candidate_id: str | None = None,
    rank: int = 1,
    allow_failed: bool = False,
) -> dict[str, Any]:
    ranking = report.get("ranking") or []
    if not ranking:
        raise ValueError("Candidate report has no ranking rows")

    if candidate_id:
        matches = [row for row in ranking if row.get("candidate_id") == candidate_id]
        if not matches:
            raise ValueError(f"Candidate not found in report: {candidate_id}")
        candidate = matches[0]
    else:
        eligible = [row for row in ranking if allow_failed or row.get("promotion", {}).get("status") == "pass"]
        if not eligible:
            raise ValueError("No promotable candidates found. Use allow_failed only for controlled experiments.")
        if rank < 1 or rank > len(eligible):
            raise ValueError(f"rank must be between 1 and {len(eligible)}")
        candidate = eligible[rank - 1]

    if not allow_failed and candidate.get("promotion", {}).get("status") != "pass":
        raise ValueError(f"Candidate is not promotable: {candidate.get('candidate_id')}")
    return candidate


def build_promoted_training_frame(
    datasets: list[AssetDataset],
    target_ticker: str,
    scope: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    scope_datasets = select_scope_datasets(datasets, target_ticker, scope)
    find_target_dataset(scope_datasets, target_ticker)
    frame = pd.concat([item.dataset for item in scope_datasets], ignore_index=True)
    frame = frame.sort_values(["timestamp", "ticker"]).reset_index(drop=True)
    return frame, asset_summaries(scope_datasets)


def promote_candidate_from_report(
    repository: LocalPostgresRepository,
    report: dict[str, Any],
    candidate: dict[str, Any],
    model_version: str,
    artifact_uri: str | Path,
    limit: int | None = None,
    min_rows: int = 120,
    persist: bool = True,
    generate_prediction: bool = True,
    latest_feature_limit: int = 1,
    risk_policy: RiskPolicy | None = None,
    prediction_batch_size: int = 500,
) -> PromotionResult:
    ticker = (candidate.get("target_ticker") or report["ticker"]).upper()
    model_name = candidate["model_name"]
    scope = candidate["scope"]
    feature_set = report["feature_set"]
    label_method = report["label_method"]
    horizon = int(report["horizon"])
    min_confidence = float(candidate.get("min_confidence") or 0.55)
    feature_columns = feature_columns_for_set(feature_set)
    datasets, skipped_assets = load_candidate_datasets(
        repository,
        feature_set=feature_set,
        label_method=label_method,
        horizon=horizon,
        feature_columns=feature_columns,
        limit=limit,
        min_rows=min_rows,
    )
    training_frame, participating_assets = build_promoted_training_frame(datasets, ticker, scope)
    model = train_final_model(training_frame, model_name=model_name, feature_columns=feature_columns)
    model_spec = get_model_spec(model_name)

    artifact_path = Path(artifact_uri)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, artifact_path, compress=3)

    metrics = build_promotion_metrics(
        report=report,
        candidate=candidate,
        model_version=model_version,
        estimator=model_spec.estimator,
        training_frame=training_frame,
        participating_assets=participating_assets,
        skipped_assets=skipped_assets,
    )
    model_run_id = None
    prediction_payload = None
    if persist:
        model_run_id = repository.create_model_run(
            model_name=model_name,
            model_version=model_version,
            feature_set=feature_set,
            label_method=label_method,
            horizon=horizon,
            train_start=training_frame["timestamp"].min(),
            train_end=training_frame["timestamp"].max(),
            params={
                "source": "candidate_matrix_promotion",
                "candidate_id": candidate.get("candidate_id"),
                "scope": scope,
                "target_ticker": ticker,
                "min_confidence": min_confidence,
                "feature_count": len(feature_columns),
                "participating_assets": participating_assets,
            },
            metrics=metrics,
            artifact_uri=str(artifact_path),
        )
        if generate_prediction:
            prediction_payload = generate_latest_prediction(
                repository=repository,
                ticker=ticker,
                model=model,
                model_run_id=model_run_id,
                feature_set=feature_set,
                feature_columns=feature_columns,
                min_confidence=min_confidence,
                latest_feature_limit=latest_feature_limit,
                risk_policy=risk_policy,
                batch_size=prediction_batch_size,
            )

    return PromotionResult(
        candidate=candidate,
        model_run_id=model_run_id,
        artifact_uri=str(artifact_path),
        metrics=metrics,
        prediction=prediction_payload,
    )


def build_promotion_metrics(
    report: dict[str, Any],
    candidate: dict[str, Any],
    model_version: str,
    estimator: str,
    training_frame: pd.DataFrame,
    participating_assets: list[dict[str, Any]],
    skipped_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "promotion": {
            "model_version": model_version,
            "source": "candidate_matrix",
            "candidate": candidate,
            "selection": report.get("selection"),
        },
        "training": {
            "rows": int(len(training_frame)),
            "train_start": pd.Timestamp(training_frame["timestamp"].min()).isoformat(),
            "train_end": pd.Timestamp(training_frame["timestamp"].max()).isoformat(),
            "label_distribution": training_frame["label"].value_counts().to_dict(),
            "participating_assets": participating_assets,
            "skipped_assets": skipped_assets,
        },
        "model": {
            "name": candidate["model_name"],
            "estimator": estimator,
            "scope": candidate["scope"],
            "min_confidence": candidate.get("min_confidence"),
        },
    }


def generate_latest_prediction(
    repository: LocalPostgresRepository,
    ticker: str,
    model,
    model_run_id: str,
    feature_set: str,
    feature_columns: list[str],
    min_confidence: float,
    latest_feature_limit: int,
    risk_policy: RiskPolicy | None = None,
    batch_size: int = 500,
) -> dict[str, Any]:
    asset_id = repository.get_asset_id(ticker)
    feature_rows = repository.get_features(
        asset_id=asset_id,
        feature_set=feature_set,
        limit=latest_feature_limit,
        ascending=False,
    )
    feature_frame = build_feature_frame_from_materialized(feature_rows, feature_columns=feature_columns)
    predictions = predict_actions(
        model,
        feature_frame,
        policy=PredictionPolicy(min_confidence=min_confidence),
        feature_columns=feature_columns,
    )
    predictions = apply_risk_policy(predictions, risk_policy or RiskPolicy())
    rows_loaded = repository.upsert_predictions(
        asset_id=asset_id,
        model_run_id=model_run_id,
        predictions=predictions,
        batch_size=batch_size,
    )
    return {
        "ticker": ticker.upper(),
        "model_run_id": model_run_id,
        "predictions_loaded": rows_loaded,
        "predictions": predictions.to_dict(orient="records"),
    }
