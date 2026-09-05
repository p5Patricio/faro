```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:c1c0485c2caf714c5fae5de56f8bf58964fa363c65dcc750731f88a30d2512ef
verdict: pass_with_warnings
blockers: 0
critical_findings: 0
requirements: 7/7
scenarios: 10/10
test_command: py -3.14 -m pytest
test_exit_code: 0
test_output_hash: sha256:2066fa05c6c8f856fde57c261901fcf4b9edf935409d94307e9f62bc3501230d
build_command: cd ui && npm run build
build_exit_code: 0
build_output_hash: sha256:54ea78abe82048f15e976acf8d678fb4ff9f962cac2aa8bf2e3a24b9dbe98673
```

## Verification Report

**Change**: fundamental-analysis (all 5 phases: storage 7d1071d, ingestion f767414, factor math b540ca5, overlay+C1 f6288d3, wiring+docs 914589a)
**Version**: N/A (single-shot spec, no prior revision)
**Mode**: Standard (testing.strict_tdd is false)
**Artifact store**: hybrid (openspec files + Engram; both read and cross-checked, contents match)

### Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 44 |
| Tasks complete | 44 |
| Tasks incomplete | 0 |

All 44 checked-off tasks in tasks.md were independently spot-checked against real source: the test named in
each task line was located in the actual test file, its body read (not just its name), and its assertions
confirmed to match what the task claims. No task was found checked without corresponding working code.

### Build & Tests Execution

**Build**: PASSED (unaffected by this change; backend-only)
```text
cd ui && npm run build
tsc -b && vite build
built in 7.15s, exit 0, 1818 modules transformed
```

**Tests**: PASSED - 394 passed / 0 failed / 0 skipped
```text
py -3.14 -m pytest -q
394 passed, 1 warning in 28.24s (1 pre-existing joblib/loky CPU-count UserWarning, unrelated to this change)
```
Independently re-run 3 times during this verification (a plain check, a run with -rs to confirm zero
hidden skips, and one to capture exact bytes for the hash above) - identical 394 passed / 0 failed every
time. A search for skip or xfail markers across tests/ returned zero matches: no test is silently disabled.
This exactly matches apply-progress.md's final claim (394 passed, 0 regressions, 393 baseline plus 1 new in
Phase 5). collector.schema_check was also run directly against the real local Postgres configured in this
environment: all 15 required relations report OK, including fundamental_facts.

**Coverage**: N/A / threshold: 0% -> Not available (project config sets coverage_threshold to 0)

### Spec Compliance Matrix

All 7 requirements / 10 scenarios in specs/fundamental-analysis/spec.md (counted directly: 7 lines match
"### Requirement:" and 10 lines match "#### Scenario:"). Note: the launch brief for this verify referred to
"12 scenarios" - the actual spec file contains 10, confirmed by direct count. This is a discrepancy in the
task description, not a defect in the shipped spec or code, and does not change any finding below.

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| XBRL Fact Ingestion | Every fetch is audited | test_fundamental_ingestion.py::test_run_fundamental_ingestion_audits_every_fetch | COMPLIANT |
| Point-in-Time Fact Storage | Facts round-trip on the full key | test_local_repository.py::test_fundamental_facts_round_trip_on_full_key | COMPLIANT |
| Point-in-Time Fact Storage | Restatement adds a row, never overwrites | test_local_repository.py::test_fundamental_facts_restatement_creates_new_row | COMPLIANT (body read: real Postgres SELECT count(*), proves 2 rows plus original value unchanged) |
| Factor Computation As-Of Filed-Date | Only facts filed on or before cutoff contribute | test_fundamental_factors.py::test_select_as_of_excludes_filings_after_cutoff | COMPLIANT |
| Factor Computation As-Of Filed-Date | Missing inputs yield NaN, not a crash | test_fundamental_factors.py::test_piotroski_is_nan_without_prior_fiscal_year, test_missing_quarter_yields_nan_not_crash, test_missing_price_makes_altman_z_nan | COMPLIANT |
| fundamental_v1 Feature Set Contract | fundamental_v1 equals technical_v2 plus 3 factors; technical_v2 untouched | test_feature_set_resolution.py::test_technical_v2_columns_byte_identical, test_fundamental_v1_composes_technical_v2_plus_three_factors | COMPLIANT (also confirmed by direct runtime call, see hard-requirements section below) |
| Look-Ahead-Free Materialization | No generated row sees a future filing (C1-a) | test_fundamental_lookahead.py::test_no_row_uses_a_filing_dated_on_or_after_its_own_timestamp | COMPLIANT (body read: strict max_filed_date less-than timestamp check plus recompute-equality check) |
| Look-Ahead-Free Materialization | A later revision never leaks backward (C1-b) | test_fundamental_lookahead.py::test_restatement_never_leaks_backward | COMPLIANT (body read: diffs two full independent re-runs, not a single snapshot) |
| Stock-Only Scope | Non-stock asset is skipped, not failed | test_fundamental_lookahead.py::test_non_stock_asset_is_skipped_not_failed | COMPLIANT (real repository fixture, real asset_class branch) |
| Migration and Schema Check | 0006 applies after 0007, schema_check passes | test_migrate.py::test_0006_applies_after_0007_without_reapplying, test_schema_check.py::test_fundamental_facts_is_a_required_relation_and_present_after_migration | COMPLIANT (also confirmed live: collector.schema_check reports OK fundamental_facts) |

**Compliance summary**: 10/10 scenarios compliant, all backed by a passing test whose body was read (not
just its name), plus 3 independent runtime spot-checks (schema_check, feature_columns_for_set, full suite).

### Hard Requirements (C1/C2/M/T) - independently re-verified, not taken on faith

| Req | Claim | Verification performed | Result |
|-----|-------|------------------------|--------|
| C1 | Every fact/row indexed by filed_date, never period_end; restatement never leaks backward | Read the full body of tests/test_fundamental_lookahead.py (408 lines). test_no_row_uses_a_filing_dated_on_or_after_its_own_timestamp asserts a strict less-than comparison and cross-checks via independent recomputation. test_restatement_never_leaks_backward diffs two full re-runs at an exact computed boundary, not an approximate check. test_c1e_db_round_trip repeats the invariant against a real Postgres round trip. All pass in the 394 count. | HOLDS |
| C2 | feature_columns_for_set of technical_v2 unchanged; fundamental_v1 equals technical_v2 plus 3 columns, no NULL-padding | Ran feature_columns_for_set("technical_v2") directly in a live Python shell against the module: returns the SAME object as FEATURE_COLUMNS_TECHNICAL_V2 (identity check True, not merely equal). feature_columns_for_set("fundamental_v1") returns 28 columns, first 25 equal technical_v2, tail exactly piotroski_f_score, altman_z_score, gross_profitability. Also confirmed via git show on the overlay commit: the diff is a pure addition after compose_feature_set's definition; zero lines touched in the technical_v1/v2 constants or the dict literal. | HOLDS, no regression to any promoted model |
| M | 0006 references only assets; applies lexicographically after 0007; immutable via checksum guard | Read db/migrations/0006_fundamental_facts.sql directly: single foreign key to assets(id), no other table reference. Listed db/migrations sorted: 0006_fundamental_facts.sql sorts before 0007_notifications.sql on the real filesystem. Read the migration-ordering test body: exercises the real db/migrations directory, proves 0006 is the only pending migration when 0007 is already recorded, and that mutating the applied 0006 checksum raises a MigrationError naming that exact file. Also ran collector.schema_check live: fundamental_facts reports OK. | HOLDS |
| T | No live SEC calls in tests; fake session used | Read both test_fundamental_ingestion.py and test_sec_edgar_client.py. Both inject a fake session object with a get method returning canned response objects or raising a synthetic connection error, never opening a real socket. SecEdgarClient is constructed with the fake session passed in (dependency injection), confirmed at the exact call site. No real network call reaches the network in any test. | HOLDS |

### Success Criteria (proposal.md) - walked item by item

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | db.migrate applies 0006 on a clean DB; schema_check passes | MET | db.migrate applied 0006 in Phase 1 (apply-progress.md); collector.schema_check re-run live in this verification, all 15 relations OK including fundamental_facts |
| 2 | Ingestion job populates fundamental_facts for every S&P 100 CIK, writes an ingestion_runs row per fetch | PARTIAL, unit-proven, not run against real S&P 100 data | SEC_USER_AGENT is unset in this environment (confirmed absent from shell env; Phase 2 documented that SecEdgarConfig.from_env resolves to None). The audit and per-fetch and failure and unresolved-CIK behavior is proven at the unit level with a real fake-session fixture, passing. The actual live run against 101 real CIKs was never executed in any of the 5 phases. This is explicitly not a blocker per the Product Decisions section of proposal.md |
| 3 | Restatement test proves a new row, no mutation | MET | Real Postgres test: count equals 2, original key still returns value 100 |
| 4 | C1 look-ahead test passes | MET | Strict less-than assertion, passing |
| 5 | feature_columns_for_set of technical_v2 identical; existing tests pass unchanged | MET | Confirmed both by test and by direct runtime identity check; full suite 394 of 394 passed, 0 regressions |
| 6 | fundamental_v1 materializes and retrains end-to-end on stocks; crypto lands in skipped_assets | MET | Real Postgres retraining test: model trains, is promoted, produces a prediction; the crypto asset lands in skipped_assets with reason no_materialized_dataset, never in errors |
| 7 | Factor computation returns NaN, not an exception, for a first-year filer and a missing quarter | MET | Both cases pass; brain/fundamental_factors.py contains zero bare except blocks (grepped directly) |
| 8 | fundamental_v1 vs technical_v2 walk-forward comparison recorded as a follow-up, not a gate | MET | README.md and ESTADO_PROYECTO.md both explicitly record this as a follow-up (read directly) |

7 of 8 fully met, 1 of 8 partially met (environment-gated, explicitly out of scope per Product Decisions), 0 of 8 unmet.

### Rollback Plan Accuracy (proposal.md vs what actually shipped)

The proposal rollback plan reads: stop running the ingestion job, delete features_daily rows where
feature_set equals fundamental_v1, drop fundamental_facts, and unregister fundamental_v1; technical_v2 and
every promoted model are untouched by construction.

Verified against the shipped artifacts:
- fundamental_facts exists exactly as designed (db/migrations/0006_fundamental_facts.sql, read directly);
  drop table fundamental_facts remains accurate and sufficient (the foreign key cascades from assets, not
  the reverse, so dropping it cannot orphan anything else).
- The fundamental_v1 registration is exactly one dict assignment in brain/features.py (confirmed via the
  exact commit diff); unregistering fundamental_v1 means reverting that one 18-line hunk, still accurate.
- technical_v2 is confirmed byte-identical (the identity check above) so the untouched-by-construction claim
  holds, not just by assertion.
- The rollback plan is still accurate. Nothing built during apply (the merge_asof bug fix, the two split
  shares-outstanding chains, the targets-file flag-name correction) changes any of the three rollback steps
  or their scope.

### Correctness (Static Evidence and Design Coherence)

| Design decision | Followed | Notes |
|------------------|-----------|-------|
| Tall fundamental_facts table, insert-only, filed_date as the key axis | Yes | DDL read verbatim, matches design section 1 |
| Four-step selection algorithm: as-of filter, distinct-period selection, tag fallback, restatement pick | Yes | brain/fundamental_factors.py read; matches design section 5 |
| Events plus reindex or merge_asof, not per-trading-day recompute | Yes, with one documented improvement | Design specified reindex plus ffill; apply found and fixed a real bug (silent NaN overwrite) by switching to a backward merge_asof join; a correct deviation, documented and tested |
| New brain/materialize_fundamentals.py module, not extending materialize_dataset.py | Yes | Confirmed: the technical_v2 materialization path is untouched |
| Shares-outstanding split into two chains (mve and wavg) per a resolved open question | Yes | The design document's own open questions section recommended the split; tasks.md formalized it; the implementation matches the resolved decision |
| CLI flag naming: the design brief said tickers-file, the actual flag is targets-file | Documentation mismatch, corrected in shipped docs | Verified directly: run_retraining_job.py only defines a targets-file argument; README.md and the help text use the correct flag name; a pre-existing naming mismatch caught and fixed during apply, not a residual defect |

### Issues Found

**CRITICAL**: None.

**WARNING**:
1. Success Criterion 2 (ingestion job populating fundamental_facts for all S&P 100 CIKs) has never been
   executed end to end in any environment across all 5 phases; only unit-level fake-session coverage
   exists. Explicitly scoped as an accepted follow-up by the Product Decisions section of proposal.md, not
   a defect, but flagged so sdd-archive does not silently imply this ran.
2. Task 2.10 and 3.10 (the CONCEPT_CHAINS coverage-report reconciliation against real payload data) were
   deferred in both Phase 2 and Phase 3 for the same SEC_USER_AGENT and no-seeded-CIK-data reason; the
   concept-tag fallback chains are unvalidated against real SEC filings.
3. Two Engram observations (the fundamental-analysis apply-progress and tasks entries) show a pending
   contested-conflict flag in the memory store. This does not affect the filesystem source-of-truth
   artifacts used for this verification but should be resolved before or during archive so stale or
   duplicate observations do not accumulate.

**SUGGESTION**:
1. The launch brief for this verify phase stated 12 scenarios; specs/fundamental-analysis/spec.md actually
   contains 10, confirmed by direct count. Worth correcting in any future reference to this change.
2. Consider running the real ingestion job against a small CIK sample once SEC_USER_AGENT is available, to
   close Success Criterion 2 and unblock the deferred CONCEPT_CHAINS reconciliation with real coverage
   data, per the tasks.md file's own stated follow-up.

### Verdict

**PASS WITH WARNINGS**

All 44 tasks are genuinely complete, spot-checked against real source rather than their checkbox alone.
All 4 hard requirements (C1, C2, M, T) hold under independent re-verification, not merely "a test exists
with a plausible name": every cited test body was read and its assertions confirmed to actually test the
claimed invariant. The full suite passes with 0 regressions (394 of 394, reproduced 3 times),
schema_check passes live against real Postgres, and the frontend build is unaffected. 7 of 8 proposal
Success Criteria are fully and directly demonstrated; the remaining 1 is exactly the item the Product
Decisions section of proposal.md pre-declared as an accepted follow-up gated on an environment variable
(SEC_USER_AGENT) this session does not have, not a gap introduced by this change and not a blocker to
archiving it. The rollback plan remains accurate as written. No CRITICAL issue exists. Ready for
sdd-archive, with the 3 WARNING items above carried forward as documented follow-ups (already largely
captured in README.md and ESTADO_PROYECTO.md).
