# Design: Fundamental Analysis

Implements `openspec/changes/fundamental-analysis/proposal.md` (both Product Decisions
RESOLVED: 3 composite overlay columns only; success = pipeline correctness). Seam
inventory verified in `explore.md`.

> Size note: this artifact deliberately exceeds the default 800-word design budget. The
> orchestrator brief enumerated ten required sections including exact DDL, exact factor
> formulas and a slice plan; density is preserved with tables and code, not prose.

## Technical Approach

Four layers, each a pure function wrapped by a thin I/O caller — the shape this codebase
already uses (`build_features` pure / `materialize_asset_dataset` does I/O).

```
SEC companyfacts JSON
   │  SecEdgarClient.fetch_company_facts (existing, audited, unmodified)
   ▼
collector/fundamentals.py  parse_company_facts()      ← pure: JSON -> fact rows
   ▼
collector/run_fundamental_ingestion.py                ← I/O: per-CIK loop + job audit
   ▼
fundamental_facts  (tall, insert-keyed by filed_date) ← 0006_fundamental_facts.sql
   ▼  LocalPostgresRepository.get_fundamental_facts(asset_id, concepts, as_of_filed_date)
brain/fundamental_factors.py  compute_factors_as_of() ← pure: facts+prices+cutoff -> 3 floats
   ▼
brain/materialize_fundamentals.py  build_fundamental_overlay()  ← pure: event dates + lag + ffill
   ▼  repository.upsert_features(..., feature_set='fundamental_v1')
features_daily  (technical_v2 spine + 3 overlay columns)
```

`technical_v2` is never on this path. `brain/features.py` gains one dict assignment.

---

## 1. `db/migrations/0006_fundamental_facts.sql`

```sql
-- Tall XBRL fact store. One row per (asset, taxonomy, concept, unit, period,
-- fiscal_period, FILING). A restatement of an already-reported period is a NEW row
-- at a later filed_date, never an update -- that is what makes the as-of read
-- point-in-time by construction (charter C1). DDL follows 0005/0007: identity PK,
-- `create ... if not exists`, FK to assets on delete cascade, explicit unique, no RLS.

create table if not exists fundamental_facts (
  id bigint primary key generated always as identity,
  asset_id uuid not null references assets(id) on delete cascade,
  taxonomy text not null,          -- 'us-gaap' | 'dei' -- the SEC facts.<taxonomy> key
  concept text not null,           -- the RAW SEC tag ('Assets', 'SalesRevenueNet'), not a logical name
  unit text not null,              -- 'USD' | 'shares' | 'USD/shares' -- the units[] key
  period_end date not null,        -- SEC `end`
  fiscal_year integer,             -- SEC `fy`; nullable because SEC omits it on some entries
  fiscal_period text not null,     -- SEC `fp`: 'FY' | 'Q1'..'Q4'; '' when absent
  filed_date date not null,        -- SEC `filed` -- THE point-in-time axis. Never period_end.
  accession text,                  -- SEC `accn` -- provenance back to the exact filing
  value numeric,                   -- SEC `val`
  created_at timestamptz not null default now(),

  -- Natural key = the SEC identity of a reported number. filed_date IS a key column:
  -- drop it and a restatement would UPDATE the original row and silently rewrite
  -- history. Every key column is `not null` on purpose -- Postgres treats NULLs as
  -- distinct in a UNIQUE constraint, so a nullable fiscal_period would let duplicate
  -- rows in AND make `_upsert_batch`'s ON CONFLICT never match (same trap 0007
  -- documents for notification_rules).
  unique (asset_id, taxonomy, concept, unit, period_end, fiscal_period, filed_date)
);

-- Exact shape of the as-of read:
--   WHERE asset_id = %s AND concept = ANY(%s) AND filed_date <= %s
-- Leading (asset_id, concept) is the filter; filed_date desc serves both the range
-- predicate and the "greatest filed_date <= D wins" selection without a sort.
-- The asset_id-only variant (concepts=None) uses the same index by prefix, so one
-- index is enough on a table whose write path is bulk insert.
create index if not exists fundamental_facts_asof_idx
  on fundamental_facts(asset_id, concept, filed_date desc);
```

Column rationale, per the restatement + as-of access pattern:

| Column | Why it exists |
|---|---|
| `taxonomy` | Same tag name can exist under `us-gaap` and `dei`; without it the shares-outstanding chain is ambiguous. |
| `concept` (raw tag) | See ADR-2 — storing the logical name would freeze a revisable interpretation into immutable data. |
| `unit` | One concept can be reported under several units (`USD`, `USD/shares`); mixing them silently corrupts a ratio. Key column so both survive. |
| `period_end` | What the number is *about*. Used only for period alignment, never for as-of filtering. |
| `fiscal_year` / `fiscal_period` | `fp='FY'` is the Piotroski/Altman selection filter. `fiscal_year` is reporting metadata only (SEC omits it on some entries), so it is out of the key. |
| `filed_date` | What the number was *known on*. The only legal as-of axis (C1). |
| `accession` | Audit: which filing produced this row. Not a key column — the same accession contributes hundreds of rows. |
| `value` | Nullable: the parser never emits NULL, but a future suppressed/non-numeric fact must be recordable without a migration. |
| `created_at` | Ingestion-run forensics; deliberately not the as-of axis. |

`0006` references only `assets` (from `0001`), so `db/migrate.py` applying it lexicographically
after the already-applied `0007` is safe — the tested non-contiguous pattern, precedent `0005`.
`collector/schema_check.py::REQUIRED_ML_RELATIONS` gains `"fundamental_facts"`.

---

## 2. `collector/fundamentals.py`

Pure module, no DB, no HTTP. Two public names: `CONCEPT_CHAINS` and `parse_company_facts`.

```python
US_GAAP, DEI = "us-gaap", "dei"
MONEY, SHARES = "USD", "shares"

# logical concept -> (expected unit, ordered (taxonomy, tag) fallback chain).
# Order = priority, evaluated per reporting period (see brain/fundamental_factors._select_as_of).
CONCEPT_CHAINS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "revenue":            (MONEY,  ((US_GAAP, "Revenues"),
                                    (US_GAAP, "RevenueFromContractWithCustomerExcludingAssessedTax"),
                                    (US_GAAP, "SalesRevenueNet"))),
    "cost_of_revenue":    (MONEY,  ((US_GAAP, "CostOfRevenue"),
                                    (US_GAAP, "CostOfGoodsAndServicesSold"),
                                    (US_GAAP, "CostOfGoodsSold"))),
    "gross_profit":       (MONEY,  ((US_GAAP, "GrossProfit"),)),          # else revenue - cost
    "assets":             (MONEY,  ((US_GAAP, "Assets"),)),
    "assets_current":     (MONEY,  ((US_GAAP, "AssetsCurrent"),)),
    "liabilities":        (MONEY,  ((US_GAAP, "Liabilities"),)),          # else assets - equity
    "liabilities_current":(MONEY,  ((US_GAAP, "LiabilitiesCurrent"),)),
    "equity":             (MONEY,  ((US_GAAP, "StockholdersEquity"),)),
    "long_term_debt":     (MONEY,  ((US_GAAP, "LongTermDebtNoncurrent"),
                                    (US_GAAP, "LongTermDebt"))),
    "net_income":         (MONEY,  ((US_GAAP, "NetIncomeLoss"), (US_GAAP, "ProfitLoss"))),
    "cfo":                (MONEY,  ((US_GAAP, "NetCashProvidedByUsedInOperatingActivities"),
                                    (US_GAAP, "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"))),
    "retained_earnings":  (MONEY,  ((US_GAAP, "RetainedEarningsAccumulatedDeficit"),)),
    "operating_income":   (MONEY,  ((US_GAAP, "OperatingIncomeLoss"),)),  # EBIT primary
    "pretax_income":      (MONEY,  ((US_GAAP, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
                                    (US_GAAP, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"))),
    "interest_expense":   (MONEY,  ((US_GAAP, "InterestExpense"), (US_GAAP, "InterestExpenseDebt"))),
    # dei first: the cover-page count is refiled with EVERY 10-Q, so it is the freshest
    # share count knowable at a filing date -- what Altman's MVE needs. See open decision 3.
    "shares_outstanding": (SHARES, ((DEI,     "EntityCommonStockSharesOutstanding"),
                                    (US_GAAP, "CommonStockSharesOutstanding"),
                                    (US_GAAP, "WeightedAverageNumberOfSharesOutstandingBasic"))),
}

# The allow-list is DERIVED from the chains, never a second literal -- they cannot drift.
ALLOWED_TAGS: frozenset[tuple[str, str]] = frozenset(
    pair for _unit, chain in CONCEPT_CHAINS.values() for pair in chain
)
```

`parse_company_facts(payload: dict, asset_id: str) -> list[dict]` walks
`payload["facts"][taxonomy][tag]["units"][unit]` and maps each entry **1:1**, no derivation:

| SEC entry key | Row column | Handling |
|---|---|---|
| `end` | `period_end` | required; entry skipped when absent |
| `filed` | `filed_date` | required; entry skipped when absent (a fact with no filing date is unusable under C1) |
| `val` | `value` | required and numeric; else skipped |
| `fy` | `fiscal_year` | `int` or `None` |
| `fp` | `fiscal_period` | `.strip().upper()`, `""` when absent |
| `accn` | `accession` | optional |
| (units key) | `unit` | verbatim |
| (taxonomy key) | `taxonomy` | verbatim, `us-gaap` or `dei` only |
| `form`, `frame`, `start` | — | not stored; `accession` already identifies the filing, and the DDL is frozen by the checksum guard once applied |

`dei` vs `us-gaap`: only shares outstanding crosses taxonomies. `dei:EntityCommonStockSharesOutstanding`
is a cover-page **instant** whose `end` is the cover date, which can fall *after* the statement
`period_end` — harmless here because selection is by `filed_date`, and the value is only ever read
as "latest share count filed on or before the cutoff", never period-matched to the balance sheet.

In-batch dedupe: companyfacts repeats an identical fact across the 10-Q and the 10-K that both
report it, producing the same natural key twice in one payload. The parser keeps the **last**
occurrence in SEC's own list order (chronological by `filed`) — deterministic and idempotent
with the DB `ON CONFLICT DO UPDATE`.

---

## 3. `collector/run_fundamental_ingestion.py`

Mirrors `collector/run_identifier_resolution.py` exactly (module constants, explicit
argument list decoupled from `collector.universe`, `main()` reads env + opens psycopg).

```python
def run_fundamental_ingestion(repository, client: SecEdgarClient, *,
                              ciks: list[str] | None = None,
                              limit: int | None = None) -> dict[str, Any]
```

1. `identifiers = repository.get_asset_identifiers(id_type="cik")` → `(asset_id, id_value)` pairs
   (`id_value` is the 10-digit padded CIK; `SecEdgarClient.pad_cik` re-pads for the URL).
   `--ciks` filters this list; it never bypasses it, so an unmapped CIK cannot be ingested.
2. Per CIK: `result = client.fetch_company_facts(cik)`.
   **The job writes no per-fetch audit row.** The client's own `finally` block already emits
   exactly one `IngestionRun` per fetch through `RepositoryIngestionRecorder` — duplicating it
   here would double-count `ingestion_runs` and create two disagreeing sources of audit truth.
3. `ok` → `rows = parse_company_facts(result["payload"], asset_id)` →
   `repository.upsert_fundamental_facts(rows)`.
   Not `ok` → append `{"cik":…, "reason": result["reason"]}` and continue. One bad CIK never
   aborts the other 100. `detail` is deliberately **not** recorded: it can echo the request URL
   or headers, and `ingestion_runs.error` must never carry `SEC_USER_AGENT` (operator email).
4. After the loop, one **job-summary** row:

```python
repository.insert_ingestion_run(
    source="sec_edgar", endpoint="fundamental_ingestion", target_key="",
    started_at=…, finished_at=…,
    status="success" if not failures else "failure",
    request_count=len(targets), rows_written=total_rows,
    max_filed_date=max_filed_date_seen,          # closes the gap ingestion_audit.py names
    metadata={"failed_ciks": failures, "assets_processed": n, "assets_with_no_facts": [...]},
)
```

`max_filed_date` was previously populated only by `fetch_submissions`; `collector/ingestion_audit.py`'s
docstring explicitly defers "full per-fact `filed`/`period_end` capture for XBRL facts" to a sibling
change. This is that sibling, so the job-summary row carries the newest `filed_date` it ingested and
the point-in-time-features spec's "which filing dates were available for this run" query now answers
for fundamentals.

CLI: `--ciks`, `--limit`, `--out PATH` (JSON report; module-constant default, operator-supplied,
never request-derived — the same non-matrix rule `run_identifier_resolution` documents). The report
is also printed to stdout via `json.dumps(..., indent=2)`.

---

## 4. Repository methods — `collector/local_repository.py`

New `# -- Fundamental facts ---` section, placed after `# -- Prices / features / labels ---`.

```python
FUNDAMENTAL_FACT_COLUMNS = ("asset_id", "taxonomy", "concept", "unit", "period_end",
                            "fiscal_year", "fiscal_period", "filed_date", "accession", "value")
FUNDAMENTAL_FACT_KEY = ("asset_id", "taxonomy", "concept", "unit",
                        "period_end", "fiscal_period", "filed_date")

def upsert_fundamental_facts(self, rows: list[dict[str, Any]], batch_size: int = 500) -> int:
    # validates every row carries exactly FUNDAMENTAL_FACT_COLUMNS, then batches
    # through the existing _upsert_batch(table, chunk, FUNDAMENTAL_FACT_KEY).

def get_fundamental_facts(self, asset_id: str, *, concepts: list[str] | None = None,
                          as_of_filed_date: str | date | None = None) -> pd.DataFrame:
    # SELECT taxonomy, concept, unit, period_end, fiscal_year, fiscal_period,
    #        filed_date, accession, value FROM fundamental_facts WHERE asset_id = %s
    #   [AND concept = ANY(%s)] [AND filed_date <= %s]
    # ORDER BY concept ASC, period_end ASC, filed_date ASC
```

Design points:

- **Upsert, not insert**, even though the table is append-shaped: with the full natural key as the
  conflict target, `update_cols` reduces to `value` + `accession`, so re-running the ingestion job on
  an unchanged payload is a byte-identical no-op instead of a unique violation. A restatement has a
  *different* `filed_date`, so it takes the INSERT branch — the restatement guarantee is enforced by
  the key, not by the method.
- `value` decodes to `float`, not `Decimal`, because `_configure` already registers `FloatLoader` for
  `numeric`; `brain/` therefore needs no Decimal handling (same reason D5 gives for `prices`).
- Empty result returns `pd.DataFrame(columns=list(...))`, a **typed** empty frame — unlike
  `get_prices`, which returns a column-less frame on empty. The factor layer indexes columns
  unconditionally and its hard requirement is NaN-never-crash; a column-less frame would raise
  `KeyError` for every asset with no CIK mapping (i.e. all crypto).
- `as_of_filed_date` is applied in SQL, not in pandas, so the index does the work and a 6-year
  backtest never materializes future facts into memory.

---

## 5. `brain/fundamental_factors.py`

Pure module. Imports `pandas`/`numpy` and `collector.fundamentals.CONCEPT_CHAINS` only —
**never** `brain/features.py` (keeps the import graph acyclic; see §6).

### The selection primitive

```python
def _select_as_of(facts, logical_concept, *, cutoff, fiscal_period="FY", offset=0)
        -> tuple[float, date | None]
```

Four ordered steps — this is the heart of the point-in-time guarantee:

1. **As-of filter**: keep rows with `filed_date <= cutoff`. Nothing else in the module ever
   looks at a filing.
2. **Period selection**: among the surviving rows for this concept's chain (and
   `fiscal_period == 'FY'` unless overridden), take the `offset`-th largest **distinct**
   `period_end`. `offset=0` = current FY, `offset=1` = prior FY. Distinct-period ordering — not
   row ordering — is what makes a missing quarter or a duplicated filing harmless.
3. **Tag fallback**: within that one period, walk the chain **in declared order** and take the
   first `(taxonomy, tag)` present with the concept's expected `unit`.
4. **Restatement**: within that `(period_end, tag, unit)`, take the row with the **greatest**
   `filed_date`. That is the newest revision knowable at the cutoff.

Returns `(np.nan, None)` at any dead end. The returned `filed_date` is accumulated by the caller
into `max_filed_date` — the C1 audit value (§8).

Priority-before-recency in step 3 (rather than "whichever tag was filed most recently") avoids a
filer that reports both `Revenues` and `RevenueFromContract...` flipping tags mid-history and
injecting an artificial level jump into the series.

### Period basis: FY only

All three factors read `fiscal_period='FY'` facts, with one designed exception:
`shares_outstanding` is selected with `fiscal_period=None` (any period), because the `dei`
cover-page count is refiled every quarter and Altman wants the freshest share count knowable at
the cutoff. Rationale for FY-only elsewhere: Piotroski is *defined* on annual data and 4 of its 9
signals are FY-over-FY; Altman's classic coefficients are calibrated on annual statements; and
mixing a quarterly numerator with an annual denominator produces a meaningless ratio. TTM
quarterly rollups were rejected — they need Q4 reconstructed as `FY − Q1 − Q2 − Q3`, which alone
exceeds the slice budget.

### Formulas

```
gross_profitability = gross_profit / assets                     # Novy-Marx (2013)
    gross_profit = GrossProfit, fallback revenue - cost_of_revenue
    denominator is TOTAL assets, not equity -- that is the published definition
```

```
altman_z_score  (classic public-firm Z, 1968)
    = 1.2*(WC/TA) + 1.4*(RE/TA) + 3.3*(EBIT/TA) + 0.6*(MVE/TL) + 1.0*(Sales/TA)

    WC   = assets_current - liabilities_current
    TA   = assets                                    (NaN when TA <= 0)
    RE   = retained_earnings
    EBIT = operating_income, fallback pretax_income + interest_expense
    TL   = liabilities, fallback assets - equity     (NaN when TL <= 0)
    Sales= revenue
    MVE  = shares_outstanding(as-of cutoff) * prices.close at the row's price date
           -- the ONLY fundamentals<->prices coupling in this change.
           No price row on that date -> MVE is NaN -> Z is NaN. Never interpolated.
```

```
piotroski_f_score  (0-9, sum of 9 binary signals; FY_t and FY_{t-1}, both filed <= cutoff)

  Profitability (4)   ROA_t > 0
                      CFO_t > 0
                      ROA_t > ROA_{t-1}
                      CFO_t > NetIncome_t                     (accruals quality)
  Leverage/liquidity/
  source of funds (3) LTD_t/TA_t < LTD_{t-1}/TA_{t-1}
                      CurrentRatio_t > CurrentRatio_{t-1}
                      SharesOut_t <= SharesOut_{t-1}          (no new equity issued)
  Efficiency (2)      GrossMargin_t > GrossMargin_{t-1}
                      AssetTurnover_t > AssetTurnover_{t-1}

  ROA           = net_income / assets
  CurrentRatio  = assets_current / liabilities_current
  GrossMargin   = gross_profit / revenue
  AssetTurnover = revenue / assets
```

Two deliberate deviations, both documented in-module: (a) ROA uses **same-year** total assets, not
Piotroski's beginning-of-year assets — one fewer required input, and the sign/ordering tests behave
equivalently in practice; (b) `SharesOut` for the equity-issuance signal uses the same chain as
Altman's MVE (see open decision 3).

**Missing-input policy** (ADR-4): if *any* of the 9 signals cannot be evaluated — including a
missing prior FY — the whole F-Score is `np.nan`, never a partial sum. A 5-of-7 score sits on a
different scale than a 9-signal score and would drift silently across assets and across time; NaN
is honest and `upsert_features`' existing `dropna` handles it.

### Public shape

```python
FACTOR_KEYS = ("piotroski_f_score", "altman_z_score", "gross_profitability")

def compute_factors_as_of(facts_df: pd.DataFrame,
                          prices_df: pd.DataFrame,
                          as_of_date) -> dict[str, Any]:
    """{piotroski_f_score, altman_z_score, gross_profitability, max_filed_date}.
    Every value is np.nan on any missing input. Never raises."""
```

`max_filed_date` is the maximum `filed_date` of every fact row this call actually selected, or
`None` when nothing was selected. It is the C1 provenance token (§8) and is **never** a feature
column. Non-raising is achieved by construction — `_select_as_of` returns NaN and `_safe_div`
propagates NaN on zero/None/NaN — **not** by a bare `except`, which would hide real bugs.

---

## 6. `brain/features.py` registration

Exactly two additions, both after the existing `compose_feature_set` definition (line 67), because
`compose_feature_set` reads `FEATURE_COLUMNS_BY_SET` and therefore cannot be called inside the dict
literal that defines it:

```python
FUNDAMENTAL_OVERLAY_COLUMNS = [
    "piotroski_f_score",
    "altman_z_score",
    "gross_profitability",
]
FEATURE_COLUMNS_BY_SET["fundamental_v1"] = compose_feature_set(
    "technical_v2", FUNDAMENTAL_OVERLAY_COLUMNS
)
```

C2 is satisfied *structurally*, not by convention:

- `FEATURE_COLUMNS_TECHNICAL_V1/_V2` and the `FEATURE_COLUMNS_BY_SET` literal are untouched;
  `FEATURE_COLUMNS_BY_SET["technical_v2"] is FEATURE_COLUMNS_TECHNICAL_V2` still holds.
- `compose_feature_set` returns a **new** list (`[*base, *overlay]`), so `technical_v2`'s list
  object is never mutated or aliased into the new entry.
- `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS` stays `{}` — out of scope; no caller passes `asset_class`.
- `build_features` is not touched: the overlay columns are produced by the materializer, not by the
  technical builder, so `technical_v1`/`technical_v2` materialization is byte-identical.

`FUNDAMENTAL_OVERLAY_COLUMNS` lives here, not in `fundamental_factors.py`, so `features.py` never
imports the factor module. A contract test asserts
`set(FUNDAMENTAL_OVERLAY_COLUMNS) == set(fundamental_factors.FACTOR_KEYS)`.

---

## 7. `brain/materialize_fundamentals.py`

**A new module, not an extension of `materialize_dataset.py`** (ADR-5): `materialize_asset_dataset`
writes features *and* labels for every asset in the daily path that feeds promoted `technical_v2`
models. Branching it on feature set would put a stock-only import on the crypto path, modify a
function whose current output must stay byte-identical, and push slice 4 over budget. The new module
still *calls* `build_features` — the spine math is reused, not duplicated, so a `fundamental_v1` row's
25 technical columns are identical to the `technical_v2` row at the same timestamp.

```python
def build_fundamental_overlay(spine: pd.DataFrame, facts: pd.DataFrame,
                              prices: pd.DataFrame, *, lag_trading_days: int = 1) -> pd.DataFrame
    # -> timestamp, piotroski_f_score, altman_z_score, gross_profitability, max_filed_date

def materialize_asset_fundamentals(repository, config: FundamentalMaterializationConfig)
        -> FundamentalMaterializationResult
```

Algorithm:

1. `spine = build_features(repository.get_prices(asset_id, limit=...))`;
   `spine_ts = spine["timestamp"]` sorted — **this is the trading calendar**. No
   `exchange_calendars` dependency: the asset's own price index is by definition the days on which
   it traded, and using anything else would let a row exist on a day the asset has no price.
2. `facts = repository.get_fundamental_facts(asset_id)` (full history; the cutoff is applied per
   event). Empty → return `feature_rows_loaded=0` and no exception. Crypto lands here.
3. **Event dates**: `events = sorted(facts["filed_date"].unique())`. For each `f`:
   ```
   i         = spine_ts.searchsorted(f, side="left")   # first trading day >= f
   effective = spine_ts[i + lag_trading_days]          # the 1-trading-day lag
   ```
   Out of range → the filing is not yet usable in this price history; skipped.
   `effective > f` **strictly**, always: if `f` is a trading day, `i` lands on `f` and `+1` moves
   past it; if `f` is a weekend/holiday, `i` lands on the next trading day and `+1` moves past that.
   This is what makes C1's strict `max(filed_date) < timestamp` hold rather than only `<=`.
4. `row = compute_factors_as_of(facts, prices, as_of_date=f)` — the cutoff is the **filing date**,
   the price date for MVE is that same `f`.
5. Overlay frame indexed by `effective`, `reindex(spine_ts).ffill()`, joined onto the spine.
6. `repository.upsert_features(asset_id, frame, feature_columns=feature_columns_for_set("fundamental_v1"),
   feature_set="fundamental_v1", batch_size=...)`. Days before the first usable filing have NaN
   overlay values and are dropped by `upsert_features`' existing `dropna(subset=feature_columns)` —
   **expected behaviour, not a failure**. The result dataclass reports `price_rows`,
   `fact_rows`, `event_dates`, `first_factor_timestamp` and `feature_rows_loaded` so an operator can
   see exactly how many rows the warm-up cost.
   `max_filed_date` is carried through the overlay frame but is **not** in `feature_columns`, so it
   never reaches `features_daily.features`.

### ADR-5b: compute at filing dates + reindex, not per trading day

| Option | Tradeoff | Decision |
|---|---|---|
| Per trading day D, cutoff = D | Altman's MVE moves daily with price — textbook Z. But ~1500 Python-level factor computations per asset × 101 assets, each re-deriving 8 unchanged fundamentals; and it re-injects daily price into a column labelled "fundamental", making the overlay's marginal contribution unattributable in the planned `fundamental_v1` vs `technical_v2` follow-up. | Rejected |
| Vectorized hybrid: fundamentals at events, MVE/Z recomputed daily in the materializer | Gets daily price sensitivity at O(n). But the Z formula would exist in two places (pure module + materializer) and drift. | Rejected |
| **Events + reindex + ffill** | ~24–50 computations per asset instead of ~1500; one implementation of every formula, exercised by both unit tests and the materializer; provably identical to per-D on every day where no filing landed, because the inputs are constant between filings. Cost: Z is annual-step. | **Chosen** — C1 declares step-shaped correct, and a daily-MVE variant is a small follow-up that reuses the same stored facts. |

---

## 8. The C1 hard test design

New file `tests/test_fundamental_lookahead.py`; the parser/factor cases live in
`tests/test_fundamental_ingestion.py` and `tests/test_fundamental_factors.py`.

**How "contributing filed_date" is tracked: the factor function returns it.**
`_select_as_of` returns the `filed_date` of every row it picks; `compute_factors_as_of` accumulates
`max_filed_date` from those same picks, and `build_fundamental_overlay` forward-fills it in the same
frame as the values. The assertion is therefore on the actual provenance of the actual numbers, not
on a reconstruction. The alternative — the test re-deriving which filings *should* have contributed
— was rejected because it re-implements the selection algorithm and would happily agree with a buggy
implementation. The residual risk (audit value and data share a code path, so a `_select_as_of` bug
could produce a self-consistent lie) is covered by C1-b, which is a pure black-box invariant.

| Test | Assertion |
|---|---|
| **C1-a look-ahead** | For every row of `build_fundamental_overlay(...)` with a non-NaN factor: `row["max_filed_date"] < row["timestamp"].date()` — strict. Plus: the value at each row equals `compute_factors_as_of(facts, prices, row["max_filed_date"])`, proving the ffill carried the right vintage. |
| **C1-b restatement** | `o0 = build_fundamental_overlay(spine, facts0, prices)` where `facts0` has FY2022 `Assets=100` filed 2023-02-15. `facts1 = facts0 + [FY2022 Assets=80 filed 2024-03-01]` (same period, later filing). Then `o1.loc[:'2024-02-29'].equals(o0.loc[:'2024-02-29'])` — adding *any* future-filed fact must not change a single earlier value — and `o1` differs from `o0` on the first trading day after 2024-03-01. |
| **C1-b (storage)** | `repository.upsert_fundamental_facts` of the original then the restatement → `count = 2`, and a `SELECT` of the original key still returns `value = 100`. Proves the restatement took the INSERT branch. |
| **C1-c NaN, never raise** | Empty facts → all three NaN. One FY only → `piotroski_f_score` NaN, other two finite. Missing price on the effective date → `altman_z_score` NaN, other two finite. A concept present only under an unexpected unit → that factor NaN. |
| **C1-d C2 regression** | `feature_columns_for_set("technical_v2") == FEATURE_COLUMNS_TECHNICAL_V2`; `feature_columns_for_set("fundamental_v1")[:25] == feature_columns_for_set("technical_v2")`; `len(...) == 28`. |
| **C1-e DB round-trip** | Via the existing `repository` fixture (real Postgres, rolled back): materialize, `get_features(asset_id, "fundamental_v1")`, assert each row's `timestamp` exceeds its recorded contributing filing and that the 25 technical values match the `technical_v2` row at the same timestamp. |

Fixture: `tests/fixtures/companyfacts_fake.json` — a hand-trimmed payload with 2 fiscal years, one
restatement, one tag-fallback case (`SalesRevenueNet` → `RevenueFromContract...` across years) and
one absent concept. Shared by the parser, factor and lookahead tests. Requirement **T** holds: the
ingestion test injects a fake `session` returning that fixture, exactly as
`tests/test_sec_edgar_client.py` does. No test opens a socket.

---

## 9. Slice plan — confirmed, 5 slices, `auto-chain` / `stacked-to-main`

`Decision needed before apply: No` · `Chained PRs recommended: Yes` · `400-line budget risk: Medium`
(slices 3 and 4 sit near the ceiling; if slice 4 forecasts over, split the C1 test file into its own
slice 4b rather than trimming assertions).

| # | Files | RED test shipped first | ~lines |
|---|---|---|---|
| 1 · Storage | `db/migrations/0006_fundamental_facts.sql` (35), `collector/local_repository.py` +2 methods (75), `collector/schema_check.py` (+1), `tests/test_local_repository.py` (+150), `tests/test_migrate.py` (+20) | `test_fundamental_facts_restatement_creates_new_row` | ~280 |
| 2 · Ingestion | `collector/fundamentals.py` (140), `collector/run_fundamental_ingestion.py` (130), `tests/fixtures/companyfacts_fake.json` (60), `tests/test_fundamental_ingestion.py` (120) | `test_parse_company_facts_maps_filed_and_period_end_one_to_one` | ~390 |
| 3 · Factor math | `brain/fundamental_factors.py` (235), `tests/test_fundamental_factors.py` (175) | `test_piotroski_is_nan_without_prior_fiscal_year` | ~400 |
| 4 · Overlay + C1 | `brain/features.py` (+6), `brain/materialize_fundamentals.py` (165), `tests/test_feature_set_resolution.py` (+30), `tests/test_fundamental_lookahead.py` (185) | `test_no_row_uses_a_filing_dated_on_or_after_its_own_timestamp` | ~385 |
| 5 · Wiring + docs | `config/targets.stocks.json` (10), `brain/run_retraining_job.py` help text (+8), `README.md` runbook (120), `tests/test_brain_pipeline.py` (+110) | `test_retraining_job_runs_on_fundamental_v1_feature_set` | ~250 |

Each slice ends green and is independently revertible: 1 leaves an unused table, 2 leaves a
populated table nothing reads, 3 leaves an unreferenced pure module, 4 makes `fundamental_v1`
materializable, 5 makes it operable.

## Threat Matrix

`N/A` — no routing, shell command, subprocess, VCS/PR automation, executable-file classification, or
process integration. The two new entry points are argparse `main()` functions in the existing job
pattern; the only outbound network call goes through the already-audited `SecEdgarClient`. Two
inherited non-matrix constraints are carried forward as design requirements: (a) file paths
(`--out`, universe path) are module constants or operator CLI arguments, never request-derived; (b)
`SEC_USER_AGENT` (an operator email) must never reach `ingestion_runs.error` or `metadata` — the job
records `reason` codes only, never the client's `detail`.

## Migration / Rollout

`py -3.14 -m db.migrate` applies `0006` after `0007` (non-contiguous is the tested pattern). `pg_dump`
before applying and before the first backfill. `0006` is immutable once applied (checksum guard) — a
correction is `0008`. Rollback: stop the job, `delete from features_daily where feature_set='fundamental_v1'`,
`drop table fundamental_facts`, remove the one `FEATURE_COLUMNS_BY_SET` assignment. No promoted model
is re-promoted, because none of them reference `fundamental_v1`.

## Open Questions (for `sdd-tasks`)

- [ ] **Altman variant.** Classic public-firm Z chosen: it is defined for public filers, uses the
      market-equity term we can compute, and the S&P 100 mixes manufacturers, banks and services so
      no single specialized variant fits. Z'' (non-manufacturer: `6.56·WC/TA + 3.26·RE/TA +
      6.72·EBIT/TA + 1.05·BVE/TL`) was rejected because it drops market equity entirely and would need
      a SIC code we do not ingest. The absolute 1.81/2.99 cutoffs are miscalibrated for non-manufacturers,
      which is acceptable because a tree model learns its own splits — confirm this framing is accepted.
- [ ] **Concept present under multiple units.** Each chain declares its expected unit and
      `_select_as_of` filters on it. Decide the behaviour when the expected unit is absent but another
      is present: proposed **NaN, never convert or guess**.
- [ ] **Shares outstanding source.** Chain is `dei:EntityCommonStockSharesOutstanding` →
      `us-gaap:CommonStockSharesOutstanding` → `WeightedAverageNumberOfSharesOutstandingBasic`.
      Consider **two** chains: the cover-page count for Altman's MVE, and
      `WeightedAverageNumberOfSharesOutstandingBasic` for Piotroski's equity-issuance signal, which is
      the more standard basis. Recommended: yes, split them in slice 3.
- [ ] **Trading calendar.** The asset's own `prices` index. Risk: a gap in `prices` widens the
      effective lag (a 3-day hole makes "1 trading day" span 4 calendar days) — conservative, never
      early. Decide whether to assert a maximum tolerated gap or leave it.
- [ ] **Ingestion cadence.** Proposal question 5 was never answered. Design assumes a **standalone**
      job on a weekly Windows Task Scheduler entry, not a step inside `collector/run_market_data_job.py`.
      Confirm before slice 5.
- [ ] **Fallback chains vs real payloads.** `ProfitLoss`, `InterestExpenseDebt`, the `pretax_income`
      tags and the `liabilities = assets - equity` fallback are chosen from the concept map, not
      measured. Slice 2 must print per-concept coverage across the 101 CIKs so slice 3 can prune or
      extend the chains on evidence.
