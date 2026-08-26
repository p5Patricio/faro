from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from brain.materialize_dataset import MaterializationConfig, materialize_asset_dataset
from collector.main import AssetCollectionConfig, ProviderFactory, collect_asset
from collector.local_repository import LocalPostgresRepository
from collector.providers import get_provider


def run_market_data_job(
    repository: LocalPostgresRepository,
    assets: list[AssetCollectionConfig],
    provider_factory: ProviderFactory = get_provider,
    feature_sets: list[str] | None = None,
    label_method: str = "triple_barrier",
    horizon: int = 5,
    buy_threshold: float = 0.015,
    sell_threshold: float = -0.015,
    profit_take: float = 0.03,
    stop_loss: float = 0.015,
    limit: int | None = None,
    batch_size: int = 500,
    collect_prices: bool = True,
    materialize: bool = True,
    materialize_tickers: list[str] | None = None,
    continue_on_error: bool = True,
) -> dict[str, Any]:
    started_at = datetime.now(tz=UTC)
    collection_results = []
    materialization_results = []
    errors = []

    selected_assets = filter_assets(assets, materialize_tickers)

    if collect_prices:
        for asset in selected_assets:
            try:
                result = collect_asset(
                    asset=asset,
                    repository=repository,
                    provider_factory=provider_factory,
                    batch_size=batch_size,
                )
                collection_results.append(asdict(result))
            except Exception as error:
                errors.append({"stage": "collection", "ticker": asset.asset_ticker, "error": str(error)})
                if not continue_on_error:
                    raise

    if materialize:
        tickers = materialize_tickers or [asset.asset_ticker for asset in selected_assets]
        for ticker in tickers:
            for feature_set in feature_sets or ["technical_v1"]:
                try:
                    result = materialize_asset_dataset(
                        repository,
                        MaterializationConfig(
                            ticker=ticker,
                            feature_set=feature_set,
                            label_method=label_method,
                            horizon=horizon,
                            buy_threshold=buy_threshold,
                            sell_threshold=sell_threshold,
                            profit_take=profit_take,
                            stop_loss=stop_loss,
                            limit=limit,
                            batch_size=batch_size,
                        ),
                    )
                    materialization_results.append(asdict(result))
                except Exception as error:
                    errors.append(
                        {
                            "stage": "materialization",
                            "ticker": ticker.upper(),
                            "feature_set": feature_set,
                            "error": str(error),
                        }
                    )
                    if not continue_on_error:
                        raise

    ended_at = datetime.now(tz=UTC)
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "collect_prices": collect_prices,
        "materialize": materialize,
        "collection": {
            "attempted": len(selected_assets) if collect_prices else 0,
            "succeeded": len(collection_results),
            "results": collection_results,
        },
        "materialization": {
            "attempted": len((materialize_tickers or [asset.asset_ticker for asset in selected_assets]))
            * len(feature_sets or ["technical_v1"])
            if materialize
            else 0,
            "succeeded": len(materialization_results),
            "results": materialization_results,
        },
        "failed": len(errors),
        "errors": errors,
    }


def filter_assets(
    assets: list[AssetCollectionConfig],
    tickers: list[str] | None = None,
) -> list[AssetCollectionConfig]:
    if not tickers:
        return assets
    wanted = {ticker.upper() for ticker in tickers}
    return [asset for asset in assets if asset.asset_ticker.upper() in wanted or asset.ticker.upper() in wanted]
