# Proposal: Local Postgres Migration

## Intent

Supabase is the sole persistence layer (Postgres via PostgREST, Auth, Storage). The project is now local-only with no production deploy, and Postgres is already installed locally. Supabase forces a network round-trip for every read, an auth model with zero real users, and cloud secrets in scheduled jobs that can no longer reach the data. Replace it with local Postgres + local filesystem artifacts, and drop auth entirely (single operator).

## Scope

### In Scope

- `LocalPostgresRepository` (psycopg3 + `psycopg_pool`) replacing `collector/supabase_repository.py`, preserving the same ~30 method contracts.
- Local DDL ported from `supabase/migrations/*.sql` with RLS / `auth.uid()` / `auth.users` stripped, plus a small SQL-file migration runner.
- Local filesystem `.joblib` storage replacing Supabase Storage/TUS in `brain/artifacts.py`.
- Call-site swap across ~20 files in `collector/`, `brain/`, `api/main.py`.
- Auth removal: API auth dependencies and frontend login/session UI; risk profiles scoped by `default` / `asset_class` / `ticker`.
- Explicit removal of `.github/workflows/operational-jobs.yml` and `render.yaml`, plus one local orchestration entrypoint driven by Windows Task Scheduler.
- Test and doc updates (README, PLAN_DESPLIEGUE, PLAN_MEJORAS_PROFESIONALES).

### Out of Scope — deferred follow-ups

| Follow-up | Why separated |
|---|---|
| `dependency-pinning` | Mechanical; likely direct work, not SDD |
| `api-security-hardening` (CORS + rate limiting) | Security review context, independent of persistence |
| `observability-structured-logging` | Cross-cutting; cheaper once call sites settle |
| `test-coverage-api` / `test-coverage-frontend` | pytest vs. Vitest/Playwright share no review context |

Also out of scope: production deploy, ORM adoption, cross-platform scheduling.

## Decisions

- **`signals`, `risk_limits`**: **drop**. Confirmed dead (no repository method or REST call). Porting them would encode contracts that do not exist; git history retains the DDL.
- **`operational-jobs.yml`**: **remove**, not `workflow_dispatch`-only. A hosted runner has no network path to a local database, so a manual trigger would be a permanently failing button holding stale secret references. Local Task Scheduler replaces it.

## Capabilities

### New Capabilities

- `local-persistence`: local Postgres schema, repository contract, and filesystem artifact storage.

### Modified Capabilities

- `professional-operations`: CI/operational requirements must no longer assume Supabase secrets or scheduled cloud jobs.

## Approach

Thin psycopg3 driver preserving the existing duck-typed repository shape. Exploration compared this against SQLAlchemy/Alembic: portability is not a real requirement here, whereas 47 call sites bound to exact method contracts is the dominant constraint. PostgREST `on_conflict` maps to `ON CONFLICT ... DO UPDATE`; pooling replaces the per-request session.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `collector/supabase_repository.py` | Removed | Replaced by `LocalPostgresRepository` |
| `supabase/migrations/*.sql` | Removed | Ported to local migration set |
| `brain/artifacts.py` | Modified | Filesystem instead of Storage/TUS |
| `api/main.py`, `app_config.py` | Modified | Pooling, auth deps removed |
| `ui/src/lib/supabase.ts`, `ui/src/App.tsx` | Removed/Modified | Login and session UI removed |
| `.github/workflows/operational-jobs.yml`, `render.yaml` | Removed | Non-functional locally |
| `tests/` (6 files) | Modified | Retarget to local Postgres |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Raw SQL diverges from PostgREST JSON semantics (NaN, jsonb) | High | Repository tests against real local Postgres before any call-site swap |
| **Review budget**: even narrowed scope is ~3,000-4,000 lines vs. 400 | High | Chained/stacked PRs required at `sdd-tasks` (`ask-on-risk` in effect) — flagged now |
| `paper_trading_*` relied on service-role RLS bypass | Med | Drop RLS fully; never partially port |
| Scheduled jobs silently stop | Med | Removal is explicit; Task Scheduler registration documented |
| Local-only pivot reversed later | Low | Rollback plan below |

## Rollback Plan

- Tag `pre-local-postgres` before slice 1. `supabase_repository.py`, `supabase/migrations/`, `operational-jobs.yml`, and `render.yaml` stay fully recoverable from git history — no history rewrite.
- Each chained PR slice is independently revertible; slices land in dependency order so a revert never leaves a half-swapped call site.
- `pg_dump` the local database before every schema slice; restore via `psql`.
- Do not delete the Supabase project until verify passes. `SUPABASE_URL` / `SUPABASE_KEY` remain valid, so reverting the call-site slices re-points the app at Supabase without new work.
- Artifacts: keep existing `.joblib` files in Supabase Storage until local copies are verified byte-identical.

## Data & Profile Migration Decisions

Resolved with the user after this proposal was drafted:

- **Existing Supabase data**: migrate, do not start empty. Export `assets`, `prices`,
  `features_daily`, `labels_daily`, `model_runs`, `predictions`, `backtests`,
  `backtest_trades`, `paper_trading_runs`, `paper_trading_events` from Supabase (via
  PostgREST, since that is the only access path) and load them into the new local
  schema before cutting the connection. This preserves the prediction/feedback
  history the continuous-learning cycle depends on. Add an explicit one-time export
  script/task; it is in scope for this change, not a follow-up.
  **Superseded 2026-08-25**: the Supabase project turned out to have zero rows
  across every one of these relations (confirmed via the user's own GitHub
  Actions failure output), and the asset universe was being widened to ~100
  stocks requiring fresh ingestion regardless. The export/import script was
  never built; see `specs/local-persistence/spec.md`'s "One-Time Supabase
  Data Migration" REMOVED requirement for the full rationale.
- **Existing `user_risk_profiles` / `scoped_user_risk_profiles` rows**: do not migrate.
  Start fresh — the new scope-only risk-profile table starts empty; the user
  re-enters `default` / `asset_class` / `ticker` preferences once via the existing
  `PUT /api/risk-profile` flow after migration. No collision/collapse logic needed.

## Dependencies

- Local PostgreSQL running and reachable.
- New `psycopg[binary]` + `psycopg_pool` in `requirements.txt`.
- Windows Task Scheduler access for job registration.

## Success Criteria

- [ ] Zero `supabase` references in Python, frontend, and workflow files.
- [ ] `py -3.14 -m pytest` passes against local Postgres.
- [ ] `py -3.14 -m collector.schema_check` passes on the local schema.
- [ ] `cd ui && npm run build` passes with no auth/session code.
- [ ] Collector, brain, and API run end-to-end offline.
- [ ] Scheduled jobs run locally via Task Scheduler.
- [x] N/A — no source data existed to migrate. The Supabase project had zero
      rows across every ML relation (confirmed via the user's own GitHub
      Actions failure output listing every relation MISSING), and the asset
      universe was being widened to ~100 stocks requiring fresh ingestion
      regardless. Row-count parity was replaced by an explicit skip decision
      (see `specs/local-persistence/spec.md`'s "One-Time Supabase Data
      Migration" REMOVED requirement); all migrated tables start empty and
      are repopulated by the collector/brain pipelines.
- [ ] Risk-profile table exists and accepts new scope-only writes; no migrated rows.
