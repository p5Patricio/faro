from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from collector.main import AssetCollectionConfig, expand_universe_document, load_asset_configs, run_collection
from collector.providers import HistoricalPriceRequest
from collector.universe import (
    UniverseDocument,
    load_universe_document,
    universe_disclosure,
    universe_report_block,
)

UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "config" / "universe.sp100.json"


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.requests: list[HistoricalPriceRequest] = []

    def fetch_prices(self, request: HistoricalPriceRequest) -> pd.DataFrame:
        self.requests.append(request)
        return pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
                "open": [10, 11],
                "high": [12, 13],
                "low": [9, 10],
                "close": [11, 12],
                "volume": [1000, 1100],
                "ticker": [request.ticker, request.ticker],
                "source": ["fake", "fake"],
            }
        )


class FakeRepository:
    def __init__(self) -> None:
        self.assets: list[dict] = []

    def get_or_create_asset(self, ticker: str, name: str | None = None, asset_class: str | None = None) -> str:
        self.assets.append({"ticker": ticker, "name": name, "asset_class": asset_class})
        return f"asset-{ticker}"

    def upsert_prices(self, asset_id: str, prices: pd.DataFrame, batch_size: int = 500) -> int:
        return len(prices)


def _fixture_doc(**overrides: object) -> dict:
    base = {
        "index": "S&P 100 (OEX)",
        "snapshot_date": "2025-09-22",
        "source": "test fixture",
        "membership_bias": "Current membership applied to historical data is survivorship bias.",
        "defaults": {"provider": "yfinance", "asset_class": "stock", "interval": "1d", "start": "2020-01-01"},
        "members": [
            {"ticker": "AAPL", "name": "Apple Inc."},
            {"ticker": "MSFT", "name": "Microsoft"},
            {"ticker": "BRK-B", "name": "Berkshire Hathaway (Class B)"},
        ],
    }
    base.update(overrides)
    return base


# -- Task 2.4: checked-in config/universe.sp100.json shape ------------------


def test_universe_snapshot_file_parses() -> None:
    raw = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))

    assert raw["index"] == "S&P 100 (OEX)"
    assert isinstance(raw["members"], list)


def test_universe_snapshot_normalizes_brk_b() -> None:
    raw = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    tickers = [member["ticker"] for member in raw["members"]]

    assert "BRK-B" in tickers
    assert "BRK.B" not in tickers


def test_universe_snapshot_has_no_dotted_tickers() -> None:
    raw = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))

    assert [member["ticker"] for member in raw["members"] if "." in member["ticker"]] == []


def test_universe_snapshot_member_count_is_101() -> None:
    raw = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))

    assert len(raw["members"]) == 101


# -- Task 2.7: expansion applies defaults; disclosure never omits the key ---


def test_expand_universe_document_applies_defaults_to_every_member() -> None:
    raw = _fixture_doc()

    configs = expand_universe_document(raw)

    assert len(configs) == 3
    assert configs == [
        AssetCollectionConfig(
            provider="yfinance",
            ticker="AAPL",
            asset_ticker="AAPL",
            name="Apple Inc.",
            asset_class="stock",
            interval="1d",
            start="2020-01-01",
        ),
        AssetCollectionConfig(
            provider="yfinance",
            ticker="MSFT",
            asset_ticker="MSFT",
            name="Microsoft",
            asset_class="stock",
            interval="1d",
            start="2020-01-01",
        ),
        AssetCollectionConfig(
            provider="yfinance",
            ticker="BRK-B",
            asset_ticker="BRK-B",
            name="Berkshire Hathaway (Class B)",
            asset_class="stock",
            interval="1d",
            start="2020-01-01",
        ),
    ]


def test_load_asset_configs_dispatches_dict_form_to_universe_expansion(tmp_path) -> None:
    universe_file = tmp_path / "universe.json"
    universe_file.write_text(json.dumps(_fixture_doc()), encoding="utf-8")

    configs = load_asset_configs(str(universe_file))

    assert len(configs) == 3
    assert [config.ticker for config in configs] == ["AAPL", "MSFT", "BRK-B"]


def test_load_asset_configs_list_form_still_rejects_non_list_non_dict(tmp_path) -> None:
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps("not-a-list-or-dict"), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON array or a universe document"):
        load_asset_configs(str(bad_file))


def test_universe_report_block_with_document_embeds_disclosure() -> None:
    doc = load_universe_document(UNIVERSE_PATH)

    block = universe_report_block(doc)

    assert block["universe"] == universe_disclosure(doc)
    assert block["universe"]["snapshot_date"] == "2025-09-22"
    assert block["universe"]["member_count"] == 101


def test_universe_report_block_with_no_document_emits_incomplete_marker() -> None:
    block = universe_report_block(None)

    assert block == {"universe": {"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}}


# -- Task 2.8: missing snapshot_date / membership_bias fails at load --------


def test_load_universe_document_raises_when_snapshot_date_missing(tmp_path) -> None:
    doc = _fixture_doc()
    del doc["snapshot_date"]
    universe_file = tmp_path / "universe.json"
    universe_file.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot_date"):
        load_universe_document(universe_file)


def test_load_universe_document_raises_when_membership_bias_missing(tmp_path) -> None:
    doc = _fixture_doc()
    del doc["membership_bias"]
    universe_file = tmp_path / "universe.json"
    universe_file.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ValueError, match="membership_bias"):
        load_universe_document(universe_file)


def test_load_universe_document_raises_when_snapshot_date_blank(tmp_path) -> None:
    universe_file = tmp_path / "universe.json"
    universe_file.write_text(json.dumps(_fixture_doc(snapshot_date="  ")), encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot_date"):
        load_universe_document(universe_file)


def test_load_universe_document_round_trips_valid_fixture(tmp_path) -> None:
    universe_file = tmp_path / "universe.json"
    universe_file.write_text(json.dumps(_fixture_doc()), encoding="utf-8")

    doc = load_universe_document(universe_file)

    assert isinstance(doc, UniverseDocument)
    assert doc.snapshot_date == "2025-09-22"
    assert len(doc.members) == 3


# -- Task 2.9: full 101-member expansion collects without configuration error --


def test_full_universe_expansion_resolves_every_asset_without_configuration_error() -> None:
    raw = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    configs = expand_universe_document(raw)
    assert len(configs) == 101

    fake_provider = FakeProvider()
    fake_repository = FakeRepository()

    results = run_collection(
        configs,
        fake_repository,  # type: ignore[arg-type]
        provider_factory=lambda _: fake_provider,
    )

    assert len(results) == 101
    assert len(fake_repository.assets) == 101
    assert {asset["ticker"] for asset in fake_repository.assets} == {config.asset_ticker for config in configs}
    assert all(asset["asset_class"] == "stock" for asset in fake_repository.assets)
