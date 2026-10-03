from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from brain.datasets import split_features_target
from brain.features import FEATURE_COLUMNS


DEFAULT_MODEL_NAME = "baseline_hist_gradient_boosting"


@dataclass
class WalkForwardResult:
    fold_metrics: list[dict]
    summary: dict


@dataclass(frozen=True)
class ModelSpec:
    name: str
    estimator: str
    description: str


MODEL_SPECS = {
    DEFAULT_MODEL_NAME: ModelSpec(
        name=DEFAULT_MODEL_NAME,
        estimator="HistGradientBoostingClassifier",
        description="Gradient boosting baseline for tabular technical features.",
    ),
    "logistic_regression": ModelSpec(
        name="logistic_regression",
        estimator="LogisticRegression",
        description="Regularized linear baseline with balanced class weights.",
    ),
    "random_forest": ModelSpec(
        name="random_forest",
        estimator="RandomForestClassifier",
        description="Bagged decision tree ensemble with balanced bootstrap class weights.",
    ),
    "extra_trees": ModelSpec(
        name="extra_trees",
        estimator="ExtraTreesClassifier",
        description="Randomized tree ensemble for non-linear tabular baselines.",
    ),
}


def available_model_names() -> list[str]:
    return sorted(MODEL_SPECS)


def get_model_spec(model_name: str = DEFAULT_MODEL_NAME) -> ModelSpec:
    try:
        return MODEL_SPECS[model_name]
    except KeyError as error:
        raise ValueError(f"Unknown model_name: {model_name}. Available: {available_model_names()}") from error


def create_model(model_name: str = DEFAULT_MODEL_NAME, random_state: int = 42) -> Pipeline:
    get_model_spec(model_name)
    if model_name == DEFAULT_MODEL_NAME:
        return Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    HistGradientBoostingClassifier(
                        learning_rate=0.05,
                        max_iter=200,
                        l2_regularization=0.01,
                        random_state=random_state,
                    ),
                ),
            ]
        )
    if model_name == "logistic_regression":
        return Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        class_weight="balanced",
                        max_iter=2000,
                    ),
                ),
            ]
        )
    if model_name == "random_forest":
        return Pipeline(
            steps=[
                (
                    "classifier",
                    RandomForestClassifier(
                        n_estimators=300,
                        min_samples_leaf=5,
                        class_weight="balanced_subsample",
                        random_state=random_state,
                        n_jobs=-1,
                    ),
                )
            ]
        )
    if model_name == "extra_trees":
        return Pipeline(
            steps=[
                (
                    "classifier",
                    ExtraTreesClassifier(
                        n_estimators=300,
                        min_samples_leaf=5,
                        class_weight="balanced",
                        random_state=random_state,
                        n_jobs=-1,
                    ),
                )
            ]
        )

    raise ValueError(f"Unknown model_name: {model_name}")


def create_baseline_model(random_state: int = 42) -> Pipeline:
    return create_model(DEFAULT_MODEL_NAME, random_state=random_state)


def walk_forward_evaluate(
    dataset: pd.DataFrame,
    n_splits: int = 5,
    test_size: int | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    feature_columns: list[str] | None = None,
    embargo_rows: int = 0,
) -> WalkForwardResult:
    """Evaluate a classifier with chronological train/test folds.

    ``embargo_rows`` rows are dropped between each train and test fold. Pass
    the label horizon: a row labelled with the price ``horizon`` bars ahead
    otherwise leaks test-period prices into the training fold."""
    if len(dataset) < max(30, n_splits + 2):
        raise ValueError("Not enough rows for walk-forward evaluation")
    if embargo_rows < 0:
        raise ValueError("embargo_rows must be non-negative")

    columns = feature_columns or FEATURE_COLUMNS
    X, y = split_features_target(dataset, feature_columns=columns)
    splitter = TimeSeriesSplit(n_splits=n_splits, test_size=test_size, gap=embargo_rows)
    fold_metrics = []
    model_spec = get_model_spec(model_name)

    for fold, (train_idx, test_idx) in enumerate(splitter.split(X), start=1):
        model = create_model(model_name)
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        model.fit(X_train, y_train)
        predictions = model.predict(X_test)

        fold_metrics.append(
            {
                "fold": fold,
                "train_rows": len(train_idx),
                "test_rows": len(test_idx),
                "accuracy": float(accuracy_score(y_test, predictions)),
                "balanced_accuracy": float(balanced_accuracy_score(y_test, predictions)),
                "f1_macro": float(f1_score(y_test, predictions, average="macro", zero_division=0)),
            }
        )

    metrics_df = pd.DataFrame(fold_metrics)
    summary = {
        "rows": len(dataset),
        "model_name": model_name,
        "estimator": model_spec.estimator,
        "features": columns,
        "embargo_rows": embargo_rows,
        "mean_accuracy": float(metrics_df["accuracy"].mean()),
        "mean_balanced_accuracy": float(metrics_df["balanced_accuracy"].mean()),
        "mean_f1_macro": float(metrics_df["f1_macro"].mean()),
    }
    return WalkForwardResult(fold_metrics=fold_metrics, summary=summary)


def train_final_model(
    dataset: pd.DataFrame,
    model_name: str = DEFAULT_MODEL_NAME,
    feature_columns: list[str] | None = None,
) -> Pipeline:
    X, y = split_features_target(dataset, feature_columns=feature_columns)
    model = create_model(model_name)
    model.fit(X, y)
    return model
