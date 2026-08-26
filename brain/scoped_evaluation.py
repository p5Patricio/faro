from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from brain.backtesting import BacktestConfig, run_prediction_backtest
from brain.datasets import build_dataset_from_materialized
from brain.features import FEATURE_COLUMNS, feature_columns_for_set
from brain.inference import PredictionPolicy, predict_actions
from brain.models import DEFAULT_MODEL_NAME, create_model
from collector.local_repository import LocalPostgresRepository


SCOPE_LOCAL = "local"
SCOPE_ASSET_CLASS = "asset_class"
SCOPE_GLOBAL = "global"
SCOPES = {SCOPE_LOCAL, SCOPE_ASSET_CLASS, SCOPE_GLOBAL}


@dataclass(frozen=True)
class AssetDataset:
    asset_id: str
    ticker: str
    asset_class: str
    dataset: pd.DataFrame


@dataclass(frozen=True)
class ScopedBacktestResult:
    summary: dict
    folds: list[dict]
    predictions: pd.DataFrame
    participating_assets: list[dict]


def load_materialized_asset_dataset(
    repository: LocalPostgresRepository,
    asset: dict,
    feature_set: str,
    label_method: str,
    horizon: int,
    feature_columns: list[str] | None = None,
    limit: int | None = None,
) -> AssetDataset | None:
    columns = feature_columns or feature_columns_for_set(feature_set)
    features = repository.get_features(asset["id"], feature_set, limit=limit)
    labels = repository.get_labels(asset["id"], label_method, horizon, limit=limit)
    if features.empty or labels.empty:
        return None

    dataset = build_dataset_from_materialized(features, labels, feature_columns=columns)
    if dataset.empty:
        return None

    dataset = dataset.copy()
    dataset["asset_id"] = asset["id"]
    dataset["ticker"] = asset["ticker"]
    dataset["asset_class"] = asset.get("asset_class") or "unknown"
    return AssetDataset(
        asset_id=asset["id"],
        ticker=asset["ticker"],
        asset_class=asset.get("asset_class") or "unknown",
        dataset=dataset,
    )


def select_scope_datasets(
    datasets: list[AssetDataset],
    target_ticker: str,
    scope: str,
) -> list[AssetDataset]:
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope: {scope}. Available: {sorted(SCOPES)}")

    normalized_ticker = target_ticker.upper()
    target = find_target_dataset(datasets, normalized_ticker)
    if scope == SCOPE_LOCAL:
        return [target]
    if scope == SCOPE_ASSET_CLASS:
        return [item for item in datasets if item.asset_class == target.asset_class]
    return datasets


def find_target_dataset(datasets: list[AssetDataset], target_ticker: str) -> AssetDataset:
    for item in datasets:
        if item.ticker.upper() == target_ticker.upper():
            return item
    raise ValueError(f"Target dataset not found: {target_ticker}")


def run_scoped_walk_forward_backtest(
    datasets: list[AssetDataset],
    target_ticker: str,
    scope: str,
    n_splits: int = 5,
    test_size: int | None = None,
    embargo_rows: int = 0,
    trade_stride: int = 1,
    model_name: str = DEFAULT_MODEL_NAME,
    feature_columns: list[str] | None = None,
    prediction_policy: PredictionPolicy | None = None,
    config: BacktestConfig | None = None,
) -> ScopedBacktestResult:
    columns = feature_columns or FEATURE_COLUMNS
    config = config or BacktestConfig()
    prediction_policy = prediction_policy or PredictionPolicy()
    scope_datasets = select_scope_datasets(datasets, target_ticker, scope)
    target = find_target_dataset(scope_datasets, target_ticker)
    target_data = target.dataset.sort_values("timestamp").reset_index(drop=True)

    if len(target_data) < max(30, n_splits + 2):
        raise ValueError("Not enough target rows for scoped walk-forward backtest")
    if embargo_rows < 0:
        raise ValueError("embargo_rows must be non-negative")
    if trade_stride < 1:
        raise ValueError("trade_stride must be at least 1")

    splitter = TimeSeriesSplit(n_splits=n_splits, test_size=test_size, gap=embargo_rows)
    fold_summaries = []
    prediction_frames = []

    for fold, (train_idx, test_idx) in enumerate(splitter.split(target_data), start=1):
        target_train = target_data.iloc[train_idx]
        target_test = target_data.iloc[test_idx].copy()
        train_end = target_train["timestamp"].max()
        train_data = build_scope_training_frame(scope_datasets, target, target_train, train_end)

        model = create_model(model_name)
        model.fit(train_data[columns], train_data["label"])

        predicted = predict_actions(
            model,
            target_test[["timestamp", *columns]],
            policy=prediction_policy,
            feature_columns=columns,
        )
        feedback = prediction_feedback_frame(predicted, target_test)
        if trade_stride > 1:
            feedback = feedback.iloc[::trade_stride].reset_index(drop=True)
        feedback["fold"] = fold
        feedback["scope"] = scope
        prediction_frames.append(feedback)

        fold_backtest = run_prediction_backtest(feedback, config)
        fold_summaries.append(
            {
                "fold": fold,
                "scope": scope,
                "train_rows": int(len(train_data)),
                "target_train_rows": int(len(target_train)),
                "test_rows": int(len(target_test)),
                "test_start": pd.Timestamp(target_test["timestamp"].min()).isoformat(),
                "test_end": pd.Timestamp(target_test["timestamp"].max()).isoformat(),
                "model_total_return": fold_backtest.metrics["total_return"],
                "model_max_drawdown": fold_backtest.metrics["max_drawdown"],
                "model_active_trade_count": fold_backtest.metrics["active_trade_count"],
                "model_win_rate": fold_backtest.metrics["win_rate"],
            }
        )

    predictions = pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
    model_backtest = run_prediction_backtest(predictions, config)
    baselines = {
        "no_trade": run_prediction_backtest(baseline_feedback(predictions, "HOLD"), config),
        "always_buy": run_prediction_backtest(baseline_feedback(predictions, "BUY"), config),
    }
    if config.allow_short:
        baselines["always_sell"] = run_prediction_backtest(baseline_feedback(predictions, "SELL"), config)

    summary = {
        "scope": scope,
        "target_ticker": target.ticker,
        "target_asset_class": target.asset_class,
        "participating_asset_count": len(scope_datasets),
        "rows": int(sum(len(item.dataset) for item in scope_datasets)),
        "target_rows": int(len(target_data)),
        "evaluated_rows": int(len(predictions)),
        "n_splits": int(n_splits),
        "test_size": test_size,
        "embargo_rows": int(embargo_rows),
        "trade_stride": int(trade_stride),
        "min_confidence": prediction_policy.min_confidence,
        "model_name": model_name,
        "features": columns,
        "model": model_backtest.metrics,
        "baselines": {name: result.metrics for name, result in baselines.items()},
    }
    return ScopedBacktestResult(
        summary=summary,
        folds=fold_summaries,
        predictions=predictions,
        participating_assets=asset_summaries(scope_datasets),
    )


def build_scope_training_frame(
    scope_datasets: list[AssetDataset],
    target: AssetDataset,
    target_train: pd.DataFrame,
    train_end: pd.Timestamp,
) -> pd.DataFrame:
    frames = []
    for item in scope_datasets:
        if item.asset_id == target.asset_id:
            frames.append(target_train)
        else:
            frames.append(item.dataset[item.dataset["timestamp"] <= train_end])
    train_data = pd.concat(frames, ignore_index=True)
    return train_data.sort_values(["timestamp", "ticker"]).reset_index(drop=True)


def prediction_feedback_frame(predictions: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    frame = predictions.rename(columns={"action": "predicted_action"}).copy()
    merged = frame.merge(labels[["timestamp", "label", "outcome_return"]], on="timestamp", how="left")
    merged = merged.rename(columns={"label": "actual_label"})
    merged["is_correct"] = merged["predicted_action"] == merged["actual_label"]
    return merged


def baseline_feedback(predictions: pd.DataFrame, action: str) -> pd.DataFrame:
    if predictions.empty:
        return predictions.copy()
    baseline = predictions.copy()
    baseline["predicted_action"] = action
    baseline["confidence"] = 1.0
    baseline["is_correct"] = baseline["predicted_action"] == baseline["actual_label"]
    return baseline


def asset_summaries(datasets: list[AssetDataset]) -> list[dict]:
    return [
        {
            "asset_id": item.asset_id,
            "ticker": item.ticker,
            "asset_class": item.asset_class,
            "rows": int(len(item.dataset)),
        }
        for item in datasets
    ]
