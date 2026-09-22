# Proposal: Fundamental Analysis

Sibling #3 of the archived `financial-intelligence-expansion` charter. Inherits C1–C4.

## Intent

Faro trains on OHLCV only, so it cannot answer "is this company financially sound?". The
archived charter shipped the S&P 100 universe, CIK identifiers, an audited SEC client and
the `filed_date` seam — all currently feeding nothing. This change converts those seams
into an opt-in `fundamental_v1` feature set so stock models can price balance-sheet
quality, while every promoted `technical_v2` model stays byte-identical.

## Scope

### In Scope

- Migration `0006_fundamental_facts.sql` (fills the real `0006` gap): tall table, one row
  per `(asset_id, taxonomy, concept, unit, period_end, fiscal_period, filed_date)` plus
  value and `accession`. A restatement is a new row at a later `filed_date`, never an update.
- `collector/fundamentals.py` (concept allow-list + per-concept tag fallback chains) and
  `collector/run_fundamental_ingestion.py`: per-CIK `SecEdgarClient.fetch_company_facts`,
  audited through `RepositoryIngestionRecorder`.
- Repository `upsert_fundamental_facts` / `get_fundamental_facts`; `schema_check` relation.
- `brain/fundamental_factors.py`: Piotroski F-Score, Altman Z-Score, Novy-Marx gross
  profitability, computed as-of a `filed_date` cutoff; NaN (never a crash) on missing
  quarters, late filers, or a first year with no prior FY.
- `fundamental_v1 = compose_feature_set("technical_v2", [piotroski_f_score,
  altman_z_score, gross_profitability])`, registered in `FEATURE_COLUMNS_BY_SET` only.
- Materialization: dense daily forward-fill onto the `technical_v2` spine with a
  1-trading-day lag, written under `feature_set='fundamental_v1'`.
- Stock-only retraining targets file (or documented `--tickers` guidance).

### Out of Scope

- **DERA bulk zips.** `fetch_dera_dataset` stays an unbuilt seam, documented as a future
  scale optimization; companyfacts-only covers 101 CIKs in ~11s throttled.
- `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS` wiring — no caller passes `asset_class`.
- Crypto assets: they get no `fundamental_v1` rows and drop out of a run automatically.
- Valuation/DCF, analyst estimates, 13F (sibling 4), UI surfacing.

## Hard Requirements

| # | Requirement |
|---|---|
| C1 | Every fact and every derived `features_daily` row is indexed by SEC `filed_date`, never `period_end`. Enforced by test: `max(contributing filed_date) < row.timestamp` for every generated row, plus a restatement case proving a later revision never leaks backward. Step-shaped sparse features are correct, not a bug. |
| C2 | `feature_columns_for_set("technical_v2")` resolution unchanged; `fundamental_v1` is a distinct named set; no NULL-padded columns. |
| M | `0006` references only `assets`; `db/migrate.py` applies it lexicographically after `0007` (tested pattern, precedent `0005`); applied files are immutable (checksum guard). |
| T | No live SEC calls in tests — fake `session`, per `tests/test_sec_edgar_client.py`. |

## Capabilities

### New Capabilities

- `fundamental-analysis`: SEC XBRL fact ingestion and storage, point-in-time factor
  computation as-of `filed_date`, and the `fundamental_v1` feature set contract.

### Modified Capabilities

- None. This change *consumes* `point-in-time-features` (C1/C2), `external-data-ingestion`
  (SEC client + audit), `local-persistence` (migration runner + repository parity) and
  `market-universe` (CIK identifiers) without altering their requirements.

## Approach

Companyfacts-only ingestion into a tall `fundamental_facts` table that mirrors the SEC JSON
1:1, so new factor inputs never need a migration and restatements are naturally
point-in-time. Factors are pure functions of facts filtered by `filed_date <= cutoff`;
Piotroski selects the two most recent `fp='FY'` facts under that cutoff for its YoY
signals. The overlay is forward-filled onto the existing daily technical spine so the
inner-join with `labels_daily` yields a full-size training set. `--feature-set
fundamental_v1` then flows through materialization and retraining with no code change.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `db/migrations/0006_fundamental_facts.sql` | New | Tall `fundamental_facts` table |
| `collector/local_repository.py` | Modified | Upsert/query fundamental facts |
| `collector/schema_check.py` | Modified | Add `fundamental_facts` relation |
| `collector/fundamentals.py` | New | companyfacts payload -> fact rows |
| `collector/run_fundamental_ingestion.py` | New | Per-CIK audited ingestion job |
| `brain/fundamental_factors.py` | New | The three point-in-time factors |
| `brain/features.py` | Modified | Register `fundamental_v1` only |
| `brain/materialize_fundamentals.py` | New | Forward-fill + 1-day lag writer |
| `brain/run_retraining_job.py`, `config/` | Modified | Stock-only targets / docs |
| `tests/` | New/Modified | C1 look-ahead, restatement, parser, pipeline |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Look-ahead bias — backtests look excellent and mean nothing | High | C1 as a hard test plus the 1-trading-day lag; restatement case mandatory |
| `us-gaap` tag inconsistency across filers | High | Per-logical-concept fallback chains; missing input -> NaN factor -> that asset's early rows drop, never a crash |
| Restatement overwriting an earlier period | Med | Insert-only keyed by `filed_date`; as-of selection takes the greatest `filed_date <= D` |
| Missing quarters / late filers / first XBRL year | Med | Prior-FY lookup tolerates gaps; no F-Score for the first ~1 year is expected |
| Altman Z depends on `prices` coverage at the as-of date | Med | Market-equity input is `close x shares outstanding` as-of D; NaN when price is absent |
| `config/targets.core.json` is crypto-heavy | Med | Ship a stock-only targets file or documented `--tickers` guidance |
| SEC rate limit / IP block | Low | Existing `min_interval=0.11` throttle, declared `SEC_USER_AGENT`, every fetch audited |
| Inherited survivorship / index-inclusion bias | High | Already disclosed by the foundation; restate in the backtest report |

## Review Workload Forecast

Budget 400 changed lines per PR; strategy `auto-chain`, `stacked-to-main`. Forecast is ~5
slices of ~400 lines: (1) migration + repository + `schema_check`; (2) parser + ingestion
job; (3) factor math; (4) `fundamental_v1` registration + materialization + the C1 hard
test; (5) job/retraining wiring + targets config. Chained PRs recommended: Yes.

## Product Decisions

Resolved with the operator (2026-09-02); rationale carried into spec + design.

1. **Overlay breadth — 3 composite factors only.** `fundamental_v1` exposes
   `piotroski_f_score`, `altman_z_score`, `gross_profitability` and nothing else.
   The raw ratios (ROA, current ratio, leverage, gross margin, asset turnover) are
   computed internally as factor inputs but are NOT feature columns. Rationale: the
   composites already aggregate those ratios, so exposing both is multicollinear —
   it dilutes tree-model feature importance, breaks logistic regression, and (via
   `upsert_features`' `dropna` on the full column list) drops more training rows for
   any asset missing a tag. Start narrow; widening the overlay on measured evidence
   is a small follow-up because `fundamental_facts` already stores every input.

2. **Success = pipeline correctness, not a backtest win.** This change is done when
   ingest + factors + materialization run with no look-ahead (C1 + restatement
   tests pass) and a model trains and infers cleanly on `fundamental_v1`. It does
   NOT have to beat `technical_v2` here. Rationale: whether the feature set *helps*
   depends on model, stock subset, horizon and thresholds — all `run_retraining_job`
   concerns — and bundling a pass/fail backtest into this change would either block a
   correct pipeline or invite threshold-tuning until it barely passes. The existing
   promotion gate already adopts `fundamental_v1` per ticker only when a candidate
   beats the `technical_v2` incumbent's `objective_score`, so per-ticker adoption is
   automatic. A deliberate `fundamental_v1` vs `technical_v2` walk-forward comparison
   on a stock subset is a defined follow-up (its own small change or an operational
   evaluation run), mirroring how the charter deferred the widened-universe retrain.

## Rollback Plan

Additive and cleanly reversible: stop running the ingestion job, delete `features_daily`
rows `where feature_set='fundamental_v1'`, drop `fundamental_facts`, and unregister
`fundamental_v1`. `technical_v2` and every promoted model are untouched by construction, so
no re-promotion is needed. Take a `pg_dump` before applying `0006` and before the backfill;
`0006` is never edited after it applies (checksum guard) — a fix is a new migration.

## Dependencies

- `depends_on: financial-intelligence-expansion` (archived 2026-08-29) — provides
  `asset_identifiers` CIKs, `ingestion_runs`, `SecEdgarClient`, `compose_feature_set`.
- `SEC_USER_AGENT` set in the environment; a populated `assets` + `prices` history.

## Success Criteria

- [ ] `py -3.14 -m db.migrate` applies `0006` on a clean database; `collector.schema_check` passes.
- [ ] The ingestion job populates `fundamental_facts` for every S&P 100 CIK and writes an
      `ingestion_runs` row per fetch, success or failure.
- [ ] A restatement test proves a later filing creates a new row and never mutates the earlier one.
- [ ] The C1 look-ahead test passes: `max(contributing filed_date) < row.timestamp` for every
      generated `fundamental_v1` row.
- [ ] `feature_columns_for_set("technical_v2")` returns the identical column list; existing tests pass unchanged.
- [ ] `--feature-set fundamental_v1` materializes and retrains end-to-end on stocks; crypto
      assets appear in `skipped_assets`, not as an error.
- [ ] Factor computation returns NaN (no exception) for a first-year filer and for a filer
      with a missing quarter.
- [ ] A `fundamental_v1` vs `technical_v2` walk-forward comparison on a stock subset is
      recorded as a follow-up (not a gate for this change).
