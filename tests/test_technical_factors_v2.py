"""Phase 5 (technical-alpha factors): `brain.technical_factors_v2`.

No-look-ahead is the acceptance contract, mirroring
`tests/test_fundamental_factors.py`'s C1 discipline tests but enforced by a
different mechanism (row position, not `filed_date`): every factor's value
at row N must be identical whether it is computed on the full frame or on
any prefix that still contains row N. Truncating away FUTURE rows must never
change a past value, and every division-by-zero corner case must resolve to
NaN, never an exception.

No DB, no HTTP -- this module is pure, so every fixture here is a small
hand-built OHLCV DataFrame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from brain.features import TECHNICAL_ALPHA_OVERLAY_COLUMNS
from brain.technical_factors_v2 import (
    FACTOR_KEYS,
    MOMENTUM_WINDOWS,
    MOVING_AVERAGE_WINDOWS,
    VOLATILITY_WINDOWS,
    VOLUME_RATIO_WINDOWS,
    _safe_div,
    compute_moving_average_ratio_factors,
    compute_momentum_factors,
    compute_price_shape_factors,
    compute_technical_alpha_factors,
    compute_volatility_factors,
    compute_volume_ratio_factors,
)


def _ohlcv(rows: list[dict[str, float]]) -> pd.DataFrame:
    """A chronological (ascending) OHLCV frame with a plain RangeIndex,
    matching what `prepare_price_frame` hands `build_features` in
    `brain/features.py`."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def _trending_ohlcv(n: int, *, start: float = 100.0, step: float = 1.0, volume: float = 1_000.0) -> pd.DataFrame:
    """A deterministic, strictly increasing synthetic series long enough to
    fill every rolling window this module uses (max window = 60)."""
    closes = [start + step * i for i in range(n)]
    rows = []
    for i, close in enumerate(closes):
        open_ = closes[i - 1] if i > 0 else close - step
        high = max(open_, close) + 0.5
        low = min(open_, close) - 0.5
        rows.append({"open": open_, "high": high, "low": low, "close": close, "volume": volume + i})
    return _ohlcv(rows)


# ---------------------------------------------------------------------------
# _safe_div
# ---------------------------------------------------------------------------


def test_safe_div_nan_on_zero_denominator_not_inf() -> None:
    numerator = pd.Series([10.0, 5.0, -3.0])
    denominator = pd.Series([2.0, 0.0, 0.0])

    result = _safe_div(numerator, denominator)

    assert result.iloc[0] == pytest.approx(5.0)
    assert np.isnan(result.iloc[1])
    assert np.isnan(result.iloc[2])
    assert not np.isinf(result).any()


def test_safe_div_propagates_nan_numerator_and_denominator() -> None:
    numerator = pd.Series([np.nan, 4.0])
    denominator = pd.Series([2.0, np.nan])

    result = _safe_div(numerator, denominator)

    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])


# ---------------------------------------------------------------------------
# price-shape factors
# ---------------------------------------------------------------------------


def test_price_shape_factors_formula() -> None:
    df = _ohlcv([{"open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0, "volume": 1000.0}])

    result = compute_price_shape_factors(df)

    assert result["candle_body_ratio"].iloc[0] == pytest.approx((105.0 - 100.0) / 100.0)
    assert result["candle_range_ratio"].iloc[0] == pytest.approx((110.0 - 95.0) / 100.0)
    assert result["candle_upper_shadow_ratio"].iloc[0] == pytest.approx(
        (110.0 - 105.0) / (110.0 - 95.0), abs=1e-6
    )
    assert result["candle_lower_shadow_ratio"].iloc[0] == pytest.approx(
        (105.0 - 95.0) / (110.0 - 95.0), abs=1e-6
    )


def test_price_shape_body_and_range_ratio_nan_on_zero_open() -> None:
    df = _ohlcv([{"open": 0.0, "high": 10.0, "low": 5.0, "close": 8.0, "volume": 1000.0}])

    result = compute_price_shape_factors(df)

    assert np.isnan(result["candle_body_ratio"].iloc[0])
    assert np.isnan(result["candle_range_ratio"].iloc[0])
    # Shadow ratios do not depend on `open`, so they remain finite.
    assert not np.isnan(result["candle_upper_shadow_ratio"].iloc[0])
    assert not np.isnan(result["candle_lower_shadow_ratio"].iloc[0])


def test_price_shape_shadow_ratios_finite_on_doji_candle() -> None:
    """A zero-range candle (high == low) must not raise or yield inf -- the
    `_EPSILON` guard keeps the denominator strictly positive."""
    df = _ohlcv([{"open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "volume": 1000.0}])

    result = compute_price_shape_factors(df)

    assert np.isfinite(result["candle_upper_shadow_ratio"].iloc[0])
    assert np.isfinite(result["candle_lower_shadow_ratio"].iloc[0])
    assert result["candle_body_ratio"].iloc[0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# momentum / volatility / moving-average-ratio / volume-ratio factors
# ---------------------------------------------------------------------------


def test_momentum_factors_match_pct_change_and_warm_up_to_nan() -> None:
    df = _trending_ohlcv(65)

    result = compute_momentum_factors(df)

    for window in MOMENTUM_WINDOWS:
        column = f"roc_{window}d"
        assert list(result.columns).count(column) == 1
        expected = df["close"].pct_change(window)
        pd.testing.assert_series_equal(result[column], expected, check_names=False)
        # First `window` rows have no `window`-bars-ago close -> NaN, not an exception.
        assert result[column].iloc[:window].isna().all()


def test_volatility_factors_match_rolling_std_of_daily_returns() -> None:
    df = _trending_ohlcv(65)

    result = compute_volatility_factors(df)

    daily_return = df["close"].pct_change(1)
    for window in VOLATILITY_WINDOWS:
        column = f"ret_volatility_{window}d"
        expected = daily_return.rolling(window).std()
        pd.testing.assert_series_equal(result[column], expected, check_names=False)


def test_moving_average_ratio_factors_match_formula() -> None:
    df = _trending_ohlcv(65)

    result = compute_moving_average_ratio_factors(df)

    for window in MOVING_AVERAGE_WINDOWS:
        column = f"ma_ratio_{window}d"
        expected = df["close"] / df["close"].rolling(window).mean()
        pd.testing.assert_series_equal(result[column], expected, check_names=False)


def test_moving_average_ratio_nan_on_zero_rolling_mean() -> None:
    # A close of exactly 0.0 for the whole window makes the rolling mean 0.
    df = _ohlcv([{"open": 1.0, "high": 1.0, "low": 0.0, "close": 0.0, "volume": 100.0} for _ in range(5)])

    result = compute_moving_average_ratio_factors(df)

    assert np.isnan(result["ma_ratio_5d"].iloc[-1])
    assert not np.isinf(result["ma_ratio_5d"]).any()


def test_volume_ratio_factors_match_formula() -> None:
    df = _trending_ohlcv(25)

    result = compute_volume_ratio_factors(df)

    for window in VOLUME_RATIO_WINDOWS:
        column = f"volume_ratio_{window}d"
        expected = df["volume"] / df["volume"].rolling(window).mean()
        pd.testing.assert_series_equal(result[column], expected, check_names=False)


def test_volume_ratio_nan_on_zero_rolling_mean_volume() -> None:
    df = _ohlcv([{"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0} for _ in range(5)])

    result = compute_volume_ratio_factors(df)

    assert np.isnan(result["volume_ratio_5d"].iloc[-1])
    assert not np.isinf(result["volume_ratio_5d"]).any()


# ---------------------------------------------------------------------------
# compute_technical_alpha_factors -- shape + never raises
# ---------------------------------------------------------------------------


def test_compute_technical_alpha_factors_returns_exactly_factor_keys() -> None:
    df = _trending_ohlcv(65)

    result = compute_technical_alpha_factors(df)

    assert list(result.columns) == list(FACTOR_KEYS)
    assert len(result) == len(df)


def test_compute_technical_alpha_factors_never_raises_on_short_frame() -> None:
    # Shorter than every rolling window -- every windowed column should be
    # all-NaN, never an exception.
    df = _trending_ohlcv(3)

    result = compute_technical_alpha_factors(df)

    assert result["roc_60d"].isna().all()
    assert result["ret_volatility_60d"].isna().all()
    assert result["ma_ratio_60d"].isna().all()


def test_compute_technical_alpha_factors_no_inf_values() -> None:
    df = _trending_ohlcv(65)

    result = compute_technical_alpha_factors(df)

    assert not np.isinf(result.to_numpy(dtype=float, na_value=np.nan)).any()


# ---------------------------------------------------------------------------
# No-look-ahead: truncating the frame to FUTURE rows must not change a value
# already computed at an earlier row.
# ---------------------------------------------------------------------------


def test_point_in_time_safety_truncating_future_rows_does_not_change_past_values() -> None:
    df = _trending_ohlcv(80)
    full_result = compute_technical_alpha_factors(df)

    # Row 65 (0-indexed) has full history for every window (max window 60).
    row = 65
    truncated = df.iloc[: row + 1].reset_index(drop=True)
    truncated_result = compute_technical_alpha_factors(truncated)

    pd.testing.assert_series_equal(
        full_result.iloc[row],
        truncated_result.iloc[row],
        check_names=False,
    )


def test_point_in_time_safety_holds_for_every_factor_group_independently() -> None:
    """Same check as above, one row earlier than full warm-up for every
    window (row 40), run against each group function directly -- proves the
    guarantee is not an artifact of `compute_technical_alpha_factors`'
    concat/reindex step."""
    df = _trending_ohlcv(80)
    row = 40
    truncated = df.iloc[: row + 1].reset_index(drop=True)

    group_functions = (
        compute_price_shape_factors,
        compute_momentum_factors,
        compute_volatility_factors,
        compute_moving_average_ratio_factors,
        compute_volume_ratio_factors,
    )
    for group_function in group_functions:
        full = group_function(df).iloc[row]
        truncated_value = group_function(truncated).iloc[row]
        pd.testing.assert_series_equal(full, truncated_value, check_names=False)


# ---------------------------------------------------------------------------
# Overlay composition (C2-style regression, mirroring
# tests/test_feature_set_resolution.py's fundamental_v1 contract test).
# ---------------------------------------------------------------------------


def test_factor_keys_match_overlay_columns_registered_in_features() -> None:
    assert set(FACTOR_KEYS) == set(TECHNICAL_ALPHA_OVERLAY_COLUMNS)
    assert len(FACTOR_KEYS) == 19
