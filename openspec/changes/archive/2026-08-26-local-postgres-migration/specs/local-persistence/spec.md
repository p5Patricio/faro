# Local Persistence Specification

## Purpose

Local Postgres repository, schema, and filesystem artifact storage replacing
Supabase (Postgres/PostgREST, Auth, Storage) for this single-operator,
local-only deployment. No authentication; risk profiles are scoped only by
`default` / `asset_class` / `ticker`.

## Requirements

### Requirement: Repository Contract Parity

The system MUST provide a `LocalPostgresRepository` exposing the same public
read/write method contracts as the removed `SupabaseRepository` (asset
lookup/creation, price upsert, feature/label upsert, model run/prediction/
backtest persistence, paper-trading run/event persistence, risk-profile
scope reads/writes), so all existing callers require only an
import/constructor swap.

#### Scenario: Asset lookup or creation is idempotent

- GIVEN an asset with a given ticker does not yet exist locally
- WHEN `get_or_create_asset` is called twice with the same ticker
- THEN the first call creates the asset and the second call returns the same asset id
- AND no duplicate row is created

#### Scenario: Price batch upsert resolves conflicts

- GIVEN prices already exist for an asset on a given date
- WHEN `upsert_prices` is called with overlapping and new rows
- THEN existing rows are updated in place and new rows are inserted
- AND the returned row count matches the input batch size

### Requirement: Local Schema and Idempotent Migration Runner

The system MUST provide local Postgres DDL derived from
`supabase/migrations/*.sql` with `auth.uid()`, `auth.users` foreign keys, and
Row Level Security policies removed, applied through a SQL-file migration
runner that tracks applied migrations and is safe to re-run.

#### Scenario: Fresh database bootstrap

- GIVEN an empty local Postgres database
- WHEN the migration runner executes
- THEN all required tables exist
- AND `collector.schema_check` passes

#### Scenario: Repeat runner invocation is a no-op

- GIVEN all migrations have already been applied
- WHEN the migration runner executes again
- THEN no migration re-applies
- AND the schema is unchanged

### Requirement: Dead-Table Exclusion

The local migration set MUST NOT port the `signals` and `risk_limits` tables,
confirmed unused by any repository method or caller.

#### Scenario: Schema check passes without dead tables

- GIVEN the local migration set has been applied
- WHEN `collector.schema_check` runs
- THEN it does not reference `signals` or `risk_limits`

### Requirement: Local Filesystem Artifact Storage

The system MUST persist and retrieve `.joblib` model artifacts on the local
filesystem instead of Supabase Storage/TUS, preserving the existing
artifact-resolution contract: accept a URI or path and return a local `Path`.

#### Scenario: Store a new artifact

- GIVEN a trained model artifact file
- WHEN it is stored via the local artifact storage function
- THEN it is written under the local artifact directory
- AND a resolvable local URI is returned

#### Scenario: Resolve an existing artifact

- GIVEN an artifact was previously stored locally
- WHEN `resolve_model_artifact` is called with its URI
- THEN it returns the local file path without any network call

#### Scenario: Missing artifact raises a clear error

- GIVEN an artifact URI with no corresponding local file
- WHEN it is resolved
- THEN the system raises an error identifying the missing artifact

### Requirement: Scope-Only Risk Profiles Start Empty

The local risk-profile table MUST be scoped only by `default` /
`asset_class` / `ticker`, with no `user_id` column, and MUST start empty.
Existing Supabase `user_risk_profiles` / `scoped_user_risk_profiles` rows
MUST NOT be migrated.

#### Scenario: Fresh install has zero risk-profile rows

- GIVEN the local schema has just been migrated
- WHEN the risk-profile table is queried
- THEN it contains zero rows

### Requirement: Unauthenticated Risk-Profile Endpoints

`GET /api/risk-profile` and `PUT /api/risk-profile` MUST NOT require an
authenticated user. Requests MUST be scoped only by `scope_type`
(`default` / `asset_class` / `ticker`) and `scope_value`.

#### Scenario: Read risk profile without auth

- GIVEN no `user_id` and no auth header
- WHEN `GET /api/risk-profile?scope_type=ticker&scope_value=AAPL` is called
- THEN it returns the profile for that scope, or defaults if none exists

#### Scenario: Write risk profile without auth

- GIVEN no `user_id` and no auth header
- WHEN `PUT /api/risk-profile` is called with a valid scope payload
- THEN it upserts the scoped profile
- AND returns the saved values, no 401 raised

#### Scenario: Invalid scope_type rejected

- GIVEN a payload with `scope_type` outside `default`/`asset_class`/`ticker`
- WHEN either endpoint is called
- THEN the API responds with HTTP 422

## REMOVED Requirements

### Removed Requirement: One-Time Supabase Data Migration

(Reason: The Supabase project had zero rows of ML data at migration time —
the user's own GitHub Actions failure output listed every ML relation
(`features_daily`, `labels_daily`, `model_runs`, `predictions`,
`prediction_feedback`, `backtests`, `backtest_trades`, `paper_trading_runs`,
`paper_trading_events`, `risk_limits`, `user_risk_profiles`) as MISSING.
Separately, the asset universe was being widened to roughly 100 stocks,
which requires fresh ingestion via the existing collector regardless of
whether an export/import path exists. Building a one-time
Supabase-to-local export/import script to move zero rows had no value, so
this requirement is dropped rather than implemented. This decision is
recorded in the project's decision log dated 2026-08-25 (superseding the
earlier `data_migration: migrate_existing` state) and in `tasks.md` Phase 4
(items 4.1-4.4, marked complete with a SKIPPED rationale).)

(Migration: No data migrates. `assets`, `prices`, `features_daily`,
`labels_daily`, `model_runs`, `predictions`, `backtests`,
`backtest_trades`, `paper_trading_runs`, and `paper_trading_events` all
start empty on the local schema; the collector and brain pipelines
re-populate them from scratch against the widened asset universe.
`ops/migrate_supabase_to_local.py` was never created and MUST NOT be
treated as a pending task.)

The system previously MUST have provided a one-time export/import script
that copies `assets`, `prices`, `features_daily`, `labels_daily`,
`model_runs`, `predictions`, `backtests`, `backtest_trades`,
`paper_trading_runs`, and `paper_trading_events` from Supabase (via
PostgREST) into the local schema before the Supabase connection was cut,
and MUST have reported per-table row counts for source and destination.

#### Scenario: Successful migration with row-count parity (removed, never implemented)

- GIVEN the migration script runs against a populated Supabase project
- WHEN it completes
- THEN each migrated table's local row count equals its Supabase row count
- AND the script prints a per-table comparison report

#### Scenario: Row-count mismatch is surfaced, not silenced (removed, never implemented)

- GIVEN a table fails to migrate all rows
- WHEN the script finishes
- THEN it reports the mismatched table and exits non-zero
