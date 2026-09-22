from __future__ import annotations

from collector.main import load_asset_configs


def test_core_assets_config_loads_with_collector_parser() -> None:
    """The daily scheduler reads this file via --assets-file, so it must carry
    the full tracked universe -- both cryptos plus every S&P 100 stock -- not
    a placeholder subset. A prior version of this test pinned the file to just
    {BTC-USD, ETH-USD, AAPL, MSFT}, which meant the other ~99 stocks were
    silently invisible to the daily market-data job (never fetched, never
    materialized) while the job itself reported success -- discovered when
    99/101 stocks turned out stale for weeks with no error surfaced anywhere."""
    assets = load_asset_configs("config/assets.core.json")

    tickers = {asset.asset_ticker for asset in assets}

    assert {"BTC-USD", "ETH-USD"} <= tickers, "both tracked cryptos must stay in the daily universe"
    assert {"AAPL", "MSFT"} <= tickers, "the original core stocks must still be present"
    assert len(tickers) >= 100, "the full S&P 100 stock universe must be present, not a placeholder subset"
    assert {asset.provider for asset in assets} == {"yfinance"}
    assert all(asset.interval == "1d" for asset in assets)
