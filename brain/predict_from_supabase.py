from __future__ import annotations

import argparse
import json

import joblib
import psycopg

from brain.artifacts import resolve_model_artifact
from brain.datasets import build_feature_frame_from_materialized
from brain.features import feature_columns_for_set
from brain.inference import PredictionPolicy, predict_actions
from brain.risk import RiskPolicy, apply_risk_policy
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and store model predictions from local Postgres features")
    parser.add_argument("--ticker", required=True, help="Asset ticker stored locally")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--limit", type=int, default=1, help="Number of most recent feature rows to score")
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--min-confidence-to-trade", type=float, default=0.60)
    parser.add_argument("--max-position-size", type=float, default=0.10)
    parser.add_argument("--max-expected-risk", type=float, default=0.05)
    parser.add_argument("--stop-loss", type=float, default=0.02)
    parser.add_argument("--take-profit", type=float, default=0.04)
    parser.add_argument("--no-short", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        asset_id = repository.get_asset_id(args.ticker)
        model_run = repository.get_model_run(args.model_name, args.model_version)
        artifact_uri = model_run.get("artifact_uri")
        if not artifact_uri:
            raise RuntimeError(f"Model run has no artifact_uri: {args.model_name}:{args.model_version}")

        model = joblib.load(resolve_model_artifact(str(artifact_uri)))
        feature_columns = feature_columns_for_set(model_run["feature_set"])
        feature_rows = repository.get_features(
            asset_id=asset_id,
            feature_set=model_run["feature_set"],
            limit=args.limit,
            ascending=False,
        )
        feature_frame = build_feature_frame_from_materialized(feature_rows, feature_columns=feature_columns)
        predictions = predict_actions(
            model,
            feature_frame,
            policy=PredictionPolicy(min_confidence=args.min_confidence),
            feature_columns=feature_columns,
        )
        predictions = apply_risk_policy(
            predictions,
            RiskPolicy(
                max_position_size=args.max_position_size,
                min_confidence_to_trade=args.min_confidence_to_trade,
                max_expected_risk=args.max_expected_risk,
                stop_loss=args.stop_loss,
                take_profit=args.take_profit,
                allow_short=not args.no_short,
            ),
        )
        rows_loaded = repository.upsert_predictions(
            asset_id=asset_id,
            model_run_id=model_run["id"],
            predictions=predictions,
            batch_size=args.batch_size,
        )

    print(
        json.dumps(
            {
                "ticker": args.ticker.upper(),
                "model_run_id": model_run["id"],
                "model_name": args.model_name,
                "model_version": args.model_version,
                "predictions_loaded": rows_loaded,
                "predictions": predictions.to_dict(orient="records"),
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
