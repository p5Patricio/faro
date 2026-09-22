from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from brain.inference_job import load_promoted_model_runs, run_latest_inference_job
from brain.risk import RiskPolicy
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run latest inference for promoted model runs")
    parser.add_argument("--model-name")
    parser.add_argument("--model-version")
    parser.add_argument("--limit", type=int, help="Max number of model_runs to inspect")
    parser.add_argument("--include-unpromoted", action="store_true")
    parser.add_argument("--latest-feature-limit", type=int, default=1)
    parser.add_argument("--min-confidence", type=float, help="Override candidate confidence threshold")
    parser.add_argument("--min-confidence-to-trade", type=float, default=0.60)
    parser.add_argument("--max-position-size", type=float, default=0.10)
    parser.add_argument("--max-expected-risk", type=float, default=0.05)
    parser.add_argument("--stop-loss", type=float, default=0.02)
    parser.add_argument("--take-profit", type=float, default=0.04)
    parser.add_argument("--no-short", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--out", help="Optional JSON summary path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        model_runs, skipped = load_promoted_model_runs(
            repository,
            model_name=args.model_name,
            model_version=args.model_version,
            limit=args.limit,
            include_unpromoted=args.include_unpromoted,
        )
        payload = run_latest_inference_job(
            repository=repository,
            model_runs=model_runs,
            latest_feature_limit=args.latest_feature_limit,
            min_confidence=args.min_confidence,
            risk_policy=RiskPolicy(
                max_position_size=args.max_position_size,
                min_confidence_to_trade=args.min_confidence_to_trade,
                max_expected_risk=args.max_expected_risk,
                stop_loss=args.stop_loss,
                take_profit=args.take_profit,
                allow_short=not args.no_short,
            ),
            batch_size=args.batch_size,
            continue_on_error=not args.fail_fast,
        )
    payload = {
        **payload,
        "selected_model_runs": len(model_runs),
        "skipped_model_runs": skipped,
    }

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
