# External Data Ingestion Specification

## Purpose

Rate-limited, audited, bulk-preferring retrieval of third-party financial data —
starting with SEC EDGAR — that makes staleness and rate-limit incidents visible instead
of silent, and resolves cross-source identifiers for assets in the tracked universe.

## Requirements

### Requirement: Ingestion Run Audit Trail

Every external fetch performed by shared ingestion infrastructure MUST write an
`ingestion_runs` row recording source, endpoint, status, row count, and error detail (if
any), whether the fetch succeeded or failed.

#### Scenario: Successful fetch is recorded

- GIVEN a successful SEC EDGAR request
- WHEN the fetch completes
- THEN an `ingestion_runs` row is written with `status = success`, the endpoint, and the
  row count

#### Scenario: Failed fetch is still recorded

- GIVEN a request that fails (network error, 403, 429, or 5xx)
- WHEN the fetch fails
- THEN an `ingestion_runs` row is written with `status = failure` and the error detail
- AND the failure is queryable, not silently dropped

### Requirement: Asset Identifier Resolution

The system MUST provide `asset_identifiers`, resolving a tracked ticker to its CIK,
CUSIP, and/or CoinGecko id as applicable, queryable by ticker or by external id.
Unresolved tickers MUST be logged, never silently skipped.

#### Scenario: Ticker resolves to CIK

- GIVEN a stock ticker in the tracked universe
- WHEN `asset_identifiers` is queried for that ticker
- THEN its SEC CIK is returned

#### Scenario: Unresolved ticker is logged, not skipped

- GIVEN a ticker with no matching entry in the SEC company-ticker map
- WHEN identifier resolution runs for that ticker
- THEN the ticker is recorded as unresolved rather than omitted from any output

### Requirement: SEC EDGAR Rate-Limited Client

The SEC EDGAR client MUST enforce a ceiling of 10 requests per second per process, MUST
require a configured `User-Agent` string before issuing any request, MUST prefer bulk
SEC DERA dataset downloads over per-company request loops when both are viable for the
same data, and MUST back off on HTTP 429 responses rather than retrying immediately.

#### Scenario: Requests stay under the rate ceiling

- GIVEN a batch of requests spanning ~100 CIKs
- WHEN the client issues them
- THEN no more than 10 requests are sent in any rolling 1-second window

#### Scenario: Missing User-Agent fails loudly

- GIVEN the client is constructed without a configured `User-Agent`
- WHEN a request is attempted
- THEN the client raises an error before sending the request, rather than sending an
  unidentified request SEC would reject with 403

#### Scenario: 429 triggers backoff, not silent failure

- GIVEN SEC EDGAR responds with HTTP 429
- WHEN the client receives that response
- THEN it backs off before retrying
- AND the incident is recorded via the ingestion run audit trail
