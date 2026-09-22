# Delta for Local Persistence

## ADDED Requirements

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
