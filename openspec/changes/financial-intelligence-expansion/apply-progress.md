# Apply Progress: financial-intelligence-expansion

## Batch 1 — Phase 1: Foundation (Migration + Repository + Schema Check)

**Mode**: Standard (no `strict_tdd` config found; `openspec/config.yaml` not present in
this checkout — proceeded in standard workflow: read spec/design, write code, verify with
real-DB round-trip tests).

### Completed Tasks

- [x] 1.1 `db/migrations/0005_shared_ingestion.sql` — DDL copied verbatim from design.md:
  `asset_identifiers` (unique `(asset_id, id_type)`, non-unique `(id_type, id_value)` lookup
  index) and `ingestion_runs` (append-only, `source`/`endpoint`/`started_at` index, partial
  `status <> 'success'` failure index).
- [x] 1.2 `collector/local_repository.py` — added `# -- Asset identifiers / ingestion audit --`
  section (before `# -- Schema introspection --`) with `upsert_asset_identifiers`,
  `get_asset_identifiers`, `resolve_asset_by_identifier`, `insert_ingestion_run`,
  `get_recent_ingestion_runs` — exact signatures from design.md, `_upsert_batch(...,
  ("asset_id", "id_type"))`, `Jsonb(_json_safe(...))` for jsonb columns.
- [x] 1.3 `collector/schema_check.py` — added `"asset_identifiers"` and `"ingestion_runs"` to
  `REQUIRED_ML_RELATIONS`.
- [x] 1.4 `tests/test_local_repository.py` — 6 new tests: upsert idempotency for
  `asset_identifiers`, `resolve_asset_by_identifier` round-trip + not-found case,
  `insert_ingestion_run` success row, `insert_ingestion_run` failure row with error detail +
  metadata, `get_recent_ingestion_runs` filter-by-source + `started_at desc` ordering.
- [x] 1.5 Migration applied and schema verified against both live databases (see Runtime
  Harness evidence below).

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `db/migrations/0005_shared_ingestion.sql` | Created | `asset_identifiers` + `ingestion_runs` tables, both indexes, verbatim from design.md |
| `collector/local_repository.py` | Modified | Added 5 methods in new `# -- Asset identifiers / ingestion audit --` section |
| `collector/schema_check.py` | Modified | Added `asset_identifiers`, `ingestion_runs` to `REQUIRED_ML_RELATIONS` |
| `tests/test_local_repository.py` | Modified | Added 6 real-DB round-trip tests for the new methods |
| `openspec/changes/financial-intelligence-expansion/tasks.md` | Modified | Marked Phase 1 tasks 1.1-1.5 `[x]` |

### Deviations from Design

None — implementation matches design.md's verbatim DDL and method signatures exactly.

### Issues Found

None.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `py -3.14 -m pytest tests/test_local_repository.py tests/test_schema_check.py -q` → `39 passed` |
| Runtime harness command/scenario and exact result | `py -3.14 -m db.migrate` (with `LOCAL_DATABASE_URL` set to `ia_inversiones`, then to `ia_inversiones_test`) → both `Applied migrations: 0005_shared_ingestion.sql`; `py -3.14 -m collector.schema_check` against both DSNs → all 14 relations `OK`, including `asset_identifiers` and `ingestion_runs` |
| Rollback boundary | Drop `ingestion_runs` then `asset_identifiers`, delete the `0005` row from `schema_migrations` on both databases; revert `local_repository.py` (5 new methods) and `schema_check.py` (2 relation entries); delete the 6 new test functions from `tests/test_local_repository.py` |

### Full Suite Regression

`py -3.14 -m pytest -q` (both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` exported):
- Before this batch: **243 passed**
- After this batch: **249 passed** (243 + 6 new tests, 0 regressions)

### Remaining Tasks

- [ ] Phase 2: S&P 100 Universe Snapshot (task 2.1 already verified by orchestrator;
  2.2-2.9 pending)
- [ ] Phase 3: Bounded Retraining-Target Policy + Global-Scope Cap
- [ ] Phase 4: SEC EDGAR Client (concurrent sibling agent scope)
- [ ] Phase 5: Ingestion Audit Recorder + Identifier Resolution Job
- [ ] Phase 6: Asset-Class Feature-Set Resolution Seam
- [ ] Phase 7: API Endpoint + Rollout Confirmation

### Workload / PR Boundary

- Mode: chained PR slice (`stacked-to-main`)
- Current work unit: PR 1 — `db/migrations/0005_shared_ingestion.sql` + 5
  `LocalPostgresRepository` methods + `collector/schema_check.py` relations
- Boundary: this batch starts from an unmigrated `0005` slot (0004 → 0007 already applied)
  and ends with both live databases migrated, schema-verified, and the new repository
  surface fully tested. No Phase 2-7 files touched.
- Estimated review budget impact: within the ~300-380 estimated line budget for PR 1
  (Medium risk); well under the 400-line threshold.

### Status

5/5 Phase 1 tasks complete. No blockers. Ready for `sdd-apply` to continue with the next
batch (Phase 2 or whichever phase the orchestrator assigns next), or `sdd-verify` if Phase 1
is being verified as its own PR slice before further phases proceed.
