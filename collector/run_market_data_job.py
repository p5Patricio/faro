from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from collector.main import apply_date_overrides, load_asset_configs
from collector.market_data_job import run_market_data_job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect prices and materialize ML datasets")
    parser.add_argument("--assets-file", help="JSON file with asset collection configs")
    parser.add_argument("--tickers", help="Comma-separated tickers to process")
    parser.add_argument("--start", help="Override start date for collection")
    parser.add_argument("--end", help="Override end date for collection")
    parser.add_argument("--skip-collection", action="store_true")
    parser.add_argument("--skip-materialization", action="store_true")
    parser.add_argument("--feature-sets", default="technical_v2", help="Comma-separated feature sets")
    parser.add_argument("--label-method", choices=["fixed_horizon", "triple_barrier"], default="triple_barrier")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--buy-threshold", type=float, default=0.015)
    parser.add_argument("--sell-threshold", type=float, default=-0.015)
    parser.add_argument("--profit-take", type=float, default=0.03)
    parser.add_argument("--stop-loss", type=float, default=0.015)
    parser.add_argument("--limit", type=int, help="Optional max number of price rows for materialization")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--out", help="Optional JSON summary path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    assets = apply_date_overrides(
        load_asset_configs(args.assets_file),
        start=args.start,
        end=args.end,
    )
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        payload = run_market_data_job(
            repository=repository,
            assets=assets,
            feature_sets=parse_csv(args.feature_sets),
            label_method=args.label_method,
            horizon=args.horizon,
            buy_threshold=args.buy_threshold,
            sell_threshold=args.sell_threshold,
            profit_take=args.profit_take,
            stop_loss=args.stop_loss,
            limit=args.limit,
            batch_size=args.batch_size,
            collect_prices=not args.skip_collection,
            materialize=not args.skip_materialization,
            materialize_tickers=parse_csv(args.tickers) if args.tickers else None,
            continue_on_error=not args.fail_fast,
        )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2, default=str))


def parse_csv(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("At least one value is required")
    return values


if __name__ == "__main__":
    main()
