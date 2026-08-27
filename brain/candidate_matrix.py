from __future__ import annotations

from typing import Any

from brain.backtesting import BacktestConfig
from brain.features import feature_columns_for_set
from brain.inference import PredictionPolicy
from brain.models import DEFAULT_MODEL_NAME
from brain.scoped_evaluation import (
    AssetDataset,
    load_materialized_asset_dataset,
    run_scoped_walk_forward_backtest,
)
from brain.selection import PromotionCriteria, rank_candidate_summaries
from collector.local_repository import LocalPostgresRepository


def load_candidate_datasets(
    repository: LocalPostgresRepository,
    feature_set: str,
    label_method: str,
    horizon: int,
    feature_columns: list[str] | None = None,
    limit: int | None = None,
    min_rows: int = 120,
) -> tuple[list[AssetDataset], list[dict[str, Any]]]:
    columns = feature_columns or feature_columns_for_set(feature_set)
    datasets = []
    skipped_assets = []

    for asset in repository.get_assets():
        try:
            item = load_materialized_asset_dataset(
                repository,
                asset,
                feature_set=feature_set,
                label_method=label_method,
                horizon=horizon,
                feature_columns=columns,
                limit=limit,
            )
        except ValueError as error:
            skipped_assets.append({"ticker": asset.get("ticker"), "reason": str(error)})
            continue
        if item is None:
            skipped_assets.append({"ticker": asset.get("ticker"), "reason": "no_materialized_dataset"})
            continue
        if len(item.dataset) < min_rows:
            skipped_assets.append({"ticker": item.ticker, "reason": f"rows_below_minimum:{len(item.dataset)}"})
            continue
        datasets.append(item)

    return datasets, skipped_assets


def run_candidate_matrix(
    datasets: list[AssetDataset],
    target_ticker: str,
    scopes: list[str],
    model_names: list[str] | None = None,
    confidence_thresholds: list[float] | None = None,
    n_splits: int = 5,
    test_size: int | None = None,
    embargo_rows: int = 0,
    trade_stride: int = 1,
    feature_columns: list[str] | None = None,
    backtest_config: BacktestConfig | None = None,
    promotion_criteria: PromotionCriteria | None = None,
    drawdown_penalty: float = 1.0,
    include_details: bool = False,
    continue_on_error: bool = True,
) -> dict[str, Any]:
    names = model_names or [DEFAULT_MODEL_NAME]
    thresholds = confidence_thresholds or [0.55]
    criteria = promotion_criteria or PromotionCriteria()
    config = backtest_config or BacktestConfig()
    results = []
    errors = []

    for model_name in names:
        for threshold in thresholds:
            for scope in scopes:
                candidate_id = build_candidate_id(target_ticker, model_name, threshold, scope)
                try:
                    result = run_scoped_walk_forward_backtest(
                        datasets,
                        target_ticker=target_ticker,
                        scope=scope,
                        n_splits=n_splits,
                        test_size=test_size,
                        embargo_rows=embargo_rows,
                        trade_stride=trade_stride,
                        model_name=model_name,
                        feature_columns=feature_columns,
                        prediction_policy=PredictionPolicy(min_confidence=threshold),
                        config=config,
                    )
                except Exception as error:
                    errors.append(
                        {
                            "candidate_id": candidate_id,
                            "model_name": model_name,
                            "min_confidence": threshold,
                            "scope": scope,
                            "error": str(error),
                        }
                    )
                    if continue_on_error:
                        continue
                    raise

                summary = {
                    **result.summary,
                    "candidate_id": candidate_id,
                    "model_name": model_name,
                    "min_confidence": threshold,
                }
                row = {"candidate_id": candidate_id, "summary": summary}
                if include_details:
                    row["folds"] = result.folds
                    row["participating_assets"] = result.participating_assets
                results.append(row)

    return {
        "results": results,
        "ranking": rank_candidate_summaries(
            [result["summary"] for result in results],
            criteria=criteria,
            drawdown_penalty=drawdown_penalty,
        ),
        "errors": errors,
    }


def build_candidate_id(target_ticker: str, model_name: str, min_confidence: float, scope: str) -> str:
    return f"{target_ticker.upper()}::{model_name}::confidence_{min_confidence:.4f}::{scope}"
