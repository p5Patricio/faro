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
