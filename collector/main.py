from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import psycopg

from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from collector.providers import HistoricalPriceRequest, get_provider
from collector.providers.base import PriceProvider


@dataclass(frozen=True)
class AssetCollectionConfig:
    provider: str
    ticker: str
    asset_ticker: str
    name: str
    asset_class: str
    interval: str = "1d"
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True)
class AssetCollectionResult:
    ticker: str
    provider: str
    rows_loaded: int


DEFAULT_ASSETS = [
    AssetCollectionConfig(
        provider="yfinance",
        ticker="BTC-USD",
        asset_ticker="BTC-USD",
        name="Bitcoin",
        asset_class="crypto",
        start="2020-01-01",
    ),
    AssetCollectionConfig(
        provider="yfinance",
        ticker="AAPL",
        asset_ticker="AAPL",
        name="Apple Inc.",
        asset_class="stock",
        start="2020-01-01",
    ),
    AssetCollectionConfig(
        provider="yfinance",
        ticker="SPY",
        asset_ticker="SPY",
        name="SPDR S&P 500 ETF Trust",
        asset_class="etf",
        start="2020-01-01",
    ),
]


ProviderFactory = Callable[[str], PriceProvider]


def expand_universe_document(raw: dict[str, Any]) -> list[AssetCollectionConfig]:
    """Expand a universe snapshot document's ``defaults`` + ``members`` into one
    `AssetCollectionConfig` per member. Kept in `main.py`, not `collector/universe.py`,
    so the `universe` <-> `AssetCollectionConfig` dependency stays one-way."""
    defaults = raw.get("defaults", {})
    provider = defaults.get("provider", "yfinance")
    asset_class = defaults.get("asset_class", "stock")
    interval = defaults.get("interval", "1d")
    start = defaults.get("start")

    return [
        AssetCollectionConfig(
            provider=provider,
            ticker=member["ticker"],
            asset_ticker=member["ticker"],
            name=member["name"],
            asset_class=asset_class,
            interval=interval,
            start=start,
        )
        for member in raw.get("members", [])
    ]


def load_asset_configs(path: str | None = None) -> list[AssetCollectionConfig]:
    if not path:
        return DEFAULT_ASSETS

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return expand_universe_document(raw)
    if not isinstance(raw, list):
        raise ValueError("assets file must contain a JSON array or a universe document")

    return [AssetCollectionConfig(**item) for item in raw]


def apply_date_overrides(
    assets: list[AssetCollectionConfig],
    start: str | None = None,
    end: str | None = None,
) -> list[AssetCollectionConfig]:
    return [
        AssetCollectionConfig(
            provider=asset.provider,
            ticker=asset.ticker,
            asset_ticker=asset.asset_ticker,
            name=asset.name,
            asset_class=asset.asset_class,
            interval=asset.interval,
            start=start or asset.start,
            end=end or asset.end,
        )
        for asset in assets
    ]


def collect_asset(
    asset: AssetCollectionConfig,
    repository: LocalPostgresRepository,
    provider_factory: ProviderFactory = get_provider,
    batch_size: int = 500,
) -> AssetCollectionResult:
    provider = provider_factory(asset.provider)
    prices = provider.fetch_prices(
        HistoricalPriceRequest(
            ticker=asset.ticker,
            interval=asset.interval,
            start=asset.start,
            end=asset.end,
        )
    )
    asset_id = repository.get_or_create_asset(
        ticker=asset.asset_ticker,
        name=asset.name,
        asset_class=asset.asset_class,
    )
    rows_loaded = repository.upsert_prices(asset_id, prices, batch_size=batch_size)
    return AssetCollectionResult(
        ticker=asset.asset_ticker,
        provider=asset.provider,
        rows_loaded=rows_loaded,
    )


def run_collection(
    assets: list[AssetCollectionConfig],
    repository: LocalPostgresRepository,
    provider_factory: ProviderFactory = get_provider,
    batch_size: int = 500,
) -> list[AssetCollectionResult]:
    results = []
    for asset in assets:
        results.append(
            collect_asset(
                asset=asset,
                repository=repository,
                provider_factory=provider_factory,
                batch_size=batch_size,
            )
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect configured assets into local Postgres")
    parser.add_argument("--assets-file", help="JSON file with asset collection configs")
    parser.add_argument("--start", help="Override start date for all assets")
    parser.add_argument("--end", help="Override end date for all assets")
    parser.add_argument("--batch-size", type=int, default=500)
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
        results = run_collection(assets, repository, batch_size=args.batch_size)

    print(json.dumps([asdict(result) for result in results], indent=2))


if __name__ == "__main__":
    main()
