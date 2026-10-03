from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from brain.datasets import build_supervised_dataset
from brain.features import feature_columns_for_set
from brain.models import (
    DEFAULT_MODEL_NAME,
    available_model_names,
    get_model_spec,
    train_final_model,
    walk_forward_evaluate,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train an investment signal model")
    parser.add_argument("--prices-csv", required=True, help="CSV with timestamp, open, high, low, close, volume")
    parser.add_argument("--model-out", required=True, help="Path where the trained model will be saved")
    parser.add_argument("--metrics-out", help="Optional JSON path for walk-forward metrics")
    parser.add_argument("--label-method", choices=["fixed_horizon", "triple_barrier"], default="triple_barrier")
    parser.add_argument("--feature-set", default="technical_v1")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--profit-take", type=float, default=0.03)
    parser.add_argument("--stop-loss", type=float, default=0.015)
    parser.add_argument("--buy-threshold", type=float, default=0.015)
    parser.add_argument("--sell-threshold", type=float, default=-0.015)
    parser.add_argument("--splits", type=int, default=5)
    parser.add_argument("--model-name", choices=available_model_names(), default=DEFAULT_MODEL_NAME)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = pd.read_csv(args.prices_csv)
    dataset = build_supervised_dataset(
        prices,
        label_method=args.label_method,
        horizon=args.horizon,
        profit_take=args.profit_take,
        stop_loss=args.stop_loss,
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
        feature_set=args.feature_set,
    )
    feature_columns = feature_columns_for_set(args.feature_set)

    evaluation = walk_forward_evaluate(
        dataset,
        n_splits=args.splits,
        model_name=args.model_name,
        feature_columns=feature_columns,
        embargo_rows=args.horizon,
    )
    model = train_final_model(dataset, model_name=args.model_name, feature_columns=feature_columns)
    model_spec = get_model_spec(args.model_name)

    model_out = Path(args.model_out)
    model_out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_out, compress=3)

    metrics = {
        "model_name": args.model_name,
        "estimator": model_spec.estimator,
        "feature_set": args.feature_set,
        "label_method": args.label_method,
        "horizon": args.horizon,
        "summary": evaluation.summary,
        "folds": evaluation.fold_metrics,
    }
    if args.metrics_out:
        metrics_out = Path(args.metrics_out)
        metrics_out.parent.mkdir(parents=True, exist_ok=True)
        metrics_out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    else:
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
