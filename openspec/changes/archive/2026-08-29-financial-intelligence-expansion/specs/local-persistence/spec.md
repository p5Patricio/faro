# Delta for local-persistence

## ADDED Requirements

### Requirement: Shared Ingestion Audit and Asset Identifier Tables

The system MUST provide migration `0005_shared_ingestion.sql`, landing in the additive
migration sequence after `0004_paper_trading.sql`, creating `asset_identifiers` (ticker
to CIK/CUSIP/CoinGecko id mapping) and `ingestion_runs` (source, endpoint, status, row
count, error, timestamped) tables. `LocalPostgresRepository` MUST expose methods to
upsert and read `asset_identifiers` by ticker, and to insert an `ingestion_runs` row for
both a successful and a failed external fetch.

#### Scenario: Fresh database bootstrap includes the new tables

- GIVEN an empty local Postgres database
- WHEN the migration runner applies `0005_shared_ingestion.sql`
- THEN `asset_identifiers` and `ingestion_runs` exist
- AND `collector.schema_check` passes

#### Scenario: Identifier upsert is idempotent

- GIVEN an `asset_identifiers` row already exists for a ticker
- WHEN the repository upserts the same ticker with the same CIK
- THEN no duplicate row is created

#### Scenario: A failed fetch is still persisted

- GIVEN an external fetch attempt that fails
- WHEN the repository records the ingestion run
- THEN the `ingestion_runs` row persists with a failure status and error detail, not
  silently dropped
