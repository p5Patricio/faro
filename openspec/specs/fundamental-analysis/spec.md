# Fundamental Analysis Specification

## Purpose

SEC XBRL fact ingestion, point-in-time storage keyed by the SEC `filed` date, factor
computation as-of a `filed_date` cutoff, and the opt-in `fundamental_v1` feature set —
added so stock models can price balance-sheet quality without altering the `technical_v2`
spine or any promoted model.

## Requirements

### Requirement: XBRL Fact Ingestion

The system MUST fetch SEC `companyfacts` for every resolved CIK in the tracked stock
universe and MUST write one `ingestion_runs` row per fetch, whether it succeeds or fails.
A stock whose CIK cannot be resolved MUST be recorded as unresolved in the run summary,
never silently skipped.

#### Scenario: Every fetch is audited

- GIVEN a stock with a resolved CIK, another whose request fails (403/429/5xx/network), and a third with no CIK entry
- WHEN the ingestion job runs
- THEN the first writes a `success` `ingestion_runs` row with a fact count, the second writes a `failure` row with the error detail, the third is listed as unresolved, and each persisted fact keeps `period_end` and `filed` as distinct values

### Requirement: Point-in-Time Fact Storage

`fundamental_facts` MUST hold exactly one row per
`(asset_id, taxonomy, concept, unit, period_end, fiscal_period, filed_date)`, each with
its value and accession, storing `period_end` and `filed_date` as distinct,
independently queryable columns. A restatement — a later filing revising a value for an
earlier `period_end` — MUST be inserted as a new row keyed by the new `filed_date` and
MUST NOT mutate or delete the earlier row.

#### Scenario: Facts round-trip on the full key

- GIVEN a `companyfacts` payload with many concepts and periods
- WHEN it is persisted, ingested again, and read back
- THEN each key tuple is exactly one row and the repeat ingest creates no duplicates

#### Scenario: Restatement adds a row, never overwrites

- GIVEN a fact for `period_end = 2022-12-31` filed `2023-02-15` is stored
- WHEN a filing dated `2023-11-01` revises that `period_end`'s value
- THEN a new row with `filed_date = 2023-11-01` is inserted and the `2023-02-15` row is unchanged

### Requirement: Factor Computation As-Of Filed-Date

Given a stock and an as-of `filed_date` cutoff `D`, the system MUST compute the Piotroski
F-Score, the Altman Z-Score, and Novy-Marx gross profitability using only facts with
`filed_date <= D`, selecting for each concept the value with the greatest
`filed_date <= D` so a restatement supersedes the value it revised. Missing quarters,
late filers, and a first fiscal year with no prior-year comparison MUST yield `NaN` for
the affected factor, never raise an exception.

#### Scenario: Only facts filed on or before the cutoff contribute

- GIVEN a stock with facts filed at `D-30`, a restated value filed at `D-20` for an earlier `period_end`, and facts filed at `D+10`
- WHEN factors are computed as-of `D`
- THEN the `D-30` and restated `D-20` values are used and the `D+10` facts are ignored

#### Scenario: Missing inputs yield NaN, not a crash

- GIVEN a stock in its first XBRL year, or one missing a required tag
- WHEN factors are computed as-of any cutoff
- THEN the affected factor is `NaN` and no exception is raised

### Requirement: fundamental_v1 Feature Set Contract

`fundamental_v1` MUST be a distinct named feature set whose column list equals the
`technical_v2` column list followed by exactly
`[piotroski_f_score, altman_z_score, gross_profitability]` and no other columns.
`feature_columns_for_set("technical_v2")` MUST return the identical list as before this
change. The overlay columns MUST NOT be NULL-padded onto `technical_v2`, and raw ratios
(ROA, current ratio, leverage, gross margin, asset turnover) MUST NOT appear as columns.

#### Scenario: fundamental_v1 composes the spine plus three factors; technical_v2 is untouched

- GIVEN the feature-set registry after this change
- WHEN `feature_columns_for_set` is resolved for each set
- THEN `fundamental_v1` returns `technical_v2`'s list + `[piotroski_f_score, altman_z_score, gross_profitability]`, and `technical_v2` returns its pre-change list with existing feature-set tests passing unchanged

### Requirement: Look-Ahead-Free Materialization

Every `features_daily` row written under `feature_set = 'fundamental_v1'` MUST have its
`timestamp` derived from a contributing SEC `filed_date` plus a lag of at least one
trading day, never from any `period_end`. A restatement MUST NOT alter any row whose
`timestamp` precedes that restatement's `filed_date` plus lag. Forward-filled,
step-shaped sparse factor values are correct output, not a defect.

#### Scenario: No generated row sees a future filing (C1)

- GIVEN the materialized `fundamental_v1` rows for a stock
- WHEN every row is checked
- THEN `max(contributing filed_date) < row.timestamp` holds for every row

#### Scenario: A later revision never leaks backward

- GIVEN a materialized row at `timestamp T` and a restatement filed after `T`
- WHEN materialization is re-run
- THEN the row at `T` is unchanged and the restated value first appears at its own `filed_date` plus lag

### Requirement: Stock-Only Scope

Materializing `fundamental_v1` MUST produce rows only for assets whose
`assets.asset_class` is `stock`. An asset of any other class MUST produce zero
`fundamental_v1` rows and MUST appear in the run's `skipped_assets`, never as an error.

#### Scenario: Non-stock asset is skipped, not failed

- GIVEN a `fundamental_v1` run over a universe containing crypto assets
- WHEN a crypto asset is processed
- THEN it yields no `fundamental_v1` `features_daily` rows and is listed in `skipped_assets` with no error raised

### Requirement: Migration and Schema Check

Migration `0006_fundamental_facts.sql` MUST create `fundamental_facts` referencing only
the `assets` table, MUST apply in lexicographic order after `0007_notifications.sql`
without re-applying `0007`, and MUST be immutable once applied (a fix is a new migration,
enforced by the checksum guard). `collector.schema_check` MUST list `fundamental_facts`
as a required relation.

#### Scenario: 0006 applies after 0007 and schema_check passes

- GIVEN a database with `0007_notifications.sql` already applied
- WHEN the migration runner runs with `0006_fundamental_facts.sql` present
- THEN `0006` applies, `0007` is not re-applied, `collector.schema_check` passes with `fundamental_facts`, and later editing the applied `0006` fails on checksum drift
