# Apply Progress: local-postgres-migration

## Batch 2 — Phases 5-7 (this batch)

### Status: Phases 5-7 complete and verified against a live local Postgres database.

Environment for this batch: `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` were both
exported (`ia_inversiones` / `ia_inversiones_test` on `localhost:5432`), closing the
verification gap Batch 1 flagged below. All DB-touching tests from Batch 1
(`tests/test_local_repository.py`, `tests/test_schema_check.py`) ran for real in this
batch, not skipped.

This batch resumed mid-edit after a prior session-limit interruption during task 6.6.
Phases 5 and most of Phase 6 (6.1-6.5) were already implemented and uncommitted when this
batch started; this batch finished 6.6, verified the whole Phase 5-6 slice, committed it,
then implemented Phase 7 from scratch.

### Phase 5 — Collector/Brain Call-Site Swap

Verified (not re-implemented; was already done): zero `SupabaseRepository`/`SupabaseConfig`
references remain in `collector/*.py` outside `collector/local_repository.py` and
`collector/supabase_repository.py` (which correctly stays alive per ADR D1 until Phase 10).
Every `brain/*.py` job module and `collector/*.py` job module imports
`LocalPostgresRepository`/`LocalPostgresConfig`. `brain/artifacts.py`,
`brain/retraining_job.py`, `brain/run_retraining_job.py`, `brain/upload_model_artifact.py`,
and `tests/test_brain_pipeline.py`'s artifact-path assertions (`SupabaseConfig` at 3 call
sites) correctly still reference Supabase — that is Phase 8 scope (local artifact storage),
confirmed out of bounds for this unit. `tests/test_collector_job.py` has zero Supabase
references.

Also bundled into this phase's diff (present when the batch started, not newly authored
here): `.github/workflows/operational-jobs.yml` had its cron `schedule:` triggers disabled
(kept `workflow_dispatch` for manual runs) with a comment explaining a hosted GitHub runner
has no network route to a local-only Postgres instance, so the daily `collector.schema_check`
step would otherwise fail by design every run until Phase 9/10 land the local scheduler and
delete this file.

### Phase 6 — API Swap + Auth Removal

`api/main.py` (6.1-6.5) was already fully swapped when this batch started: `_POOL` built in
`lifespan` via `psycopg_pool.ConnectionPool(configure=LocalPostgresRepository._configure)`;
`get_repository()` returns `None` on `RuntimeError` (degraded mode preserved);
`get_access_token`/`get_optional_user_id`/`get_user_risk_profile` deleted;
`GET`/`PUT /api/risk-profile` call `get_scoped_risk_profile`/`upsert_risk_profile` directly
with no auth dependency; `/api/health` uses `checks["database"]` and
`checks["schema"]["reason"] == "database_unavailable"`. Verified all of this by reading the
current file rather than re-deriving it.

**Task 6.6 (`tests/test_api.py` rework) — this is what was actually incomplete and is the
core of this batch's work:**

Before this batch: `py -3.14 -m pytest` → 167 passed, 5 failed (all 5 in `tests/test_api.py`,
all auth-shaped: `test_risk_profile_endpoint_returns_scoped_profile`,
`test_risk_profile_update_requires_auth`, `test_risk_profile_update_persists_authenticated_profile`,
`test_risk_profile_update_persists_ticker_scope`, `test_risk_profile_endpoint_rejects_invalid_token`).

Fix applied:
- **Deleted 3 tests**, not 2: `test_risk_profile_update_requires_auth`,
  `test_risk_profile_endpoint_rejects_invalid_token`, **and**
  `test_risk_profile_endpoint_returns_authenticated_profile`. The batch handoff prompt named
  only the first two for deletion, but `design.md` line 270 explicitly lists all three by
  name ("Delete `test_risk_profile_endpoint_returns_authenticated_profile`,
  `…_rejects_invalid_token`, `test_risk_profile_update_requires_auth`"), and the original
  task 6.6 wording says "delete the **3** auth-required tests" — matching design.md's count,
  not the handoff's narrower list. Followed design.md as the authoritative source per the
  apply-phase rule to always follow design decisions. Coverage is not lost: the deleted
  GET-with-existing-profile-at-default-scope case is subsumed by the combination of
  `test_risk_profile_endpoint_returns_default_without_auth` (empty-profile case) and the
  rewritten `test_risk_profile_endpoint_returns_scoped_profile` (existing-profile case, now
  at a non-default scope).
- **Rewrote 3 tests** (kept their names, per design.md): `test_risk_profile_endpoint_returns_scoped_profile`,
  `test_risk_profile_update_persists_authenticated_profile`,
  `test_risk_profile_update_persists_ticker_scope` — dropped the `Authorization` header from
  every request and removed `user_id` from every `FakeRepository` kwargs/return-value
  assertion, matching the already-unauthenticated `FakeRepository.get_scoped_risk_profile`/
  `upsert_risk_profile` signatures (those had already been renamed off `user_id` earlier in
  this same uncommitted diff, ahead of my edit).
- **Renamed**: `test_health_endpoint_reports_degraded_without_supabase` →
  `test_health_endpoint_reports_degraded_without_database` (this rename, and the
  `checks["supabase"]`→`checks["database"]` fixture assertions, were already done before this
  batch started).
- **Added 1 new test**: `test_health_endpoint_schema_check_succeeds_against_real_database`,
  using `tests/conftest.py`'s real-DB `repository` fixture (not `FakeRepository`) to override
  `get_repository` and hit `GET /api/health?include_schema=true` through `TestClient`. This
  closes the interim gap Batch 1 flagged below: it proves `check_relations` now runs against
  a real `LocalPostgresRepository.relation_exists` without `AttributeError`, and that all 10
  `REQUIRED_ML_RELATIONS` are `ok` post-migration.

Net test count for `tests/test_api.py`'s slice: 172 total → 169 (after 3 deletions) → 170
(after 1 addition). This is a **net -2 from the pre-batch 172-test baseline**, not the
"172 passed, 0 failed" figure given in this batch's Definition of Done — that DoD figure
assumed only 2 deletions (matching the handoff prompt's narrower list); following design.md's
explicit 3-deletion list instead makes 170 the correct number. Flagged here rather than
silently reconciled.

After the fix: `py -3.14 -m pytest` → **170 passed, 0 failed** (full suite, DSNs exported,
before the concurrent `telegram-notifications` commits landed more tests on top — see
"Shared workspace" note below). `py -3.14 -m pytest tests/test_api.py` → 30 passed.

Live end-to-end verification: booted `uvicorn api.main:app` and called
`GET /api/health?include_schema=true` against the real migrated `ia_inversiones` database.
Response: `status: "ok"`, `checks.database.status: "ok"`, `checks.schema.status: "ok"`,
`checks.schema.missing: []`, all 10 `REQUIRED_ML_RELATIONS` `true`. No `AttributeError`.

### Phase 7 — Frontend Auth Removal (implemented from scratch this batch)

- Deleted `ui/src/lib/supabase.ts`.
- `ui/src/App.tsx`: removed `session`/`authMode`/`authEmail`/`authPassword`/`authBusy`/
  `authMessage` state, `accessToken`, the `requestConfig` `useMemo`, the `AccountPanel`
  component and its `handleAuthSubmit`/`handleSignOut` handlers, and the
  `supabase.auth.getSession()`/`onAuthStateChange` effect. Every `axios` call
  (`fetchData`'s 8 parallel requests, `persistPaperTrading`'s 2 requests, `fetchRiskProfile`,
  `saveRiskProfile`) dropped its `requestConfig`/per-call `config` argument.
  `fetchRiskProfile` dropped its `activeSession` parameter. `saveRiskProfile` dropped the
  `if (!accessToken) { setRiskStatus('Inicia sesion para guardar.'); return; }` early exit —
  the endpoint has no auth gate per Phase 6, so there is nothing to gate on client-side
  either. `RiskProfilePanel`'s Save button changed from `disabled={!session || saving}` to
  `disabled={saving}` — the profile card is always editable now, satisfying spec's
  "Unauthenticated Risk-Profile Endpoints" requirement end-to-end (backend + frontend).
  `SystemHealthPanel`'s `InfoRow label="Supabase" value={health?.checks.supabase?.status}`
  became `InfoRow label="Base de datos" value={health?.checks.database?.status}`, matching
  the exact key Phase 6 produces in `/api/health`'s JSON (confirmed by reading `api/main.py`,
  not assumed). Also reworded one leftover UI copy string that said "perfil autenticado" to
  "perfil configurado" since there is no more authentication concept in this feature.
  Confirmed via `grep -i "supabase\|session\|accessToken\|requestConfig\|FormEvent"` that zero
  references remain in `App.tsx`.
- `ui/package.json`: removed the `@supabase/supabase-js` dependency line. Ran `npm install`
  in `ui/` (not a hand-edit) — removed 8 packages, `package-lock.json` regenerated.
- `README.md`, `PLAN_DESPLIEGUE.md`: removed `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY`
  from the documented env blocks and the README variable table; reworded the one sentence
  that said the frontend "activates login and profile editing" when those two vars are
  configured, to state plainly that no authentication is required.
  - **Known gap**: `.env.example` also has both `VITE_SUPABASE_*` lines (confirmed via `rg`
    from outside the file). This environment's sandbox denies **all** tool access to
    `.env.example` — Bash, Read, Edit, and Grep were each independently denied with a
    permission error when targeting that exact path. This needs a manual two-line removal
    by whoever has non-sandboxed local file access; it is not a decision to leave it, it is
    a hard tooling block.
  - Deliberately **not** touched: the rest of README's "Perfiles de Riesgo" section still
    shows `curl -H "Authorization: Bearer <access_token>"` examples and still documents
    `SUPABASE_KEY` as a backend var. That is real staleness, but it is explicitly Phase 9.5
    scope ("Update README/PLAN_DESPLIEGUE/PLAN_MEJORAS_PROFESIONALES: local setup ... remove
    SUPABASE_URL/SUPABASE_KEY references") — a full doc rewrite, not this frontend-only
    unit's "remove two VITE_ vars" instruction. Flagged here so Phase 9.5 doesn't miss it.
- Verified: `cd ui && npm run lint` → clean, zero errors/warnings. `cd ui && npm run build`
  → `tsc -b && vite build` succeeds (1799 modules transformed, no type errors).
  **Not verified**: no headless-browser or manual click-through was run in this environment
  (no browser available); "the risk-profile card is always editable" was confirmed by
  reading the rendered JSX (`disabled={saving}` with no session condition), not by clicking
  through a running UI.

### Shared workspace note (read before merging)

Partway through this batch, `git log` showed two new commits
(`58738e1 feat(notifications): add notification rules/log migration and repository methods`,
`3680b59 feat(notifications): add Telegram transport client`) land on this same branch from
what must be a **concurrent session working on the unrelated `telegram-notifications` SDD
change in the same working tree**, on top of this batch's own `7e90841` commit. This was not
this batch's work and was not touched, staged, or committed by this batch — every `git add`
in this batch used explicit file paths (never `git add -A`/`git add .`) specifically to avoid
capturing that concurrent work. It does explain an apparent anomaly: a `pytest -q` run late
in this batch reported 193 passed instead of the expected 170 — the extra 23 are
`tests/test_telegram_notifier.py` and related notification tests from those two unrelated
commits, not anything from this change. Confirmed via `pytest --collect-only` that the extra
tests are all `test_telegram_notifier.py`. This batch's own scope stayed at 170 tests
passing (verified in isolation via `pytest tests/test_api.py` → 30 passed).

### Commits (this batch, on top of the 3 pre-existing Phase 1-3 commits — none of those were
amended or squashed)

4. `feat(api): swap api/main.py and brain/collector call sites to local Postgres` (Phases 5-6,
   including finishing task 6.6)
5. `feat(ui): remove Supabase auth from the frontend` (Phase 7)

(Commits 5-6 from the concurrent `telegram-notifications` session —
`feat(notifications): add notification rules/log migration and repository methods` and
`feat(notifications): add Telegram transport client` — landed on the same branch between
this batch's two commits above; they are unrelated to this change and are not this batch's
work product.)

### Remaining work (not this batch's scope)

Phases 4, 8, 9, 10 are still `[ ]` in `tasks.md`. Phase 4 (one-time Supabase data migration)
was apparently skipped/deferred rather than done before Phase 5 landed — Phase 5's collector
call-site swap does not strictly depend on Phase 4 having run (the repository contract is
identical either way), but the data itself has presumably not been copied from Supabase to
local Postgres yet. That is a real open item for whoever picks up Phase 4, not something
this batch could resolve (it was explicitly out of scope: Phases 5-7 only).

---

# Apply Progress: local-postgres-migration (Batch 1 — Phases 1-3)

## Status: Phases 1-3 implemented. NOT verified against a live database (see "Verification gap" below).

## What was built

### Phase 1 — Schema + Migration Runner
- `db/migrations/0001_core_market.sql` — `assets`, `prices` (drops `signals`).
- `db/migrations/0002_ml_pipeline.sql` — `features_daily`, `labels_daily`, `model_runs`,
  `predictions`, `prediction_feedback` view, `backtests`, `backtest_trades` (drops `risk_limits`).
- `db/migrations/0003_risk_profiles.sql` — new `risk_profiles` table: no `user_id`, no
  `auth.users` FK, no RLS, no `is_default` column (redundant once scope_type='default' is
  the only "default" row and is already unique via `UNIQUE(scope_type, scope_value)`). The
  scope check constraint and unique index from the two source Supabase migrations are
  folded directly in since there are zero rows to migrate around.
- `db/migrations/0004_paper_trading.sql` — `paper_trading_runs`, `paper_trading_events`,
  RLS lines dropped entirely (zero policies existed; RLS only worked via service-role bypass).
- `db/migrate.py` — idempotent SQL-file runner: `schema_migrations` tracking table,
  `pg_advisory_lock(hashtext(...))` for concurrency safety, sha256 checksum-drift guard
  (`migration_checksum_mismatch:<version>`), `--dry-run`, `--dsn` override.
- `tests/test_migrate.py` — 10 pure unit tests (`tmp_path`, no DB): lexicographic ordering,
  pending-migration filtering, checksum-drift detection, DSN resolution precedence.
- `requirements.txt` — added `psycopg[binary]`, `psycopg-pool`.
- `collector/schema_check.py` — rewritten to use `LocalPostgresRepository.relation_exists`
  instead of an HTTP HEAD probe; `REQUIRED_ML_RELATIONS` drops `risk_limits`, renames
  `user_risk_profiles` → `risk_profiles`; missing-relation hint now points to `db.migrate`.

### Phase 2 — `collector/local_repository.py`
All 30 methods from the design's Repository Method Mapping table, implemented with
`psycopg` (parameterized `%s` everywhere; identifiers only via `psycopg.sql.Identifier`).

Key decisions beyond the literal SQL snippets in design.md (flagged since they weren't
spelled out verbatim there):
- **UUID-to-str loader.** Registered a custom `_UUIDStrLoader` for the `uuid` OID
  alongside `FloatLoader`, so `uuid` columns decode to `str` instead of psycopg3's default
  `uuid.UUID` object. This preserves exact type parity with `SupabaseRepository` (which
  returned every id as a JSON string via PostgREST) — required by the "Signature change: —"
  column in the design's method table for every id-returning method, and avoids
  `TypeError: Object of type UUID is not JSON serializable` surprises downstream.
- **FloatLoader/UUID loader registered defensively on every acquired connection**
  (`_configure()`, called inside `_cursor()`), not only via a pool's `configure=` hook.
  Phase 6 (api/main.py) is what will eventually set `configure=` on its `ConnectionPool`;
  until that lands, this repository is correct on its own regardless of how the caller
  built the pool/connection, including the injected-`connection=` test seam.
- Batch writes (`upsert_prices`, `upsert_features`, `upsert_labels`, `upsert_predictions`,
  `insert_backtest_trades`, `insert_paper_trading_events`) keep their `batch_size`
  parameter for signature parity and chunk `executemany` calls accordingly, though Postgres
  has no per-request payload cap the way PostgREST did.
- `get_backtests`/`get_paper_trading_runs` reproduce the PostgREST `model_runs(...)` embed
  via `LEFT JOIN model_runs` + `CASE WHEN mr.id IS NULL THEN NULL ELSE jsonb_build_object(...)
  END AS model_runs`, exactly as specified in design.md.
- `relation_exists` aliases its boolean column `relation_exists` rather than the design's
  literal `exists` example, to sidestep any ambiguity around `EXISTS` as a bare column label.

### Phase 3 — Repository Tests
- `tests/conftest.py` — `test_database_url` (session-scoped: resolves `TEST_DATABASE_URL`,
  probes connectivity, `pytest.skip`s every dependent test if unreachable, then runs
  `db.migrate.apply_migrations` once), `db_connection` (function-scoped, opens a fresh
  connection per test, always `.rollback()`s and closes in a `finally`), `repository`
  (wraps `db_connection` in a `LocalPostgresRepository`).
- `tests/test_local_repository.py` — 32 tests covering every method group: asset CRUD +
  idempotency, price upsert-conflict resolution + `FloatLoader` type check, features/labels
  upsert+read, model-run idempotency + not-found errors, predictions + prediction-feedback
  view + latest-prediction, backtests/paper-trading-runs with the `model_runs` embed
  (both present and `None` cases), backtest-trade/paper-trading-event inserts, the full
  risk-profile scope-fallback chain (ticker → asset_class → default), fresh-table
  zero-rows assertion, and `relation_exists` true/false. Includes the required RED test:
  `test_ticker_with_sql_injection_payload_round_trips_as_literal_data` (a ticker literally
  containing `'; drop table assets; --` round-trips as data; `assets` survives).
- `tests/test_schema_check.py` — rewritten without `FakeSession`; exercises
  `check_relations` against the real test DB, including dropping `features_daily` inside
  the rolled-back transaction to assert the MISSING branch, plus a dead-table/rename
  assertion on `REQUIRED_ML_RELATIONS`.
- `tests/test_supabase_repository.py` is **untouched** (ADR D1: `supabase_repository.py`
  and its tests stay alive together until the Phase 10 deletion unit).

## Verification gap (read before merging)

**I could not run any DB-touching test against a real Postgres instance in this session.**
`.env` in this repo currently contains only `SUPABASE_URL`/`SUPABASE_KEY` — no
`LOCAL_DATABASE_URL`, `TEST_DATABASE_URL`, or `PGPASSWORD` are set there or in the process
environment, and I have no other way to obtain the `postgres` role's password (by design —
it must never be hardcoded). Concretely:
- `py -3.14 -m pytest tests/test_migrate.py` — **actually ran, 10/10 passed** (pure unit
  tests, no DB needed).
- `py -3.14 -m pytest tests/test_local_repository.py tests/test_schema_check.py` — **ran,
  but every DB-touching test SKIPPED** (`TEST_DATABASE_URL unreachable`) rather than
  passing on real data. Only the one pure-Python assertion test in each file executed.
- Full suite: `py -3.14 -m pytest` → **140 passed, 32 skipped, 0 failed** (skips are all
  the new DB tests; the 140 passing include the full pre-existing suite, confirming no
  regression in anything that doesn't touch Postgres).
- I verified SQL correctness indirectly: rendered the composed `_upsert_batch` and
  `upsert_risk_profile` queries via `psycopg.sql.Composed.as_string(None)` outside a
  connection to check the generated SQL text by eye, and confirmed `gen_random_uuid()` is
  a Postgres-13+ built-in (no `pgcrypto` extension needed on Postgres 18.4).

**Action needed from you**: add `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` to your local
`.env` (with the real password), then run:

```
py -3.14 -m pytest tests/test_migrate.py tests/test_local_repository.py tests/test_schema_check.py -v
```

and confirm all 43 tests pass for real. If any DB-touching test fails, the most likely
causes are (in order of likelihood): a jsonb/dict comparison edge case in
`test_upsert_and_get_features`/`test_upsert_and_get_labels` (pandas empty-string vs NaN
handling), or a param-count mismatch in the dynamically-built WHERE clauses in
`get_model_runs`/`get_prediction_feedback`/`get_latest_prediction`.

## Known accepted interim inconsistency (by design, not a bug to fix here)

`collector/schema_check.py` (Phase 1, in scope) now calls `repository.relation_exists(...)`,
which only `LocalPostgresRepository` implements. `api/main.py` (Phase 6, **out of scope**
for this batch per the batch instructions) still constructs a `SupabaseRepository` and
passes it into `check_relations()` from the `/api/health?include_schema=true` code path.
Until Phase 6 lands, hitting that endpoint with schema checks enabled will raise
`AttributeError: 'SupabaseRepository' object has no attribute 'relation_exists'`.

This is not something I introduced by mistake — the task list's own PR-unit breakdown
(Unit 1 = `schema_check.py` swap, Unit 6 = `api/main.py` swap) bundles them into separate,
independently-revertible, **stacked** PRs (`chain_strategy: stacked-to-main`), so this gap
is expected to exist only between PR1 landing and PR6 landing, not in a deployed
production state. `tests/test_api.py`'s existing coverage never exercises
`include_schema=true`, so this doesn't show up as a test failure — it's a real but
intentionally-deferred runtime gap, flagged here for visibility.

## Deviations from a literal reading of design.md

1. Added `_UUIDStrLoader` (uuid → str) alongside the design's explicit `FloatLoader`
   (numeric → float) registration. Design only calls out D5 (FloatLoader) by name, but the
   "Signature change: —" contract for every id-returning method requires the same string
   type PostgREST produced; without this, ids come back as `uuid.UUID` instead of `str`.
2. `relation_exists`'s SQL aliases the boolean column `relation_exists` instead of the
   design snippet's literal `exists`, to avoid any doubt about `EXISTS` as a column label.
3. `risk_profiles` DDL omits the `is_default` column entirely (design says "no `is_default`
   index-by-user", which I read as removing the whole column since it's fully redundant
   once there's no `user_id` to index by — the repository's own SQL never reads or writes
   `is_default`).

Both are additive/clarifying, not contradicting anything explicit in design.md, and don't
change any public method signature.

## Commits

Three commits, one per phase, left local (not pushed) per delivery instructions:
1. `feat(db): add local Postgres schema and migration runner` (Phase 1)
2. `feat(collector): add LocalPostgresRepository` (Phase 2)
3. `test(collector): add LocalPostgresRepository test suite` (Phase 3)
