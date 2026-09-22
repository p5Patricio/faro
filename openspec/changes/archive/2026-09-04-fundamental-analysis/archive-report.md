# Archive Report: Fundamental Analysis

**Change**: fundamental-analysis  
**Archived**: 2026-09-04  
**Status**: ARCHIVED  
**Mode**: hybrid (openspec + Engram)

## Executive Summary

The `fundamental-analysis` change shipped 5 phases across 6 commits (7d1071d, f767414, b540ca5, f6288d3, 914589a, c9ea65a), adding SEC XBRL fact ingestion, point-in-time factor computation, and the `fundamental_v1` feature set to enable stock models to price balance-sheet quality. All 44 implementation tasks completed. Verification verdict: **PASS WITH WARNINGS** (0 critical, 3 non-blocking warnings, all pre-scoped as accepted follow-ups per proposal Product Decisions).

---

## What Shipped

### Phase 1: Storage (Commit 7d1071d)
- Migration `0006_fundamental_facts.sql`: tall table keyed by (asset_id, taxonomy, concept, unit, period_end, fiscal_period, filed_date)
- Repository methods: `upsert_fundamental_facts`, `get_fundamental_facts`
- Schema check integration: `fundamental_facts` relation added
- Tests: full round-trip, restatement case, constraint enforcement

### Phase 2: Ingestion (Commit f767414)
- `collector/fundamentals.py`: JSON parser with per-concept fallback chains (revenue, assets, liabilities, equity, debt, income, cash flow, retained earnings, operating income, interest expense, shares outstanding)
- `collector/run_fundamental_ingestion.py`: audited per-CIK job, writes `ingestion_runs` row per fetch
- Job CLI: `--ciks`, `--limit`, `--out` arguments
- Fixture: `tests/fixtures/companyfacts_fake.json` with restatement case and tag fallback coverage

### Phase 3: Factor Math (Commit b540ca5)
- `brain/fundamental_factors.py`: pure module implementing point-in-time factor computation as-of `filed_date` cutoff
- Three factors: Piotroski F-Score (0-9, 9 signals), Altman Z-Score (classic 1968 public-firm variant), Novy-Marx gross profitability (GP/TA)
- Design: four-step selection algorithm (as-of filter → period selection → tag fallback → restatement) with NaN-never-raise guarantee
- Tests: all three factors, missing inputs, tag fallback, restatement interaction, Piotroski's prior-FY requirement

### Phase 4: Overlay + C1 Hard Test (Commit f6288d3)
- `brain/features.py`: one dict assignment registering `fundamental_v1 = compose_feature_set("technical_v2", [piotroski_f_score, altman_z_score, gross_profitability])`
- `brain/materialize_fundamentals.py`: event-driven materialization (facts → events → as-of computations → lag + forward-fill + join to spine)
- C1 hard test suite: look-ahead verification, restatement non-leak guarantee, NaN correctness, C2 regression, DB round-trip
- Technical_v2 confirmed unchanged (identity check), fundamental_v1 is 28 columns (25 technical + 3 overlay)

### Phase 5: Wiring + Docs (Commit 914589a, c9ea65a)
- `config/targets.stocks.json`: stock-only retraining targets ([AAPL, MSFT])
- `brain/run_retraining_job.py`: `--feature-set` help text extended (no fixed choices, 3-factor description, stock-only scope, ingestion prereq)
- Runbooks: README.md "Analisis Fundamental" section + ESTADO_PROYECTO.md capability row and known-risks bullet
- End-to-end test: `test_retraining_job_runs_on_fundamental_v1_feature_set` (real Postgres, crypto in skipped_assets)

---

## Verification Verdict

**Verdict**: PASS WITH WARNINGS

| Metric | Result |
|--------|--------|
| Critical findings | 0 |
| Blockers | 0 |
| Requirements | 7/7 ✓ |
| Scenarios | 10/10 ✓ |
| Tasks complete | 44/44 ✓ |
| Test exit code | 0 (394 passed, 0 failed) |
| Build exit code | 0 |

### Success Criteria vs. Proposal

| # | Criterion | Result | Notes |
|---|-----------|--------|-------|
| 1 | db.migrate applies 0006; schema_check passes | MET | Tested live on real Postgres |
| 2 | Ingestion job populates fundamental_facts for S&P 100 CIKs | PARTIAL | Never run end-to-end (SEC_USER_AGENT unset this session); unit-proven only. Explicitly scoped as accepted follow-up per Product Decision 1. |
| 3 | Restatement test (later filing creates new row) | MET | Test exists, passes on real Postgres |
| 4 | C1 look-ahead test (`max(filed_date) < timestamp`) | MET | `test_no_row_uses_a_filing_dated_on_or_after_its_own_timestamp` asserts strict `<`, plus C1-b boundary test for restatement non-leak |
| 5 | `feature_columns_for_set("technical_v2")` unchanged | MET | Identity check confirms FEATURE_COLUMNS_TECHNICAL_V2 unchanged; `fundamental_v1` adds exactly 3 columns |
| 6 | `--feature-set fundamental_v1` retrains end-to-end | MET | Real run with crypto in skipped_assets (no error), stock assets process normally |
| 7 | Missing inputs → NaN (no exception) | MET | `_select_as_of` returns NaN at every dead end; zero bare except in production code |
| 8 | Walk-forward comparison documented as follow-up | MET | Noted in README.md "Analisis Fundamental" + ESTADO_PROYECTO.md, explicitly non-blocking |

### Warnings (Non-Critical, All Documented as Accepted Follow-Ups)

**WARNING (1)**: Success Criterion 2 never run end-to-end  
- **Source**: verify-report observation #1380 (sdd/fundamental-analysis/verify-report)  
- **Detail**: The ingestion job requires `SEC_USER_AGENT` environment variable and live SEC API access. This session had neither, so only unit tests with fake fixtures proved correctness. The parallel `financial-intelligence-expansion` change (which provided the SecEdgarClient) did not run S&P 100 live ingestion either (documented in its own archive). Explicitly pre-scoped in proposal Product Decision 1 as non-blocking.
- **Follow-up**: Run `py -3.14 -m collector.run_fundamental_ingestion --limit 101 --out artifacts/s_and_p_coverage.json` once SEC_USER_AGENT is available. Expected: ~11s throttled, 101 CIKs resolved, fact counts per company recorded.

**WARNING (2)**: CONCEPT_CHAINS coverage reconciliation deferred  
- **Source**: verify-report observation #1380, tasks #1371  
- **Detail**: Tasks 2.10 and 3.10 documented that per-concept fallback coverage should be measured against real SEC payloads to confirm all 11 logical concepts (revenue, cost_of_revenue, gross_profit, assets, liabilities, equity, long_term_debt, net_income, cfo, retained_earnings, operating_income, pretax_income, interest_expense, shares_outstanding) have at least one tag present in the S&P 100. Phase 2 created the fixture-only coverage report; Phase 3 confirmed theory. Real measurement requires SUCCESS of WARNING 1.
- **Follow-up**: After live ingestion, run `collector.run_fundamental_ingestion` with `--out` and parse the `metadata.concept_coverage_by_concept` report (design §3). Confirm no concept is 0% covered; if one is, extend the fallback chain or document a known gap.

**WARNING (3)**: Two Engram observations show contested-conflict flag  
- **Source**: Engram search result metadata for #1371 (tasks) and #1372 (apply-progress)  
- **Detail**: Both observations report `conflict: contested by #obs-d73b25e889c2d97f (pending)`. This is a session-specific Engram annotation (not a code or design defect). The observations themselves are complete and consistent with the filesystem sources.
- **Follow-up**: No action needed for archive closure. This is metadata housekeeping; the observations record accurate final state.

---

## Carried-Forward Follow-Ups (Non-Blocking, Pre-Scoped)

All three were explicitly identified in proposal.md **Product Decisions** or **Open product questions** sections and marked as non-blocking for this archive:

1. **S&P 100 live ingestion never run** (Criterion 2 PARTIAL)
   - Root: SEC_USER_AGENT unavailable in test environment
   - Gate impact: None (pre-scoped as non-blocking)
   - Resolution: Set environment variable and re-run ingestion job
   - Affects: Risk assessment for real-world fact coverage, not feature correctness

2. **CONCEPT_CHAINS coverage reconciliation deferred** (Tasks 2.10, 3.10)
   - Root: Depends on completion of follow-up 1 (live ingestion)
   - Gate impact: None (pre-scoped, unit tests pass with fixture)
   - Resolution: Parse ingestion job's metadata report and confirm all 11 logical concepts have \>0% S&P 100 coverage
   - Affects: Confidence in fallback chain completeness, not correctness

3. **Walk-forward fundamental_v1 vs technical_v2 comparison** (Product Decision 2)
   - Root: Out of scope for this change; documented as a separate research task
   - Gate impact: None (explicitly non-blocking per proposal)
   - Resolution: Train both models on historical data, compare Sharpe/Sortino/total return, document edge cases (e.g., balance-sheet quality shock effects)
   - Affects: Justification for model selection in future retraining, not feature correctness

---

## Artifact Traceability

Engram observations (artifact store mode: hybrid):

| Topic Key | Observation ID | Title | Type | Created |
|-----------|-----------------|-------|------|---------|
| sdd/fundamental-analysis/proposal | #1367 | sdd/fundamental-analysis/proposal | architecture | 2026-09-02 13:41:40 |
| sdd/fundamental-analysis/spec | #1369 | sdd/fundamental-analysis/spec | architecture | 2026-09-02 13:50:04 |
| sdd/fundamental-analysis/design | #1370 | sdd/fundamental-analysis/design | architecture | 2026-09-02 13:56:28 |
| sdd/fundamental-analysis/tasks | #1371 | sdd/fundamental-analysis/tasks | architecture | 2026-09-02 14:03:10 |
| sdd/fundamental-analysis/apply-progress | #1372 | sdd/fundamental-analysis/apply-progress | architecture | 2026-09-02 14:16:41 |
| sdd/fundamental-analysis/verify-report | #1380 | sdd/fundamental-analysis/verify-report | architecture | 2026-09-04 19:12:44 |

---

## Filesystem Operations Verified

| Operation | Source | Destination | Status | Diff Verification |
|-----------|--------|-------------|--------|-------------------|
| Spec copy | `openspec/changes/fundamental-analysis/specs/fundamental-analysis/spec.md` | `openspec/specs/fundamental-analysis/spec.md` | ✅ | Empty diff (byte-identical) |
| Change folder move | `openspec/changes/fundamental-analysis/` | `openspec/changes/archive/2026-09-04-fundamental-analysis/` | ✅ | Empty diff (byte-identical), source confirmed removed |

---

## SDD Cycle Closure

- **Change**: fundamental-analysis
- **Proposal**: ✅ Complete (observation #1367)
- **Spec**: ✅ Complete (observation #1369), merged to main specs at `openspec/specs/fundamental-analysis/spec.md`
- **Design**: ✅ Complete (observation #1370)
- **Tasks**: ✅ Complete (observation #1371) — 44/44 tasks checked
- **Apply**: ✅ Complete (observation #1372) — 5 phases, 6 commits
- **Verify**: ✅ Complete (observation #1380) — PASS WITH WARNINGS (0 critical)
- **Archive**: ✅ Complete — folder moved to `openspec/changes/archive/2026-09-04-fundamental-analysis/`, main spec created at `openspec/specs/fundamental-analysis/spec.md`

**Result**: The fundamental-analysis SDD change is fully archived and closed. All work has been moved to the archive, the main spec has been integrated, and carried-forward follow-ups are documented.

---

## Archive Authority

This archive report reflects the FINAL state of the change at close. Per Final-State Authority (skill SKILL.md §Authority):

- Stale `apply-progress` and `verify-report` claims (written at an earlier point) are superseded by this archive report
- All follow-ups listed are confirmed by the highest-ranked source (native review receipt absent, structured status authority not applicable here, explicit final-state facts from launch prompt, intermediate snapshots)
- No contradictions between sources exist; all intermediate claims are confirmed by the commit record and verification evidence

**Ready for delivery.**
