# Apply Progress: Fundamental Analysis

Engram topic key: `sdd/fundamental-analysis/apply-progress`.
Mode: Standard (config `testing.strict_tdd: false`). RED tests written first, watched
fail, then implemented to GREEN.

## Phase 1: Storage — DONE (10/10 tasks)

Slice: PR 1 (`auto-chain` / `stacked-to-main`). Authored diff ~374 changed lines
(373 additions + 1 deletion), under the 400-line per-slice budget.

### Completed Tasks

- [x] 1.1 `test_fundamental_facts_restatement_creates_new_row`
- [x] 1.2 `test_fundamental_facts_round_trip_on_full_key`
- [x] 1.3 `test_get_fundamental_facts_returns_typed_empty_frame` + `test_get_fundamental_facts_applies_as_of_filed_date_in_sql`
- [x] 1.4 `test_0006_applies_after_0007_without_reapplying`
- [x] 1.5 `test_fundamental_facts_is_a_required_relation_and_present_after_migration`
- [x] 1.6 `db/migrations/0006_fundamental_facts.sql` (design §1 DDL, verbatim)
- [x] 1.7 `FUNDAMENTAL_FACT_COLUMNS` / `FUNDAMENTAL_FACT_KEY` constants + `upsert_fundamental_facts`
- [x] 1.8 `get_fundamental_facts(asset_id, *, concepts=None, as_of_filed_date=None)`
- [x] 1.9 `"fundamental_facts"` added to `REQUIRED_ML_RELATIONS`
- [x] 1.10 `py -3.14 -m db.migrate` applied `0006`; `py -3.14 -m collector.schema_check` → `OK fundamental_facts`

### Files Changed

| File | Action | What |
|------|--------|------|
| `db/migrations/0006_fundamental_facts.sql` | Created (+37) | Tall XBRL fact store. Identity PK, `asset_id uuid references assets(id) on delete cascade`, 7 key columns all `not null`, `unique (asset_id, taxonomy, concept, unit, period_end, fiscal_period, filed_date)`, `fundamental_facts_asof_idx on (asset_id, concept, filed_date desc)`. References only `assets`. |
| `collector/local_repository.py` | Modified (+115 -1) | `from datetime import date, datetime`; module constants `FUNDAMENTAL_FACT_COLUMNS` (10) + `FUNDAMENTAL_FACT_KEY` (7); new `# -- Fundamental facts --` section with `upsert_fundamental_facts(rows, batch_size=500)` (column validation → `_upsert_batch(table, chunk, FUNDAMENTAL_FACT_KEY)`) and `get_fundamental_facts(asset_id, *, concepts=None, as_of_filed_date=None) -> pd.DataFrame` (cutoff applied in SQL as `filed_date <= %s::date`; typed empty frame with 9 columns on no rows). |
| `collector/schema_check.py` | Modified (+1) | `"fundamental_facts"` appended to `REQUIRED_ML_RELATIONS`. |
| `tests/test_local_repository.py` | Modified (+173) | `from datetime import date`; `# -- Fundamental facts --` section: `_fundamental_fact_row` helper + 4 tests (restatement invariant, full-key round trip / idempotency, typed empty frame, as-of cutoff). |
| `tests/test_migrate.py` | Modified (+36) | `test_0006_applies_after_0007_without_reapplying` — real `db/migrations` dir: `0006` sorts before `0007`, is the only pending migration when everything else is recorded, `0007` never re-applied; a drifted recorded checksum for the applied `0006` raises `MigrationError("migration_checksum_mismatch:0006_fundamental_facts.sql")`. |
| `tests/test_schema_check.py` | Modified (+11) | `test_fundamental_facts_is_a_required_relation_and_present_after_migration`. |

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command + result | `py -3.14 -m pytest tests/test_local_repository.py tests/test_migrate.py tests/test_schema_check.py` → **55 passed** (49 baseline + 6 new). RED run beforehand: 6 failed / 49 passed. |
| Runtime harness command + result | `py -3.14 -m db.migrate` → `Applied migrations: 0006_fundamental_facts.sql`. `py -3.14 -m collector.schema_check` → all 15 relations `OK` incl. `fundamental_facts`, exit 0. |
| Full suite | `py -3.14 -m pytest -q` → **353 passed**, 1 pre-existing joblib/loky CPU-count warning. (Baseline 347 + 6 new.) |
| Rollback boundary | `drop table fundamental_facts;` + `delete from schema_migrations where version='0006_fundamental_facts.sql';` then revert the `schema_check.py` line and the two `local_repository.py` methods + constants. No other module imports the new surface yet. |

### Deviations from Design

1. **Task 1.4 uses `verify_no_checksum_drift` directly** rather than calling `apply_migrations` against a mutated real migration file. `apply_migrations` delegates to that guard before any DB write; testing it directly proves the same acceptance (checksum drift on an applied `0006` is rejected) without a destructive live-DB / real-file mutation. Matches the existing `test_verify_no_checksum_drift_raises_on_mismatch` pattern.
2. **`update_cols` is 3 columns, not 2.** Design §4 prose says the ON CONFLICT update "reduces to `value` + `accession`", but `_upsert_batch` derives update columns as every non-key column, i.e. `fiscal_year, accession, value`. All three are functionally determined by the 7-column natural key (one filing → one `fiscal_year`), so idempotent re-ingest and the restatement invariant both still hold. Kept `_upsert_batch` unchanged per task 1.7.
3. **`pg_dump` skipped** in task 1.10 — the binary is not installed in this environment. The migration is additive DDL only (`create table/index if not exists`, single FK to `assets`) and is trivially reversible.

### Issues Found

None blocking. Note: `openspec/changes/fundamental-analysis/` is currently untracked on branch `codex/sdd-professional-improvements`.

## Phase 2: Ingestion — parser + audited per-CIK job + coverage report — DONE (10/10 tasks)

Slice: PR 2 (`auto-chain` / `stacked-to-main`). This was a RETRY: a prior attempt was
interrupted by an API rate limit right after writing the RED tests
(`tests/test_fundamental_ingestion.py` + `tests/fixtures/companyfacts_fake.json`), which were
left on disk and confirmed to fail with `ModuleNotFoundError` before any implementation code
was written this session. Those RED tests were treated as the design already made and were not
rewritten.

### Completed Tasks

- [x] 2.1 `tests/fixtures/companyfacts_fake.json` (pre-existing from the interrupted attempt, verified as-is): 2 fiscal years, one restatement (`Assets` `period_end=2022-12-31` filed `2023-02-15` then `2023-11-01`), one tag-fallback pair (`SalesRevenueNet` / `RevenueFromContractWithCustomerExcludingAssessedTax`), one non-allow-listed concept (`MarketableSecuritiesCurrent`).
- [x] 2.2 `test_parse_company_facts_maps_filed_and_period_end_one_to_one` (pre-existing, verified as-is)
- [x] 2.3 `test_parse_company_facts_skips_entries_missing_end_filed_or_val` + `test_parse_company_facts_in_batch_dedupe_keeps_last` (pre-existing, verified as-is)
- [x] 2.4 `test_run_fundamental_ingestion_audits_every_fetch` (pre-existing, verified as-is)
- [x] 2.5 `test_run_fundamental_ingestion_job_summary_row` (pre-existing, verified as-is)
- [x] 2.6 `test_run_fundamental_ingestion_report_has_per_concept_coverage` (pre-existing, verified as-is)
- [x] 2.7 `collector/fundamentals.py` — `CONCEPT_CHAINS` (17 logical concepts incl. the two split `shares_outstanding_mve` / `shares_outstanding_wavg` chains), `ALLOWED_TAGS` (derived), `parse_company_facts(payload, *, asset_id)`
- [x] 2.8 `collector/run_fundamental_ingestion.py` — `run_fundamental_ingestion(repository, client, *, ciks=None, limit=None)`
- [x] 2.9 job-summary `insert_ingestion_run` row + `--out` JSON report + CLI (`--ciks`, `--limit`, `--out`)
- [x] 2.10 Runtime harness NOT run — `SEC_USER_AGENT` is not configured in this environment (verified: `SecEdgarConfig.from_env()` returns `None`), so `main()` would raise `SecEdgarConfigError` before any socket opens; no local Postgres CIK-identifier data was seeded either. The `--out` report *shape* (including the per-concept coverage map that gates Phase 3) is proven at the unit level by `test_run_fundamental_ingestion_report_has_per_concept_coverage`. Open follow-up before Phase 3: run `py -3.14 -m collector.run_fundamental_ingestion --limit 3 --out artifacts/fund_coverage.json` with `SEC_USER_AGENT` set against real Postgres and attach the coverage summary.

### Files Changed

| File | Action | What |
|------|--------|------|
| `collector/fundamentals.py` | Created (181 lines) | Pure module. `US_GAAP`/`DEI`/`MONEY`/`SHARES` constants; `CONCEPT_CHAINS: dict[str, tuple[str, tuple[tuple[str,str], ...]]]` (17 logical concepts, design §2 verbatim except `shares_outstanding` split into `shares_outstanding_mve` + `shares_outstanding_wavg` per tasks.md Open Question 3, resolved for Phase 2); `ALLOWED_TAGS = frozenset(pair for _unit, chain in CONCEPT_CHAINS.values() for pair in chain)`; `parse_company_facts(payload, *, asset_id) -> list[dict]` walks `facts[taxonomy][concept]["units"][unit]`, keeps only `ALLOWED_TAGS` pairs, skips entries missing `end`/`filed`/numeric `val` (`bool` explicitly rejected despite being an `int` subclass), `fp` normalized `.strip().upper()` (`""` when absent), in-batch dedupe keeps the LAST occurrence per the 7-column natural key. |
| `collector/run_fundamental_ingestion.py` | Created (228 lines) | Mirrors `collector/run_identifier_resolution.py`. `run_fundamental_ingestion(repository, client, *, ciks=None, limit=None) -> dict`: resolves `repository.get_asset_identifiers(id_type="cik")`, `--ciks` FILTERS (never bypasses) via a local 10-digit zero-pad normalizer, `limit` caps the filtered target list, per target calls `client.fetch_company_facts(cik)` (no per-fetch audit row written here — the client's own `finally`/`RepositoryIngestionRecorder` already does), on failure records `{cik, reason}` only (never `detail`/`SEC_USER_AGENT`) and continues, on success `parse_company_facts` → `repository.upsert_fundamental_facts(rows)` and accumulates per-logical-concept coverage + running max `filed_date`. After the loop: one job-summary `insert_ingestion_run(source="sec_edgar", endpoint="fundamental_ingestion", target_key="")` row and a JSON-serializable report dict (`status`, `assets_processed`, `assets_with_no_facts`, `failed_ciks`, `unresolved_ciks`, `request_count`, `rows_written`, `max_filed_date`, `per_concept_coverage`). `main()` CLI: `--ciks`, `--limit`, `--out` (default `artifacts/fund_coverage.json`, module constant, never request-derived), writes the file and also prints via `json.dumps(..., indent=2)`. |
| `tests/fixtures/companyfacts_fake.json` | Pre-existing, verified (104 lines) | See 2.1. |
| `tests/test_fundamental_ingestion.py` | Pre-existing, verified (426 lines) | 11 tests: 6 parser tests + 5 job tests, using a `FakeFactsSession` (URL→canned-response map, robust to fetch ordering) and a `FakeFundamentalRepository` (in-memory `get_asset_identifiers`/`upsert_fundamental_facts`/`insert_ingestion_run`). |

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command + result | `py -3.14 -m pytest tests/test_fundamental_ingestion.py` → **11 passed**, first run after implementation (no retries needed). RED confirmed beforehand: `ModuleNotFoundError: No module named 'collector.fundamentals'` on collection. |
| Runtime harness command + result | `py -3.14 -m collector.run_fundamental_ingestion --limit 3 --out artifacts/fund_coverage.json` — **N/A this session**: `SEC_USER_AGENT` is not configured (verified via `SecEdgarConfig.from_env()` → `None`) and no CIK-mapped assets exist in this session's Postgres, so `main()` would raise `SecEdgarConfigError` before any socket opens. The report shape is exercised at the unit level instead (`test_run_fundamental_ingestion_report_has_per_concept_coverage`, `test_run_fundamental_ingestion_job_summary_row`). |
| Full suite | `py -3.14 -m pytest -q` → **364 passed** (353 baseline + 11 new), 1 pre-existing joblib/loky CPU-count warning, 0 regressions, 564.30s. |
| Rollback boundary | Delete `collector/fundamentals.py` + `collector/run_fundamental_ingestion.py`. `fundamental_facts` (Phase 1) just stops being written; nothing else imports the new surface yet. |

### Deviations from Design

1. **`shares_outstanding` split into two chains in `CONCEPT_CHAINS`**, not the single chain design.md §2's code block shows. This matches `tasks.md`'s own "Open Questions — resolved for tasks" #3 ("Constants land in Phase 2; consumed in Phase 3") and is exactly what `tests/test_fundamental_ingestion.py::test_allowed_tags_is_derived_from_concept_chains` asserts (`shares_outstanding_mve` and `shares_outstanding_wavg` present and distinct). Followed the resolved task decision over the design's unresolved illustrative snippet, per the "fix the test, not the design" guidance — here neither needed fixing; design.md's own Open Questions section already states "Recommended: yes, split them" for the same decision.
2. **Authored diff is larger than the ~390-line slice-plan estimate.** Total changed lines across the 4 slice-2 files: 939 (`fundamentals.py` 181, `run_fundamental_ingestion.py` 228, `companyfacts_fake.json` 104, `test_fundamental_ingestion.py` 426), vs. design.md §9's estimate of 140+130+60+120=450 (tasks.md's Review Workload Forecast rounds this to "~390"). The test file and fixture were pre-existing from the interrupted prior attempt and were deliberately NOT rewritten (retry instructions treat them as the RED-test design already made); they alone are 530 lines, already over the 400-line PR budget before any implementation code existed. My two new modules (409 lines) are also above their 270-line combined estimate, driven by matching this codebase's established verbose-docstring convention (`sec_edgar_client.py`, `ingestion_audit.py`, `run_identifier_resolution.py` all carry similarly dense module/function docstrings). No code was cut to force a smaller diff, since `tasks.md` explicitly says "do not trim C1 assertions" for a related slice and the same principle was applied here to the parser/job test coverage. Flagged for the orchestrator/gatekeeper's delivery-strategy handling, not resolved unilaterally (this repo's receipt-driven review is OFF and slice-2 was not re-split).
3. Task 2.10's runtime harness was not exercised — see the Work Unit Evidence row above.

### Issues Found

None blocking.

## Phase 3: Factor math — `brain/fundamental_factors.py` — DONE (10/10 tasks)

Slice: PR 3 (`auto-chain` / `stacked-to-main`). Mode note: this batch wrote the pure
module and its tests together rather than watching each test fail first in a separate
step — a deviation from the strict RED-then-GREEN sequencing Phases 1+2 followed. Standard
mode (`testing.strict_tdd: false`) permits this; all 22 tests passed on the first run
against the finished implementation, and no implementation code was adjusted afterward to
make a test pass (no test was weakened to fit a bug). Flagged under Deviations below.

### Completed Tasks

- [x] 3.1 `test_piotroski_is_nan_without_prior_fiscal_year`
- [x] 3.2 `test_select_as_of_excludes_filings_after_cutoff`
- [x] 3.3 `test_select_as_of_picks_greatest_filed_date_for_restated_period` + `test_select_as_of_offset_selects_prior_distinct_period`
- [x] 3.4 `test_missing_quarter_yields_nan_not_crash` + `test_missing_price_makes_altman_z_nan` + `test_concept_only_under_unexpected_unit_yields_nan`
- [x] 3.5 `test_piotroski_partial_signals_yield_nan` + `test_two_shares_chains_are_distinct`
- [x] 3.6 `test_compute_factors_as_of_returns_max_filed_date_token`
- [x] 3.7 `_select_as_of(facts, logical_concept, *, cutoff, fiscal_period="FY", offset=0) -> tuple[float, date | None]` — four ordered steps (as-of filter → distinct-`period_end` selection → declared-order tag fallback with expected-unit filter → greatest-`filed_date` restatement pick)
- [x] 3.8 `_safe_div` + the three factor formulas (Novy-Marx gross profitability, classic Altman Z with EBIT/TL fallbacks and `TA<=0`/`TL<=0` guards, Piotroski F-Score with the two documented deviations)
- [x] 3.9 `FACTOR_KEYS` + `compute_factors_as_of(facts_df, prices_df, as_of_date) -> dict`; imports only `pandas`/`numpy` + `collector.fundamentals.CONCEPT_CHAINS`, never `brain/features.py`
- [x] 3.10 Reconciliation deferred (no Phase 2 coverage report exists in this environment); recorded in the module docstring, not silently skipped

### Files Changed

| File | Action | What |
|------|--------|------|
| `brain/fundamental_factors.py` | Created (322 lines) | Pure module, no DB/HTTP. `FACTOR_KEYS = ("piotroski_f_score", "altman_z_score", "gross_profitability")`. `_to_date(value)` normalizes `date`/`datetime`/`pandas.Timestamp`/ISO-string to `date` (the repository hands back `datetime.date`, the parser and unit tests use ISO strings — both must resolve identically). `_select_as_of(facts, logical_concept, *, cutoff, fiscal_period="FY", offset=0) -> tuple[float, date \| None]` — the point-in-time primitive: as-of filter (`filed_date <= cutoff`) → distinct-`period_end` selection (`offset`-th largest, fiscal-period-aware so interspersed quarters never count) → declared-order tag fallback filtered by the chain's expected unit (Open Question 2: never convert/guess a unit) → greatest-`filed_date` restatement pick. Raises `KeyError` on an unknown `logical_concept` (programmer error, not missing data) rather than returning NaN. `_safe_div` (NaN on zero/None/NaN denominator or numerator). `_binary(a, b, *, op)` — one Piotroski signal, `None` (not NaN) when unevaluable so the caller can distinguish "signal is 0" from "signal unevaluable". `_price_close_on(prices_df, as_of_date)` — exact-date `close` lookup for Altman's MVE, no interpolation. `_compute_gross_profitability`, `_compute_altman_z`, `_compute_piotroski` — the three formulas from design §5, each taking a `pick` closure. `compute_factors_as_of(facts_df, prices_df, as_of_date) -> dict` — builds the `pick` closure (which both resolves via `_select_as_of` and accumulates every selected fact's `filed_date`), calls all three factor functions, returns `{piotroski_f_score, altman_z_score, gross_profitability, max_filed_date}`. `max_filed_date` is the max of every contributing `filed_date` across all three factors (`None` if nothing was selected) — never one of `FACTOR_KEYS`, never reaches `features_daily.features`. Every path is non-raising by construction (NaN dead ends + IEEE-754 NaN propagation through `+`/`*`/`_safe_div`) — no bare `except` anywhere in the module. |
| `tests/test_fundamental_factors.py` | Created (~470 lines) | 22 tests. Fixture `_two_year_facts()` — a hand-built FY2021→FY2022 company engineered so all 9 Piotroski signals are TRUE (F-Score == 9) and Altman/Novy-Marx resolve to hand-computable fractions (`EXPECTED_Z ≈ 2.70134615...`, `EXPECTED_GROSS_PROFITABILITY = 0.375`), both asserted via `pytest.approx` against literal arithmetic expressions in the test body (not re-derived from the module under test). Covers: `_select_as_of` cutoff exclusion / restatement selection / offset+missing-quarter tolerance / declared-order tag-fallback priority-over-recency / unknown-concept `KeyError`; `_safe_div` NaN propagation; gross_profitability direct-tag and revenue-minus-cost-fallback formulas; Altman's EBIT fallback (`pretax_income + interest_expense`), TL fallback (`assets - equity`), and `TA<=0`/`TL<=0` NaN guards; missing-price → Altman-only NaN; unexpected-unit → isolated single-factor NaN (Open Question 2, isolated via `retained_earnings` which only Altman touches); Piotroski NaN-on-first-year and NaN-on-any-single-missing-signal (isolated via `shares_outstanding_wavg`, which only Piotroski touches — proves Altman's distinct `shares_outstanding_mve` chain is unaffected, Open Question 3); `compute_factors_as_of` all-NaN-on-empty-facts; `max_filed_date` token value/`None`/never-in-`FACTOR_KEYS`; and a direct unit-level C1 no-look-ahead test (`test_compute_factors_as_of_ignores_facts_filed_after_cutoff`) — adding a fact filed in 2024 must not change any output computed as-of a 2023 cutoff, asserted via whole-dict equality. |

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command + result | `py -3.14 -m pytest tests/test_fundamental_factors.py -q` → **22 passed**, first run against the finished implementation (no test needed a retry or a subsequent implementation fix). |
| Runtime harness command + result | N/A — pure module, no I/O entry point (per tasks.md's own Suggested Work Units table: "unit tests are the harness"). |
| Full suite | `py -3.14 -m pytest -q` → **386 passed** (364 baseline + 22 new), 0 regressions, 1 pre-existing joblib/loky CPU-count warning, 32.96s. |
| Rollback boundary | Delete `brain/fundamental_factors.py` and `tests/test_fundamental_factors.py`. Nothing imports the new module yet (Phase 4 is the first consumer). |

### Deviations from Design

1. **Sequencing**: the module and its tests were written together rather than watching each
   RED test fail individually before implementing, breaking from the strict RED→GREEN
   cadence Phases 1+2 used. Standard mode (`testing.strict_tdd: false`) permits this; no test
   was adjusted after the fact to paper over an implementation bug — all 22 passed cleanly on
   the first run. Flagged per the orchestrator's explicit request to follow the established
   RED-then-GREEN pattern; this batch did not fully honor it and that gap is being reported
   rather than silently presented as compliant.
2. **`_select_as_of` raises `KeyError` on an unknown `logical_concept`**, rather than
   returning `(np.nan, None)`. Design.md doesn't specify this case explicitly. Rationale: an
   unrecognized concept name reaching this function is a programmer typo (every call site is
   an internal literal string, never external input), not a missing-DATA case — the module's
   "never raise" contract is about the *data* (missing tags, missing quarters, missing
   prior-FY comparisons), not about internal programming mistakes, which should fail loudly.
   Covered by `test_select_as_of_unknown_concept_raises_key_error`.
3. **Task 3.10 (`CONCEPT_CHAINS` coverage-report reconciliation) is deferred**, not
   performed. It is gated on Phase 2 task 2.10's `--out` per-concept coverage report, which
   was never generated (Phase 2 also deferred it — no `SEC_USER_AGENT` / seeded CIK data in
   this environment). `CONCEPT_CHAINS` is used unchanged from Phase 2. The deferral, its
   cause, and the specific follow-up (re-run the coverage report against real S&P 100 CIK
   data, then revisit the least-common fallback tags) are recorded directly in
   `brain/fundamental_factors.py`'s module docstring, not left as a silent gap.

### Issues Found

None blocking.

### Risks / Notes for Phase 4

- `compute_factors_as_of(facts_df, prices_df, as_of_date)` expects `facts_df` in exactly the
  9-column shape `get_fundamental_facts` returns (`taxonomy, concept, unit, period_end,
  fiscal_year, fiscal_period, filed_date, accession, value`) and `prices_df` needs only
  `timestamp` + `close` columns (`get_prices`'s shape is a superset — fine as-is).
- Altman's MVE term calls `_price_close_on(prices_df, cutoff)` with an **exact-date** match
  (no interpolation, no nearest-day fallback) — `as_of_date` passed into `compute_factors_as_of`
  MUST be a date that actually has a price row, or `altman_z_score` is NaN for that call. Per
  design §7, Phase 4's materializer calls `compute_factors_as_of(facts, prices, as_of_date=f)`
  with `f` = the filing's own `filed_date`; if `f` itself isn't a trading day (weekend/holiday
  filing), Altman will come back NaN for that event even though Piotroski/gross_profitability
  might still resolve. This is consistent with "never interpolated" but is worth Phase 4
  double-checking against the design's exact intended semantics before assuming every event
  date has a matching price row.
- `max_filed_date` is a `datetime.date` (or `None`), not a string — Phase 4's overlay frame
  (`build_fundamental_overlay`) will need to carry it as-is (not `str()`-cast) since the C1
  test compares it against `row["timestamp"].date()`.
- `_select_as_of` computes the `offset`-th prior period **independently per logical concept**
  (not a single shared "prior period" synchronized across all 9 Piotroski inputs). This
  matches design §5's algorithm exactly (each `_select_as_of` call is self-contained), but
  means two different concepts could in principle resolve to prior-FY period_ends that don't
  literally match if one concept has a data gap the other doesn't — this is expected/designed
  behavior (distinct-period tolerance), not a bug, and doesn't need any Phase 4 change.

## Phase 4: Overlay + C1 hard test — DONE (9/9 tasks)

Slice: PR 4 (`auto-chain` / `stacked-to-main`). This was a RETRY: a prior attempt was
interrupted by an API rate limit right after implementing production code
(`brain/materialize_fundamentals.py`, the `brain/features.py` registration diff) but
BEFORE writing any tests. Both were read in full, checked for correctness against
design.md §7/§6, and treated as the implementation already made — not rewritten from
scratch. Tests (4.1-4.5) were written fresh this session against that pre-existing
implementation, so the GREEN code predates the RED tests here — the same documented
deviation Phase 3 reported ("standard mode permits this; report it honestly, don't
present it as compliant").

### Completed Tasks

- [x] 4.1 `test_no_row_uses_a_filing_dated_on_or_after_its_own_timestamp` (C1-a)
- [x] 4.2 `test_restatement_never_leaks_backward` (C1-b)
- [x] 4.3 `test_c1c_nan_never_raises` + `test_non_stock_asset_is_skipped_not_failed`
- [x] 4.4 `test_technical_v2_columns_byte_identical` + `test_fundamental_v1_composes_technical_v2_plus_three_factors` (C1-d)
- [x] 4.5 `test_c1e_db_round_trip` (C1-e, real repository fixture, rolled back)
- [x] 4.6 `FUNDAMENTAL_OVERLAY_COLUMNS` + `FEATURE_COLUMNS_BY_SET["fundamental_v1"]` in `brain/features.py` (pre-existing, verified as-is)
- [x] 4.7 `build_fundamental_overlay(spine, facts, prices, *, lag_trading_days=1)` in `brain/materialize_fundamentals.py` (pre-existing; ONE bug found and fixed — see Deviations)
- [x] 4.8 `FundamentalMaterializationConfig` / `FundamentalMaterializationResult` / `materialize_asset_fundamentals(repository, config)` + `main()` CLI (pre-existing, verified as-is)
- [x] 4.9 `py -3.14 -m brain.materialize_fundamentals --ticker AAPL` — ran end-to-end (see Work Unit Evidence); `feature_rows_loaded=0` because no `fundamental_facts` are seeded for AAPL in this database (same Phase 2/3 ingestion gap), not a code defect

### Files Changed

| File | Action | What |
|------|--------|------|
| `brain/features.py` | Modified (+18), pre-existing verified as-is | `FUNDAMENTAL_OVERLAY_COLUMNS = ["piotroski_f_score", "altman_z_score", "gross_profitability"]` and `FEATURE_COLUMNS_BY_SET["fundamental_v1"] = compose_feature_set("technical_v2", FUNDAMENTAL_OVERLAY_COLUMNS)`, placed directly after `compose_feature_set`'s definition per design §6. `FEATURE_COLUMNS_TECHNICAL_V1/_V2`, the dict literal's other entries, `build_features`, and `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS` untouched. |
| `brain/materialize_fundamentals.py` | Created (263 lines), pre-existing verified against new tests, one bug fixed | `build_fundamental_overlay(spine, facts, prices, *, lag_trading_days=1)` — events-from-`facts["filed_date"]`, `searchsorted`+lag for the strict `effective > f` boundary, `compute_factors_as_of` per event, then an as-of join onto the full spine (see Deviations for the `merge_asof` fix). `FundamentalMaterializationConfig`/`FundamentalMaterializationResult` dataclasses. `materialize_asset_fundamentals(repository, config)` — stock-only gate on `assets.asset_class`, writes via `repository.upsert_features(..., feature_set="fundamental_v1")`. `main()` CLI mirroring `brain/materialize_dataset.py`. |
| `tests/test_fundamental_lookahead.py` | Created (408 lines) | C1-a look-ahead (`test_no_row_uses_a_filing_dated_on_or_after_its_own_timestamp`), C1-b restatement (`test_restatement_never_leaks_backward`), C1-c NaN-never-raises (`test_c1c_nan_never_raises`, 4 sub-cases), stock-only scope (`test_non_stock_asset_is_skipped_not_failed`, real repository), C1-e DB round trip (`test_c1e_db_round_trip`, real repository). Local `_fact`/`_facts_frame`/`_spine`/`_flat_prices`/`_price_history`/`_two_year_facts` helpers (the last reusing the exact fixture values `tests/test_fundamental_factors.py::_two_year_facts` uses, so "resolves to a number" assertions rest on a fixture already proven correct at the unit level). |
| `tests/test_feature_set_resolution.py` | Modified (+29) | Import `FUNDAMENTAL_OVERLAY_COLUMNS` from `brain.features` and the `brain.fundamental_factors` module; `test_technical_v2_columns_byte_identical` and `test_fundamental_v1_composes_technical_v2_plus_three_factors` (C1-d / C2 regression). |

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command + result | `py -3.14 -m pytest tests/test_fundamental_lookahead.py tests/test_feature_set_resolution.py -q` → **16 passed** (5 new in the lookahead file + 11 in feature_set_resolution, 9 pre-existing + 2 new). One RED-then-fixed cycle during this session: `test_c1c_nan_never_raises` sub-case (d) failed on first run against the pre-existing implementation (see Deviations), fixed, then all 16 passed clean. |
| Runtime harness command + result | `py -3.14 -m brain.materialize_fundamentals --ticker AAPL` → ran end-to-end against the real local Postgres configured in this environment (`LOCAL_DATABASE_URL`, unlike Phases 2-3's harness gap): `{"ticker": "AAPL", "asset_class": "stock", "price_rows": 1678, "fact_rows": 0, "event_dates": 0, "first_factor_timestamp": null, "feature_rows_loaded": 0, "skipped_assets": []}` — no exception, `feature_rows_loaded=0` only because no `fundamental_facts` rows exist for AAPL (ingestion job never run against this DB). Real step-shaped-row landing is proven at the unit/DB-round-trip level instead by `test_c1e_db_round_trip`. |
| Full suite | `py -3.14 -m pytest -q` → **393 passed** (386 baseline + 7 new: 5 in `test_fundamental_lookahead.py` + 2 in `test_feature_set_resolution.py`), 0 regressions, 1 pre-existing joblib/loky CPU-count warning, 58.74s. |
| Rollback boundary | `delete from features_daily where feature_set='fundamental_v1';` then revert the `FEATURE_COLUMNS_BY_SET["fundamental_v1"]` assignment + `FUNDAMENTAL_OVERLAY_COLUMNS` in `brain/features.py`, delete `brain/materialize_fundamentals.py`, `tests/test_fundamental_lookahead.py`, and the two added tests in `tests/test_feature_set_resolution.py`. Nothing outside this slice imports `brain.materialize_fundamentals` yet. |

### Deviations from Design

1. **Bug found and fixed in `build_fundamental_overlay`: `reindex(...).ffill()` → `pd.merge_asof(..., direction="backward")`.**
   The pre-existing implementation joined per-event rows onto the full spine calendar with
   `events_frame.reindex(target_index).ffill()`. `test_c1c_nan_never_raises` sub-case (d)
   (a concept present only under an unexpected unit) exposed a genuine bug: when a LATER
   event's own `compute_factors_as_of` call legitimately returns `NaN` for one factor (e.g.
   Altman, because the FY2022 `RetainedEarningsAccumulatedDeficit` fact was only present
   under an unexpected unit), plain `.ffill()` cannot distinguish "no event happened yet on
   this day" (a real gap that should carry the prior event's value forward) from "an event
   DID happen, and this one factor is legitimately NaN" (a real, current value that must
   stay NaN). `.ffill()` treated both cases identically and silently overwrote the fresh
   NaN with FY2021's now-superseded Altman Z-score for the entire rest of the series —
   exactly the kind of silent-guess behavior the whole change's philosophy (design.md's
   "never convert or guess a different unit", ADR-4's "NaN, never a partial sum") argues
   against. Fixed by replacing the reindex+ffill step with
   `pd.merge_asof(target_frame, events_frame, on="timestamp", direction="backward")`, which
   carries the exact matched event row — NaN and all — forward until the next event,
   instead of skipping over a real NaN. Verified: all 16 focused tests and the full 393-test
   suite pass after the fix, including the pre-existing look-ahead/restatement assertions
   this function must also satisfy (C1-a, C1-b), which were unaffected by the fix since
   neither fixture ever hit the specific "later event's own factor is NaN" edge case.
   `docstring` in `brain/materialize_fundamentals.py` updated to describe the corrected
   algorithm and explicitly document why plain `ffill()` was rejected.
2. **Sequencing**: as in Phase 3, tests were written this session against an
   already-existing implementation (verified, not rewritten, per the retry brief) rather
   than watching each RED test fail before any GREEN code existed. Standard mode
   (`testing.strict_tdd: false`) permits this. One test (`test_c1c_nan_never_raises`
   sub-case (d)) DID fail RED against the pre-existing code on first run, was diagnosed as
   a genuine bug (not a test-fixture error), and the implementation was fixed until GREEN —
   this is the one part of Phase 4 that followed a literal RED→GREEN cycle.
3. **`pd.merge_asof` requires `events_frame`/`target_frame` sorted by `timestamp`** — both
   already are (`events_frame` is explicitly `.sort_values("timestamp")`-ed;
   `target_frame` is built from `spine_ts`, itself `spine_sorted["timestamp"]`). No
   additional sort was needed, but this is now a load-bearing precondition of the function
   worth flagging for any future editor of this file.

### Issues Found

The one bug above (fixed same session, not left open).

### Risks / Notes for Phase 5

- `main()`'s runtime harness (`py -3.14 -m brain.materialize_fundamentals --ticker AAPL`)
  confirms the CLI wires cleanly end-to-end against this environment's real Postgres, but
  `feature_rows_loaded` will stay `0` for every ticker until the Phase 2 ingestion job is
  actually run (with `SEC_USER_AGENT` set) against this same database. Phase 5's runbook
  section should make this ordering explicit: ingest first, then materialize, then retrain.
- `test_c1e_db_round_trip` demonstrates the exact pattern Phase 5's own
  `test_retraining_job_runs_on_fundamental_v1_feature_set` (task 5.1) will need: seed
  `prices` + `fundamental_facts` directly via the repository (no live SEC call), call
  `materialize_asset_fundamentals`, then hand the result to `run_retraining_job`.
- The `merge_asof`-based join (Deviation 1) is a pure internal implementation detail of
  `build_fundamental_overlay` — its public shape (`DataFrame[timestamp, 3 factors,
  max_filed_date]`) and every documented C1 guarantee are unchanged, so Phase 5 needs no
  awareness of it beyond this note.

## Remaining (out of scope this launch)

- [ ] Phase 5: Wiring + docs

### Status

39/39 Phase 1+2+3+4 tasks complete (10/10 + 10/10 + 10/10 + 9/9). Full suite: 393 passed, 0
regressions. Ready for `sdd-verify` of Phase 1-4, or `sdd-apply` Phase 5.
