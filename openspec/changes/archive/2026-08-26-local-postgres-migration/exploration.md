# Exploration: Local Postgres Migration (remove Supabase, local-only pivot)

Date: 2026-08-10

## Trigger

The project will not go to production for now; everything stays local. PostgreSQL is
already installed locally. Supabase (currently the only persistence layer, plus Auth
and Storage) must be fully removed and replaced with a local Postgres database. Five
previously-agreed hardening areas (dependency pinning, CORS, rate limiting, API/frontend
test coverage, structured logging) are folded into the same effort at the user's request.

Decision already made: no users/login. Supabase Auth is removed entirely; risk profiles
are scoped only by `default` / `asset_class` / `ticker` (no `user_id`, no users table).

## Current State

**Persistence surface** — confirmed via CodeGraph blast-radius + grep: 37 files touch
Supabase. `collector/supabase_repository.py` (796 lines) is the entire persistence layer
(`SupabaseConfig.from_env()` reads `SUPABASE_URL`/`SUPABASE_KEY`; `SupabaseRepository`
wraps `requests.Session` against PostgREST `{url}/rest/v1/*`, plus `get_auth_user`
against `{url}/auth/v1/user`). `brain/artifacts.py` separately hits Supabase Storage
(including TUS resumable upload) for `.joblib` artifacts.

`SupabaseRepository` has 47 callers, `SupabaseConfig` has 32 callers, spanning
`collector/` (main.py, schema_check.py, load_history_to_supabase.py,
run_market_data_job.py, market_data_job.py), 20 files in `brain/`, `api/main.py`, the
frontend (`ui/src/lib/supabase.ts`, `ui/src/App.tsx` — 23 supabase/session/login
references), 5 test files, and docs/CI (README.md, PLAN_DESPLIEGUE.md, render.yaml,
`.github/workflows/operational-jobs.yml`). Every one of the 47 callers treats
`SupabaseRepository` as duck-typed — constructed fresh via
`SupabaseRepository(SupabaseConfig.from_env())` at each entrypoint, with no dependence
on Supabase-specific behavior beyond the ~30 method contracts. This drives the
recommendation below.

`api/main.py get_repository()` (lines 46-50) builds a new `SupabaseRepository` +
`requests.Session` per request — no pooling. Auth plumbing: `get_access_token` (57-63),
`get_optional_user_id` (66-77), `GET/PUT /api/risk-profile` (502-548),
`get_user_risk_profile` (618-632) — all gated on Supabase Auth `user_id`. Frontend has
full login/logout/session UI in `App.tsx`.

CORS: `app_config.py` defaults `cors_origins=("*",)`; `api/main.py` sets
`allow_origins=list(cors_origins)` + `allow_credentials=True` — spec-invalid combo.
No `.env.example` file exists; vars documented inline in README. Rate limiting: none.
Every GET endpoint wraps repository calls in bare `except (RuntimeError, RequestException)`
→ silent demo fallback; zero `logging` usage in `api/main.py`. `requirements.txt`
(12 lines) is fully unpinned, no psycopg/sqlalchemy present.

**Schema** (`supabase/migrations/*.sql`, 6 files) — RLS/auth footprint is narrow:

1. `20260515183844_initial_schema.sql` — `assets`, `prices`, `signals` (`signals`
   confirmed dead — no repository method or REST call ever touches it).
2. `20260705000100_ml_pipeline_tables.sql` — `features_daily`, `labels_daily`,
   `model_runs`, `predictions`, `prediction_feedback` (view), `backtests`,
   `backtest_trades`, `risk_limits` (also confirmed unused — `RiskPolicy` applied
   in-process only, never persisted). Pure DDL, portable as-is.
3. `20260707000100_user_risk_profiles.sql` — `user_id uuid references auth.users(id)`
   + 3 RLS policies using `auth.uid()`. **The only hard dependency on
   `auth.users`/`auth.uid()` in the whole schema.**
4. `20260707000200_scoped_user_risk_profiles.sql` — adds `scope_type`/`scope_value` +
   constraint. Pure DDL, portable.
5. `20260707000300_paper_trading_runs.sql` — `paper_trading_runs`,
   `paper_trading_events` + `enable row level security` with no explicit policies
   (only ever reachable via Supabase's service-role RLS bypass).
6. `20260708000100_public_market_rls.sql` — dynamic PL/pgSQL granting
   anon/authenticated read policies, including a `news_events` table guarded by
   `to_regclass(...) is not null` that was never actually created (dead placeholder).

Net: migrations 1, 2, 4, 5 (minus their `enable row level security` lines) are directly
portable local Postgres DDL. Only migration 3's `auth.users` FK/policies and migration
6's anon/authenticated policies are Supabase-specific and must be stripped given the
no-auth decision.

**operational-jobs.yml** runs on `ubuntu-latest` GitHub-hosted runners via
`SUPABASE_URL`/`SUPABASE_KEY` secrets — confirmed this becomes fundamentally
non-functional (no network path to a local machine), not just a config problem.
`.github/workflows/ci.yml` is separate and NOT Supabase-coupled — leave untouched.
Also found: `render.yaml` (production deploy config, also references
`SUPABASE_URL`/`KEY`) is likewise now obsolete under the local-only pivot.
`PLAN_MEJORAS_PROFESIONALES.md` explicitly assumed "mantener Supabase" and is now stale.

## Affected Areas

- `collector/supabase_repository.py` — entire persistence layer to replace.
- `api/main.py` — `get_repository()`, auth dependencies (57-77, 502-548, 618-632), CORS.
- `app_config.py` — `cors_origins` default.
- `brain/artifacts.py`, `brain/upload_model_artifact.py`, + 18 other `brain/*.py`
  scripts — Storage logic + call sites.
- `collector/main.py`, `collector/schema_check.py`, `collector/load_history_to_supabase.py`,
  `collector/run_market_data_job.py`.
- `supabase/migrations/*.sql` (6 files) → new local Postgres migration set.
- `tests/test_supabase_repository.py`, `test_collector_job.py`, `test_schema_check.py`,
  `test_model_artifacts.py`, `test_brain_pipeline.py`, `test_api.py`.
- `requirements.txt` — new psycopg dependency + full pinning.
- `ui/src/lib/supabase.ts`, `ui/src/App.tsx`, `ui/package.json` — remove Supabase Auth
  client/login UI.
- `.github/workflows/operational-jobs.yml`, `render.yaml`, `README.md`, `PLAN_DESPLIEGUE.md`.

## Approaches Considered

### Persistence driver

1. **psycopg3 thin driver, same repository shape (recommended)** — new
   `LocalPostgresRepository` with identical public method signatures,
   `psycopg_pool.ConnectionPool`.
   - Pros: minimal call-site churn (all 47 callers are duck-typed, only ~20 files
     change import+constructor); natural translation of existing
     `on_conflict`/`Prefer: resolution=merge-duplicates` to `ON CONFLICT ... DO UPDATE`;
     pooling directly fixes the flagged per-request-session issue; tests can run
     against a real local Postgres.
   - Cons: manual parameterized SQL discipline required; no ORM migration tooling
     (mitigated with a small SQL-file runner).
2. **SQLAlchemy Core/ORM** — tables as SQLAlchemy models, Alembic migrations.
   - Pros: built-in pooling, Alembic tooling, engine portability.
   - Cons: heavier dependency, session-lifecycle indirection, higher risk of
     behavioral drift vs. the exact contract 47 call sites depend on; portability is
     not a real requirement for a solo local tool.

**Recommendation**: option 1. The dominant constraint is the 47 existing call sites
depending on exact method contracts, not database portability. Pair with
`psycopg_pool` and a lightweight SQL-file migration runner (reusing the
`supabase/migrations`-style convention) rather than Alembic.

### operational-jobs.yml replacement

1. **Windows Task Scheduler + one new thin orchestration entrypoint (recommended)**
   wrapping existing unchanged CLI scripts, mirroring the current `JOB_MODE` branching.
   - Pros: OS-native, no new always-running process, matches the user's Windows
     environment, smallest new-code surface.
   - Cons: Windows-only, manual one-time registration, no built-in retry (pairs
     naturally with the structured-logging hardening item).
2. **Persistent local scheduler process** (APScheduler/`schedule`).
   - Pros: cross-platform, testable.
   - Cons: still needs an OS mechanism to survive reboot — doesn't remove the
     OS-scheduler dependency, just relocates it; extra failure mode.

**Recommendation**: option 1. The workflow file must NOT be silently deleted — convert
to `workflow_dispatch`-only (drop `schedule:` + secret checks) or remove it outright,
but this must be a visible, explicit decision in the proposal.

### Scope boundary

Line-count reality check (400-line review budget, ask-on-risk delivery):
`supabase_repository.py` deletion + new repository (~1,500 lines) + `brain/artifacts.py`
rewrite (~300) + ~20 call-site updates (~150) + `api/main.py` auth removal/pooling
(~150) + test rework (~500) + new migrations (~200) + frontend auth-UI removal (~200)
+ operational-jobs.yml/docs cleanup (~200) ≈ **3,000-4,000+ changed lines for the
persistence migration alone** — 7-10x the budget, before any of the 5 hardening areas.

**Recommendation**: split into separate SDD changes. Scope `local-postgres-migration`
to persistence-only work plus the two items causally forced by removing Supabase
(local artifact storage, auth/risk-profile scope simplification) and minimal
operational-jobs.yml consequence handling. Even this narrowed scope needs a chained
delivery plan at `sdd-tasks`, e.g.: (1) schema+repository+repository tests,
(2) collector+brain call-site swap, (3) api/main.py swap + auth removal,
(4) local artifact storage, (5) operational-jobs.yml+docs. The 5 hardening areas
become 3-4 follow-up changes: `dependency-pinning` (likely mechanical direct work,
outside SDD), `api-security-hardening` (CORS + rate limiting),
`observability-structured-logging`, and `test-coverage-api` / `test-coverage-frontend`
(split — pytest vs. Vitest/Playwright share no review context).

## Risks

- Repository rewrite risk: PostgREST JSON semantics (NaN, jsonb) vs. raw SQL row
  mapping could silently diverge — mitigate with repository-level tests against real
  local Postgres before touching call sites.
- `paper_trading_runs`/`paper_trading_events` RLS-enabled-with-no-policies only worked
  via Supabase's service-role bypass — local Postgres has no equivalent, RLS must be
  fully dropped, not partially ported.
- operational-jobs.yml is silently broken by this migration if not explicitly
  addressed in the proposal.
- Review-budget risk is HIGH even for the narrowed scope — requires an explicit
  chained-PR plan; this is multi-PR, not single-PR.
- `render.yaml` and `PLAN_MEJORAS_PROFESIONALES.md` are now stale.
- `signals` and `risk_limits` tables are confirmed dead — proposal should decide
  carry-forward vs. drop.

## Ready for Proposal

Yes.
