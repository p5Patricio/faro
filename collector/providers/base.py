from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


STANDARD_PRICE_COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "ticker",
    "source",
]


@dataclass(frozen=True)
class HistoricalPriceRequest:
    ticker: str
    interval: str = "1d"
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True)
class AnalystConsensus:
    ticker: str
    source: str
    recommendation_key: str
    recommendation_mean: float
    analyst_count: int
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int
    target_mean: float
    target_median: float
    target_high: float
    target_low: float


class PriceProvider(Protocol):
    name: str

    def fetch_prices(self, request: HistoricalPriceRequest) -> pd.DataFrame:
        """Return historical OHLCV data using STANDARD_PRICE_COLUMNS."""


def normalize_price_frame(
    prices: pd.DataFrame,
    ticker: str,
    source: str,
    timestamp_column: str = "timestamp",
) -> pd.DataFrame:
    """Validate and normalize provider output into the project's OHLCV shape."""
    df = prices.copy()
    required = {timestamp_column, "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns from {source}: {sorted(missing)}")

    df = df.rename(columns={timestamp_column: "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["ticker"] = ticker.upper()
    df["source"] = source
    df = df[STANDARD_PRICE_COLUMNS]
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df.sort_values("timestamp").drop_duplicates(["ticker", "timestamp"], keep="last")
    return df.reset_index(drop=True)


def ensure_non_empty(df: pd.DataFrame, provider_name: str, ticker: str) -> pd.DataFrame:
    if df.empty:
        raise ValueError(f"{provider_name} returned no prices for {ticker}")
    return df
