# Tasks: Local Postgres Migration

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~4,600-5,700 total (additions + deletions) across 10 code units |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → ... → PR 10 (strict dependency order; see units below) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

Units 2 (repository) and 3 (repository tests) stay above budget even after splitting by
concern — they are one duck-typed contract and one test suite mirroring it; fragmenting
by CRUD group would produce non-independently-runnable slices. Recommend `size:exception`
for units 2 and 3 specifically, or reviewer-paced review across two sessions each. Unit 10
is almost entirely deletion of files already reviewed as their replacements landed in
earlier units (low re-review cost despite high line count).

### Suggested Work Units

| # | Goal | PR | Est. lines | Risk | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|---|---|
| 1 | `db/migrations/0001-0004*.sql` + `db/migrate.py` + `tests/test_migrate.py` + `requirements.txt` (psycopg deps) + `collector/schema_check.py` relation rename | PR 1 | ~550 | Medium | `py -3.14 -m pytest tests/test_migrate.py` | `py -3.14 -m db.migrate --dry-run` against confirmed local DB | Delete `db/migrations/`, `db/migrate.py`; revert `schema_check.py`, `requirements.txt` |
| 2 | `collector/local_repository.py` — all 30 methods per design's mapping table | PR 2 | ~600-650 | High | N/A (covered by unit 3) | N/A — additive, unused by callers | Delete `collector/local_repository.py` |
| 3 | `tests/test_local_repository.py` + `tests/conftest.py` (session/`BEGIN`-`ROLLBACK` fixtures) + `tests/test_schema_check.py` rework | PR 3 | ~800-950 | High | `py -3.14 -m pytest tests/test_local_repository.py tests/test_schema_check.py` | Real run against `ia_inversiones_test` DB | Delete the 3 test files; unit 2 stays inert with no callers |
| 4 | `ops/migrate_supabase_to_local.py` (export/import + checkpoint + `setval` + verify) | PR 4 | ~380-450 | Medium | `py -3.14 -m pytest tests/test_migrate_supabase_to_local.py` (new, `tmp_path` + fake PostgREST) | `py -3.14 -m ops.migrate_supabase_to_local --verify-only` against real Supabase project | Delete the script; no other file references it yet |
| 5 | Collector + brain call-site import/constructor swap (config only, not artifacts) | PR 5 | ~250-350 | Low | `py -3.14 -m pytest tests/test_collector_job.py tests/test_brain_pipeline.py -k "not artifact"` | `py -3.14 -m collector.run_market_data_job --tickers AAPL --skip-collection` | Revert imports to `supabase_repository`; `supabase_repository.py` still present |
| 6 | `api/main.py` swap + auth removal + `tests/test_api.py` rework | PR 6 | ~350-470 | Medium | `py -3.14 -m pytest tests/test_api.py` | `uvicorn api.main:app` + `curl /api/health`, `GET/PUT /api/risk-profile` | Revert `api/main.py`; frontend (unit 7) still sends now-ignored auth headers harmlessly |
| 7 | Frontend auth removal: delete `ui/src/lib/supabase.ts`, trim `ui/src/App.tsx`, drop `@supabase/supabase-js` | PR 7 | ~150-220 | Low | `cd ui && npm run lint` | `cd ui && npm run build` + manual click-through | Revert `App.tsx`; backend (unit 6) tolerates either frontend state |
| 8 | `brain/artifacts.py` rewrite + delete `brain/upload_model_artifact.py` + call sites + `tests/test_model_artifacts.py`/`test_brain_pipeline.py` artifact parts | PR 8 | ~450-600 | Medium | `py -3.14 -m pytest tests/test_model_artifacts.py tests/test_brain_pipeline.py -k artifact` | `py -3.14 -m brain.run_retraining_job --models logistic_regression` | Revert `brain/artifacts.py`, restore `upload_model_artifact.py` from git |
| 9 | `ops/run_local_scheduler.py` + `ops/register_local_jobs.ps1` + CI Postgres service in `ci.yml` + docs | PR 9 | ~450-600 | Medium | `py -3.14 -m pytest tests/test_run_local_scheduler.py` (new) | `py -3.14 -m ops.run_local_scheduler --job market_data --tickers AAPL` | Delete `ops/run_local_scheduler.py`, `.ps1`; revert `ci.yml`/docs |
| 10 | Delete `.github/workflows/operational-jobs.yml`, `render.yaml`, `collector/supabase_repository.py`, `supabase/`, `ops/migrate_supabase_to_local.py` | PR 10 | ~2,400 (deletions) | High (size) / Low (novelty) | `py -3.14 -m pytest` (full suite) + `rg supabase` returns nothing | Full offline cycle per design Testing Strategy | Restore any file from git history (tag `pre-local-postgres`) |

## Phase 0: Environment Confirmation (blocking prerequisite)

- [x] 0.1 Confirmed with user 2026-08-25: host localhost, port 5432, database `ia_inversiones` (+ `ia_inversiones_test`), role `postgres`.
- [ ] 0.2 PARTIAL: recorded in state.yaml. `.env.example` still needs LOCAL_DATABASE_URL/TEST_DATABASE_URL added by hand -- harness denies agent tool access to that exact path.
- [x] 0.3 Tagged `pre-local-postgres` on 8d77fc9 (last commit before migration work).

## Phase 1: Schema + Migration Runner (Req: Local Schema and Idempotent Migration Runner; Dead-Table Exclusion)

- [x] 1.1 Add `psycopg[binary]`, `psycopg-pool` to `requirements.txt`.
- [x] 1.2 Port `db/migrations/0001_core_market.sql` (assets, prices; drop `signals`).
- [x] 1.3 Port `db/migrations/0002_ml_pipeline.sql` (drop `risk_limits`).
- [x] 1.4 Write `db/migrations/0003_risk_profiles.sql` (no `user_id`/RLS/`auth.users`; fold scoped-profile constraint).
- [x] 1.5 Port `db/migrations/0004_paper_trading.sql` (drop RLS lines).
- [x] 1.6 Implement `db/migrate.py` (`schema_migrations` table, advisory lock, checksum, `--dry-run`) per design.
- [x] 1.7 `tests/test_migrate.py`: version ordering + `migration_checksum_mismatch` guard (no DB, `tmp_path`).
- [x] 1.8 Update `collector/schema_check.py`: `REQUIRED_ML_RELATIONS` drops `risk_limits`, renames to `risk_profiles`, hint text points to `db.migrate`.

## Phase 2: Repository Implementation (Req: Repository Contract Parity)

- [x] 2.1 Create `collector/local_repository.py`: `LocalPostgresConfig.from_env()` (D2), `LocalPostgresError(RuntimeError)` (D3), pool/connection constructor (D4), `FloatLoader` registration (D5).
- [x] 2.2 Implement `_cursor()`, `_upsert_batch()`, copy `_json_value`/`_timestamp_or_none`/`_json_safe`.
- [x] 2.3 Implement all 30 methods per design's Repository Method Mapping table (asset, price/feature/label, model-run/prediction, backtest/paper-trading, risk-profile scope methods, `relation_exists`).

## Phase 3: Repository Tests (Req: Repository Contract Parity; Scope-Only Risk Profiles Start Empty)

- [x] 3.1 **RED**: write failing test — a ticker containing `'; drop table assets; --` round-trips as literal data and leaves `assets` intact (threat matrix: SQL composition).
- [x] 3.2 `tests/conftest.py`: session fixture applies `db.migrate` against `TEST_DATABASE_URL` (default `ia_inversiones_test`); function fixture opens connection, `BEGIN`/`ROLLBACK`, `pytest.skip` module if DSN unreachable.
- [x] 3.3 `tests/test_local_repository.py`: retarget every `test_supabase_repository.py` assertion to real DB state; cover asset idempotency and price-upsert-conflict scenarios (spec scenarios).
- [x] 3.4 `tests/test_schema_check.py`: drop `FakeSession`; exercise `relation_exists` against test DB, including a dropped-table MISSING-branch case.
- [x] 3.5 Confirm risk-profile table has zero rows after fresh migrate (spec scenario "Fresh install has zero risk-profile rows") — written as `test_fresh_risk_profile_table_is_empty`; not executed against a live DB in this environment (see apply-progress.md).

## Phase 4: One-Time Data Migration (Req: One-Time Supabase Data Migration)

- [x] 4.1 SKIPPED -- Supabase project has no ML data (GitHub Actions confirmed every ML relation MISSING); universe is being widened to ~100 stocks requiring fresh ingestion regardless.
- [x] 4.2 SKIPPED -- see 4.1.
- [x] 4.3 SKIPPED -- see 4.1.
- [x] 4.4 SKIPPED -- see 4.1. Data comes from fresh yfinance ingestion via the existing collector instead.

## Phase 5: Collector/Brain Call-Site Swap (Req: Repository Contract Parity)

- [x] 5.1 Swap `collector.local_repository` import/constructor across `collector/` job modules.
- [x] 5.2 Swap in `brain/` job modules (config only — artifact calls stay untouched until Phase 8).
- [x] 5.3 Update `tests/test_collector_job.py` and `tests/test_brain_pipeline.py` imports/constructors (non-artifact assertions).

## Phase 6: API Swap + Auth Removal (Req: Unauthenticated Risk-Profile Endpoints)

- [x] 6.1 `api/main.py`: swap import; create `_POOL` in `lifespan` with `FloatLoader` `configure=`; `get_repository()` uses pool, `None` on `RuntimeError` (degraded mode preserved).
- [x] 6.2 Delete `get_access_token`, `get_optional_user_id`, `get_user_risk_profile`; `except (RuntimeError, RequestException)` → `except RuntimeError` (~15 sites, safe per D3).
- [x] 6.3 `GET /api/risk-profile`: drop `user_id` dependency, call `get_scoped_risk_profile`.
- [x] 6.4 `PUT /api/risk-profile`: drop 401 path, call `upsert_risk_profile`; keep 503-when-unavailable and 422-on-invalid-`scope_type`.
- [x] 6.5 `/api/health`: rename `checks["supabase"]` → `checks["database"]`.
- [x] 6.6 `tests/test_api.py`: delete the 3 auth-required tests, rewrite the 3 scope tests without `Authorization` headers, rename `..._degraded_without_supabase` → `..._without_database`.

## Phase 7: Frontend Auth Removal (Req: Unauthenticated Risk-Profile Endpoints)

- [x] 7.1 Delete `ui/src/lib/supabase.ts`; remove `@supabase/supabase-js` from `ui/package.json` + lockfile.
- [x] 7.2 `ui/src/App.tsx`: remove session state, `AuthPanel`, sign-in/out handlers, `requestConfig`/`accessToken` threading per design's Frontend Changes line list; `InfoRow label="Supabase"` → `"Base de datos"` reading `health.checks.database.status`.
- [x] 7.3 Remove `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` from `.env` and docs. (README.md, PLAN_DESPLIEGUE.md done; `.env.example` still has both lines — sandboxed from all tool access (Bash/Read/Edit/Grep all denied) in this environment, needs a manual one-line-removal x2 by a human with local file access.)
- [x] 7.4 `cd ui && npm run build` passes; manually verify risk-profile card is always editable. (`npm run lint` and `npm run build` both pass; the Save button in `RiskProfilePanel` no longer has a `disabled={!session}` gate, so the card is always editable — confirmed by reading the rendered JSX, not a live browser click-through.)

## Phase 8: Local Artifact Storage (Req: Local Filesystem Artifact Storage)

- [x] 8.1 Rewrite `brain/artifacts.py`: `MODEL_ARTIFACT_ROOT`, keep `resolve_model_artifact` (drop `config` param + `supabase://` branch), add `store_model_artifact(local_path, object_path=None)`.
- [x] 8.2 Delete Storage/TUS symbols (`SupabaseArtifactUri`, `upload_supabase_artifact*`, `create_resumable_upload_url`, etc.) and `brain/upload_model_artifact.py`.
- [x] 8.3 Update call sites: `brain/retraining_job.py` (drop `artifact_bucket`/`remote_artifact_uri`), `brain/run_retraining_job.py` (drop `--artifact-bucket`), `brain/inference_job.py`, `brain/predict_from_supabase.py`. Also dropped the now-fully-unused `supabase_config` parameter from `run_retraining_job()` entirely (both call sites already flagged this in a pre-existing code comment); `inference_job.py`/`predict_from_supabase.py` needed zero changes since neither ever passed the now-removed `config` kwarg to `resolve_model_artifact`.
- [x] 8.4 `tests/test_model_artifacts.py`: delete the 4 Storage/TUS tests, add `store_model_artifact` tests on `tmp_path`.
- [x] 8.5 `tests/test_brain_pipeline.py`: retarget monkeypatch to `store_model_artifact`, drop `supabase://` URI assertions.
- [x] 8.6 Trim `brain/README.md` "Supabase Storage" section.

## Phase 9: Local Scheduler + CI (Req: Local Scheduled Operations Replace Hosted Automation; Pull Request Quality Gates)

- [x] 9.1 **RED**: write failing test — ticker/model args containing `&`, `"`, spaces, trailing `\` pass through the scheduler's argv builder as single, unsplit elements (threat matrix: subprocess composition).
- [x] 9.2 `ops/run_local_scheduler.py`: `--job` branching mirroring the removed workflow's `JOB_MODE`, fixed `[sys.executable, "-m", module, *args]` per step (D13), fail on non-zero exit or `failed > 0` in report JSON, tee to `logs/local_scheduler_{job}_{date}.log`.
- [x] 9.3 `ops/register_local_jobs.ps1` + README section with the two `schtasks /Create` commands (daily 06:20, weekly Sun 06:40).
- [x] 9.4 Add `postgres:16` service container to `.github/workflows/ci.yml`, set `TEST_DATABASE_URL`, run `db.migrate` before `pytest` — closes the gap between design's deferred Open Question and the `professional-operations` spec's MUST-provision-Postgres-in-CI requirement (flagged as a conflict; see Risks).
- [x] 9.5 Update README/PLAN_DESPLIEGUE/PLAN_MEJORAS_PROFESIONALES: local setup, Task Scheduler registration, remove `SUPABASE_URL`/`SUPABASE_KEY` references.

## Phase 10: Final Removal (Req: Local Scheduled Operations Replace Hosted Automation)

- [x] 10.1 Delete `.github/workflows/operational-jobs.yml`.
- [x] 10.2 Delete `render.yaml`.
- [x] 10.3 Delete `collector/supabase_repository.py`.
- [x] 10.4 Delete `supabase/` (migrations + `config.toml`).
- [x] 10.5 SKIPPED (no-op) -- `ops/migrate_supabase_to_local.py` and its test were never created (Phase 4 was skipped per 4.1-4.4; confirmed genuinely absent via directory listing, not assumed). Also deleted `tests/test_supabase_repository.py` as part of this unit (design.md line 267: superseded by `tests/test_local_repository.py`; dead weight once `collector/supabase_repository.py` is gone).
- [x] 10.6 `rg -i supabase` across `.py`/`.ts`/`.tsx`/`.yml` (excluding `openspec/changes/**`) returns nothing (proposal success criterion). Beyond the 10.1-10.5 deletions, this required renaming `brain/evaluate_candidate_matrix_from_supabase.py` -> `brain/evaluate_candidate_matrix.py` and `brain/candidate_matrix.load_candidate_datasets_from_supabase` -> `load_candidate_datasets` (pure naming leftovers pre-dating the Phase 5 call-site swap; the functions/module already used `LocalPostgresRepository` with zero Supabase/PostgREST calls), updating all call sites (`brain/promotion.py`, `brain/retraining_job.py`, `brain/run_retraining_job.py`, `tests/test_brain_pipeline.py`, `brain/README.md`), and rewording two docstrings in `collector/local_repository.py` that referenced `SupabaseRepository` by name.
- [x] 10.7 Full offline run: `py -3.14 -m db.migrate`, `py -3.14 -m ops.run_local_scheduler --job market_data --tickers BTC-USD`, `py -3.14 -m collector.schema_check`, `cd ui && npm run build`, `py -3.14 -m pytest` -- all five passed for real; see apply-progress.md Batch 5 for full output.
