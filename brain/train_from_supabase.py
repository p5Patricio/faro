from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import psycopg

from brain.datasets import build_dataset_from_materialized
from brain.features import feature_columns_for_set
from brain.models import (
    DEFAULT_MODEL_NAME,
    available_model_names,
    get_model_spec,
    train_final_model,
    walk_forward_evaluate,
)
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


def default_model_version() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a model from materialized local Postgres features and labels")
    parser.add_argument("--ticker", required=True, help="Asset ticker stored locally")
    parser.add_argument("--feature-set", default="technical_v1")
    parser.add_argument("--label-method", choices=["fixed_horizon", "triple_barrier"], default="triple_barrier")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--model-name", choices=available_model_names(), default=DEFAULT_MODEL_NAME)
    parser.add_argument("--model-version", default=default_model_version())
    parser.add_argument("--model-out", help="Optional path for the trained joblib artifact")
    parser.add_argument("--metrics-out", help="Optional JSON path for metrics")
    parser.add_argument("--limit", type=int, help="Optional max number of materialized rows to read")
    parser.add_argument("--splits", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    feature_columns = feature_columns_for_set(args.feature_set)

    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        asset_id = repository.get_asset_id(args.ticker)
        features = repository.get_features(asset_id, args.feature_set, limit=args.limit)
        labels = repository.get_labels(asset_id, args.label_method, args.horizon, limit=args.limit)
        dataset = build_dataset_from_materialized(features, labels, feature_columns=feature_columns)

        evaluation = walk_forward_evaluate(
            dataset,
            n_splits=args.splits,
            model_name=args.model_name,
            feature_columns=feature_columns,
        )
        model = train_final_model(dataset, model_name=args.model_name, feature_columns=feature_columns)
        model_spec = get_model_spec(args.model_name)

        artifact_path = Path(
            args.model_out or f"models/{args.ticker.upper()}_{args.model_name}_{args.feature_set}_{args.model_version}.joblib"
        )
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, artifact_path, compress=3)

        metrics = {
            "ticker": args.ticker.upper(),
            "asset_id": asset_id,
            "model_name": args.model_name,
            "model_version": args.model_version,
            "feature_set": args.feature_set,
            "label_method": args.label_method,
            "horizon": args.horizon,
            "summary": evaluation.summary,
            "folds": evaluation.fold_metrics,
        }

        if args.metrics_out:
            metrics_path = Path(args.metrics_out)
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        model_run_id = repository.create_model_run(
            model_name=args.model_name,
            model_version=args.model_version,
            feature_set=args.feature_set,
            label_method=args.label_method,
            horizon=args.horizon,
            train_start=dataset["timestamp"].min(),
            train_end=dataset["timestamp"].max(),
            params={"splits": args.splits, "estimator": model_spec.estimator},
            metrics=metrics,
            artifact_uri=str(artifact_path),
        )

    print(
        json.dumps(
            {
                "model_run_id": model_run_id,
                "artifact_uri": str(artifact_path),
                "metrics": metrics,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
