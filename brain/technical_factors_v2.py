"""Point-in-time technical-alpha factor computation: price-shape, momentum,
rolling volatility, moving-average ratio, and volume-ratio factors computed
directly off a chronological per-ticker OHLCV DataFrame.

Inspired by Microsoft Qlib's "Alpha158" factor CATEGORY (momentum,
volatility, volume, price-range/shape) -- this is NOT a port of Qlib's code
and does not reproduce Qlib's exact formulas. Every formula below is a
standard, textbook technical-analysis construction (rate of change, rolling
return volatility, close/SMA ratio, volume/its own moving average, candle
body/shadow ratios) assembled from general quantitative-finance knowledge;
none of it is proprietary or copied from any single source.

Pure module -- no DB, no HTTP. Imports only `numpy`/`pandas`. Like
`brain/fundamental_factors.py`, this module is deliberately kept OUT of
`brain/features.py`: `brain/features.py` gains a
`TECHNICAL_ALPHA_OVERLAY_COLUMNS` list (declared independently, a plain
literal, never importing `FACTOR_KEYS` from here) and composes it onto
`technical_v2` as the new `technical_alpha_v1` feature set. That keeps the
import graph acyclic and mirrors `fundamental_factors.py`'s own reasoning
(see that module's docstring) -- the two column lists are kept in sync by
`tests/test_feature_set_resolution.py`'s contract test, not by a shared
import.

No-look-ahead discipline (the single most important rule in this module,
same principle as `fundamental_factors.py`'s C1 `filed_date <= cutoff` rule,
enforced by a DIFFERENT mechanism): every windowed computation here is
causal by construction --
- `Series.pct_change(n)` and `Series.rolling(n)` only ever read the current
  row and the `n - 1` rows strictly BEFORE it;
- there is no centered window (`center=True` is never passed), no
  `.shift(-n)`, and no other operation that reads a future row.
A factor value at row N therefore never changes if the DataFrame is
truncated to any prefix ending at or after row N -- only truncating away
FUTURE rows (rows after N) can ever affect it. This is what
`tests/test_technical_factors_v2.py` checks directly: computing a factor on
the full frame and on a frame truncated to `rows[: N + 1]` must agree at row
N.

Non-raising is achieved BY CONSTRUCTION, not by a bare `except`:
- `_safe_div` (mirroring `fundamental_factors.py`'s scalar `_safe_div`,
  vectorized here over `pandas.Series`) turns a zero or NaN denominator into
  NaN rather than `inf`/`ZeroDivisionError`;
- the two shadow-ratio factors use a small additive `_EPSILON` in their
  denominator (the standard textbook guard for a candle with `high == low`,
  a "doji"), so they never divide by exactly zero either;
- `rolling(n)`/`pct_change(n)` on their own already yield NaN for the first
  rows of any series shorter than the window -- ordinary pandas behavior,
  not a bug to work around.
A bare `except` would only ever hide a real bug here, never a legitimate
missing-data case.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Candle-shadow guard (see module docstring): keeps (high - low) + _EPSILON
# strictly positive for a zero-range ("doji") candle, matching the standard
# textbook definition of these ratios. Negligible relative to any real price.
_EPSILON = 1e-12

MOMENTUM_WINDOWS: tuple[int, ...] = (5, 10, 20, 60)
VOLATILITY_WINDOWS: tuple[int, ...] = (5, 10, 20, 60)
MOVING_AVERAGE_WINDOWS: tuple[int, ...] = (5, 10, 20, 60)
VOLUME_RATIO_WINDOWS: tuple[int, ...] = (5, 10, 20)

FACTOR_KEYS: tuple[str, ...] = (
    "candle_body_ratio",
    "candle_range_ratio",
    "candle_upper_shadow_ratio",
    "candle_lower_shadow_ratio",
    "roc_5d",
    "roc_10d",
    "roc_20d",
    "roc_60d",
    "ret_volatility_5d",
    "ret_volatility_10d",
    "ret_volatility_20d",
    "ret_volatility_60d",
    "ma_ratio_5d",
    "ma_ratio_10d",
    "ma_ratio_20d",
    "ma_ratio_60d",
    "volume_ratio_5d",
    "volume_ratio_10d",
    "volume_ratio_20d",
)


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Vectorized NaN-propagating division mirroring
    `fundamental_factors._safe_div`'s guard, adapted for `pandas.Series`: a
    zero (or NaN) denominator yields NaN at that row, never `inf` and never
    a divide-by-zero warning. Ordinary NaN propagation handles a NaN
    numerator on its own."""
    safe_denominator = denominator.mask(denominator == 0)
    return numerator / safe_denominator


def compute_price_shape_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Candle body/range/shadow ratios for each row, independent of every
    other row (no rolling window, so no warm-up period): `body_ratio` and
    `range_ratio` are guarded by `_safe_div` (NaN on `open == 0`);
    `upper_shadow_ratio`/`lower_shadow_ratio` use the standard `+ _EPSILON`
    guard on a zero-range candle."""
    open_ = df["open"]
    high = df["high"]
    low = df["low"]
    close = df["close"]
    high_low_range = high - low

    return pd.DataFrame(
        {
            "candle_body_ratio": _safe_div(close - open_, open_),
            "candle_range_ratio": _safe_div(high_low_range, open_),
            "candle_upper_shadow_ratio": (high - close) / (high_low_range + _EPSILON),
            "candle_lower_shadow_ratio": (close - low) / (high_low_range + _EPSILON),
        },
        index=df.index,
    )


def compute_momentum_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Rate-of-change momentum: `close.pct_change(n)` for each window in
    `MOMENTUM_WINDOWS`. The first `n` rows of each column are NaN by
    construction (not enough history), never an exception."""
    close = df["close"]
    return pd.DataFrame(
        {f"roc_{window}d": close.pct_change(window) for window in MOMENTUM_WINDOWS},
        index=df.index,
    )


def compute_volatility_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling standard deviation of 1-day returns over each window in
    `VOLATILITY_WINDOWS`. Uses the same causal `rolling(n)` primitive as
    every other factor here -- never a centered window."""
    daily_return = df["close"].pct_change(1)
    return pd.DataFrame(
        {f"ret_volatility_{window}d": daily_return.rolling(window).std() for window in VOLATILITY_WINDOWS},
        index=df.index,
    )


def compute_moving_average_ratio_factors(df: pd.DataFrame) -> pd.DataFrame:
    """`close / close.rolling(n).mean()` for each window in
    `MOVING_AVERAGE_WINDOWS`, guarded by `_safe_div` (NaN, not inf, on a
    degenerate zero rolling mean)."""
    close = df["close"]
    return pd.DataFrame(
        {
            f"ma_ratio_{window}d": _safe_div(close, close.rolling(window).mean())
            for window in MOVING_AVERAGE_WINDOWS
        },
        index=df.index,
    )


def compute_volume_ratio_factors(df: pd.DataFrame) -> pd.DataFrame:
    """`volume / volume.rolling(n).mean()` for each window in
    `VOLUME_RATIO_WINDOWS`, guarded by `_safe_div` (NaN, not inf, on a
    zero-volume rolling mean, e.g. a newly listed or halted ticker)."""
    volume = df["volume"]
    return pd.DataFrame(
        {
            f"volume_ratio_{window}d": _safe_div(volume, volume.rolling(window).mean())
            for window in VOLUME_RATIO_WINDOWS
        },
        index=df.index,
    )


def compute_technical_alpha_factors(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute every `technical_alpha_v1` factor for one chronological
    (ascending-by-date) per-ticker OHLCV DataFrame with `open/high/low/close/
    volume` columns. Row order is trusted as given -- this module never
    sorts or validates the frame itself (that is `prepare_price_frame`'s job
    in `brain/features.py`, the same division of responsibility
    `fundamental_factors.py` has with its caller).

    Returns a DataFrame aligned to `prices.index` with exactly `FACTOR_KEYS`
    as columns, in that order. Every value is `np.nan` on missing/undefined
    input (insufficient warm-up history, a zero denominator) -- this
    function never raises for that reason.
    """
    factor_frame = pd.concat(
        [
            compute_price_shape_factors(prices),
            compute_momentum_factors(prices),
            compute_volatility_factors(prices),
            compute_moving_average_ratio_factors(prices),
            compute_volume_ratio_factors(prices),
        ],
        axis=1,
    )
    factor_frame = factor_frame.replace([np.inf, -np.inf], np.nan)
    return factor_frame[list(FACTOR_KEYS)]
