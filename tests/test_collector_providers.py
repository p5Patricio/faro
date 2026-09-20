from __future__ import annotations

import pandas as pd
import pytest

from collector.providers import HistoricalPriceRequest, get_provider, list_providers
from collector.providers.base import STANDARD_PRICE_COLUMNS, normalize_price_frame
from collector.providers.binance_provider import BinanceProvider
from collector.providers.stooq_provider import StooqProvider
from collector.providers.yfinance_provider import YFinanceProvider


class FakeResponse:
    def __init__(self, text: str = "", payload: list | None = None) -> None:
        self.text = text
        self._payload = payload or []

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    def get(self, url: str, params: dict, timeout: int) -> FakeResponse:
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        return self.responses.pop(0)


def test_normalize_price_frame_outputs_standard_columns() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "open": ["10", "11"],
            "high": ["12", "13"],
            "low": ["9", "10"],
            "close": ["11", "12"],
            "volume": ["1000", "1200"],
        }
    )

    result = normalize_price_frame(raw, ticker="aapl.us", source="test", timestamp_column="date")

    assert list(result.columns) == STANDARD_PRICE_COLUMNS
    assert result.loc[0, "ticker"] == "AAPL.US"
    assert result.loc[0, "source"] == "test"
    assert result["timestamp"].dt.tz is not None


def test_stooq_provider_parses_csv_response() -> None:
    csv = "Date,Open,High,Low,Close,Volume\n2024-01-01,10,12,9,11,1000\n"
    session = FakeSession([FakeResponse(text=csv)])
    provider = StooqProvider(session=session)

    result = provider.fetch_prices(
        HistoricalPriceRequest(ticker="aapl.us", interval="1d", start="2024-01-01", end="2024-01-31")
    )

    assert len(result) == 1
    assert list(result.columns) == STANDARD_PRICE_COLUMNS
    assert session.requests[0]["params"]["d1"] == "20240101"
    assert session.requests[0]["params"]["d2"] == "20240131"
    assert session.requests[0]["params"]["i"] == "d"


def test_binance_provider_parses_kline_response() -> None:
    payload = [
        [
            1704067200000,
            "42000.0",
            "43000.0",
            "41000.0",
            "42500.0",
            "123.45",
            1704153599999,
            "0",
            1,
            "0",
            "0",
            "0",
        ]
    ]
    session = FakeSession([FakeResponse(payload=payload)])
    provider = BinanceProvider(session=session)

    result = provider.fetch_prices(
        HistoricalPriceRequest(ticker="BTCUSDT", interval="1d", start="2024-01-01", end="2024-01-02")
    )

    assert len(result) == 1
    assert result.loc[0, "ticker"] == "BTCUSDT"
    assert result.loc[0, "source"] == "binance"
    assert result.loc[0, "close"] == 42500.0
    assert session.requests[0]["params"]["symbol"] == "BTCUSDT"
    assert session.requests[0]["params"]["interval"] == "1d"


def test_provider_registry_lists_initial_sources() -> None:
    assert {"binance", "stooq", "yfinance"}.issubset(set(list_providers()))
    assert get_provider("stooq").name == "stooq"


class FakeYfTicker:
    def __init__(
        self,
        info: dict,
        recommendations_summary: pd.DataFrame,
        analyst_price_targets: dict,
    ) -> None:
        self.info = info
        self.recommendations_summary = recommendations_summary
        self.analyst_price_targets = analyst_price_targets


def test_yfinance_provider_fetch_analyst_consensus_parses_amd_like_data(monkeypatch) -> None:
    info = {
        "recommendationKey": "strong_buy",
        "recommendationMean": 1.8,
        # Deliberately different from the recommendations_summary bucket sum
        # below (50 vs 55) to exercise the known Yahoo panel-mismatch quirk.
        "numberOfAnalystOpinions": 50,
    }
    summary = pd.DataFrame(
        [
            {"period": "0m", "strongBuy": 25, "buy": 20, "hold": 8, "sell": 1, "strongSell": 1},
            {"period": "-1m", "strongBuy": 24, "buy": 19, "hold": 9, "sell": 1, "strongSell": 1},
        ]
    )
    targets = {"current": 180.0, "high": 250.0, "low": 150.0, "mean": 200.0, "median": 195.0}

    fake_ticker = FakeYfTicker(info=info, recommendations_summary=summary, analyst_price_targets=targets)
    monkeypatch.setattr(
        "collector.providers.yfinance_provider.yf.Ticker",
        lambda ticker: fake_ticker,
    )

    provider = YFinanceProvider()
    result = provider.fetch_analyst_consensus("amd")

    assert result.ticker == "AMD"
    assert result.source == "yfinance"
    assert result.recommendation_key == "strong_buy"
    assert result.recommendation_mean == 1.8
    # Bucket sum (55), not info["numberOfAnalystOpinions"] (50).
    assert result.analyst_count == 55
    assert result.strong_buy == 25
    assert result.buy == 20
    assert result.hold == 8
    assert result.sell == 1
    assert result.strong_sell == 1
    assert result.target_mean == 200.0
    assert result.target_median == 195.0
    assert result.target_high == 250.0
    assert result.target_low == 150.0


def test_yfinance_provider_fetch_analyst_consensus_raises_for_empty_summary(monkeypatch) -> None:
    fake_ticker = FakeYfTicker(
        info={"recommendationKey": "buy", "recommendationMean": 2.0},
        recommendations_summary=pd.DataFrame(),
        analyst_price_targets={},
    )
    monkeypatch.setattr(
        "collector.providers.yfinance_provider.yf.Ticker",
        lambda ticker: fake_ticker,
    )

    provider = YFinanceProvider()

    with pytest.raises(ValueError, match="no analyst recommendations"):
        provider.fetch_analyst_consensus("AMD")


def test_yfinance_provider_fetch_analyst_consensus_raises_for_empty_info(monkeypatch) -> None:
    fake_ticker = FakeYfTicker(
        info={},
        recommendations_summary=pd.DataFrame([{"period": "0m", "strongBuy": 1, "buy": 1, "hold": 1, "sell": 0, "strongSell": 0}]),
        analyst_price_targets={},
    )
    monkeypatch.setattr(
        "collector.providers.yfinance_provider.yf.Ticker",
        lambda ticker: fake_ticker,
    )

    provider = YFinanceProvider()

    with pytest.raises(ValueError, match="no info"):
        provider.fetch_analyst_consensus("AMD")
