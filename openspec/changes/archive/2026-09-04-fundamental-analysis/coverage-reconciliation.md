# CONCEPT_CHAINS Coverage Reconciliation (tasks 2.10 / 3.10)

Deferred at apply time (no `SEC_USER_AGENT` / no ingested data). Run 2026-09-06
against the first real ingestion: 101 S&P 100 CIKs, 247,673 `fundamental_facts`
rows, per-tag coverage from `artifacts/fund_coverage_sp100.json` plus a direct
`fundamental_facts` group-by and a raw-`companyfacts` inspection of five
zero-`fundamental_v1`-row tickers (JPM, GS, MCD, NEE, XOM).

## Decision: leave `CONCEPT_CHAINS` unchanged.

### 1. Nothing to prune

Every allow-listed `(taxonomy, tag)` pair resolved for at least 24 of the 101
companies. Lowest tiers — `us-gaap:InterestExpenseDebt` (24),
`us-gaap:CostOfRevenue` (32), `us-gaap:CostOfGoodsAndServicesSold`-only-Q (see
below) — are all legitimate fallbacks that carry real companies. No dead tags.

### 2. Nothing worth adding

~35 of 101 tickers materialize zero `fundamental_v1` rows. The cause is
*structural* reporting differences that a tag fallback cannot repair, and
because `upsert_features` drops any row with a NaN in **any** of the 28
`fundamental_v1` columns, a partial rescue (e.g. adding a utility revenue tag)
produces zero extra rows unless the gross-profit and current-asset terms also
resolve for that company.

| Group | Tickers (examples) | Why no chain fixes it |
|---|---|---|
| Financials | JPM, GS, BAC, MS, C, WFC, USB, SCHW, COF, AXP, BLK, BNY, V, MA, BRK-B | Banks file an **unclassified** balance sheet — `AssetsCurrent` / `LiabilitiesCurrent` do not exist in their XBRL at all. Altman's working-capital term and Piotroski's current-ratio signal are permanently NaN. Altman Z / Piotroski F are textbook-inapplicable to financials. |
| Quarterly-only COGS | MCD | `us-gaap:CostOfGoodsAndServicesSold` is present but only tagged at `fp='Q1..Q3'`, never `fp='FY'`; no `GrossProfit` tag. `gross_profit` is unresolvable at annual cadence. Would need a trailing-4-quarter sum. |
| Utilities | NEE | Revenue reported mostly under `RegulatedAndUnregulatedOperatingRevenue` (not in the chain); no COGS tag of any kind. Capturing that revenue tag still leaves `gross_profit` and the current-asset terms unresolved. |

### 3. Separate finding — XOM ticker→CIK mismatch (not a chain issue)

SEC's own `company_tickers.json` maps `XOM → CIK 2115436` ("ExxonMobil
Holdings Corp"), a post-reorganization entity with almost no XBRL history. The
~20-year financial record is under the old CIK `34088` ("EXXON MOBIL CORP").
The identifier-resolution job faithfully used SEC's authoritative mapping, so
this is upstream data, not a Faro bug. A small manual ticker→CIK override list
would fix it.

## Follow-ups this creates

All consistent with proposal Product Decision 1 ("start narrow; widen the
overlay on measured evidence"):

1. Sector-aware factor handling for financials — either dedicated bank/insurer
   factor variants, or drop financials from the `fundamental_v1` target set
   explicitly rather than letting them fall out as all-NaN.
2. Trailing-twelve-month aggregation fallback for flow concepts a filer only
   tags quarterly (`_select_as_of` currently requires a single `fp='FY'` fact).
3. A manual ticker→CIK override map in identifier resolution for post-reorg
   mismatches (XOM today; recurs whenever an index constituent restructures
   into a new holding company).

Current effective `fundamental_v1` universe: ~66 of 101 S&P 100 names. Adequate
for the pipeline-correctness goal of this change; widening it is the work
above, not a chain edit.
