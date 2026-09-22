from __future__ import annotations

import numpy as np
import pandas as pd


BASE_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}
FEATURE_COLUMNS_TECHNICAL_V1 = [
    "return_1d",
    "return_3d",
    "return_5d",
    "log_return_1d",
    "volatility_10d",
    "volatility_20d",
    "sma_10_ratio",
    "sma_20_ratio",
    "ema_10_ratio",
    "rsi_14",
    "macd",
    "macd_signal",
    "volume_zscore_20",
    "atr_14",
    "drawdown_20",
]
FEATURE_COLUMNS_TECHNICAL_V2 = [
    *FEATURE_COLUMNS_TECHNICAL_V1,
    "return_10d",
    "return_20d",
    "volatility_ratio_10_20",
    "sma_50_ratio",
    "bollinger_percent_b_20",
    "bollinger_bandwidth_20",
    "stochastic_k_14",
    "stochastic_d_3",
    "obv_zscore_20",
    "adx_14",
]
FEATURE_COLUMNS_BY_SET = {
    "technical_v1": FEATURE_COLUMNS_TECHNICAL_V1,
    "technical_v2": FEATURE_COLUMNS_TECHNICAL_V2,
}
FEATURE_COLUMNS = FEATURE_COLUMNS_TECHNICAL_V1

# Asset-class -> feature-set-name overlay registry. "crypto" resolves to
# technical_alpha_v1 (see that feature set's registration below): every
# column in technical_alpha_v1 (the technical_v2 spine plus the 19
# Alpha158-inspired factors) is a pure function of OHLCV prices, which every
# crypto asset has, unlike fundamental_v1 (SEC XBRL filings -- stock-only, no
# equivalent data exists for a cryptocurrency). This entry only takes effect
# for a caller that actually resolves a feature set via
# `feature_set_for_asset_class`/`feature_columns_for_set(..., asset_class=...)`
# -- as of this change, no production call site does (every training/
# inference entry point still takes an explicit `feature_set` string), so
# this registers the POLICY without yet being wired into an automatic
# per-asset-class default; see tests/test_crypto_feature_set.py.
FEATURE_SET_OVERLAYS_BY_ASSET_CLASS: dict[str, str] = {"crypto": "technical_alpha_v1"}
DEFAULT_BASE_FEATURE_SET = "technical_v2"


def feature_set_for_asset_class(asset_class: str, base_feature_set: str = DEFAULT_BASE_FEATURE_SET) -> str:
    """Policy: which feature-set name an asset SHOULD use. Never raises; unmapped class -> base."""
    return FEATURE_SET_OVERLAYS_BY_ASSET_CLASS.get((asset_class or "").strip().lower(), base_feature_set)


def feature_columns_for_set(feature_set: str, *, asset_class: str | None = None) -> list[str]:
    # asset_class is None on all existing call sites -> strictly string-keyed,
    # byte-identical behavior including the ValueError for an unknown name.
    resolved = feature_set if asset_class is None else feature_set_for_asset_class(asset_class, feature_set)
    try:
        return FEATURE_COLUMNS_BY_SET[resolved]
    except KeyError as error:
        raise ValueError(f"Unknown feature_set: {resolved}. Available: {sorted(FEATURE_COLUMNS_BY_SET)}") from error


def compose_feature_set(base_feature_set: str, overlay_columns: list[str]) -> list[str]:
    """Siblings register the result under a NEW name; technical_v2 is never mutated."""
    return [*feature_columns_for_set(base_feature_set), *overlay_columns]


# fundamental-analysis (Phase 4): the opt-in stock-only overlay. `compose_feature_set`
# returns a NEW list ([*base, *overlay]), so technical_v2's list object is never
# mutated or aliased -- C2 holds structurally, not by convention. The three columns
# here MUST equal set(brain.fundamental_factors.FACTOR_KEYS) -- asserted by a
# contract test in tests/test_feature_set_resolution.py. This module intentionally
# never imports brain.fundamental_factors (keeps the import graph acyclic; see that
# module's own docstring), so the two lists are declared independently and kept in
# sync by the contract test, not by a shared import.
FUNDAMENTAL_OVERLAY_COLUMNS = [
    "piotroski_f_score",
    "altman_z_score",
    "gross_profitability",
]
FEATURE_COLUMNS_BY_SET["fundamental_v1"] = compose_feature_set(
    "technical_v2", FUNDAMENTAL_OVERLAY_COLUMNS
)

# technical-alpha (Phase 5): an opt-in overlay of Qlib "Alpha158"-inspired
# technical factors (price-shape, momentum, rolling volatility, moving-average
# ratio, volume ratio) -- see brain.technical_factors_v2's module docstring for
# the exact formulas and the no-look-ahead discipline. As with
# FUNDAMENTAL_OVERLAY_COLUMNS above, `compose_feature_set` returns a NEW list,
# so technical_v2's list object is never mutated or aliased. These 19 columns
# MUST equal set(brain.technical_factors_v2.FACTOR_KEYS) -- asserted by a
# contract test in tests/test_feature_set_resolution.py. This module
# intentionally never imports brain.technical_factors_v2 (same acyclic-import
# reasoning as the fundamental_v1 overlay above), so the two lists are declared
# independently and kept in sync by the contract test, not by a shared import.
TECHNICAL_ALPHA_OVERLAY_COLUMNS = [
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
]
FEATURE_COLUMNS_BY_SET["technical_alpha_v1"] = compose_feature_set(
    "technical_v2", TECHNICAL_ALPHA_OVERLAY_COLUMNS
)

# news-sentiment (Phase 6, point 4): an opt-in overlay of two FinBERT-scored,
# exponentially-decayed news-sentiment factors -- see
# brain.sentiment_factors's module docstring for the point-in-time
# (published_at <= cutoff) discipline and the exact window/half-life
# definition. Composed onto the bare technical_v2 spine, same base
# fundamental_v1 uses -- not technical_alpha_v1 -- so this feature set stays
# independent of the technical-alpha materializer (see
# brain/materialize_sentiment.py's module docstring). Unlike
# fundamental_v1, there is no stock-only restriction: a news-driven signal
# is at least as plausible for crypto as it is for stocks. As with the two
# overlays above, compose_feature_set returns a NEW list, so technical_v2's
# list object is never mutated or aliased. These two columns MUST equal
# set(brain.sentiment_factors.FACTOR_KEYS) -- asserted by a contract test in
# tests/test_feature_set_resolution.py. This module intentionally never
# imports brain.sentiment_factors (same acyclic-import reasoning as the two
# overlays above), so the two lists are declared independently and kept in
# sync by the contract test, not by a shared import.
SENTIMENT_OVERLAY_COLUMNS = [
    "sentiment_score_7d",
    "sentiment_headline_count_7d",
]
FEATURE_COLUMNS_BY_SET["sentiment_v1"] = compose_feature_set(
    "technical_v2", SENTIMENT_OVERLAY_COLUMNS
)


def prepare_price_frame(prices: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """Normalize raw OHLCV rows into a chronological DataFrame."""
    df = pd.DataFrame(prices).copy()
    missing = BASE_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required price columns: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    return df.reset_index(drop=True)


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period).mean()


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    atr = calculate_atr(df, period)
    plus_di = 100 * plus_dm.rolling(period).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(period).mean() / atr.replace(0, np.nan)
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.rolling(period).mean()


def build_features(prices: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """
    Build point-in-time features using only data available at each timestamp.

    The target labels are intentionally created elsewhere to keep leakage checks
    simple: this module never looks forward.
    """
    df = prepare_price_frame(prices)
    close = df["close"]
    volume = df["volume"]

    df["return_1d"] = close.pct_change(1)
    df["return_3d"] = close.pct_change(3)
    df["return_5d"] = close.pct_change(5)
    df["return_10d"] = close.pct_change(10)
    df["return_20d"] = close.pct_change(20)
    df["log_return_1d"] = np.log(close / close.shift(1))
    df["volatility_10d"] = df["log_return_1d"].rolling(10).std()
    df["volatility_20d"] = df["log_return_1d"].rolling(20).std()
    df["volatility_ratio_10_20"] = df["volatility_10d"] / df["volatility_20d"].replace(0, np.nan)

    sma_10 = close.rolling(10).mean()
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()
    ema_10 = close.ewm(span=10, adjust=False).mean()
    df["sma_10_ratio"] = close / sma_10 - 1
    df["sma_20_ratio"] = close / sma_20 - 1
    df["sma_50_ratio"] = close / sma_50 - 1
    df["ema_10_ratio"] = close / ema_10 - 1

    bollinger_mean = sma_20
    bollinger_std = close.rolling(20).std()
    bollinger_upper = bollinger_mean + (2 * bollinger_std)
    bollinger_lower = bollinger_mean - (2 * bollinger_std)
    bollinger_range = (bollinger_upper - bollinger_lower).replace(0, np.nan)
    df["bollinger_percent_b_20"] = (close - bollinger_lower) / bollinger_range
    df["bollinger_bandwidth_20"] = bollinger_range / bollinger_mean.replace(0, np.nan)

    exp_fast = close.ewm(span=12, adjust=False).mean()
    exp_slow = close.ewm(span=26, adjust=False).mean()
    df["macd"] = exp_fast - exp_slow
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["rsi_14"] = calculate_rsi(close)

    volume_mean = volume.rolling(20).mean()
    volume_std = volume.rolling(20).std()
    df["volume_zscore_20"] = (volume - volume_mean) / volume_std.replace(0, np.nan)
    df["atr_14"] = calculate_atr(df)
    df["adx_14"] = calculate_adx(df)

    low_14 = df["low"].rolling(14).min()
    high_14 = df["high"].rolling(14).max()
    df["stochastic_k_14"] = 100 * (close - low_14) / (high_14 - low_14).replace(0, np.nan)
    df["stochastic_d_3"] = df["stochastic_k_14"].rolling(3).mean()

    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume).cumsum()
    obv_mean = obv.rolling(20).mean()
    obv_std = obv.rolling(20).std()
    df["obv_zscore_20"] = (obv - obv_mean) / obv_std.replace(0, np.nan)

    rolling_high = close.rolling(20).max()
    df["drawdown_20"] = close / rolling_high - 1

    return df.replace([np.inf, -np.inf], np.nan)
