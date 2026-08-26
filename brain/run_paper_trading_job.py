from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from brain.paper_trading import PaperTradingConfig
from brain.paper_trading_job import run_paper_trading_job
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist paper trading simulations for stored predictions")
    parser.add_argument("--tickers", help="Comma-separated stored tickers, for example BTC-USD,AAPL")
    parser.add_argument("--model-name")
    parser.add_argument("--model-version")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--default-position-size", type=float, default=0.10)
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--no-short", action="store_true")
    parser.add_argument("--persist-empty", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--out", help="Optional JSON report path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        payload = run_paper_trading_job(
            repository=repository,
            tickers=_parse_tickers(args.tickers),
            model_name=args.model_name,
            model_version=args.model_version,
            limit=args.limit,
            config=PaperTradingConfig(
                initial_capital=args.initial_capital,
                default_position_size=args.default_position_size,
                fee_bps=args.fee_bps,
                slippage_bps=args.slippage_bps,
                allow_short=not args.no_short,
            ),
            persist_empty=args.persist_empty,
            continue_on_error=not args.fail_fast,
        )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2, default=str))


def _parse_tickers(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [ticker.strip().upper() for ticker in value.split(",") if ticker.strip()]


if __name__ == "__main__":
    main()
