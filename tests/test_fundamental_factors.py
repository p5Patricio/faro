"""Phase 3 (Factor math): `brain.fundamental_factors`.

Requirement "Factor Computation As-Of Filed-Date" is the acceptance
contract: every factor is computed from facts with `filed_date <= cutoff`
only, selecting the greatest `filed_date <= D` per concept so a restatement
supersedes the value it revised, and a missing quarter / first fiscal year /
absent tag yields `NaN`, never an exception.

Two fixtures anchor these tests:

- `_two_year_facts()` -- a hand-built two-fiscal-year company (FY2021,
  FY2022) whose numbers are chosen so every one of Piotroski's 9 signals is
  TRUE (F-Score == 9) and Altman/Novy-Marx come out to hand-computable
  fractions. `CUTOFF` is FY2022's own `filed_date`, matching how
  `brain/materialize_fundamentals.py` (Phase 4) will call
  `compute_factors_as_of(..., as_of_date=f)` at each filing event.
- Minimal ad hoc `_facts_frame([...])` calls for the fallback / missing-input
  / no-look-ahead cases, so each test's cause and effect stay legible.

No DB, no HTTP, no fixtures shared with Phase 2 -- this module is pure.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from brain.fundamental_factors import (
    FACTOR_KEYS,
    _safe_div,
    _select_as_of,
    compute_factors_as_of,
)
from collector.fundamentals import CONCEPT_CHAINS, US_GAAP

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

# FY2022's filed_date -- the cutoff most tests use, matching how the
# materializer will call compute_factors_as_of(..., as_of_date=<filing date>).
CUTOFF = "2023-02-15"


def _primary_tag(logical_concept: str) -> tuple[str, str]:
    _unit, chain = CONCEPT_CHAINS[logical_concept]
    return chain[0]


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
    expected_unit, _chain = CONCEPT_CHAINS[logical_concept]
    taxonomy, concept = tag if tag is not None else _primary_tag(logical_concept)
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


def _prices_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["timestamp", "close"])
    return pd.DataFrame(rows)


def _two_year_facts() -> list[dict[str, Any]]:
    """FY2021 -> FY2022, engineered so all 9 Piotroski signals are TRUE:
    ROA up (0.05 -> 0.075), CFO positive and > net income, leverage down
    (0.30 -> 0.2333), current ratio up (2.0 -> 2.2727), shares outstanding
    down (100 -> 98), gross margin up (0.3333 -> 0.4091), asset turnover up
    (0.90 -> 0.9167)."""
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


# Hand-computed Altman Z for the FY2022 row of `_two_year_facts()` at
# CUTOFF with a close price of 10.0 (MVE = 99 shares * 10.0 = 990):
#   WC=280, TA=1200, RE=200, EBIT=130, TL=650, MVE=990, Sales=1100
EXPECTED_Z = (
    1.2 * (280.0 / 1200.0)
    + 1.4 * (200.0 / 1200.0)
    + 3.3 * (130.0 / 1200.0)
    + 0.6 * (990.0 / 650.0)
    + 1.0 * (1100.0 / 1200.0)
)
EXPECTED_GROSS_PROFITABILITY = (1100.0 - 650.0) / 1200.0  # revenue - cost_of_revenue, over assets


def _cutoff_prices(close: float = 10.0) -> pd.DataFrame:
    return _prices_frame([{"timestamp": CUTOFF, "close": close}])


# ---------------------------------------------------------------------------
# _select_as_of -- the point-in-time selection primitive
# ---------------------------------------------------------------------------


def test_select_as_of_excludes_filings_after_cutoff() -> None:
    facts = _facts_frame(
        [
            _fact("assets", value=900.0, period_end="2020-12-31", filed_date="2021-03-01"),  # D-30
            _fact("assets", value=880.0, period_end="2020-12-31", filed_date="2021-03-20"),  # D-20, restates the above
            _fact("assets", value=1000.0, period_end="2021-12-31", filed_date="2021-04-10"),  # D+10, must be ignored
        ]
    )

    value, filed = _select_as_of(facts, "assets", cutoff="2021-03-31")  # D

    # The D-30 original and its D-20 restatement are visible; the greatest
    # filed_date <= D wins (880.0), and the D+10 fact never contributes.
    assert value == pytest.approx(880.0)
    assert filed == date(2021, 3, 20)


def test_select_as_of_picks_greatest_filed_date_for_restated_period() -> None:
    facts = _facts_frame(
        [
            _fact("assets", value=100.0, period_end="2022-12-31", filed_date="2023-02-15"),
            _fact("assets", value=88.0, period_end="2022-12-31", filed_date="2023-11-01"),
        ]
    )

    before_restatement = _select_as_of(facts, "assets", cutoff="2023-06-01")
    after_restatement = _select_as_of(facts, "assets", cutoff="2024-01-01")

    assert before_restatement == (pytest.approx(100.0), date(2023, 2, 15))
    assert after_restatement == (pytest.approx(88.0), date(2023, 11, 1))


def test_select_as_of_offset_selects_prior_distinct_period() -> None:
    facts = _facts_frame(
        [
            _fact("assets", value=1000.0, period_end="2021-12-31", filed_date="2022-02-10", fiscal_period="FY"),
            # A quarter that falls chronologically between the two FYs must
            # not count as a distinct period when fiscal_period='FY'.
            _fact("assets", value=1050.0, period_end="2022-03-31", filed_date="2022-05-01", fiscal_period="Q1"),
            _fact("assets", value=1200.0, period_end="2022-12-31", filed_date="2023-02-15", fiscal_period="FY"),
        ]
    )

    current = _select_as_of(facts, "assets", cutoff="2023-06-30", offset=0)
    prior = _select_as_of(facts, "assets", cutoff="2023-06-30", offset=1)

    assert current == (pytest.approx(1200.0), date(2023, 2, 15))
    assert prior == (pytest.approx(1000.0), date(2022, 2, 10))


def test_select_as_of_tag_fallback_walks_chain_in_declared_order() -> None:
    # Chain priority beats recency: "Revenues" (chain[0]) is filed EARLIER
    # than "SalesRevenueNet" (chain[2]), yet must still win -- a filer
    # flipping tags across filings must never inject an artificial level
    # jump into the series.
    facts = _facts_frame(
        [
            _fact(
                "revenue", value=510.0, period_end="2022-12-31", filed_date="2023-01-01",
                tag=(US_GAAP, "Revenues"),
            ),
            _fact(
                "revenue", value=500.0, period_end="2022-12-31", filed_date="2023-02-01",
                tag=(US_GAAP, "SalesRevenueNet"),
            ),
        ]
    )

    value, filed = _select_as_of(facts, "revenue", cutoff="2023-06-30")

    assert value == pytest.approx(510.0)
    assert filed == date(2023, 1, 1)


def test_select_as_of_unknown_concept_raises_key_error() -> None:
    # An unknown logical concept is a programmer error (typo), not a
    # missing-data case, so it raises rather than silently returning NaN.
    with pytest.raises(KeyError):
        _select_as_of(_facts_frame([]), "not_a_real_concept", cutoff="2023-01-01")


def test_missing_quarter_yields_nan_not_crash() -> None:
    # Only quarterly filings exist as-of the cutoff; the annual 10-K has not
    # been filed yet. fiscal_period='FY' (the default) must yield NaN, never
    # raise, and never accidentally match a quarter.
    facts = _facts_frame(
        [
            _fact("cfo", value=10.0, period_end="2023-03-31", filed_date="2023-05-01", fiscal_period="Q1"),
            _fact("cfo", value=25.0, period_end="2023-06-30", filed_date="2023-08-01", fiscal_period="Q2"),
            _fact("cfo", value=40.0, period_end="2023-09-30", filed_date="2023-11-01", fiscal_period="Q3"),
        ]
    )

    value, filed = _select_as_of(facts, "cfo", cutoff="2023-12-31")

    assert np.isnan(value)
    assert filed is None

    # compute_factors_as_of must not raise even though `cfo` (a Piotroski
    # input) never resolves.
    result = compute_factors_as_of(facts, _prices_frame([]), as_of_date="2023-12-31")
    assert np.isnan(result["piotroski_f_score"])


def test_two_shares_chains_are_distinct() -> None:
    facts = _facts_frame(
        [
            # mve: dei cover-page count, refiled with a Q1 10-Q -- the
            # freshest count knowable at the cutoff, any fiscal period.
            _fact(
                "shares_outstanding_mve", value=105.0, period_end="2023-03-31",
                filed_date="2023-05-01", fiscal_period="Q1",
            ),
            # wavg: Piotroski's equity-issuance basis, FY only.
            _fact(
                "shares_outstanding_wavg", value=98.0, period_end="2022-12-31",
                filed_date="2023-02-15", fiscal_period="FY",
            ),
        ]
    )

    mve_value, _ = _select_as_of(facts, "shares_outstanding_mve", cutoff="2023-06-30", fiscal_period=None)
    wavg_value, _ = _select_as_of(facts, "shares_outstanding_wavg", cutoff="2023-06-30", fiscal_period="FY")

    assert mve_value == pytest.approx(105.0)
    assert wavg_value == pytest.approx(98.0)
    assert mve_value != wavg_value


# ---------------------------------------------------------------------------
# _safe_div
# ---------------------------------------------------------------------------


def test_safe_div_nan_propagation() -> None:
    assert _safe_div(10.0, 2.0) == pytest.approx(5.0)
    assert np.isnan(_safe_div(10.0, 0.0))
    assert np.isnan(_safe_div(np.nan, 2.0))
    assert np.isnan(_safe_div(10.0, np.nan))
    assert np.isnan(_safe_div(None, 2.0))


# ---------------------------------------------------------------------------
# gross_profitability (Novy-Marx)
# ---------------------------------------------------------------------------


def test_gross_profitability_formula_with_direct_gross_profit_tag() -> None:
    facts = _facts_frame(
        [
            _fact("gross_profit", value=300.0, period_end="2022-12-31", filed_date="2023-02-15"),
            _fact("assets", value=1200.0, period_end="2022-12-31", filed_date="2023-02-15"),
        ]
    )

    result = compute_factors_as_of(facts, _prices_frame([]), as_of_date="2023-02-15")

    assert result["gross_profitability"] == pytest.approx(300.0 / 1200.0)
    assert np.isnan(result["altman_z_score"])
    assert np.isnan(result["piotroski_f_score"])


def test_gross_profitability_falls_back_to_revenue_minus_cost() -> None:
    facts = _facts_frame(
        [
            _fact("revenue", value=1100.0, period_end="2022-12-31", filed_date="2023-02-15"),
            _fact("cost_of_revenue", value=650.0, period_end="2022-12-31", filed_date="2023-02-15"),
            _fact("assets", value=1200.0, period_end="2022-12-31", filed_date="2023-02-15"),
        ]
    )

    result = compute_factors_as_of(facts, _prices_frame([]), as_of_date="2023-02-15")

    assert result["gross_profitability"] == pytest.approx((1100.0 - 650.0) / 1200.0)


# ---------------------------------------------------------------------------
# altman_z_score
# ---------------------------------------------------------------------------


def test_altman_ebit_falls_back_to_pretax_plus_interest() -> None:
    common = dict(period_end="2022-12-31", filed_date="2023-02-15")
    facts = _facts_frame(
        [
            _fact("assets", value=1200.0, **common),
            _fact("assets_current", value=500.0, **common),
            _fact("liabilities_current", value=220.0, **common),
            _fact("retained_earnings", value=200.0, **common),
            _fact("liabilities", value=650.0, **common),
            _fact("revenue", value=1100.0, **common),
            _fact("shares_outstanding_mve", value=99.0, **common),
            # No operating_income tag -- EBIT must fall back to
            # pretax_income + interest_expense = 110 + 20 = 130.
            _fact("pretax_income", value=110.0, **common),
            _fact("interest_expense", value=20.0, **common),
        ]
    )

    result = compute_factors_as_of(facts, _cutoff_prices(), as_of_date=CUTOFF)

    assert result["altman_z_score"] == pytest.approx(EXPECTED_Z)


def test_altman_liabilities_falls_back_to_assets_minus_equity() -> None:
    common = dict(period_end="2022-12-31", filed_date="2023-02-15")
    facts = _facts_frame(
        [
            _fact("assets", value=1200.0, **common),
            _fact("assets_current", value=500.0, **common),
            _fact("liabilities_current", value=220.0, **common),
            _fact("retained_earnings", value=200.0, **common),
            _fact("operating_income", value=130.0, **common),
            _fact("revenue", value=1100.0, **common),
            _fact("shares_outstanding_mve", value=99.0, **common),
            # No liabilities tag -- TL must fall back to assets - equity =
            # 1200 - 550 = 650, matching the direct-liabilities fixture.
            _fact("equity", value=550.0, **common),
        ]
    )

    result = compute_factors_as_of(facts, _cutoff_prices(), as_of_date=CUTOFF)

    assert result["altman_z_score"] == pytest.approx(EXPECTED_Z)


def test_altman_z_is_nan_when_total_assets_non_positive() -> None:
    common = dict(period_end="2022-12-31", filed_date="2023-02-15")
    facts = _facts_frame(
        [
            _fact("assets", value=0.0, **common),  # TA <= 0
            _fact("assets_current", value=500.0, **common),
            _fact("liabilities_current", value=220.0, **common),
            _fact("liabilities", value=650.0, **common),
            _fact("retained_earnings", value=200.0, **common),
            _fact("operating_income", value=130.0, **common),
            _fact("revenue", value=1100.0, **common),
            _fact("shares_outstanding_mve", value=99.0, **common),
        ]
    )

    result = compute_factors_as_of(facts, _cutoff_prices(), as_of_date=CUTOFF)

    assert np.isnan(result["altman_z_score"])


def test_altman_z_is_nan_when_total_liabilities_non_positive() -> None:
    common = dict(period_end="2022-12-31", filed_date="2023-02-15")
    facts = _facts_frame(
        [
            _fact("assets", value=1200.0, **common),
            _fact("assets_current", value=500.0, **common),
            _fact("liabilities_current", value=220.0, **common),
            _fact("liabilities", value=0.0, **common),  # TL <= 0, and no fallback needed since tag is present
            _fact("retained_earnings", value=200.0, **common),
            _fact("operating_income", value=130.0, **common),
            _fact("revenue", value=1100.0, **common),
            _fact("shares_outstanding_mve", value=99.0, **common),
        ]
    )

    result = compute_factors_as_of(facts, _cutoff_prices(), as_of_date=CUTOFF)

    assert np.isnan(result["altman_z_score"])


def test_missing_price_makes_altman_z_nan() -> None:
    facts = _facts_frame(_two_year_facts())
    prices = _prices_frame([{"timestamp": "2019-01-01", "close": 5.0}])  # nowhere near CUTOFF

    result = compute_factors_as_of(facts, prices, as_of_date=CUTOFF)

    assert np.isnan(result["altman_z_score"])
    assert result["gross_profitability"] == pytest.approx(EXPECTED_GROSS_PROFITABILITY)
    assert result["piotroski_f_score"] == pytest.approx(9.0)


def test_concept_only_under_unexpected_unit_yields_nan() -> None:
    # Open Question 2: never convert or guess a different unit.
    df = _facts_frame(_two_year_facts())
    mask = (df["concept"] == "RetainedEarningsAccumulatedDeficit") & (df["period_end"] == "2022-12-31")
    df.loc[mask, "unit"] = "EUR"

    result = compute_factors_as_of(df, _cutoff_prices(), as_of_date=CUTOFF)

    assert np.isnan(result["altman_z_score"])  # RE/TA term unresolved
    assert result["gross_profitability"] == pytest.approx(EXPECTED_GROSS_PROFITABILITY)  # untouched
    assert result["piotroski_f_score"] == pytest.approx(9.0)  # untouched


# ---------------------------------------------------------------------------
# piotroski_f_score
# ---------------------------------------------------------------------------


def test_piotroski_is_nan_without_prior_fiscal_year() -> None:
    fy2022_only = [row for row in _two_year_facts() if row["period_end"] == "2022-12-31"]
    facts = _facts_frame(fy2022_only)

    result = compute_factors_as_of(facts, _cutoff_prices(), as_of_date=CUTOFF)

    assert np.isnan(result["piotroski_f_score"])
    assert result["altman_z_score"] == pytest.approx(EXPECTED_Z)
    assert result["gross_profitability"] == pytest.approx(EXPECTED_GROSS_PROFITABILITY)


def test_piotroski_partial_signals_yield_nan() -> None:
    # shares_outstanding_wavg is Piotroski-only (Altman uses the distinct
    # shares_outstanding_mve chain) -- dropping the FY2021 comparison value
    # breaks exactly one of the 9 signals and must NaN the whole score,
    # never a partial sum, while the other two factors stay untouched.
    rows = [
        row
        for row in _two_year_facts()
        if not (
            row["concept"] == "WeightedAverageNumberOfSharesOutstandingBasic"
            and row["period_end"] == "2021-12-31"
        )
    ]
    facts = _facts_frame(rows)

    result = compute_factors_as_of(facts, _cutoff_prices(), as_of_date=CUTOFF)

    assert np.isnan(result["piotroski_f_score"])
    assert result["altman_z_score"] == pytest.approx(EXPECTED_Z)
    assert result["gross_profitability"] == pytest.approx(EXPECTED_GROSS_PROFITABILITY)


def test_piotroski_full_score_from_hand_computed_fixture() -> None:
    facts = _facts_frame(_two_year_facts())

    result = compute_factors_as_of(facts, _cutoff_prices(), as_of_date=CUTOFF)

    assert result["piotroski_f_score"] == pytest.approx(9.0)
    assert result["altman_z_score"] == pytest.approx(EXPECTED_Z)
    assert result["gross_profitability"] == pytest.approx(EXPECTED_GROSS_PROFITABILITY)


# ---------------------------------------------------------------------------
# compute_factors_as_of -- NaN-never-raise + max_filed_date + no look-ahead
# ---------------------------------------------------------------------------


def test_compute_factors_as_of_all_nan_on_empty_facts() -> None:
    result = compute_factors_as_of(_facts_frame([]), _prices_frame([]), as_of_date=CUTOFF)

    assert np.isnan(result["piotroski_f_score"])
    assert np.isnan(result["altman_z_score"])
    assert np.isnan(result["gross_profitability"])
    assert result["max_filed_date"] is None


def test_compute_factors_as_of_returns_max_filed_date_token() -> None:
    facts = _facts_frame(_two_year_facts())

    result = compute_factors_as_of(facts, _cutoff_prices(), as_of_date=CUTOFF)

    assert result["max_filed_date"] == date(2023, 2, 15)
    assert "max_filed_date" not in FACTOR_KEYS

    empty_result = compute_factors_as_of(_facts_frame([]), _prices_frame([]), as_of_date=CUTOFF)
    assert empty_result["max_filed_date"] is None


def test_compute_factors_as_of_ignores_facts_filed_after_cutoff() -> None:
    """C1 discipline, unit-level: adding a LATER-filed fact must not change
    any factor computed as-of an EARLIER cutoff -- the single most important
    correctness rule in this module. A restatement filed in the future must
    not leak backward into a value already computed at an earlier cutoff."""
    baseline = compute_factors_as_of(_facts_frame(_two_year_facts()), _cutoff_prices(), as_of_date=CUTOFF)

    future_restatement = _fact(
        "assets", value=1_000_000.0, period_end="2022-12-31", filed_date="2024-03-01", fiscal_year=2022
    )
    with_future_fact = compute_factors_as_of(
        _facts_frame([*_two_year_facts(), future_restatement]), _cutoff_prices(), as_of_date=CUTOFF
    )

    assert with_future_fact == baseline
    assert with_future_fact["max_filed_date"] == date(2023, 2, 15)  # unaffected by the 2024 filing
