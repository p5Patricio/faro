from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from brain.backtesting import BacktestConfig
from brain.candidate_matrix import load_candidate_datasets, run_candidate_matrix
from brain.features import feature_columns_for_set
from brain.models import available_model_names
from brain.scoped_evaluation import SCOPES
from brain.selection import PromotionCriteria
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


DEFAULT_CONFIDENCE_THRESHOLDS = "0.50,0.55,0.60,0.65,0.70,0.75"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate model x confidence x scope candidate matrix")
    parser.add_argument("--ticker", required=True, help="Target asset ticker evaluated out-of-sample")
    parser.add_argument("--feature-set", default="technical_v2")
    parser.add_argument("--label-method", choices=["fixed_horizon", "triple_barrier"], default="triple_barrier")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--models", default=",".join(available_model_names()), help="Comma-separated model names")
    parser.add_argument(
        "--confidence-thresholds",
        default=DEFAULT_CONFIDENCE_THRESHOLDS,
        help="Comma-separated confidence thresholds",
    )
    parser.add_argument("--scopes", default="local,asset_class,global", help=f"Comma-separated scopes: {sorted(SCOPES)}")
    parser.add_argument("--splits", type=int, default=5)
    parser.add_argument("--test-size", type=int)
    parser.add_argument("--embargo-rows", type=int, help="Rows skipped between target train and test. Defaults to horizon")
    parser.add_argument("--trade-stride", type=int, help="Evaluate one target trade every N rows. Defaults to horizon")
    parser.add_argument("--limit", type=int, help="Optional max number of materialized rows per asset")
    parser.add_argument("--min-rows", type=int, default=120, help="Minimum materialized rows required per asset")
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
    parser.add_argument("--include-details", action="store_true", help="Include fold and asset details for every candidate")
    parser.add_argument("--fail-fast", action="store_true", help="Stop on the first failed candidate")
    parser.add_argument("--out", help="Optional JSON report path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    feature_columns = feature_columns_for_set(args.feature_set)
    model_names = parse_model_names(args.models)
    confidence_thresholds = parse_float_list(args.confidence_thresholds, "confidence-thresholds")
    scopes = parse_scopes(args.scopes)
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        datasets, skipped_assets = load_candidate_datasets(
            repository,
            feature_set=args.feature_set,
            label_method=args.label_method,
            horizon=args.horizon,
            feature_columns=feature_columns,
            limit=args.limit,
            min_rows=args.min_rows,
        )
    promotion_criteria = PromotionCriteria(
        min_total_return=args.min_total_return,
        min_profit_factor=args.min_profit_factor,
        max_drawdown_floor=args.max_drawdown_floor,
        min_active_trades=args.min_active_trades,
    )
    matrix = run_candidate_matrix(
        datasets,
        target_ticker=args.ticker,
        scopes=scopes,
        model_names=model_names,
        confidence_thresholds=confidence_thresholds,
        n_splits=args.splits,
        test_size=args.test_size,
        embargo_rows=args.embargo_rows if args.embargo_rows is not None else args.horizon,
        trade_stride=args.trade_stride if args.trade_stride is not None else args.horizon,
        feature_columns=feature_columns,
        backtest_config=BacktestConfig(
            initial_capital=args.initial_capital,
            position_size=args.position_size,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
            allow_short=not args.no_short,
        ),
        promotion_criteria=promotion_criteria,
        drawdown_penalty=args.drawdown_penalty,
        include_details=args.include_details,
        continue_on_error=not args.fail_fast,
    )
    payload = {
        "ticker": args.ticker.upper(),
        "feature_set": args.feature_set,
        "label_method": args.label_method,
        "horizon": args.horizon,
        "models": model_names,
        "confidence_thresholds": confidence_thresholds,
        "scopes": scopes,
        "selection": {
            "drawdown_penalty": args.drawdown_penalty,
            "criteria": {
                "min_total_return": promotion_criteria.min_total_return,
                "min_profit_factor": promotion_criteria.min_profit_factor,
                "max_drawdown_floor": promotion_criteria.max_drawdown_floor,
                "min_active_trades": promotion_criteria.min_active_trades,
                "require_positive_edge_vs_no_trade": promotion_criteria.require_positive_edge_vs_no_trade,
            },
        },
        "available_dataset_count": len(datasets),
        "skipped_assets": skipped_assets,
        **matrix,
    }

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2, default=str))


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
