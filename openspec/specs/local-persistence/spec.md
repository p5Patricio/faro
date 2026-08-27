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

### Requirement: Notification Rule and Delivery Log Persistence

The system MUST provide migration `0007_notifications.sql` creating
`notification_rules` (`rule_type`, nullable `asset_id`, `params jsonb`,
`channel`, `is_active`, `cooldown_minutes`) and `notifications` (delivery
log) with a unique constraint on `dedupe_key`. `LocalPostgresRepository`
MUST expose methods to read active rules scoped by `rule_type`/asset and to
insert a delivery record in a way that a duplicate `dedupe_key` insert MUST
NOT create a second row.

#### Scenario: Fresh database seeds four active default rules

- GIVEN an empty local Postgres database
- WHEN the migration runner applies `0007_notifications.sql`
- THEN `notification_rules` contains four rows, one per default trigger,
  each with `is_active = true`

#### Scenario: Duplicate dedupe_key is rejected at the database level

- GIVEN a `notifications` row already exists with a given `dedupe_key`
- WHEN a second insert is attempted with the same `dedupe_key`
- THEN the unique constraint prevents a duplicate row from being created

#### Scenario: Rule reads are scoped by type and asset

- GIVEN `notification_rules` holds rules for multiple `rule_type` values and
  both global (`asset_id IS NULL`) and per-asset rows
- WHEN the repository reads active rules for one `rule_type` and one asset
- THEN only the matching global and asset-specific active rules are returned

### Requirement: Migration Runner Tolerates Non-Contiguous Numbering

The migration runner MUST apply pending `db/migrations/*.sql` files in
lexicographic filename order regardless of numeric gaps, so a
higher-numbered migration applied before a lower-numbered one exists MUST
NOT block that lower-numbered file from applying once it is added, and MUST
NOT be re-applied itself.

#### Scenario: A later-arriving lower-numbered migration still applies

- GIVEN `0007_notifications.sql` has already been applied and
  `0005_shared_ingestion.sql` did not yet exist at that time
- WHEN `0005_shared_ingestion.sql` is later added and the migration runner
  executes
- THEN `0005_shared_ingestion.sql` applies successfully
- AND `0007_notifications.sql` is not re-applied
