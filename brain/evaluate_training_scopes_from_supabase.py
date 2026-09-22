from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from brain.backtesting import BacktestConfig
from brain.features import feature_columns_for_set
from brain.inference import PredictionPolicy
from brain.models import DEFAULT_MODEL_NAME, available_model_names
from brain.scoped_evaluation import (
    SCOPES,
    load_materialized_asset_dataset,
    run_scoped_walk_forward_backtest,
)
from brain.selection import PromotionCriteria, rank_candidate_summaries
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare local, asset-class and global training scopes")
    parser.add_argument("--ticker", required=True, help="Target asset ticker evaluated out-of-sample")
    parser.add_argument("--feature-set", default="technical_v1")
    parser.add_argument("--label-method", choices=["fixed_horizon", "triple_barrier"], default="triple_barrier")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--model-name", choices=available_model_names(), default=DEFAULT_MODEL_NAME)
    parser.add_argument("--scopes", default="local,asset_class,global", help=f"Comma-separated scopes: {sorted(SCOPES)}")
    parser.add_argument("--splits", type=int, default=5)
    parser.add_argument("--test-size", type=int)
    parser.add_argument("--embargo-rows", type=int, help="Rows skipped between target train and test. Defaults to horizon")
    parser.add_argument("--trade-stride", type=int, help="Evaluate one target trade every N rows. Defaults to horizon")
    parser.add_argument("--limit", type=int, help="Optional max number of materialized rows per asset")
    parser.add_argument("--min-rows", type=int, default=120, help="Minimum materialized rows required per asset")
    parser.add_argument("--min-confidence", type=float, default=0.55)
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
    parser.add_argument("--out", help="Optional JSON report path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    feature_columns = feature_columns_for_set(args.feature_set)
    datasets = []
    skipped_assets = []

    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        assets = repository.get_assets()

        for asset in assets:
            try:
                item = load_materialized_asset_dataset(
                    repository,
                    asset,
                    feature_set=args.feature_set,
                    label_method=args.label_method,
                    horizon=args.horizon,
                    feature_columns=feature_columns,
                    limit=args.limit,
                )
            except ValueError as error:
                skipped_assets.append({"ticker": asset.get("ticker"), "reason": str(error)})
                continue
            if item is None:
                skipped_assets.append({"ticker": asset.get("ticker"), "reason": "no_materialized_dataset"})
                continue
            if len(item.dataset) < args.min_rows:
                skipped_assets.append({"ticker": item.ticker, "reason": f"rows_below_minimum:{len(item.dataset)}"})
                continue
            datasets.append(item)

    scopes = parse_scopes(args.scopes)
    results = []
    for scope in scopes:
        result = run_scoped_walk_forward_backtest(
            datasets,
            target_ticker=args.ticker,
            scope=scope,
            n_splits=args.splits,
            test_size=args.test_size,
            embargo_rows=args.embargo_rows if args.embargo_rows is not None else args.horizon,
            trade_stride=args.trade_stride if args.trade_stride is not None else args.horizon,
            model_name=args.model_name,
            feature_columns=feature_columns,
            prediction_policy=PredictionPolicy(min_confidence=args.min_confidence),
            config=BacktestConfig(
                initial_capital=args.initial_capital,
                position_size=args.position_size,
                fee_bps=args.fee_bps,
                slippage_bps=args.slippage_bps,
                allow_short=not args.no_short,
            ),
        )
        results.append(
            {
                "summary": result.summary,
                "folds": result.folds,
                "participating_assets": result.participating_assets,
            }
        )

    promotion_criteria = PromotionCriteria(
        min_total_return=args.min_total_return,
        min_profit_factor=args.min_profit_factor,
        max_drawdown_floor=args.max_drawdown_floor,
        min_active_trades=args.min_active_trades,
    )
    payload = {
        "ticker": args.ticker.upper(),
        "feature_set": args.feature_set,
        "label_method": args.label_method,
        "horizon": args.horizon,
        "model_name": args.model_name,
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
        "results": results,
        "ranking": rank_candidate_summaries(
            [result["summary"] for result in results],
            criteria=promotion_criteria,
            drawdown_penalty=args.drawdown_penalty,
        ),
    }

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2, default=str))


def parse_scopes(raw: str) -> list[str]:
    scopes = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = sorted(set(scopes) - SCOPES)
    if invalid:
        raise ValueError(f"Unknown scopes: {invalid}. Available: {sorted(SCOPES)}")
    if not scopes:
        raise ValueError("At least one scope is required")
    return scopes


if __name__ == "__main__":
    main()
