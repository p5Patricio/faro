# Design: Local Postgres Migration

## Technical Approach

Thin psycopg3 repository preserving the existing duck-typed contract (proposal "Approach").
Supabase modules survive until the final slice so every chained PR is independently
revertible and the one-time export script still has a working PostgREST reader
(proposal "Rollback Plan"). Auth disappears entirely; risk profiles become scope-only.

## Architecture Decisions

| # | Decision | Choice | Rejected alternative | Rationale |
|---|---|---|---|---|
| D1 | Repository module location | New `collector/local_repository.py`; delete `collector/supabase_repository.py` only in the final slice | Rewrite `supabase_repository.py` in place | In-place rewrite makes slice 1 an atomic 20-file break (>>400-line budget) and violates "a revert never leaves a half-swapped call site". The export script (D9) also needs `SupabaseRepository` alive until data is copied. |
| D2 | Connection config | `LocalPostgresConfig.from_env()`: `LOCAL_DATABASE_URL` (canonical, single DSN mirroring `SUPABASE_URL`), else compose from `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD`; raise `RuntimeError` if neither | PG* only | A single DSN var keeps `.env` and README one-line; PG* fallback lets `psql`/`pg_dump` in the rollback plan use the same environment. `RuntimeError` preserves `api/main.py`'s existing degraded-mode `except RuntimeError` path. |
| D3 | Error type | `class LocalPostgresError(RuntimeError)`; wrap `psycopg.Error` at the `_cursor()` boundary | Let `psycopg.Error` propagate | ~15 call sites already do `except (RuntimeError, RequestException)`. Subclassing `RuntimeError` collapses them to `except RuntimeError` with zero behavior change. |
| D4 | Connection acquisition | Constructor takes `pool` **or** `connection` (injected) | Pool only | Mirrors today's `session: requests.Session \| None` seam. The `connection` slot is what makes per-test transactional rollback (D12) possible without a second code path. |
| D5 | `numeric` decoding | Register `psycopg.types.numeric.FloatLoader` in the pool `configure=` callback | Cast `::float8` in every SELECT | PostgREST returned JSON floats; psycopg3 returns `Decimal` by default, which would give pandas `object` dtype and silently break arithmetic in `brain/`. One loader fixes all ~12 read methods. This is the highest-value mitigation for the proposal's "raw SQL diverges from PostgREST JSON semantics" risk. |
| D6 | Row pagination | Single query with optional `LIMIT` | Port the `Range`-header pager | The 1000-row page loop existed only to work around PostgREST's response cap. Local Postgres has none. |
| D7 | Table/method rename | `user_risk_profiles` → `risk_profiles`; methods drop `user_` and the `user_id` parameter | Keep names, ignore the column | Signatures must change anyway (no `user_id`), and the "start fresh" decision means zero rows to rename around. A missed call site then fails loudly at import/TypeError instead of silently reading nobody's profile. |
| D8 | Dead tables | Drop `signals`, `risk_limits`, `news_events` | Port for symmetry | Proposal "Decisions"; git history retains the DDL. |
| D9 | Export path | One-shot script reading Supabase over PostgREST, preserving **all** primary keys (including `bigint` identity, via `OVERRIDING SYSTEM VALUE`), then `setval` the sequences | Let identity PKs regenerate | Preserved UUIDs keep every FK valid; preserved bigint PKs make `ON CONFLICT (id) DO NOTHING` a free idempotency/resume primitive. |
| D10 | Artifact storage | Reuse the existing gitignored `models/` directory; `artifact_uri` stays the relative path `brain/promotion.py` already writes | New external artifact root | `promotion.py` and `promote_candidate_from_report.py` already emit `models/<name>.joblib`; only `retraining_job.py` rewrote it to `supabase://`. Removing that rewrite makes the convention uniform with no new concept. |
| D11 | `brain/upload_model_artifact.py` | **Delete** | Repurpose as local-copy / no-op | Its only job was making a local `.joblib` reachable by a *remote* runner. Trainer and inference now share one filesystem, so it would copy a file onto itself and rewrite a URI scheme nothing resolves. `store_model_artifact()` already covers the one legitimate residual (normalizing a stray path into `models/`), and `retraining_job.py` calls it automatically. |
| D12 | DB test isolation | Dedicated `ia_inversiones_test` DB + `BEGIN`/`ROLLBACK` per test via the injected connection (D4) | `TRUNCATE` after each test; testcontainers | Rollback is fastest and leaks no sequence state; testcontainers would add Docker to a Windows-local solo setup for no benefit. |
| D13 | Scheduler shape | `subprocess.run([sys.executable, "-m", mod, *args])`, fixed argv, never `shell=True` | In-process `main()` imports | Matches the workflow's process-per-step isolation, so one crashed job cannot poison the next; argv lists remove all quoting/injection surface on Windows paths. |

## Data Flow

    collector/ brain/ api/  ──┐
                              ├─→ LocalPostgresRepository ─→ ConnectionPool ─→ localhost:5432
    ops/run_local_scheduler ──┘          │
                                         └─→ models/*.joblib (filesystem, gitignored)

    One-time (deleted after use):
    Supabase PostgREST ──→ ops/migrate_supabase_to_local.py ──→ local Postgres

## Repository Method Mapping

`collector/local_repository.py`. All SQL is parameterized (`%s`); rows come back via
`psycopg.rows.dict_row`. `_json_value` / `_timestamp_or_none` / `_json_safe` are copied
verbatim from `supabase_repository.py` (pure, 20 lines; duplicating avoids importing from
a module scheduled for deletion). `jsonb` columns are wrapped in `psycopg.types.json.Jsonb`.

**Upsert semantics.** PostgREST `?on_conflict=a,b` + `Prefer: resolution=merge-duplicates`
updates *every column present in the payload*. Exact equivalent:

```sql
INSERT INTO {table} ({payload_cols}) VALUES ({placeholders})
ON CONFLICT ({conflict_cols}) DO UPDATE SET
  {col} = EXCLUDED.{col}   -- for every payload col NOT in conflict_cols
```

`_upsert_batch(table, rows, conflict_cols)` composes this with `psycopg.sql` and runs
`cursor.executemany`, returning `len(rows)` — preserving today's return semantics
(the current code counts submitted rows, not affected rows).

| # | Method | Signature change | SQL |
|---|---|---|---|
| 1 | `get_assets` | — | `SELECT * FROM assets ORDER BY ticker ASC` |
| 2 | `get_auth_user` | **removed** | — (Supabase Auth) |
| 3 | `get_or_create_asset` | — | `INSERT INTO assets (ticker,name,asset_class) VALUES (%s,%s,%s) ON CONFLICT (ticker) DO UPDATE SET ticker=EXCLUDED.ticker RETURNING id` — single statement replaces today's race-prone SELECT-then-INSERT; the no-op `DO UPDATE` returns the existing id without touching `name`/`asset_class`, matching current behavior |
| 4 | `get_asset_id` | — | `SELECT id FROM assets WHERE ticker=%s`; raises `ValueError("Asset not found: {t}")` (message drops "in Supabase") |
| 5 | `get_asset` | — | `SELECT id,ticker,name,asset_class FROM assets WHERE ticker=%s`; same `ValueError` |
| 6 | `get_prices` | — | `SELECT timestamp,open,high,low,close,volume FROM prices WHERE asset_id=%s ORDER BY timestamp {ASC\|DESC} [LIMIT %s]` → `pd.DataFrame` |
| 7 | `get_features` | — | `... FROM features_daily WHERE asset_id=%s AND feature_set=%s ORDER BY timestamp …` |
| 8 | `get_labels` | — | `... FROM labels_daily WHERE asset_id=%s AND label_method=%s AND horizon=%s ORDER BY timestamp ASC` |
| 9 | `upsert_prices` | — | `_upsert_batch("prices", rows, ("asset_id","timestamp"))` |
| 10 | `upsert_features` | — | `_upsert_batch("features_daily", rows, ("asset_id","timestamp","feature_set"))` |
| 11 | `upsert_labels` | — | `_upsert_batch("labels_daily", rows, ("asset_id","timestamp","label_method","horizon"))` |
| 12 | `create_model_run` | — | `INSERT INTO model_runs (...) VALUES (...) ON CONFLICT (model_name,model_version) DO UPDATE SET model_name=EXCLUDED.model_name RETURNING id` (same no-op-update idiom as #3) |
| 13 | `get_model_run` | — | `SELECT * FROM model_runs WHERE model_name=%s AND model_version=%s`; `ValueError` if empty |
| 14 | `get_model_runs` | — | `SELECT * FROM model_runs [WHERE …] ORDER BY created_at {ASC\|DESC} [LIMIT %s]` |
| 15 | `get_default_risk_profile` | drops `user_id` | `SELECT * FROM risk_profiles WHERE scope_type='default' ORDER BY updated_at DESC LIMIT 1` |
| 16 | `get_scoped_risk_profile` | drops `user_id` | `… WHERE scope_type=%s AND scope_value=%s ORDER BY updated_at DESC LIMIT 1` |
| 17 | `get_risk_profile_for_asset` | drops `user_id` | unchanged composition: ticker → asset_class → default |
| 18 | `upsert_default_risk_profile` | drops `user_id` | delegates to #19 with `scope_type='default'` |
| 19 | `upsert_risk_profile` | drops `user_id` | `INSERT INTO risk_profiles (...) ON CONFLICT (scope_type,scope_value) DO UPDATE SET <all payload cols>, updated_at=now() RETURNING *` |
| 20 | `update_model_run_artifact_uri` | — | `UPDATE model_runs SET artifact_uri=%s WHERE id=%s RETURNING *` |
| 21 | `upsert_predictions` | — | `_upsert_batch("predictions", rows, ("asset_id","model_run_id","timestamp"))` |
| 22 | `get_prediction_feedback` | — | `SELECT * FROM prediction_feedback [WHERE model_name=%s …] [AND actual_label IS NOT NULL] ORDER BY timestamp …` (`only_evaluated` → the `IS NOT NULL` clause, replacing `not.is.null`) |
| 23 | `get_latest_prediction` | — | `… FROM prediction_feedback WHERE asset_id=%s […] ORDER BY timestamp DESC LIMIT 1` |
| 24 | `create_backtest` | — | `INSERT INTO backtests (...) VALUES (...) RETURNING id` |
| 25 | `get_backtests` | — | PostgREST embed `*,model_runs(...)` → `SELECT b.*, CASE WHEN mr.id IS NULL THEN NULL ELSE jsonb_build_object('model_name',mr.model_name,'model_version',mr.model_version,'feature_set',mr.feature_set,'label_method',mr.label_method,'horizon',mr.horizon) END AS model_runs FROM backtests b LEFT JOIN model_runs mr ON mr.id=b.model_run_id …` — reproduces the nested `model_runs` key `api/main.py:719` reads |
| 26 | `insert_backtest_trades` | — | plain batched `INSERT` (no `on_conflict` today) |
| 27 | `create_paper_trading_run` | — | `INSERT INTO paper_trading_runs (...) RETURNING id` |
| 28 | `get_paper_trading_runs` | — | same embed pattern as #25 (`api/main.py:965`) |
| 29 | `insert_paper_trading_events` | — | plain batched `INSERT` |
| 30 | `relation_exists(name)` | **new** | `SELECT to_regclass(%s) IS NOT NULL` — replaces `schema_check.py`'s use of the private `repository._session` HTTP probe |

`headers`, `_get_rows`, `_post_batches` disappear; `_cursor()` and `_upsert_batch()` replace them.

## Schema and Migrations

`db/migrations/`, applied by `db/migrate.py`.

| Source (`supabase/migrations/`) | Disposition | Target |
|---|---|---|
| `20260515183844_initial_schema.sql` | Port, drop `signals` (D8) | `db/migrations/0001_core_market.sql` — `assets`, `prices` |
| `20260705000100_ml_pipeline_tables.sql` | Port as-is, drop `risk_limits` (D8) | `db/migrations/0002_ml_pipeline.sql` — `features_daily`, `labels_daily`, `model_runs`, `predictions`, `prediction_feedback` view, `backtests`, `backtest_trades` |
| `20260707000100_user_risk_profiles.sql` | **Rewrite**: no `user_id`, no `auth.users` FK, no RLS, no `is_default` index-by-user | `db/migrations/0003_risk_profiles.sql` |
| `20260707000200_scoped_user_risk_profiles.sql` | **Folded** into `0003` (scope check constraint + `UNIQUE (scope_type, scope_value)`); no ALTER needed on a fresh database | — |
| `20260707000300_paper_trading_runs.sql` | Port minus the two `enable row level security` lines | `db/migrations/0004_paper_trading.sql` |
| `20260708000100_public_market_rls.sql` | **Drop entirely** — pure RLS + `anon`/`authenticated` grants + the dead `news_events` placeholder; no local equivalent exists | — |

All six source files plus `supabase/` are deleted in the final slice.

**Runner** — `db/migrate.py`, CLI `py -3.14 -m db.migrate [--dsn DSN] [--dry-run]`:
- Ensures `schema_migrations(version text primary key, checksum text, applied_at timestamptz default now())`.
- Takes `pg_advisory_lock(hashtext('ia_inversiones_migrations'))`, scans `db/migrations/*.sql` lexicographically, applies each **pending** file in its own transaction, records `version` + sha256.
- Applied file whose checksum changed → exits non-zero with `migration_checksum_mismatch:<version>` (migrations are immutable; add a new file instead).
- `--dry-run` prints pending versions and exits 1 if any, 0 if none.
- `collector/schema_check.py`: `REQUIRED_ML_RELATIONS` drops `risk_limits`, renames `user_risk_profiles`→`risk_profiles`; `check_relations` calls `repository.relation_exists`; the hint text becomes `Run py -3.14 -m db.migrate`.

## One-Time Data Migration

`ops/migrate_supabase_to_local.py`:

```
py -3.14 -m ops.migrate_supabase_to_local
    [--tables assets,prices,...]   # default: all, in FK order
    [--batch-size 1000]
    [--out reports/supabase_migration.json]
    [--verify-only]
```

- **Source**: `SupabaseConfig.from_env()` + `SupabaseRepository`; a script-local
  `fetch_table(repository, table)` pages with the `Range` header using the public
  `headers` property and `config.url` (no dependency on the private `_get_rows`).
- **Order (FK-safe)**: `assets` → `prices`, `features_daily`, `labels_daily`, `model_runs`
  → `predictions`, `backtests`, `paper_trading_runs` → `backtest_trades`,
  `paper_trading_events`. `prediction_feedback` is a view — derived, never copied.
- **Idempotency / resume**: every insert is `ON CONFLICT (id) DO NOTHING` with the source
  PK preserved (D9); re-running resumes with no duplicates. Per-table checkpoint
  (`rows_copied`, `last_id`) written to the `--out` JSON after each batch.
- **Sequences**: after each identity-PK table,
  `SELECT setval(pg_get_serial_sequence(%s,'id'), coalesce(max(id),0)+1, false)`.
- **Verification**: source count from PostgREST `HEAD ...?select=id` with
  `Prefer: count=exact` (`Content-Range: */N`) vs local `SELECT count(*)`; report
  `{table, source, target, match}` per table, exit 1 on any mismatch. `--verify-only`
  runs just this pass. Satisfies the proposal's row-count success criterion.
- `risk_profiles` is **not** in the table list — "start fresh" per proposal.
- Deleted together with `supabase_repository.py` in the final slice.

## Local Artifact Storage

`brain/artifacts.py` is rewritten around `MODEL_ARTIFACT_ROOT = Path(os.getenv("MODEL_ARTIFACT_DIR", "models"))` (D10):

| Symbol | Action |
|---|---|
| `resolve_model_artifact(artifact_uri, cache_dir=None)` | Keep; drop the `config` parameter and the `supabase://` branch. Resolve as-is → `\`→`/` normalized → relative to `MODEL_ARTIFACT_ROOT`. Unchanged failure: `ValueError(f"artifact_not_found:{uri}")` |
| `store_model_artifact(local_path, object_path=None) -> str` | **New.** No-op returning the relative POSIX path when already under `models/`; otherwise copies in. Replaces `upload_supabase_artifact` |
| `SupabaseArtifactUri`, `is_supabase_artifact_uri`, `parse_supabase_artifact_uri`, `download_supabase_artifact`, `upload_supabase_artifact`, `upload_supabase_artifact_resumable`, `create_resumable_upload_url`, `ensure_artifact_bucket`, `storage_headers`, `storage_object_url`, `resumable_upload_endpoint`, `encode_tus_metadata`, `DEFAULT_MODEL_ARTIFACT_BUCKET`, `TUS_*` | Delete |

Call sites: `brain/retraining_job.py` (`upload_supabase_artifact` → `store_model_artifact`;
`artifact_bucket` field and the `remote_artifact_uri` indirection removed — `artifact_uri`
and `local_artifact_uri` become the same value), `brain/run_retraining_job.py`
(`--artifact-bucket` removed), `brain/inference_job.py` and `brain/predict_from_supabase.py`
(unchanged call, one fewer argument), `brain/README.md` §"Supabase Storage" removed.
`brain/upload_model_artifact.py` deleted (D11).

## api/main.py Changes

| Location | Change |
|---|---|
| imports | `collector.local_repository` instead of `collector.supabase_repository`; drop `from requests import RequestException`; drop `Header`, `Annotated` if unused after auth removal |
| module scope | `_POOL: ConnectionPool` created in a FastAPI `lifespan` (`pool.open()` on startup, `pool.close()` on shutdown) with the `FloatLoader` `configure=` hook (D5) |
| `get_repository()` 46-50 | returns `LocalPostgresRepository(pool=_POOL)`, or `None` when `LocalPostgresConfig.from_env()` raised at startup — degraded/demo path preserved |
| `get_access_token` 57-63 | **delete** |
| `get_optional_user_id` 66-77 | **delete** |
| `get_user_risk_profile` 618-632 | **delete** — the analysis endpoint calls `repository.get_risk_profile_for_asset(ticker=…, asset_class=…)` directly |
| `GET /api/risk-profile` 502-520 | drop the `user_id` dependency; call `get_scoped_risk_profile(scope_type, scope_value)`. Empty table (first run) → `format_risk_profile(None, source="default")` — unchanged response shape |
| `PUT /api/risk-profile` 523-548 | drop the 401 `Autenticacion requerida`; only 503 when the repository is unavailable; call `upsert_risk_profile(payload, scope_type, scope_value)` |
| `/api/health` 91-108 | `checks["supabase"]` → `checks["database"]`; skip reason `supabase_unavailable` → `database_unavailable` |
| ~15 handlers | `except (RuntimeError, RequestException)` → `except RuntimeError` (safe via D3) |

`normalize_risk_profile_scope`, `format_risk_profile`, `risk_policy_from_profile`,
`apply_user_risk_profile_to_prediction` and every demo-fallback helper are unchanged.

## Frontend Changes

- **Delete** `ui/src/lib/supabase.ts`; remove `@supabase/supabase-js` from `ui/package.json` + lockfile.
- `ui/src/App.tsx` removals: import (26); `session` state (274); `accessToken`/`requestConfig` (287-291) and the `requestConfig` argument at every axios call; `activeSession` parameter of `fetchRiskProfile` (407-409); sign-in/sign-up handler (438-447); sign-out handler (461-464); the `!accessToken` guard in the risk-save handler (473); the session-bootstrap effect (524-538); `session` from the risk-profile effect deps (551-558); the `AuthPanel` component and its props (730-760) and render site (601-607); the `session` prop on the risk-profile card (664, 978-990); `disabled={!session || saving}` → `disabled={saving}` (1059). `InfoRow label="Supabase"` (869) → `"Base de datos"` reading `health.checks.database.status`.
- `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` removed from docs and `.env`.
- **Stays functional**: assets, prices, analysis, prediction history, feedback summary, backtests, paper trading, operational alerts, and the risk-profile card — now always editable because the API no longer authenticates.

## CI / Deploy Removal

**`.github/workflows/operational-jobs.yml` — remove.** It exists to run the daily
(`cron: 20 6 * * *` → `JOB_MODE=full`) and weekly (`cron: 40 6 * * 0` → `full_retrain`)
operational cycles on GitHub-hosted `ubuntu-latest` runners, authenticating with the
`SUPABASE_URL`/`SUPABASE_KEY` repository secrets, plus `workflow_dispatch` manual runs and
a closing webhook notification. **Not salvageable**: a hosted runner is an ephemeral remote
VM with no network route to a Postgres bound to `localhost` on the operator's Windows
machine, and the `.joblib` artifacts it needs are gitignored, so it could not load a model
even with database access. Reducing it to `workflow_dispatch`-only would leave a
permanently-failing manual button pinned to secrets that should be deleted from repository
settings. `ops/notify_operational_job.py` and `tests/test_operational_notifications.py`
are **kept** — the notifier reads `reports/*.json` and posts to `OPERATIONAL_WEBHOOK_URL`,
which is transport-agnostic; the local orchestrator invokes it as its final step.

**`render.yaml` — remove.** It is Render.com Infrastructure-as-Code for the production API
web service (`uvicorn api.main:app`, health check `/api/health?include_schema=false`,
`autoDeploy: true`, `APP_ENV=production`, `ALLOW_DEMO_FALLBACK=false`, and `API_CORS_ORIGINS`
/ `SUPABASE_URL` / `SUPABASE_KEY` as `sync: false` dashboard secrets). **Not salvageable**:
it describes a public cloud deployment of an API whose only data source is now a localhost
database — a Render instance would boot, get `None` from `get_repository()`, and serve 503s
or demo data indefinitely. The local-only pivot removes production deploy from scope, so no
rewritten form of the file is meaningful. Recoverable from git history if the pivot reverses.

**`.github/workflows/ci.yml` — untouched.** Lint/test only, zero Supabase coupling; it is
this change's regression gate and must keep passing.

**Replacement — `ops/run_local_scheduler.py`:**

```
py -3.14 -m ops.run_local_scheduler
    --job {market_data|inference|paper_trading|retraining|full|full_retrain}
    [--tickers BTC-USD,AAPL] [--feature-sets technical_v2] [--skip-collection]
    [--model-name ...] [--model-version ...]
    [--models logistic_regression,random_forest,extra_trees]
    [--confidence-thresholds 0.55,0.60,0.65,0.70] [--scopes local,asset_class,global]
    [--no-require-incumbent-improvement] [--min-objective-improvement 0.0]
    [--reports-dir reports] [--no-notify]
```

Mirrors the workflow's `JOB_MODE` branching 1:1 over the **unchanged** job modules.
Step 0 is `collector.schema_check` (replacing "Check Supabase schema"); then
`collector.run_market_data_job`, `brain.run_retraining_job`, `brain.run_inference_job`,
`brain.run_paper_trading_job` per mode; final step `ops.notify_operational_job
--reports-dir reports` unless `--no-notify`. Each step runs via `subprocess.run` with a
fixed argv list (D13) and is considered failed when the exit code is non-zero **or** its
report JSON has `failed > 0` — the same predicate as the workflow's inline `python -c`.
Process exit code is non-zero if any step failed, so Task Scheduler's "Last Run Result"
is meaningful. Console output tees to `logs/local_scheduler_{job}_{YYYYMMDD}.log`
(`logs/` is already gitignored).

**Windows Task Scheduler registration** — `ops/register_local_jobs.ps1`, also documented
verbatim in `README.md`:

```bat
schtasks /Create /TN "IAInversiones\DailyOperationalCycle" /SC DAILY /ST 06:20 /RL LIMITED /F ^
  /TR "cmd /c cd /d C:\Users\Usuario\Documents\plataforma-ia-inversiones && py -3.14 -m ops.run_local_scheduler --job full"

schtasks /Create /TN "IAInversiones\WeeklyRetrainingCycle" /SC WEEKLY /D SUN /ST 06:40 /RL LIMITED /F ^
  /TR "cmd /c cd /d C:\Users\Usuario\Documents\plataforma-ia-inversiones && py -3.14 -m ops.run_local_scheduler --job full_retrain"
```

Verify `schtasks /Query /TN "IAInversiones\DailyOperationalCycle" /V /FO LIST`; smoke-test
`schtasks /Run /TN "..."`; remove `schtasks /Delete /TN "IAInversiones\..." /F`. Times match
the removed crons. `/RL LIMITED` avoids needless elevation; append `/RU "%USERNAME%" /RP *`
(prompts for the password) if the jobs must run while logged off. An importable
`/XML` task definition was rejected: it embeds an absolute path *and* a user SID, is harder
to review in a diff, and offers nothing over two self-documenting one-liners.

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit (no DB) | `db/migrate.py` version ordering + checksum-mismatch guard; `brain/artifacts.py` path resolution | `tmp_path`, pure functions |
| Integration (real DB) | All 30 repository methods, especially upsert conflict targets, `numeric`→`float`, `jsonb` round-trip, and the nested `model_runs` embed | `tests/conftest.py`: session fixture reads `TEST_DATABASE_URL` (default `postgresql://postgres@localhost:5432/ia_inversiones_test`) and runs `db.migrate` once; function fixture opens a connection, `BEGIN`, injects it via `connection=` (D4), `ROLLBACK` after. `pytest.skip` the module when the DSN is unreachable so `ci.yml` still passes |
| API | Endpoint behavior | Existing `FakeRepository` duck-type in `tests/test_api.py` — no DB needed, stays fast |
| E2E | Full offline cycle | Manual: `py -3.14 -m db.migrate`, `py -3.14 -m ops.run_local_scheduler --job full`, `py -3.14 -m collector.schema_check`, `cd ui && npm run build` |

| Test file | Rework |
|---|---|
| `tests/test_supabase_repository.py` | → `tests/test_local_repository.py`. Delete `FakeResponse`/`FakeSession`/`make_repository`; retarget every assertion from "which HTTP params were sent" to "what the database actually holds" |
| `tests/test_schema_check.py` | Delete the HTTP `FakeSession`; exercise `relation_exists` against the test DB (drop a table inside the rolled-back transaction to assert the MISSING branch) |
| `tests/test_model_artifacts.py` | Delete the 4 Storage/TUS tests (`download_…`, `upload_…_creates_bucket`, `…_resumable`, `parse_supabase_artifact_uri`); keep the local-path `resolve_model_artifact` tests; add `store_model_artifact` tests on `tmp_path` |
| `tests/test_api.py` | Delete `test_risk_profile_endpoint_returns_authenticated_profile`, `…_rejects_invalid_token`, `test_risk_profile_update_requires_auth`; rewrite `…_returns_scoped_profile` / `…_persists_authenticated_profile` / `…_persists_ticker_scope` without `Authorization` headers; rename `…_degraded_without_supabase` → `…_without_database` |
| `tests/test_collector_job.py` | `FakeRepository` duck-type unchanged; only import/constructor lines |
| `tests/test_brain_pipeline.py` | `SupabaseConfig` → `LocalPostgresConfig`; `monkeypatch` target `brain.retraining_job.upload_supabase_artifact` → `store_model_artifact` returning `models/model.joblib`; drop the `supabase://` URI assertions (lines 749-773) |

`requirements.txt`: add `psycopg[binary]` and `psycopg-pool`. `requests` stays
(`ops/notify_operational_job.py`, collector providers).

## Threat Matrix

| Boundary | Applicability | Design response | Planned RED tests |
|---|---|---|---|
| Documentation-like paths | **N/A** — no file-classification or execute-by-extension logic; `db/migrations/*.sql` are read and sent to Postgres, never executed as programs | — | — |
| Git repository selection | **N/A** — no `git` invocation anywhere in the change | — | — |
| Commit state | **N/A** — no VCS automation | — | — |
| Push state | **N/A** — no VCS automation | — | — |
| PR commands | **N/A** — no PR automation | — | — |
| **Subprocess composition** (added — `ops/run_local_scheduler.py`, D13) | **Applicable** | Fixed `[sys.executable, "-m", module, *args]` argv list; never `shell=True`, never string interpolation of `--tickers`/`--model-name` values; `cwd` pinned to the repository root; non-zero exit propagated | Ticker/model arguments containing `&`, `"`, spaces, and a trailing `\` are passed through as single argv elements and never split or interpreted |
| **SQL composition** (added) | **Applicable** | All values are `%s` parameters; identifiers only via `psycopg.sql.Identifier`, never f-strings | A ticker containing `'; drop table assets; --` round-trips as literal data and leaves `assets` intact |

## Migration / Rollout

Chained PR slices, in dependency order (each independently revertible; tag
`pre-local-postgres` first; `pg_dump` before each schema slice):
(1) `db/migrations/` + `db/migrate.py` + `collector/local_repository.py` + repository tests
(additive, no call-site change); (2) `ops/migrate_supabase_to_local.py` + verified row
counts; (3) collector + brain call-site swap; (4) `api/main.py` swap + auth removal +
frontend auth removal; (5) `brain/artifacts.py` + `upload_model_artifact.py` deletion;
(6) `operational-jobs.yml` / `render.yaml` removal + `ops/run_local_scheduler.py` + docs +
deletion of `collector/supabase_repository.py`, `supabase/`, and `ops/migrate_supabase_to_local.py`.
`sdd-tasks` owns the final slicing and the 400-line forecast.

## Open Questions

- [ ] `ci.yml` gets no Postgres service, so DB tests **skip** in CI and only run locally.
      Accepted here (exploration says leave `ci.yml` untouched); a follow-up may add a
      `postgres:16` service container.
- [ ] Local database name and role are assumed `ia_inversiones` / `postgres`; confirm
      against the already-installed instance before slice 1.
