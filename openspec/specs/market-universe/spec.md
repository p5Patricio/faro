# Market Universe Specification

## Purpose

The tracked asset universe, its constituent snapshot and refresh procedure, the policy
that decouples ingestion breadth from training-target breadth, and the disclosure the
snapshot's inherent bias requires.

## Requirements

### Requirement: S&P 100 Universe Snapshot

The system MUST widen the tracked asset universe from the current 4 assets to
approximately 100 S&P 100 (OEX) constituents plus the 4 existing assets, sourced from a
dated static snapshot checked into the repository — never scraped or fetched from a paid
API at runtime. Each entry MUST carry `asset_class` per `assets.asset_class`.

#### Scenario: Widened universe collects without error

- GIVEN the S&P 100 snapshot configuration lists ~100 stock entries plus the 4 existing assets
- WHEN the collector job runs against the full configuration
- THEN every listed asset is created or resolved via `get_or_create_asset`
- AND price rows are ingested for each without a configuration error

#### Scenario: Snapshot is dated and independently refreshable

- GIVEN the constituent snapshot configuration
- WHEN it is inspected
- THEN it carries a snapshot date distinguishable from the price data it lists
- AND updating the snapshot does not require a code change to the collector

### Requirement: Bounded Retraining-Target Policy

Widening the ingested universe MUST NOT widen the default retraining-target list.
`run_retraining_job`'s target resolution MUST stay bounded by an explicit,
user-controlled policy independent of how many assets have a stored dataset, and MUST
continue honoring an explicit `--tickers`/`tickers` override exactly as today.

#### Scenario: Universe growth does not inflate default targets

- GIVEN ~100 assets exist with a stored dataset
- WHEN `run_retraining_job` is invoked with no explicit `tickers` argument
- THEN the resolved target list size is governed by the retraining-target policy, not by
  the count of assets with a stored dataset
- AND the resolved list does not silently grow to ~100 tickers

#### Scenario: Explicit tickers still override the policy

- GIVEN the widened universe
- WHEN `run_retraining_job` is invoked with an explicit `tickers` list
- THEN only the requested tickers present among the available datasets become targets

### Requirement: Survivorship Bias Disclosure

Any report or UI surface presenting data derived from the S&P 100 universe snapshot MUST
record and display the membership snapshot date as a caveat, because applying today's
membership to historical data selects survivors and post-inclusion winners, and no free
source carries constituent history.

#### Scenario: Backtest report discloses snapshot bias

- GIVEN a backtest run over assets sourced from the S&P 100 snapshot
- WHEN the backtest report is generated
- THEN it includes the snapshot date and a survivorship/index-inclusion-bias caveat

#### Scenario: Missing snapshot date blocks disclosure-bearing output

- GIVEN a universe-derived report generator with no recorded snapshot date
- WHEN the report is generated
- THEN generation MUST fail or flag the report as incomplete rather than omitting the
  caveat
