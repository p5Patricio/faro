from __future__ import annotations

import argparse

import psycopg

from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from collector.providers import HistoricalPriceRequest, get_provider, list_providers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download historical OHLCV data and load it into local Postgres")
    parser.add_argument("--provider", required=True, choices=list_providers())
    parser.add_argument("--ticker", required=True, help="Provider ticker, e.g. AAPL.US, SPY, BTCUSDT")
    parser.add_argument("--asset-ticker", help="Ticker stored locally. Defaults to --ticker")
    parser.add_argument("--name", help="Asset display name. Defaults to stored ticker")
    parser.add_argument("--asset-class", default="unknown", help="stock, etf, crypto, index, forex, etc.")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--start", help="Start date, e.g. 2020-01-01")
    parser.add_argument("--end", help="End date, e.g. 2026-07-05")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    provider = get_provider(args.provider)
    request = HistoricalPriceRequest(
        ticker=args.ticker,
        interval=args.interval,
        start=args.start,
        end=args.end,
    )
    prices = provider.fetch_prices(request)

    stored_ticker = (args.asset_ticker or args.ticker).upper()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        asset_id = repository.get_or_create_asset(
            ticker=stored_ticker,
            name=args.name or stored_ticker,
            asset_class=args.asset_class,
        )
        inserted = repository.upsert_prices(asset_id, prices, batch_size=args.batch_size)
    print(f"Loaded {inserted} {args.interval} rows for {stored_ticker} from {args.provider}")


if __name__ == "__main__":
    main()
