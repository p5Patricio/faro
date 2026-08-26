from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from brain.promotion import (
    default_promotion_version,
    load_candidate_report,
    promote_candidate_from_report,
    select_candidate,
)
from brain.risk import RiskPolicy
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote the best candidate matrix row into a versioned model run")
    parser.add_argument("--report", required=True, help="Candidate matrix JSON report path")
    parser.add_argument("--candidate-id", help="Specific candidate_id to promote. Defaults to the top passing rank")
    parser.add_argument("--rank", type=int, default=1, help="Passing candidate rank to promote when no candidate-id is given")
    parser.add_argument("--allow-failed", action="store_true", help="Allow promoting a candidate that failed promotion gates")
    parser.add_argument("--model-version", default=default_promotion_version())
    parser.add_argument("--model-out", help="Optional artifact path. Defaults to models/<ticker>_<model>_<scope>_<version>.joblib")
    parser.add_argument("--limit", type=int, help="Optional max number of materialized rows per asset")
    parser.add_argument("--min-rows", type=int, default=120, help="Minimum materialized rows required per asset")
    parser.add_argument("--skip-prediction", action="store_true", help="Train and register only, without writing latest prediction")
    parser.add_argument("--latest-feature-limit", type=int, default=1)
    parser.add_argument("--min-confidence-to-trade", type=float, default=0.60)
    parser.add_argument("--max-position-size", type=float, default=0.10)
    parser.add_argument("--max-expected-risk", type=float, default=0.05)
    parser.add_argument("--stop-loss", type=float, default=0.02)
    parser.add_argument("--take-profit", type=float, default=0.04)
    parser.add_argument("--no-short", action="store_true")
    parser.add_argument("--prediction-batch-size", type=int, default=500)
    parser.add_argument("--out", help="Optional JSON summary path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = load_candidate_report(args.report)
    candidate = select_candidate(
        report,
        candidate_id=args.candidate_id,
        rank=args.rank,
        allow_failed=args.allow_failed,
    )
    ticker = (candidate.get("target_ticker") or report["ticker"]).upper()
    artifact_uri = args.model_out or (
        f"models/{ticker}_{candidate['model_name']}_{report['feature_set']}_{candidate['scope']}_{args.model_version}.joblib"
    )
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        result = promote_candidate_from_report(
            repository=repository,
            report=report,
            candidate=candidate,
            model_version=args.model_version,
            artifact_uri=artifact_uri,
            limit=args.limit,
            min_rows=args.min_rows,
            persist=True,
            generate_prediction=not args.skip_prediction,
            latest_feature_limit=args.latest_feature_limit,
            risk_policy=RiskPolicy(
                max_position_size=args.max_position_size,
                min_confidence_to_trade=args.min_confidence_to_trade,
                max_expected_risk=args.max_expected_risk,
                stop_loss=args.stop_loss,
                take_profit=args.take_profit,
                allow_short=not args.no_short,
            ),
            prediction_batch_size=args.prediction_batch_size,
        )
    payload = {
        "candidate": result.candidate,
        "model_run_id": result.model_run_id,
        "artifact_uri": result.artifact_uri,
        "metrics": result.metrics,
        "prediction": result.prediction,
    }

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
