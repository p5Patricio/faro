from __future__ import annotations

import pandas as pd

from brain.features import FEATURE_COLUMNS, build_features, feature_columns_for_set
from brain.labeling import fixed_horizon_labels, triple_barrier_labels


def build_supervised_dataset(
    prices: list[dict] | pd.DataFrame,
    label_method: str = "triple_barrier",
    horizon: int = 5,
    buy_threshold: float = 0.015,
    sell_threshold: float = -0.015,
    profit_take: float = 0.03,
    stop_loss: float = 0.015,
    feature_set: str = "technical_v1",
) -> pd.DataFrame:
    """Create a training-ready dataset from OHLCV rows."""
    features = build_features(prices)

    if label_method == "fixed_horizon":
        labels = fixed_horizon_labels(
            prices,
            horizon=horizon,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
        )
    elif label_method == "triple_barrier":
        labels = triple_barrier_labels(
            prices,
            horizon=horizon,
            profit_take=profit_take,
            stop_loss=stop_loss,
        )
    else:
        raise ValueError("label_method must be 'fixed_horizon' or 'triple_barrier'")

    dataset = features.merge(labels, on="timestamp", how="inner")
    feature_columns = feature_columns_for_set(feature_set)
    required = feature_columns + ["label"]
    return dataset.dropna(subset=required).reset_index(drop=True)


def split_features_target(
    dataset: pd.DataFrame,
    feature_columns: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    columns = feature_columns or FEATURE_COLUMNS
    missing = set(columns + ["label"]) - set(dataset.columns)
    if missing:
        raise ValueError(f"Dataset missing required columns: {sorted(missing)}")

    return dataset[columns], dataset["label"]


def build_dataset_from_materialized(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    feature_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Build a training dataset from materialized features_daily and labels_daily rows."""
    columns = feature_columns or FEATURE_COLUMNS
    if features.empty:
        raise ValueError("No materialized features found")
    if labels.empty:
        raise ValueError("No materialized labels found")
    if not {"timestamp", "features"}.issubset(features.columns):
        raise ValueError("features must include timestamp and features columns")
    if not {"timestamp", "label"}.issubset(labels.columns):
        raise ValueError("labels must include timestamp and label columns")

    features_df = build_feature_frame_from_materialized(features, feature_columns=columns)

    labels_df = labels.copy()
    dataset = features_df.merge(labels_df, on="timestamp", how="inner")
    required = columns + ["label"]
    return dataset.dropna(subset=required).sort_values("timestamp").reset_index(drop=True)


def build_feature_frame_from_materialized(
    features: pd.DataFrame,
    feature_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Expand materialized feature JSON rows into timestamp + feature columns."""
    columns = feature_columns or FEATURE_COLUMNS
    if features.empty:
        raise ValueError("No materialized features found")
    if not {"timestamp", "features"}.issubset(features.columns):
        raise ValueError("features must include timestamp and features columns")

    expanded = pd.json_normalize(features["features"]).reindex(columns=columns)
    feature_frame = pd.concat([features[["timestamp"]].reset_index(drop=True), expanded], axis=1)
    return feature_frame.dropna(subset=columns).sort_values("timestamp").reset_index(drop=True)
