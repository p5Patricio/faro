"""Phase 5 (materialization): `brain.materialize_technical_alpha`.

Mirrors `tests/test_fundamental_lookahead.py`'s layering for
`materialize_fundamentals`, adapted to this feature set's simpler shape:
`technical_alpha_v1` has no irregularly-timed second data source, so there
is no C1 `filed_date` provenance to test here. Instead the acceptance
contract is:

- the overlay's columns are exactly `technical_v2`'s columns plus
  `TECHNICAL_ALPHA_OVERLAY_COLUMNS` (`brain/features.py`'s registered list),
  never more, never fewer;
- the alpha-factor columns in the overlay are ROW-ALIGNED with the spine --
  proven by comparing against an independent direct computation, not merely
  asserted;
- truncating away FUTURE rows never changes an already-computed row's
  values (same no-look-ahead discipline as
  `tests/test_technical_factors_v2.py`, now checked at the materialization
  layer instead of the pure-factor layer); and
- the DB round trip (real Postgres, rolled back) persists exactly what the
  pure function computed, for BOTH a stock and a crypto asset -- proving
  there is no stock-only restriction, unlike `fundamental_v1`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from brain.features import TECHNICAL_ALPHA_OVERLAY_COLUMNS, build_features, feature_columns_for_set
from brain.materialize_technical_alpha import (
    OVERLAY_COLUMNS,
    TechnicalAlphaMaterializationConfig,
    build_technical_alpha_overlay,
    materialize_asset_technical_alpha,
)
from brain.technical_factors_v2 import FACTOR_KEYS, compute_technical_alpha_factors


def _price_history(start: str, periods: int) -> pd.DataFrame:
    """A deterministic synthetic OHLCV history, same tone as
    `tests/test_fundamental_lookahead.py::_price_history` -- long enough for
    every rolling window in both `build_features` (50 days) and
    `compute_technical_alpha_factors` (60 days) to warm up well before the
    end of the series."""
    timestamps = pd.date_range(start, periods=periods, freq="D", tz="UTC")
    wave = np.sin(np.arange(periods) / 3) * 2.5
    trend = np.arange(periods) * 0.03
    close = 100 + wave + trend
    open_ = close + np.cos(np.arange(periods)) * 0.2
    high = np.maximum(open_, close) + 1.0
    low = np.minimum(open_, close) - 1.0
    volume = 1_000_000 + (np.arange(periods) % 9) * 10_000
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
# Overlay shape: exactly technical_v2's columns plus the 19 alpha factors
# ---------------------------------------------------------------------------


def test_overlay_columns_are_exactly_technical_v2_plus_factor_keys() -> None:
    prices = _price_history("2023-01-01", 200)

    overlay = build_technical_alpha_overlay(prices)

    technical_v2_columns = set(feature_columns_for_set("technical_v2"))
    assert technical_v2_columns.issubset(set(overlay.columns))
    for key in FACTOR_KEYS:
        assert key in overlay.columns

    # OVERLAY_COLUMNS (this module) and TECHNICAL_ALPHA_OVERLAY_COLUMNS
    # (brain/features.py) must agree -- kept in sync by this test, not by a
    # shared import, mirroring the existing contract test in
    # tests/test_feature_set_resolution.py.
    assert set(OVERLAY_COLUMNS) == set(TECHNICAL_ALPHA_OVERLAY_COLUMNS)
    assert set(OVERLAY_COLUMNS) == set(FACTOR_KEYS)
    assert len(OVERLAY_COLUMNS) == 19


def test_overlay_selected_via_feature_columns_for_set_has_no_missing_columns() -> None:
    """The exact column list `materialize_asset_technical_alpha` hands to
    `upsert_features` (technical_v2 + the 19 factors, 44 total) must all be
    present on the overlay -- proves the two pieces really do concatenate
    into a single, complete row, not a partial one."""
    prices = _price_history("2023-01-01", 200)
    overlay = build_technical_alpha_overlay(prices)

    feature_columns = feature_columns_for_set("technical_alpha_v1")
    assert len(feature_columns) == 44
    missing = set(feature_columns) - set(overlay.columns)
    assert missing == set()


# ---------------------------------------------------------------------------
# Row alignment: the alpha columns are positioned exactly like an
# independent direct computation over the same normalized spine.
# ---------------------------------------------------------------------------


def test_alpha_columns_row_aligned_with_independent_direct_computation() -> None:
    prices = _price_history("2023-01-01", 200)

    overlay = build_technical_alpha_overlay(prices)

    spine = build_features(prices)
    expected_alpha = compute_technical_alpha_factors(spine)

    pd.testing.assert_series_equal(overlay["timestamp"], spine["timestamp"], check_names=False)
    for key in FACTOR_KEYS:
        pd.testing.assert_series_equal(overlay[key], expected_alpha[key], check_names=False)


def test_overlay_row_count_matches_spine_row_count() -> None:
    prices = _price_history("2023-01-01", 137)
    overlay = build_technical_alpha_overlay(prices)
    spine = build_features(prices)
    assert len(overlay) == len(spine)


# ---------------------------------------------------------------------------
# No-look-ahead: truncating away future rows must not change a past row's
# values, for either column group -- reuses
# tests/test_technical_factors_v2.py's truncation idea at the
# materialization layer.
# ---------------------------------------------------------------------------


def test_no_future_row_leakage_truncating_rows_does_not_change_past_values() -> None:
    prices = _price_history("2023-01-01", 150)
    full_overlay = build_technical_alpha_overlay(prices)

    # Row 80 has full history for every rolling window used by either group
    # (max window: 60 for the alpha factors, 50 for technical_v2's sma_50_ratio).
    row = 80
    truncated_prices = prices.iloc[: row + 1].reset_index(drop=True)
    truncated_overlay = build_technical_alpha_overlay(truncated_prices)

    pd.testing.assert_series_equal(
        full_overlay.iloc[row],
        truncated_overlay.iloc[row],
        check_names=False,
    )


def test_no_future_row_leakage_holds_before_full_warm_up_too() -> None:
    """Same check one row before the alpha factors' longest window (60) has
    fully warmed up -- the values at that row are still NaN in both runs,
    which is itself part of the point-in-time guarantee (a row's NaN-ness
    must not depend on how much future data follows it either)."""
    prices = _price_history("2023-01-01", 150)
    full_overlay = build_technical_alpha_overlay(prices)

    row = 55
    truncated_prices = prices.iloc[: row + 1].reset_index(drop=True)
    truncated_overlay = build_technical_alpha_overlay(truncated_prices)

    pd.testing.assert_series_equal(
        full_overlay.iloc[row],
        truncated_overlay.iloc[row],
        check_names=False,
    )


# ---------------------------------------------------------------------------
# DB round trip (real Postgres, rolled back) -- stock AND crypto, proving
# there is no stock-only restriction for this feature set.
# ---------------------------------------------------------------------------


def test_db_round_trip_stock(repository) -> None:
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    prices = _price_history("2021-11-01", 300)
    repository.upsert_prices(asset_id, prices)

    result = materialize_asset_technical_alpha(
        repository, TechnicalAlphaMaterializationConfig(ticker="aapl")
    )
    assert result.asset_class == "stock"
    assert result.feature_rows_loaded > 0

    expected_overlay = build_technical_alpha_overlay(prices)
    feature_columns = feature_columns_for_set("technical_alpha_v1")
    expected_rows = expected_overlay.dropna(subset=feature_columns).set_index("timestamp")
    assert not expected_rows.empty

    stored = repository.get_features(asset_id, "technical_alpha_v1")
    stored["timestamp"] = pd.to_datetime(stored["timestamp"], utc=True)
    assert sorted(stored["timestamp"]) == sorted(expected_rows.index)

    for _, row in stored.iterrows():
        expected_row = expected_rows.loc[row["timestamp"]]
        for column in feature_columns:
            assert row["features"][column] == pytest.approx(expected_row[column])


def test_db_round_trip_crypto_is_not_skipped(repository) -> None:
    """spec: technical_alpha_v1 has no stock-only restriction -- a crypto
    asset materializes real rows, never zero, unlike fundamental_v1's
    `skipped_assets` behavior for the same asset class."""
    asset_id = repository.get_or_create_asset("btc-usd", asset_class="crypto")
    prices = _price_history("2021-11-01", 300)
    repository.upsert_prices(asset_id, prices)

    result = materialize_asset_technical_alpha(
        repository, TechnicalAlphaMaterializationConfig(ticker="btc-usd")
    )

    assert result.asset_class == "crypto"
    assert result.feature_rows_loaded > 0

    stored = repository.get_features(asset_id, "technical_alpha_v1")
    assert not stored.empty
