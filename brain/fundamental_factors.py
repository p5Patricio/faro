"""Point-in-time factor computation: SEC XBRL facts -> the three
`fundamental_v1` composite factors, as-of a `filed_date` cutoff.

Pure module -- no DB, no HTTP. Imports `pandas`/`numpy` and
`collector.fundamentals.CONCEPT_CHAINS` only, **never** `brain/features.py`
(keeps the import graph acyclic; `brain/features.py` gains
`FUNDAMENTAL_OVERLAY_COLUMNS` in Phase 4 and must never import this module's
raw-ratio internals -- see proposal.md's Product Decision 1: `fundamental_v1`
exposes only the three composites, never `roa`/`current_ratio`/etc. as
feature columns).

C1 discipline (the single most important rule in this module): every factor
is a function of facts filtered by `filed_date <= cutoff` -- **never**
`period_end`. `period_end` is used only to align a period's own facts with
each other (e.g. matching `Assets` to `Liabilities` for the same fiscal
year); it never gates which facts are visible. `_select_as_of` is the one
place that enforces the cutoff; every other function in this module reads
its inputs through `_select_as_of` (via the `pick` closure in
`compute_factors_as_of`), so there is exactly one code path that can leak a
future filing into a factor value.

Non-raising is achieved BY CONSTRUCTION, not by a bare `except`: every
missing/absent input resolves to `np.nan` (`_select_as_of`'s dead ends,
`_safe_div`'s zero/None/NaN guard, ordinary IEEE-754 NaN propagation through
`+`/`*`), so a bare `except` would only ever hide a real bug, never a
legitimate missing-data case.

CONCEPT_CHAINS reconciliation (task 3.10, deferred): tasks.md gates this
reconciliation on the Phase 2 `--out` per-concept coverage report generated
by `py -3.14 -m collector.run_fundamental_ingestion --limit 3 --out
artifacts/fund_coverage.json` against real Postgres CIK data. That report
was never produced -- Phase 2's own runtime harness (task 2.10) was skipped
for the same reason (no `SEC_USER_AGENT` / seeded CIK-mapped assets in this
environment), so there is no coverage evidence to prune or extend
`CONCEPT_CHAINS` against yet. `CONCEPT_CHAINS` is therefore used here
UNCHANGED from `collector/fundamentals.py` (Phase 2), on the design-time
tag choices only. Follow-up: run that coverage report against real S&P 100
CIK data, then revisit this module's chain usage (in particular the
`pretax_income` / `interest_expense` / `ProfitLoss` / `InterestExpenseDebt`
fallback tags, which are the least commonly used in practice) on measured
evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from collector.fundamentals import CONCEPT_CHAINS

FACTOR_KEYS: tuple[str, ...] = ("piotroski_f_score", "altman_z_score", "gross_profitability")


def _to_date(value: Any) -> date:
    """Normalize a `filed_date`/`period_end`/cutoff value to a plain
    `date`. Accepts `datetime.date`, `datetime.datetime`, `pandas.Timestamp`
    or an ISO `"YYYY-MM-DD"` string -- the repository layer (real Postgres)
    hands back `datetime.date` objects (psycopg2's default DATE decoding),
    while unit tests and `parse_company_facts` output use ISO strings
    verbatim, so both must resolve identically here.
    """
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _select_as_of(
    facts: pd.DataFrame,
    logical_concept: str,
    *,
    cutoff: Any,
    fiscal_period: str | None = "FY",
    offset: int = 0,
) -> tuple[float, date | None]:
    """The point-in-time selection primitive. Four ordered steps (design.md
    §5) -- this is the heart of the C1 guarantee:

    1. **As-of filter**: keep rows with `filed_date <= cutoff`. Nothing else
       in this module ever looks at a filing that has not happened yet.
    2. **Period selection**: among the surviving rows for this concept's
       chain (and `fiscal_period` unless `None`), take the `offset`-th
       largest **distinct** `period_end`. `offset=0` = current period,
       `offset=1` = prior period. Distinct-period ordering -- not row
       ordering -- is what makes a missing quarter or a duplicated filing
       harmless.
    3. **Tag fallback**: within that one period, walk the chain in
       *declared* order and take the first `(taxonomy, tag)` present with
       the concept's expected unit. Priority-before-recency avoids a filer
       that reports both tags flipping mid-history and injecting an
       artificial level jump.
    4. **Restatement**: within that `(period_end, tag, unit)`, take the row
       with the greatest `filed_date` -- the newest revision knowable at the
       cutoff.

    Returns `(np.nan, None)` at any dead end: no facts, nothing survives the
    as-of filter, the chain's expected unit is never present (Open Question
    2 -- never convert or guess a different unit), or `offset` runs past the
    number of distinct periods available (the first-fiscal-year case).

    `logical_concept` must be a key of `CONCEPT_CHAINS`; an unknown concept
    is a programmer error (typo), not a missing-data case, so it raises
    `KeyError` rather than silently returning NaN.
    """
    expected_unit, chain = CONCEPT_CHAINS[logical_concept]

    if facts is None or facts.empty:
        return (np.nan, None)

    cutoff_date = _to_date(cutoff)
    filed = facts["filed_date"].apply(_to_date)
    period_end = facts["period_end"].apply(_to_date)
    in_chain = pd.Series(
        [(taxonomy, concept) in chain for taxonomy, concept in zip(facts["taxonomy"], facts["concept"])],
        index=facts.index,
    )

    mask = (filed <= cutoff_date) & in_chain
    if fiscal_period is not None:
        mask &= facts["fiscal_period"] == fiscal_period

    candidates = facts.loc[mask]
    if candidates.empty:
        return (np.nan, None)

    candidate_periods = period_end.loc[candidates.index]
    candidate_filed = filed.loc[candidates.index]

    distinct_periods = sorted(candidate_periods.unique(), reverse=True)
    if offset >= len(distinct_periods):
        return (np.nan, None)
    selected_period = distinct_periods[offset]

    period_mask = candidate_periods == selected_period
    period_rows = candidates.loc[period_mask]
    period_filed = candidate_filed.loc[period_mask]

    for taxonomy, tag in chain:
        tag_mask = (
            (period_rows["taxonomy"] == taxonomy)
            & (period_rows["concept"] == tag)
            & (period_rows["unit"] == expected_unit)
        )
        tag_rows = period_rows.loc[tag_mask]
        if tag_rows.empty:
            continue
        tag_filed = period_filed.loc[tag_mask]
        best_index = tag_filed.idxmax()  # greatest filed_date -> newest revision
        value = tag_rows.loc[best_index, "value"]
        if value is None or (isinstance(value, float) and np.isnan(value)):
            continue
        return (float(value), tag_filed.loc[best_index])

    return (np.nan, None)


def _safe_div(numerator: float, denominator: float) -> float:
    """NaN-propagating division: NaN on a None/NaN numerator, a None/NaN
    denominator, or a zero denominator. Never raises `ZeroDivisionError`."""
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return np.nan
    return numerator / denominator


def _binary(a: float, b: float, *, op: str) -> int | None:
    """One Piotroski signal: `None` when either input is unevaluable (NaN),
    else `1`/`0` for the comparator. `None` (not NaN) is the sentinel here
    because the caller sums integers and must distinguish "signal is 0"
    from "signal could not be evaluated"."""
    if pd.isna(a) or pd.isna(b):
        return None
    if op == ">":
        return int(a > b)
    if op == "<":
        return int(a < b)
    if op == "<=":
        return int(a <= b)
    raise ValueError(f"unknown comparator: {op!r}")


def _price_close_on(prices_df: pd.DataFrame | None, as_of_date: date) -> float:
    """Exact-date close lookup for Altman's MVE term -- `shares * close`
    where `close` is the price on exactly `as_of_date` (the filing date).
    No interpolation, no forward-fill: a missing price row on that date
    yields NaN, per design.md ("No price row on that date -> MVE is NaN ->
    Z is NaN. Never interpolated."). `brain/materialize_fundamentals.py`
    (Phase 4) owns the trading-calendar reindex/ffill of the *output*
    overlay -- that is a different concern from this exact-date input read.
    """
    if prices_df is None or prices_df.empty or "timestamp" not in prices_df.columns:
        return np.nan
    if "close" not in prices_df.columns:
        return np.nan
    price_dates = pd.to_datetime(prices_df["timestamp"], utc=True).dt.date
    matches = prices_df.loc[price_dates == as_of_date, "close"]
    if matches.empty or pd.isna(matches.iloc[-1]):
        return np.nan
    return float(matches.iloc[-1])


def _compute_gross_profitability(pick: Callable[..., float]) -> float:
    """Novy-Marx (2013): `gross_profit / assets`. Denominator is TOTAL
    assets, not equity -- that is the published definition. `gross_profit`
    falls back to `revenue - cost_of_revenue` when the SEC filer never tags
    `GrossProfit` directly (many filers omit it)."""
    gross_profit = pick("gross_profit")
    if pd.isna(gross_profit):
        gross_profit = pick("revenue") - pick("cost_of_revenue")
    return _safe_div(gross_profit, pick("assets"))


def _compute_altman_z(pick: Callable[..., float], prices_df: pd.DataFrame, cutoff: date) -> float:
    """Classic public-firm Z (1968):
    `1.2*(WC/TA) + 1.4*(RE/TA) + 3.3*(EBIT/TA) + 0.6*(MVE/TL) + 1.0*(Sales/TA)`.

    `TA` and `TL` are forced to NaN when `<= 0` (a non-positive total-assets
    or total-liabilities figure is not a legitimate going-concern ratio);
    every other missing input drops the corresponding term to NaN via
    `_safe_div` or ordinary NaN-propagating arithmetic, so the whole score
    naturally collapses to NaN without any explicit "if any NaN" check.
    `MVE = shares_outstanding_mve(as-of cutoff) * close(cutoff)` -- the ONLY
    fundamentals<->prices coupling in this module.
    """
    assets_raw = pick("assets")
    ta = assets_raw if (not pd.isna(assets_raw) and assets_raw > 0) else np.nan

    working_capital = pick("assets_current") - pick("liabilities_current")
    retained_earnings = pick("retained_earnings")

    ebit = pick("operating_income")
    if pd.isna(ebit):
        ebit = pick("pretax_income") + pick("interest_expense")

    liabilities = pick("liabilities")
    if pd.isna(liabilities):
        liabilities = assets_raw - pick("equity")
    tl = liabilities if (not pd.isna(liabilities) and liabilities > 0) else np.nan

    # Any fiscal period -- the dei cover-page count is the freshest share
    # count knowable at the cutoff (design.md §5 / collector/fundamentals.py).
    shares = pick("shares_outstanding_mve", fiscal_period=None)
    price = _price_close_on(prices_df, cutoff)
    mve = shares * price

    sales = pick("revenue")

    return (
        1.2 * _safe_div(working_capital, ta)
        + 1.4 * _safe_div(retained_earnings, ta)
        + 3.3 * _safe_div(ebit, ta)
        + 0.6 * _safe_div(mve, tl)
        + 1.0 * _safe_div(sales, ta)
    )


def _compute_piotroski(pick: Callable[..., float]) -> float:
    """0-9 sum of binary signals over `FY_t` vs `FY_{t-1}` (design.md §5).

    ADR-4 (missing-input policy): if ANY of the 9 signals cannot be
    evaluated -- including a missing prior FY (the first-XBRL-year case) --
    the whole score is `NaN`, never a partial sum. A 5-of-7 score sits on a
    different scale than a 9-signal score and would drift silently across
    assets and across time; `upsert_features`' existing `dropna` handles the
    resulting NaN row.

    Two deliberate deviations from the textbook definition, both from
    design.md §5: (a) ROA uses same-year total assets, not beginning-of-year
    assets -- one fewer required input; (b) the equity-issuance signal uses
    `shares_outstanding_wavg` (weighted-average-basic, `fp='FY'`), the more
    standard basis for that signal -- distinct from Altman's
    `shares_outstanding_mve` chain (Open Question 3).
    """
    net_income_t = pick("net_income")
    net_income_t1 = pick("net_income", offset=1)
    assets_t = pick("assets")
    assets_t1 = pick("assets", offset=1)
    cfo_t = pick("cfo")
    ltd_t = pick("long_term_debt")
    ltd_t1 = pick("long_term_debt", offset=1)
    assets_current_t = pick("assets_current")
    assets_current_t1 = pick("assets_current", offset=1)
    liabilities_current_t = pick("liabilities_current")
    liabilities_current_t1 = pick("liabilities_current", offset=1)
    shares_t = pick("shares_outstanding_wavg")
    shares_t1 = pick("shares_outstanding_wavg", offset=1)
    revenue_t = pick("revenue")
    revenue_t1 = pick("revenue", offset=1)
    cost_t = pick("cost_of_revenue")
    cost_t1 = pick("cost_of_revenue", offset=1)

    gross_profit_t = pick("gross_profit")
    if pd.isna(gross_profit_t):
        gross_profit_t = revenue_t - cost_t
    gross_profit_t1 = pick("gross_profit", offset=1)
    if pd.isna(gross_profit_t1):
        gross_profit_t1 = revenue_t1 - cost_t1

    roa_t = _safe_div(net_income_t, assets_t)
    roa_t1 = _safe_div(net_income_t1, assets_t1)
    ltd_ratio_t = _safe_div(ltd_t, assets_t)
    ltd_ratio_t1 = _safe_div(ltd_t1, assets_t1)
    current_ratio_t = _safe_div(assets_current_t, liabilities_current_t)
    current_ratio_t1 = _safe_div(assets_current_t1, liabilities_current_t1)
    gross_margin_t = _safe_div(gross_profit_t, revenue_t)
    gross_margin_t1 = _safe_div(gross_profit_t1, revenue_t1)
    asset_turnover_t = _safe_div(revenue_t, assets_t)
    asset_turnover_t1 = _safe_div(revenue_t1, assets_t1)

    signals = (
        _binary(roa_t, 0.0, op=">"),                      # profitability: positive ROA
        _binary(cfo_t, 0.0, op=">"),                       # profitability: positive CFO
        _binary(roa_t, roa_t1, op=">"),                    # profitability: ROA improved YoY
        _binary(cfo_t, net_income_t, op=">"),              # profitability: accruals quality
        _binary(ltd_ratio_t, ltd_ratio_t1, op="<"),         # leverage decreased YoY
        _binary(current_ratio_t, current_ratio_t1, op=">"),  # liquidity improved YoY
        _binary(shares_t, shares_t1, op="<="),              # no new equity issued
        _binary(gross_margin_t, gross_margin_t1, op=">"),   # efficiency: margin improved YoY
        _binary(asset_turnover_t, asset_turnover_t1, op=">"),  # efficiency: turnover improved YoY
    )
    if any(signal is None for signal in signals):
        return np.nan
    return float(sum(signals))


def compute_factors_as_of(
    facts_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    as_of_date: Any,
) -> dict[str, Any]:
    """Compute the three `fundamental_v1` composite factors as-of a
    `filed_date` cutoff `as_of_date`.

    Returns `{piotroski_f_score, altman_z_score, gross_profitability,
    max_filed_date}`. Every factor value is `np.nan` on any missing input,
    never an exception. `max_filed_date` is the greatest `filed_date` of
    every fact row actually selected across all three factors (or `None`
    when nothing was selected) -- the C1 provenance token
    `brain/materialize_fundamentals.py` (Phase 4) forward-fills alongside
    the values and asserts `< row["timestamp"]` for. It is deliberately NOT
    one of `FACTOR_KEYS` and must never reach `features_daily.features`.
    """
    cutoff = _to_date(as_of_date)
    contributing_filed_dates: list[date] = []

    def pick(logical_concept: str, *, fiscal_period: str | None = "FY", offset: int = 0) -> float:
        value, filed = _select_as_of(
            facts_df, logical_concept, cutoff=cutoff, fiscal_period=fiscal_period, offset=offset
        )
        if filed is not None:
            contributing_filed_dates.append(filed)
        return value

    gross_profitability = _compute_gross_profitability(pick)
    altman_z_score = _compute_altman_z(pick, prices_df, cutoff)
    piotroski_f_score = _compute_piotroski(pick)

    return {
        "piotroski_f_score": piotroski_f_score,
        "altman_z_score": altman_z_score,
        "gross_profitability": gross_profitability,
        "max_filed_date": max(contributing_filed_dates) if contributing_filed_dates else None,
    }
