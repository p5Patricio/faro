from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from app_config import AppConfig
from api.main import app, get_app_config, get_repository

TILE_KEYS = {"ticker", "name", "sector", "market_cap", "change_pct", "price"}


class FakeHeatmapRepository:
    """Minimal repository stub exercising the heatmap's two read calls:
    `get_assets` and the batch `get_latest_price_pairs`."""

    def __init__(self, assets: list[dict], price_pairs: pd.DataFrame | None = None) -> None:
        self._assets = assets
        self._price_pairs = price_pairs if price_pairs is not None else pd.DataFrame(
            columns=["asset_id", "timestamp", "close"]
        )
        self.requested_asset_ids: list[str] | None = None

    def get_assets(self) -> list[dict]:
        return self._assets

    def get_latest_price_pairs(self, asset_ids: list[str]) -> pd.DataFrame:
        self.requested_asset_ids = asset_ids
        return self._price_pairs[self._price_pairs["asset_id"].isin(asset_ids)]


class RaisingRepository:
    def get_assets(self) -> list[dict]:
        raise RuntimeError("connection lost")


def override_repository(repository) -> None:
    app.dependency_overrides[get_repository] = lambda: repository


def override_config(config: AppConfig) -> None:
    app.dependency_overrides[get_app_config] = lambda: config


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_heatmap_rejects_non_us_market() -> None:
    client = TestClient(app)

    response = client.get("/api/heatmap", params={"market": "mx"})

    assert response.status_code == 422


def test_heatmap_demo_fallback_when_repository_unavailable() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    response = client.get("/api/heatmap", params={"market": "us"})

    clear_overrides()
    assert response.status_code == 200
    tiles = response.json()
    # Full S&P-100 universe snapshot (config/universe.sp100.json) has 101 members.
    assert len(tiles) == 101
    tickers = {tile["ticker"] for tile in tiles}
    assert "AAPL" in tickers
    assert "MSFT" in tickers
    for tile in tiles:
        assert TILE_KEYS <= tile.keys()
        assert tile["market_cap"] > 0
        assert isinstance(tile["change_pct"], (int, float))


def test_heatmap_demo_fallback_is_deterministic() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)

    first = client.get("/api/heatmap", params={"market": "us"}).json()
    second = client.get("/api/heatmap", params={"market": "us"}).json()

    clear_overrides()
    assert first == second


def test_heatmap_demo_disabled_returns_503() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    override_config(AppConfig(environment="production", allow_demo_fallback=False))
    client = TestClient(app)

    response = client.get("/api/heatmap", params={"market": "us"})

    clear_overrides()
    assert response.status_code == 503
    assert response.json()["detail"] == "Fuente de datos no disponible y modo demo desactivado"


def test_heatmap_uses_repository_prices_and_filters_non_stock_assets() -> None:
    assets = [
        {"id": "asset-aapl", "ticker": "AAPL", "name": "Apple Inc.", "asset_class": "stock"},
        {"id": "asset-msft", "ticker": "MSFT", "name": "Microsoft Corp.", "asset_class": "stock"},
        {"id": "asset-btc", "ticker": "BTC-USD", "name": "Bitcoin", "asset_class": "crypto"},
    ]
    price_pairs = pd.DataFrame(
        [
            {"asset_id": "asset-aapl", "timestamp": "2026-09-16T00:00:00+00:00", "close": 220.0},
            {"asset_id": "asset-aapl", "timestamp": "2026-09-15T00:00:00+00:00", "close": 200.0},
            {"asset_id": "asset-msft", "timestamp": "2026-09-16T00:00:00+00:00", "close": 480.0},
            {"asset_id": "asset-msft", "timestamp": "2026-09-15T00:00:00+00:00", "close": 500.0},
        ]
    )
    override_repository(FakeHeatmapRepository(assets, price_pairs))
    client = TestClient(app)

    response = client.get("/api/heatmap", params={"market": "us"})

    clear_overrides()
    assert response.status_code == 200
    tiles = {tile["ticker"]: tile for tile in response.json()}
    assert set(tiles.keys()) == {"AAPL", "MSFT"}  # crypto excluded

    assert tiles["AAPL"]["price"] == 220.0
    assert tiles["AAPL"]["change_pct"] == 10.0  # (220-200)/200 * 100

    assert tiles["MSFT"]["price"] == 480.0
    assert tiles["MSFT"]["change_pct"] == -4.0  # (480-500)/500 * 100


def test_heatmap_skips_stock_assets_with_no_price_history() -> None:
    assets = [{"id": "asset-new", "ticker": "NEW", "name": "New Co.", "asset_class": "stock"}]
    override_repository(FakeHeatmapRepository(assets))
    client = TestClient(app)

    response = client.get("/api/heatmap", params={"market": "us"})

    clear_overrides()
    assert response.status_code == 200
    assert response.json() == []


def test_heatmap_falls_back_to_demo_on_repository_runtime_error() -> None:
    override_repository(RaisingRepository())
    client = TestClient(app)

    response = client.get("/api/heatmap", params={"market": "us"})

    clear_overrides()
    assert response.status_code == 200
    tiles = response.json()
    assert len(tiles) == 101
