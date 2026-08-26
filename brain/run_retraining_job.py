from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from brain.evaluate_candidate_matrix_from_supabase import DEFAULT_CONFIDENCE_THRESHOLDS
from brain.models import available_model_names
from brain.retraining_job import RetrainingJobConfig, run_retraining_job
from brain.scoped_evaluation import SCOPES
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate, promote and upload improved model candidates")
    parser.add_argument("--tickers", help="Comma-separated stored tickers, for example BTC-USD,AAPL")
    parser.add_argument("--feature-set", default="technical_v2")
    parser.add_argument("--label-method", choices=["fixed_horizon", "triple_barrier"], default="triple_barrier")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--models", default=",".join(available_model_names()))
    parser.add_argument("--confidence-thresholds", default=DEFAULT_CONFIDENCE_THRESHOLDS)
    parser.add_argument("--scopes", default="local,asset_class,global")
    parser.add_argument("--splits", type=int, default=5)
    parser.add_argument("--test-size", type=int)
    parser.add_argument("--embargo-rows", type=int)
    parser.add_argument("--trade-stride", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-rows", type=int, default=120)
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--position-size", type=float, default=1.0)
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--no-short", action="store_true")
    parser.add_argument("--min-total-return", type=float, default=0.0)
    parser.add_argument("--min-profit-factor", type=float, default=1.0)
    parser.add_argument("--max-drawdown-floor", type=float, default=-0.25)
    parser.add_argument("--min-active-trades", type=int, default=20)
    parser.add_argument("--drawdown-penalty", type=float, default=1.0)
    parser.add_argument("--skip-prediction", action="store_true")
    parser.add_argument("--latest-feature-limit", type=int, default=1)
    parser.add_argument("--min-confidence-to-trade", type=float, default=0.60)
    parser.add_argument("--max-position-size", type=float, default=0.10)
    parser.add_argument("--max-expected-risk", type=float, default=0.05)
    parser.add_argument("--stop-loss", type=float, default=0.02)
    parser.add_argument("--take-profit", type=float, default=0.04)
    parser.add_argument("--skip-upload", action="store_true", help="Skip normalizing the artifact into models/")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--no-require-incumbent-improvement", action="store_true")
    parser.add_argument("--min-objective-improvement", type=float, default=0.0)
    parser.add_argument("--incumbent-lookup-limit", type=int, default=100)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--out", help="Optional JSON report path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        payload = run_retraining_job(
            repository=repository,
            tickers=parse_tickers(args.tickers),
            config=RetrainingJobConfig(
                feature_set=args.feature_set,
                label_method=args.label_method,
                horizon=args.horizon,
                model_names=parse_model_names(args.models),
                confidence_thresholds=parse_float_list(args.confidence_thresholds, "confidence-thresholds"),
                scopes=parse_scopes(args.scopes),
                splits=args.splits,
                test_size=args.test_size,
                embargo_rows=args.embargo_rows,
                trade_stride=args.trade_stride,
                limit=args.limit,
                min_rows=args.min_rows,
                initial_capital=args.initial_capital,
                position_size=args.position_size,
                fee_bps=args.fee_bps,
                slippage_bps=args.slippage_bps,
                allow_short=not args.no_short,
                min_total_return=args.min_total_return,
                min_profit_factor=args.min_profit_factor,
                max_drawdown_floor=args.max_drawdown_floor,
                min_active_trades=args.min_active_trades,
                drawdown_penalty=args.drawdown_penalty,
                generate_prediction=not args.skip_prediction,
                latest_feature_limit=args.latest_feature_limit,
                max_position_size=args.max_position_size,
                min_confidence_to_trade=args.min_confidence_to_trade,
                max_expected_risk=args.max_expected_risk,
                stop_loss=args.stop_loss,
                take_profit=args.take_profit,
                upload_artifacts=not args.skip_upload,
                model_dir=args.model_dir,
                require_incumbent_improvement=not args.no_require_incumbent_improvement,
                min_objective_improvement=args.min_objective_improvement,
                incumbent_lookup_limit=args.incumbent_lookup_limit,
                continue_on_error=not args.fail_fast,
            ),
        )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2, default=str))


def parse_tickers(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [ticker.strip().upper() for ticker in value.split(",") if ticker.strip()]


def parse_model_names(raw: str) -> list[str]:
    names = parse_string_list(raw, "models")
    available = set(available_model_names())
    invalid = sorted(set(names) - available)
    if invalid:
        raise ValueError(f"Unknown models: {invalid}. Available: {sorted(available)}")
    return names


def parse_scopes(raw: str) -> list[str]:
    scopes = parse_string_list(raw, "scopes")
    invalid = sorted(set(scopes) - SCOPES)
    if invalid:
        raise ValueError(f"Unknown scopes: {invalid}. Available: {sorted(SCOPES)}")
    return scopes


def parse_string_list(raw: str, name: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError(f"At least one {name} value is required")
    return values


def parse_float_list(raw: str, name: str) -> list[float]:
    values = []
    for item in parse_string_list(raw, name):
        value = float(item)
        if value < 0 or value > 1:
            raise ValueError(f"{name} values must be between 0 and 1")
        values.append(value)
    return values


if __name__ == "__main__":
    main()
