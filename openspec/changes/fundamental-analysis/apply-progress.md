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

## Remaining (out of scope for this launch)

- [ ] Phase 2: Ingestion — parser + audited per-CIK job + coverage report
- [ ] Phase 3: Factor math — `brain/fundamental_factors.py`
- [ ] Phase 4: Overlay + C1 hard test
- [ ] Phase 5: Wiring + docs

### Status

10/10 Phase 1 tasks complete. Ready for `sdd-verify` of Phase 1, or `sdd-apply` Phase 2.
