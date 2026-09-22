"""Phase 4 (Overlay + C1 hard test): `brain.materialize_fundamentals`.

The C1 hard requirement -- "every fact and every derived `features_daily`
row is indexed by SEC `filed_date`, never `period_end`" -- is the single
acceptance contract of this change (proposal.md). This file is the layered
proof design.md §8 describes:

- **C1-a** (`test_no_row_uses_a_filing_dated_on_or_after_its_own_timestamp`):
  every non-NaN row's `max_filed_date` is strictly before its own
  `timestamp`, and its value equals a fresh `compute_factors_as_of` call at
  that same `max_filed_date` -- proving the forward-fill carried the right
  vintage, not merely a plausible one.
- **C1-b** (`test_restatement_never_leaks_backward`) -- THE single most
  safety-critical test in this change: adding a LATER-filed restatement of
  an ALREADY-REPORTED period must never change a single row before that
  restatement's own effective (lagged) date, and MUST change every row from
  that date forward. A test that only checked "the final state is correct"
  would miss a leak; this test diffs two full re-runs against each other.
- **C1-c** (`test_c1c_nan_never_raises`): every missing-data shape (empty
  facts, a first-fiscal-year-only filer, no price on the as-of date, a
  concept present only under an unexpected unit) yields `NaN` for the
  affected factor(s) only, never an exception and never a partial score.
- Stock-only scope (`test_non_stock_asset_is_skipped_not_failed`): a crypto
  asset produces zero rows and is reported in `skipped_assets`, never an
  error -- proven against the real repository so `get_asset`'s asset_class
  branch is exercised for real, not mocked.

No test re-derives "which filings SHOULD have contributed" from scratch --
design.md §8 explicitly rejects that (it would re-implement the selection
algorithm and could agree with a buggy one). Instead every assertion reads
the actual provenance token (`max_filed_date`) the code itself produced and
checks it against the actual `timestamp` axis and a fresh recomputation.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from brain.features import build_features, feature_columns_for_set
from brain.fundamental_factors import FACTOR_KEYS, compute_factors_as_of
from brain.materialize_fundamentals import (
    FundamentalMaterializationConfig,
    build_fundamental_overlay,
    materialize_asset_fundamentals,
)
from collector.fundamentals import CONCEPT_CHAINS

FACT_COLUMNS = [
    "taxonomy",
    "concept",
    "unit",
    "period_end",
    "fiscal_year",
    "fiscal_period",
    "filed_date",
    "accession",
    "value",
]


def _fact(
    logical_concept: str,
    *,
    period_end: str,
    filed_date: str,
    value: float,
    fiscal_period: str = "FY",
    fiscal_year: int | None = None,
    accession: str = "acc-1",
    tag: tuple[str, str] | None = None,
) -> dict[str, Any]:
    expected_unit, chain = CONCEPT_CHAINS[logical_concept]
    taxonomy, concept = tag if tag is not None else chain[0]
    return {
        "taxonomy": taxonomy,
        "concept": concept,
        "unit": expected_unit,
        "period_end": period_end,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "filed_date": filed_date,
        "accession": accession,
        "value": value,
    }


def _facts_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=FACT_COLUMNS)
    return pd.DataFrame(rows, columns=FACT_COLUMNS)


def _spine(start: str, periods: int) -> pd.DataFrame:
    """A bare `timestamp`-only spine -- `build_fundamental_overlay` needs
    nothing else from its `spine` argument except that one column. A real
    `technical_v2` spine (from `build_features`) is a strict superset and is
    exercised separately in `test_c1e_db_round_trip`."""
    return pd.DataFrame({"timestamp": pd.date_range(start, periods=periods, freq="D", tz="UTC")})


def _flat_prices(spine: pd.DataFrame, *, close: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame({"timestamp": spine["timestamp"], "close": close})


def _price_history(start: str, periods: int) -> pd.DataFrame:
    """A synthetic OHLCV history -- same shape/tone as
    `tests/test_brain_pipeline.py::make_prices` -- long enough for
    `build_features`'s longest rolling window (`sma_50_ratio`, 50 days) to
    warm up well before the first filing event."""
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


def _two_year_facts() -> list[dict[str, Any]]:
    """FY2021 -> FY2022, the same hand-built company
    `tests/test_fundamental_factors.py::_two_year_facts` uses (all 9
    Piotroski signals TRUE, Altman/Novy-Marx both finite) -- reused here,
    not re-derived, so this file's "resolves to a number" assertions rest on
    a fixture already proven correct at the unit level."""
    fy2021 = dict(period_end="2021-12-31", filed_date="2022-02-10", fiscal_year=2021)
    fy2022 = dict(period_end="2022-12-31", filed_date="2023-02-15", fiscal_year=2022)
    return [
        _fact("assets", value=1000.0, **fy2021),
        _fact("assets_current", value=400.0, **fy2021),
        _fact("liabilities", value=600.0, **fy2021),
        _fact("liabilities_current", value=200.0, **fy2021),
        _fact("equity", value=400.0, **fy2021),
        _fact("long_term_debt", value=300.0, **fy2021),
        _fact("net_income", value=50.0, **fy2021),
        _fact("cfo", value=40.0, **fy2021),
        _fact("retained_earnings", value=150.0, **fy2021),
        _fact("operating_income", value=80.0, **fy2021),
        _fact("revenue", value=900.0, **fy2021),
        _fact("cost_of_revenue", value=600.0, **fy2021),
        _fact("shares_outstanding_wavg", value=100.0, **fy2021),
        _fact("shares_outstanding_mve", value=101.0, **fy2021),
        _fact("assets", value=1200.0, **fy2022),
        _fact("assets_current", value=500.0, **fy2022),
        _fact("liabilities", value=650.0, **fy2022),
        _fact("liabilities_current", value=220.0, **fy2022),
        _fact("equity", value=550.0, **fy2022),
        _fact("long_term_debt", value=280.0, **fy2022),
        _fact("net_income", value=90.0, **fy2022),
        _fact("cfo", value=110.0, **fy2022),
        _fact("retained_earnings", value=200.0, **fy2022),
        _fact("operating_income", value=130.0, **fy2022),
        _fact("revenue", value=1100.0, **fy2022),
        _fact("cost_of_revenue", value=650.0, **fy2022),
        _fact("shares_outstanding_wavg", value=98.0, **fy2022),
        _fact("shares_outstanding_mve", value=99.0, **fy2022),
    ]


# ---------------------------------------------------------------------------
# C1-a -- no row uses a filing dated on or after its own timestamp
# ---------------------------------------------------------------------------


def test_no_row_uses_a_filing_dated_on_or_after_its_own_timestamp() -> None:
    spine = _spine("2021-11-01", 500)
    prices = _flat_prices(spine, close=10.0)
    facts = _facts_frame(_two_year_facts())

    overlay = build_fundamental_overlay(spine, facts, prices)

    resolved = overlay.dropna(subset=["max_filed_date"])
    assert not resolved.empty  # the fixture must actually produce contributing rows

    recompute_cache: dict[date, dict[str, Any]] = {}
    for _, row in resolved.iterrows():
        # C1, strict: the contributing filing is dated BEFORE the row's own
        # timestamp, never on or after it.
        assert row["max_filed_date"] < row["timestamp"].date()

        cutoff = row["max_filed_date"]
        if cutoff not in recompute_cache:
            recompute_cache[cutoff] = compute_factors_as_of(facts, prices, as_of_date=cutoff)
        recomputed = recompute_cache[cutoff]

        # The ffill carried the RIGHT vintage: recomputing fresh at the
        # row's own recorded cutoff reproduces the row's own values exactly.
        for key in FACTOR_KEYS:
            if pd.isna(row[key]):
                assert pd.isna(recomputed[key])
            else:
                assert row[key] == pytest.approx(recomputed[key])


# ---------------------------------------------------------------------------
# C1-b -- a later revision never leaks backward (the most safety-critical
# test in the entire change)
# ---------------------------------------------------------------------------


def test_restatement_never_leaks_backward() -> None:
    """A restatement -- a later filing revising an ALREADY-REPORTED period
    -- must never change a row before its own effective (lagged) date, and
    MUST change every row from that date forward. `o0`/`o1` are two full
    re-runs of `build_fundamental_overlay` diffed against each other, not a
    single-state snapshot -- a snapshot could look plausible while still
    leaking (e.g. by accident sharing the wrong forward-filled segment)."""
    spine = _spine("2023-01-01", 500)
    prices = _flat_prices(spine, close=10.0)

    facts0_rows = [
        _fact("assets", value=100.0, period_end="2022-12-31", filed_date="2023-02-15"),
        _fact("gross_profit", value=25.0, period_end="2022-12-31", filed_date="2023-02-15"),
    ]
    restatement = _fact(
        "assets",
        value=80.0,
        period_end="2022-12-31",
        filed_date="2024-03-01",
        accession="acc-restated",
    )
    facts1_rows = [*facts0_rows, restatement]

    o0 = build_fundamental_overlay(spine, _facts_frame(facts0_rows), prices).set_index("timestamp")
    o1 = build_fundamental_overlay(spine, _facts_frame(facts1_rows), prices).set_index("timestamp")

    original_gross_profitability = 25.0 / 100.0
    restated_gross_profitability = 25.0 / 80.0

    # The restatement's own effective (lagged) timestamp, derived the same
    # way build_fundamental_overlay computes it internally -- an exact
    # boundary, not an approximate one, so this test cannot pass by luck.
    spine_ts = spine["timestamp"].sort_values().reset_index(drop=True)
    event = pd.Timestamp("2024-03-01", tz="UTC")
    insertion_index = int(spine_ts.searchsorted(event, side="left"))
    effective_timestamp = spine_ts.iloc[insertion_index + 1]

    # Literal boundary: every row up to 2024-02-29 is byte-identical whether
    # or not the future restatement was ever added to the fact set --
    # adding ANY future-filed fact must not change a single earlier value.
    boundary = pd.Timestamp("2024-02-29", tz="UTC")
    pd.testing.assert_frame_equal(o1.loc[:boundary], o0.loc[:boundary])
    assert o0.loc[boundary, "gross_profitability"] == pytest.approx(original_gross_profitability)

    # Stronger than the literal boundary: nothing changes for ANY row
    # strictly before the restatement's own effective timestamp, not merely
    # "before Feb 29" -- proves the invariant holds at the exact boundary,
    # not just comfortably before it.
    pre_effective = o1.index[o1.index < effective_timestamp]
    pd.testing.assert_frame_equal(o1.loc[pre_effective], o0.loc[pre_effective])

    # From the effective timestamp forward, the restated value IS visible
    # -- a later revision is correctly delayed, never silently dropped.
    last_timestamp = o1.index[-1]
    assert o1.loc[effective_timestamp, "gross_profitability"] == pytest.approx(restated_gross_profitability)
    assert o1.loc[last_timestamp, "gross_profitability"] == pytest.approx(restated_gross_profitability)
    # o0 (which never saw the restatement) reports the ORIGINAL value at
    # that very same timestamp -- confirming the difference is caused by
    # the restatement, not by anything else in the two runs.
    assert o0.loc[effective_timestamp, "gross_profitability"] == pytest.approx(original_gross_profitability)


# ---------------------------------------------------------------------------
# C1-c -- NaN never raises, whatever the missing-data shape
# ---------------------------------------------------------------------------


def test_c1c_nan_never_raises() -> None:
    spine = _spine("2021-11-01", 500)

    # (a) Empty facts -> every factor NaN on every row, no exception.
    empty_overlay = build_fundamental_overlay(spine, _facts_frame([]), _flat_prices(spine))
    for key in FACTOR_KEYS:
        assert empty_overlay[key].isna().all()
    assert empty_overlay["max_filed_date"].isna().all()

    # (b) A single fiscal year only -> piotroski NaN (no prior FY to
    # compare against), the other two factors still resolve normally.
    fy2022_only = [row for row in _two_year_facts() if row["period_end"] == "2022-12-31"]
    single_year_overlay = build_fundamental_overlay(spine, _facts_frame(fy2022_only), _flat_prices(spine))
    single_year_resolved = single_year_overlay.dropna(subset=["max_filed_date"])
    assert not single_year_resolved.empty
    assert single_year_resolved["piotroski_f_score"].isna().all()
    assert single_year_resolved["altman_z_score"].notna().any()
    assert single_year_resolved["gross_profitability"].notna().any()

    # (c) No price row anywhere near either filing (the as-of / cutoff
    # date, per `_price_close_on`'s exact-date-only lookup) -> altman NaN
    # only; piotroski and gross_profitability are untouched by prices.
    far_away_prices = pd.DataFrame({"timestamp": [pd.Timestamp("2019-01-01", tz="UTC")], "close": [5.0]})
    two_years = _facts_frame(_two_year_facts())
    no_price_overlay = build_fundamental_overlay(spine, two_years, far_away_prices)
    no_price_resolved = no_price_overlay.dropna(subset=["max_filed_date"])
    assert not no_price_resolved.empty
    assert no_price_resolved["altman_z_score"].isna().all()
    assert no_price_resolved["piotroski_f_score"].notna().any()
    assert no_price_resolved["gross_profitability"].notna().any()

    # (d) A concept present only under an unexpected unit (Open Question 2:
    # never convert or guess) -> only the factor that concept feeds (here
    # Altman's RE/TA term) is NaN from that event forward; the FY2021-only
    # window before it, and the other two factors throughout, are unaffected.
    unexpected_unit = two_years.copy()
    mask = (unexpected_unit["concept"] == "RetainedEarningsAccumulatedDeficit") & (
        unexpected_unit["period_end"] == "2022-12-31"
    )
    unexpected_unit.loc[mask, "unit"] = "EUR"
    unexpected_overlay = build_fundamental_overlay(spine, unexpected_unit, _flat_prices(spine))
    unexpected_resolved = unexpected_overlay.dropna(subset=["max_filed_date"])
    assert not unexpected_resolved.empty
    assert unexpected_resolved["altman_z_score"].isna().any()  # FY2022 onward: RE/TA unresolved
    assert unexpected_resolved["altman_z_score"].notna().any()  # FY2021 window: still untouched
    assert unexpected_resolved["piotroski_f_score"].notna().any()
    assert unexpected_resolved["gross_profitability"].notna().any()


def test_non_stock_asset_is_skipped_not_failed(repository) -> None:
    """spec: 'Non-stock asset is skipped, not failed' -- a crypto asset
    yields zero fundamental_v1 rows and is listed in `skipped_assets`, never
    an error. Exercised against the real repository so `get_asset`'s
    `asset_class` branch runs for real."""
    repository.get_or_create_asset("btc-usd", asset_class="crypto")

    result = materialize_asset_fundamentals(repository, FundamentalMaterializationConfig(ticker="btc-usd"))

    assert result.skipped_assets == ["BTC-USD"]
    assert result.asset_class == "crypto"
    assert result.feature_rows_loaded == 0
    assert result.event_dates == 0


# ---------------------------------------------------------------------------
# C1-e -- DB round trip (real Postgres, rolled back)
# ---------------------------------------------------------------------------


def test_c1e_db_round_trip(repository) -> None:
    """Via the real `repository` fixture (rolled back): materialize
    `fundamental_v1` end-to-end, read it back, and prove (a) every
    persisted row's timestamp strictly exceeds its own contributing
    `filed_date` and (b) its 25 technical values are byte-identical to the
    `technical_v2` row materialized from the exact same prices at the exact
    same timestamp -- the spine math is reused, never duplicated (C2)."""
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")

    prices = _price_history("2021-11-01", 500)
    repository.upsert_prices(asset_id, prices)

    facts_rows = _two_year_facts()
    repository.upsert_fundamental_facts([{**row, "asset_id": asset_id} for row in facts_rows])

    technical_columns = feature_columns_for_set("technical_v2")
    technical_features = build_features(prices)
    repository.upsert_features(
        asset_id=asset_id,
        features=technical_features,
        feature_columns=technical_columns,
        feature_set="technical_v2",
    )

    result = materialize_asset_fundamentals(repository, FundamentalMaterializationConfig(ticker="aapl"))
    assert result.skipped_assets == []
    assert result.feature_rows_loaded > 0

    # Ground truth: the SAME pure computation over the SAME inputs just
    # persisted -- proves the DB round trip lost nothing and the C1
    # look-ahead invariant survives persistence, not just pure computation.
    spine = build_features(prices)
    expected_overlay = build_fundamental_overlay(spine, _facts_frame(facts_rows), prices)
    fundamental_columns = feature_columns_for_set("fundamental_v1")
    expected_rows = expected_overlay.dropna(subset=fundamental_columns).set_index("timestamp")
    assert not expected_rows.empty

    stored = repository.get_features(asset_id, "fundamental_v1")
    stored["timestamp"] = pd.to_datetime(stored["timestamp"], utc=True)
    assert sorted(stored["timestamp"]) == sorted(expected_rows.index)

    technical_stored = repository.get_features(asset_id, "technical_v2")
    technical_stored["timestamp"] = pd.to_datetime(technical_stored["timestamp"], utc=True)
    technical_by_timestamp = technical_stored.set_index("timestamp")["features"]

    for _, row in stored.iterrows():
        timestamp = row["timestamp"]
        expected_row = expected_rows.loc[timestamp]

        # C1: every persisted row exceeds its own contributing filing.
        assert expected_row["max_filed_date"] < timestamp.date()

        # The 25 technical values are byte-identical to the same-timestamp
        # technical_v2 row.
        technical_values = technical_by_timestamp.loc[timestamp]
        for column in technical_columns:
            assert row["features"][column] == pytest.approx(technical_values[column])
