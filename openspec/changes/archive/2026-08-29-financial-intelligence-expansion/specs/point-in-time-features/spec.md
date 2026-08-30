# Point-in-Time Features Specification

## Purpose

The `filed_date`-based timestamping contract for externally-sourced features, and the
`asset_class`-branched feature-set resolution seam that lets a sibling change register a
composed feature set without touching the existing technical spine.

## Requirements

### Requirement: Filed-Date Capture for Externally-Sourced Facts

Shared ingestion infrastructure MUST capture and persist the source filing date
(`filed_date`, or the per-fact equivalent SEC exposes, e.g. XBRL `filed`) for every
externally-sourced fact it ingests, distinct from any `period_end` the fact describes.
Downstream feature computation — a sibling change's responsibility — MUST be able to
derive `features_daily.timestamp` from this captured `filed_date` alone, never from
`period_end`.

#### Scenario: Ingested fact retains both dates

- GIVEN an SEC XBRL fact with a `period_end` and a distinct `filed` date
- WHEN the ingestion infrastructure persists it
- THEN both dates are stored, and `filed_date` is queryable independently of `period_end`

#### Scenario: Ingestion run records enable point-in-time audit

- GIVEN a completed ingestion run against SEC EDGAR
- WHEN the corresponding `ingestion_runs` row is inspected
- THEN it is possible to determine, for that run, which filing dates were available for
  use

### Requirement: Asset-Class Feature-Set Resolution Seam

`feature_columns_for_set` MUST support resolving a feature set by an asset's
`assets.asset_class`, in addition to resolving by an explicit `feature_set` name, so a
sibling change can register a composed/overlay set (e.g. `fundamental_v1`) without
modifying `technical_v2`. An asset class with no registered overlay MUST fall back to
the `technical_v2` spine without raising an error.

#### Scenario: technical_v2 remains behavior-identical

- GIVEN no asset-class overlay is registered
- WHEN `feature_columns_for_set("technical_v2")` is called
- THEN it returns the identical column list as before this change
- AND existing tests pass unchanged

#### Scenario: Asset class with a registered overlay resolves the composed set

- GIVEN an asset class with a registered overlay feature set
- WHEN feature-set resolution is invoked for an asset of that class
- THEN the composed set (spine plus overlay) is returned

#### Scenario: Asset class without an overlay falls back cleanly

- GIVEN an asset class with no registered overlay (e.g. `crypto` before any sibling ships)
- WHEN feature-set resolution is invoked for an asset of that class
- THEN the `technical_v2` spine is returned
- AND no error is raised
