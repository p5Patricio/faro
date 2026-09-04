"""Pure SEC `companyfacts` parsing: JSON -> tall fact rows.

No DB, no HTTP. Two public names: `CONCEPT_CHAINS` (logical concept -> ordered
tag fallback chain, per design.md §2) and `parse_company_facts` (the 1:1
mapper). `ALLOWED_TAGS` is derived from `CONCEPT_CHAINS` -- never a second
literal -- so the allow-list and the chains cannot drift apart.

`CONCEPT_CHAINS` is defined here but NOT applied to compute anything in this
phase (no fallback resolution, no unit filtering, no fiscal-period
selection). `brain/fundamental_factors.py` (Phase 3) interprets the chain at
read time via `_select_as_of`. The raw SEC tag is stored verbatim in
`fundamental_facts.concept` -- never collapsed to a logical name here (see
design.md ADR-2) -- so a later re-interpretation of the chains never requires
a backfill.
"""

from __future__ import annotations

from typing import Any

US_GAAP, DEI = "us-gaap", "dei"
MONEY, SHARES = "USD", "shares"

# logical concept -> (expected unit, ordered (taxonomy, tag) fallback chain).
# Order = priority, evaluated per reporting period by
# `brain/fundamental_factors.py::_select_as_of` (Phase 3).
#
# Open Question 3 (tasks.md, resolved): shares outstanding splits into TWO
# distinct logical concepts rather than one shared chain -- Altman's MVE wants
# the freshest cover-page count knowable at a cutoff (any fiscal period),
# while Piotroski's equity-issuance signal wants the more standard
# weighted-average-basic basis, evaluated FY-over-FY. Sharing one chain would
# make one of the two consumers silently wrong.
CONCEPT_CHAINS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "revenue": (
        MONEY,
        (
            (US_GAAP, "Revenues"),
            (US_GAAP, "RevenueFromContractWithCustomerExcludingAssessedTax"),
            (US_GAAP, "SalesRevenueNet"),
        ),
    ),
    "cost_of_revenue": (
        MONEY,
        (
            (US_GAAP, "CostOfRevenue"),
            (US_GAAP, "CostOfGoodsAndServicesSold"),
            (US_GAAP, "CostOfGoodsSold"),
        ),
    ),
    "gross_profit": (MONEY, ((US_GAAP, "GrossProfit"),)),  # else revenue - cost_of_revenue
    "assets": (MONEY, ((US_GAAP, "Assets"),)),
    "assets_current": (MONEY, ((US_GAAP, "AssetsCurrent"),)),
    "liabilities": (MONEY, ((US_GAAP, "Liabilities"),)),  # else assets - equity
    "liabilities_current": (MONEY, ((US_GAAP, "LiabilitiesCurrent"),)),
    "equity": (MONEY, ((US_GAAP, "StockholdersEquity"),)),
    "long_term_debt": (
        MONEY,
        (
            (US_GAAP, "LongTermDebtNoncurrent"),
            (US_GAAP, "LongTermDebt"),
        ),
    ),
    "net_income": (MONEY, ((US_GAAP, "NetIncomeLoss"), (US_GAAP, "ProfitLoss"))),
    "cfo": (
        MONEY,
        (
            (US_GAAP, "NetCashProvidedByUsedInOperatingActivities"),
            (US_GAAP, "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
        ),
    ),
    "retained_earnings": (MONEY, ((US_GAAP, "RetainedEarningsAccumulatedDeficit"),)),
    "operating_income": (MONEY, ((US_GAAP, "OperatingIncomeLoss"),)),  # EBIT primary
    "pretax_income": (
        MONEY,
        (
            (
                US_GAAP,
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            ),
            (
                US_GAAP,
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            ),
        ),
    ),
    "interest_expense": (MONEY, ((US_GAAP, "InterestExpense"), (US_GAAP, "InterestExpenseDebt"))),
    # dei first: the cover-page count is refiled with EVERY 10-Q, so it is the
    # freshest share count knowable at a filing date -- what Altman's MVE
    # needs. Selected at any fiscal period (Phase 3).
    "shares_outstanding_mve": (
        SHARES,
        (
            (DEI, "EntityCommonStockSharesOutstanding"),
            (US_GAAP, "CommonStockSharesOutstanding"),
            (US_GAAP, "WeightedAverageNumberOfSharesOutstandingBasic"),
        ),
    ),
    # Piotroski's equity-issuance signal: the standard weighted-average basis,
    # selected fp='FY' only (Phase 3).
    "shares_outstanding_wavg": (
        SHARES,
        (
            (US_GAAP, "WeightedAverageNumberOfSharesOutstandingBasic"),
            (US_GAAP, "WeightedAverageNumberOfDilutedSharesOutstanding"),
        ),
    ),
}

# The allow-list is DERIVED from the chains, never a second literal -- they
# cannot drift.
ALLOWED_TAGS: frozenset[tuple[str, str]] = frozenset(
    pair for _unit, chain in CONCEPT_CHAINS.values() for pair in chain
)


def _numeric_value(raw: Any) -> float | None:
    """SEC `val` -> `float`, or `None` when absent/non-numeric. `bool` is
    rejected even though it is an `int` subclass -- `True`/`False` are never
    a legitimate XBRL fact value."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def parse_company_facts(payload: dict[str, Any], *, asset_id: str) -> list[dict[str, Any]]:
    """Map a `companyfacts` payload 1:1 into tall fact rows -- no derivation.

    Walks `payload["facts"][taxonomy][tag]["units"][unit]`, keeping only
    entries whose `(taxonomy, tag)` is in `ALLOWED_TAGS`. An entry missing
    `end`, `filed`, or a numeric `val` is skipped (unusable under the
    point-in-time guarantee). `form`/`frame`/`start` are not stored.

    In-batch dedupe: `companyfacts` repeats an identical fact across the
    10-Q and the 10-K that both report it, producing the same natural key
    twice in one payload. The LAST occurrence in SEC's own list order wins --
    deterministic and idempotent with the DB `ON CONFLICT DO UPDATE`.
    """
    rows_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    facts = payload.get("facts") or {}

    for taxonomy, concepts in facts.items():
        for concept, body in (concepts or {}).items():
            if (taxonomy, concept) not in ALLOWED_TAGS:
                continue
            units = (body or {}).get("units") or {}
            for unit, entries in units.items():
                for entry in entries or []:
                    period_end = entry.get("end")
                    filed_date = entry.get("filed")
                    value = _numeric_value(entry.get("val"))
                    if period_end is None or filed_date is None or value is None:
                        continue

                    fiscal_period = str(entry.get("fp") or "").strip().upper()
                    row = {
                        "asset_id": asset_id,
                        "taxonomy": taxonomy,
                        "concept": concept,
                        "unit": unit,
                        "period_end": period_end,
                        "fiscal_year": entry.get("fy"),
                        "fiscal_period": fiscal_period,
                        "filed_date": filed_date,
                        "accession": entry.get("accn"),
                        "value": value,
                    }
                    key = (
                        asset_id,
                        taxonomy,
                        concept,
                        unit,
                        period_end,
                        fiscal_period,
                        filed_date,
                    )
                    rows_by_key[key] = row  # last occurrence in list order wins

    return list(rows_by_key.values())
