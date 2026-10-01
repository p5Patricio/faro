from __future__ import annotations

from types import SimpleNamespace

import pytest

from collector.local_repository import LocalPostgresRepository
from collector.run_market_cap_job import run_market_cap_job


class FakeYahooTicker:
    """`yfinance.Ticker` stand-in: `fast_info.market_cap` and `info`, per ticker."""

    def __init__(self, fast_caps: dict, info_caps: dict, failing: set[str], ticker: str) -> None:
        if ticker in failing:
            raise RuntimeError("yahoo down")
        self.fast_info = SimpleNamespace(market_cap=fast_caps.get(ticker))
        self.info = {"marketCap": info_caps[ticker]} if ticker in info_caps else {}


def fake_factory(fast_caps: dict | None = None, info_caps: dict | None = None, failing: set[str] | None = None):
    return lambda ticker: FakeYahooTicker(fast_caps or {}, info_caps or {}, failing or set(), ticker)


class FakeRepository:
    def __init__(self, tickers: list[str], table_exists: bool = True) -> None:
        self._assets = [{"id": f"id-{ticker}", "ticker": ticker} for ticker in tickers]
        self._table_exists = table_exists
        self.inserted: list[tuple] = []

    def relation_exists(self, name: str) -> bool:
        return self._table_exists

    def get_assets(self) -> list[dict]:
        return self._assets

    def insert_asset_market_cap(self, asset_id: str, market_cap: float, currency: str, source: str) -> None:
        self.inserted.append((asset_id, market_cap, currency, source))


def test_job_stores_fast_info_with_info_fallback_in_the_market_currency() -> None:
    repository = FakeRepository(["AAPL", "WALMEX.MX", "RY.TO", "MSFT"])
    factory = fake_factory(
        fast_caps={"AAPL": 3.4e12, "WALMEX.MX": 1.5e12},
        info_caps={"RY.TO": 2.5e11, "MSFT": 3.1e12},  # fast_info has no value for these: info is the fallback
    )

    report = run_market_cap_job(repository, ticker_factory=factory)

    assert sorted(repository.inserted) == [
        ("id-AAPL", 3.4e12, "USD", "yfinance"),
        ("id-MSFT", 3.1e12, "USD", "yfinance"),
        ("id-RY.TO", 2.5e11, "CAD", "yfinance"),
        ("id-WALMEX.MX", 1.5e12, "MXN", "yfinance"),
    ]
    assert report["status"] == "ok"
    assert report["stored"] == 4
    assert [report["markets"][key]["stored"] for key in ("us", "mx", "ca")] == [2, 1, 1]
    assert "failed" not in report  # the notifier reads `failed`; market caps are non-fatal


def test_job_isolates_a_failing_ticker_and_reports_it() -> None:
    repository = FakeRepository(["AAPL", "MSFT", "AMXB.MX"])
    factory = fake_factory(fast_caps={"AAPL": 3.4e12, "MSFT": 3.1e12}, failing={"MSFT"})

    report = run_market_cap_job(repository, ticker_factory=factory)

    assert [row[0] for row in repository.inserted] == ["id-AAPL"]
    problems = report["markets"]["us"]["problems"]
    assert problems["MSFT"] == "RuntimeError: yahoo down"
    assert report["markets"]["mx"]["problems"]["AMXB.MX"] == "no market cap returned"  # neither source had a value
    assert report["stored"] == 1


def test_job_skips_without_touching_yahoo_when_the_table_is_missing() -> None:
    repository = FakeRepository(["AAPL"], table_exists=False)

    def exploding_factory(ticker: str):
        raise AssertionError("must not fetch while the table is missing")

    report = run_market_cap_job(repository, ticker_factory=exploding_factory)

    assert report["status"] == "skipped"
    assert "0015_asset_market_caps.sql" in report["reason"]
    assert repository.inserted == []


def test_repository_returns_the_latest_stored_market_cap(repository: LocalPostgresRepository) -> None:
    """Exercises migration 0015 and the real SQL against the (rolled-back) test database."""
    older = repository.get_or_create_asset("ZZCAP.MX", name="Cap test", asset_class="stock_mx")
    other = repository.get_or_create_asset("ZZCAP2.MX", name="Cap test 2", asset_class="stock_mx")

    assert repository.get_latest_market_caps([older, other]) == {}

    repository.insert_asset_market_cap(older, 100.0, "MXN", "yfinance")
    repository.insert_asset_market_cap(older, 250.5, "MXN", "yfinance")  # a newer reading wins
    latest = repository.get_latest_market_caps([older, other])

    assert latest == {older: 250.5}
