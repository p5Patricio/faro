"""Point 5 (crypto prediction wiring): crypto tickers must resolve to the
`technical_alpha_v1` feature set -- never `fundamental_v1` (SEC-filing-only,
no equivalent data exists for a cryptocurrency) -- and the pure computation
layers (`brain.features`, `brain.technical_factors_v2`,
`brain.materialize_technical_alpha`) must not choke on a crypto-shaped
OHLCV history: a hyphenated ticker (`BTC-USD`) and a continuous 7-day/week
calendar (no weekend gaps, unlike a stock's Mon-Fri series).

This is a pure/synthetic-data suite -- no Postgres dependency, so it runs
the same everywhere `tests/test_feature_set_resolution.py` and
`tests/test_technical_factors_v2.py` do, including a sandbox with no local
database configured.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from brain.backtesting import BacktestConfig, run_prediction_backtest
from brain.features import (
    FEATURE_SET_OVERLAYS_BY_ASSET_CLASS,
    TECHNICAL_ALPHA_OVERLAY_COLUMNS,
    build_features,
    feature_columns_for_set,
    feature_set_for_asset_class,
    prepare_price_frame,
)
from brain.materialize_technical_alpha import build_technical_alpha_overlay
from brain.retraining_job import build_artifact_path, build_model_version
from brain.technical_factors_v2 import FACTOR_KEYS, compute_technical_alpha_factors


def _crypto_price_history(start: str, periods: int) -> pd.DataFrame:
    """Synthetic BTC-USD-shaped OHLCV: one bar every CALENDAR day (freq="D"),
    unlike a stock's business-day-only series -- this is what
    BinanceProvider/yfinance actually produce for a 24/7 crypto market, and
    is the shape every function under test must handle without error."""
    timestamps = pd.date_range(start, periods=periods, freq="D", tz="UTC")
    wave = np.sin(np.arange(periods) / 4) * 800
    trend = np.arange(periods) * 15
    close = 40_000 + wave + trend
    open_ = close + np.cos(np.arange(periods)) * 50
    high = np.maximum(open_, close) + 150
    low = np.minimum(open_, close) - 150
    volume = 5_000 + (np.arange(periods) % 11) * 250
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


# ---------------------------------------------------------------------------
# FEATURE_SET_OVERLAYS_BY_ASSET_CLASS["crypto"] resolves to technical_alpha_v1
# ---------------------------------------------------------------------------


def test_crypto_overlay_registered_to_technical_alpha_v1():
    assert FEATURE_SET_OVERLAYS_BY_ASSET_CLASS["crypto"] == "technical_alpha_v1"


@pytest.mark.parametrize("asset_class", ["crypto", "CRYPTO", "  crypto  ", "Crypto"])
def test_feature_set_for_asset_class_resolves_crypto_case_and_whitespace_insensitively(asset_class):
    assert feature_set_for_asset_class(asset_class) == "technical_alpha_v1"


def test_feature_set_for_asset_class_crypto_never_resolves_to_fundamental_v1():
    """The whole point of this registration: a crypto ticker must never be
    routed to fundamental_v1 (requires SEC XBRL filings, which do not exist
    for a cryptocurrency)."""
    assert feature_set_for_asset_class("crypto") != "fundamental_v1"


def test_feature_columns_for_set_with_crypto_asset_class_matches_technical_alpha_v1():
    resolved = feature_columns_for_set("technical_v2", asset_class="crypto")
    assert resolved == feature_columns_for_set("technical_alpha_v1")
    assert len(resolved) == 44


def test_feature_columns_for_set_registered_overlay_wins_over_invalid_explicit_feature_set():
    """Documents an existing, previously-untestable-with-real-data contract:
    `feature_set_for_asset_class` resolves the OVERLAY when asset_class is
    registered, ignoring whatever explicit feature_set string was passed --
    even an invalid one. Registering "crypto" makes this observable for the
    first time without monkeypatching (see
    tests/test_feature_set_resolution.py's
    test_feature_columns_for_set_unknown_name_raises_regardless_of_asset_class,
    updated alongside this change)."""
    assert feature_columns_for_set("does_not_exist", asset_class="crypto") == feature_columns_for_set(
        "technical_alpha_v1"
    )


# ---------------------------------------------------------------------------
# A crypto-formatted, 24/7-cadence OHLCV history does not break the pure
# feature-computation layers.
# ---------------------------------------------------------------------------


def test_prepare_price_frame_handles_crypto_shaped_history():
    prices = _crypto_price_history("2023-01-01", 200)
    df = prepare_price_frame(prices)
    assert len(df) == 200
    assert list(df["timestamp"]) == sorted(df["timestamp"])


def test_build_features_handles_crypto_shaped_history_without_raising():
    prices = _crypto_price_history("2023-01-01", 200)
    features = build_features(prices)
    assert len(features) == 200
    # technical_v2 spine columns are all present, not silently dropped.
    for column in feature_columns_for_set("technical_v2"):
        assert column in features.columns


def test_compute_technical_alpha_factors_handles_crypto_shaped_history_without_raising():
    prices = _crypto_price_history("2023-01-01", 200)
    spine = build_features(prices)
    factors = compute_technical_alpha_factors(spine)
    assert len(factors) == len(spine)
    assert list(factors.columns) == list(FACTOR_KEYS)
    assert set(TECHNICAL_ALPHA_OVERLAY_COLUMNS) == set(FACTOR_KEYS)


def test_technical_alpha_v1_end_to_end_for_a_btc_usd_shaped_ticker():
    """Exercises the exact same code path materialize_asset_technical_alpha
    uses (build_technical_alpha_overlay -> feature_columns_for_set), minus
    the Postgres I/O, for a ticker string in crypto's hyphenated format."""
    ticker = "BTC-USD"
    prices = _crypto_price_history("2022-06-01", 250)

    overlay = build_technical_alpha_overlay(prices)
    feature_columns = feature_columns_for_set(
        feature_set_for_asset_class("crypto")
    )
    assert feature_columns == feature_columns_for_set("technical_alpha_v1")

    materialized_rows = overlay.dropna(subset=feature_columns)
    assert not materialized_rows.empty, f"{ticker} produced no usable technical_alpha_v1 rows"
    for column in feature_columns:
        assert column in overlay.columns


# ---------------------------------------------------------------------------
# Ticker-format regression: a hyphenated crypto ticker must not corrupt an
# artifact path or model version string (both interpolate the raw ticker).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ticker", ["BTC-USD", "ETH-USD"])
def test_hyphenated_crypto_ticker_produces_a_safe_model_version(ticker):
    version = build_model_version(ticker)
    assert "-" not in version
    assert ticker.replace("-", "_") in version


@pytest.mark.parametrize("ticker", ["BTC-USD", "ETH-USD"])
def test_hyphenated_crypto_ticker_produces_a_safe_artifact_path(ticker):
    candidate = {"model_name": "random_forest", "scope": "local"}
    report = {"feature_set": "technical_alpha_v1"}
    path = build_artifact_path(ticker, candidate, report, "auto_v1", "models")
    assert "-" not in path
    assert ticker.replace("-", "_") in path


# ---------------------------------------------------------------------------
# Step-2 finding: brain.backtesting's Sharpe-like ratio hardcoded an
# NYSE-252-trading-day/year annualization factor. BacktestConfig now exposes
# `periods_per_year` (default 252, unchanged for every existing stock
# caller) so a caller that knows it is scoring a 24/7 market (crypto trades
# ~365 bars/year via BinanceProvider's daily klines, not ~252) can correct
# the annualization. Nothing auto-detects asset_class here yet -- same
# unwired-hook shape as FEATURE_SET_OVERLAYS_BY_ASSET_CLASS itself before
# this change -- so this is regression coverage for the new parameter, not a
# claim that crypto backtests are auto-corrected today.
# ---------------------------------------------------------------------------


def _feedback_frame() -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "predicted_action": ["BUY", "SELL", "BUY", "HOLD", "BUY", "SELL"],
            "confidence": [0.8, 0.7, 0.65, 0.5, 0.9, 0.75],
            "outcome_return": [0.02, -0.01, 0.015, 0.0, -0.005, 0.01],
        }
    )


def test_backtest_config_defaults_periods_per_year_to_252_stock_behavior_unchanged():
    assert BacktestConfig().periods_per_year == 252


def test_sharpe_like_scales_with_periods_per_year():
    feedback = _feedback_frame()
    stock_result = run_prediction_backtest(feedback, BacktestConfig(periods_per_year=252))
    crypto_result = run_prediction_backtest(feedback, BacktestConfig(periods_per_year=365))

    stock_sharpe = stock_result.metrics["sharpe_like"]
    crypto_sharpe = crypto_result.metrics["sharpe_like"]
    assert stock_sharpe is not None
    assert crypto_sharpe is not None
    # Same trade returns, only the annualization factor differs -> the ratio
    # between the two Sharpe-like values must equal sqrt(365/252) exactly.
    assert crypto_sharpe / stock_sharpe == pytest.approx((365 / 252) ** 0.5)
