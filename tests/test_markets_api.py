from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from api.main import app, get_app_config, get_repository
from api.routers.markets import GROUPS
from app_config import AppConfig
from collector.main import load_asset_configs
from collector.universe import MARKET_ASSET_CLASSES, load_universe_document

MARKETS_PATH = Path(__file__).resolve().parent.parent / "config" / "universe.markets.json"
ITEM_KEYS = {"ticker", "name", "last", "change_pct", "as_of", "stale", "currency", "unit"}


class FakeMarketsRepository:
    def __init__(self, assets: list[dict], price_pairs: pd.DataFrame) -> None:
        self._assets = assets
        self._price_pairs = price_pairs

    def get_assets(self) -> list[dict]:
        return self._assets

    def get_latest_price_pairs(self, asset_ids: list[str]) -> pd.DataFrame:
        return self._price_pairs[self._price_pairs["asset_id"].isin(asset_ids)]


class RaisingRepository:
    def get_assets(self) -> list[dict]:
        raise RuntimeError("connection lost")


def _bars(asset_id: str, last: float, previous: float, days_old: int = 0) -> list[dict]:
    newest = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_old)
    return [
        {"asset_id": asset_id, "timestamp": newest.isoformat(), "close": last},
        {"asset_id": asset_id, "timestamp": (newest - timedelta(days=1)).isoformat(), "close": previous},
    ]


def _use(repository, config: AppConfig | None = None) -> TestClient:
    app.dependency_overrides[get_repository] = lambda: repository
    if config is not None:
        app.dependency_overrides[get_app_config] = lambda: config
    return TestClient(app)


def test_markets_overview_groups_live_items_and_skips_missing_data() -> None:
    assets = [
        {"id": "a-spx", "ticker": "^GSPC", "name": "S&P 500", "asset_class": "index"},
        {"id": "a-ndx", "ticker": "^IXIC", "name": "Nasdaq", "asset_class": "index"},  # no prices -> skipped
        {"id": "a-ipc", "ticker": "^MXX", "name": "IPC", "asset_class": "index"},  # old bar -> stale
        {"id": "a-mxn", "ticker": "MXN=X", "name": "USD/MXN", "asset_class": "fx"},
        {"id": "a-wti", "ticker": "CL=F", "name": "Crudo WTI", "asset_class": "commodity"},
        {"id": "a-tnx", "ticker": "^TNX", "name": "Bono 10 años", "asset_class": "yield"},
        {"id": "a-aapl", "ticker": "AAPL", "name": "Apple Inc.", "asset_class": "stock"},  # not a market asset
    ]
    pairs = pd.DataFrame(
        _bars("a-spx", 5100.0, 5000.0)
        + _bars("a-ipc", 58000.0, 59000.0, days_old=10)
        + _bars("a-mxn", 17.0, 17.5)
        + _bars("a-wti", 70.0, 70.0)
        + _bars("a-tnx", 4.2, 4.0)
        + _bars("a-aapl", 200.0, 100.0)
    )
    client = _use(FakeMarketsRepository(assets, pairs))

    response = client.get("/api/markets/overview")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["is_demo"] is False
    assert datetime.fromisoformat(body["as_of"]).tzinfo is not None
    # Display order is fixed; groups without items (Canadá, China y Hong Kong) are omitted.
    assert [group["key"] for group in body["groups"]] == ["indices_us", "indices_mx", "fx", "commodities", "yields"]
    assert body["groups"][0]["label"] == "EE.UU."

    items = {item["ticker"]: item for group in body["groups"] for item in group["items"]}
    assert set(items) == {"^GSPC", "^MXX", "MXN=X", "CL=F", "^TNX"}  # ^IXIC has no data, AAPL is not a market asset
    assert all(ITEM_KEYS == item.keys() for item in items.values())
    assert items["^GSPC"]["last"] == 5100.0
    assert items["^GSPC"]["change_pct"] == 2.0  # (5100-5000)/5000 * 100
    assert items["^GSPC"]["unit"] == "points" and items["^GSPC"]["stale"] is False
    assert items["^MXX"]["stale"] is True
    assert items["CL=F"]["currency"] == "USD" and items["CL=F"]["unit"] == "price"
    assert items["^TNX"]["unit"] == "percent"


def test_markets_overview_serves_demo_data_and_honours_the_503_gate() -> None:
    client = _use(None)
    from_none = client.get("/api/markets/overview")
    app.dependency_overrides.clear()

    client = _use(RaisingRepository())
    from_error = client.get("/api/markets/overview")
    app.dependency_overrides.clear()

    for response in (from_none, from_error):
        assert response.status_code == 200
        body = response.json()
        assert body["is_demo"] is True
        assert [group["key"] for group in body["groups"]] == [key for key, _ in GROUPS]
        assert sum(len(group["items"]) for group in body["groups"]) == 18

    client = _use(None, AppConfig(environment="production", allow_demo_fallback=False))
    disabled = client.get("/api/markets/overview")
    app.dependency_overrides.clear()
    assert disabled.status_code == 503


def test_assets_picker_hides_market_instruments() -> None:
    assets = [
        {"id": "1", "ticker": "AAPL", "name": "Apple Inc.", "asset_class": "stock"},
        {"id": "2", "ticker": "BTC-USD", "name": "Bitcoin", "asset_class": "crypto"},
        {"id": "3", "ticker": "^GSPC", "name": "S&P 500", "asset_class": "index"},
        {"id": "4", "ticker": "MXN=X", "name": "USD/MXN", "asset_class": "fx"},
        {"id": "5", "ticker": "CL=F", "name": "Crudo WTI", "asset_class": "commodity"},
        {"id": "6", "ticker": "^TNX", "name": "Bono 10 años", "asset_class": "yield"},
    ]
    client = _use(FakeMarketsRepository(assets, pd.DataFrame(columns=["asset_id", "timestamp", "close"])))

    response = client.get("/api/assets")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert [asset["ticker"] for asset in response.json()] == ["AAPL", "BTC-USD"]


def test_markets_universe_file_loads_and_stays_out_of_ml_targets() -> None:
    doc = load_universe_document(MARKETS_PATH)
    tickers = [member["ticker"] for member in doc.members]

    assert len(tickers) == len(set(tickers)) == 18
    assert {member["asset_class"] for member in doc.members} == MARKET_ASSET_CLASSES
    assert {member["group"] for member in doc.members} == {key for key, _ in GROUPS}
    assert {member["unit"] for member in doc.members} <= {"points", "price", "percent"}

    # Collection configs keep each member's own asset_class (the document default is not used).
    configs = load_asset_configs(str(MARKETS_PATH))
    assert [(c.asset_ticker, c.asset_class) for c in configs] == [(m["ticker"], m["asset_class"]) for m in doc.members]

    for targets_file in MARKETS_PATH.parent.glob("targets*.json"):
        assert not set(tickers) & set(json.loads(targets_file.read_text(encoding="utf-8")))
