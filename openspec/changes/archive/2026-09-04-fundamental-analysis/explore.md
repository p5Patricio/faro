# Exploration: fundamental-analysis

Sibling #3 of the archived `financial-intelligence-expansion` roadmap
(`openspec/changes/archive/2026-08-29-financial-intelligence-expansion/`).
Also saved to Engram: topic key `sdd/fundamental-analysis/explore`.

## Current State

The archived `financial-intelligence-expansion` change shipped every seam this
change builds on.

### SEC transport — `collector/providers/sec_edgar_client.py`

- `SecEdgarClient` (dataclass; injectable `session`/`sleep`/`monotonic`/`recorder`;
  `min_interval=0.11` -> ~9.1 req/s). Public methods: `fetch_company_tickers()`
  (bulk `www.sec.gov/files/company_tickers.json`), `fetch_company_facts(cik)`
  (`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`),
  `fetch_submissions(cik)` (`data.sec.gov/submissions/CIK##########.json`).
- Two-tier failure contract: `SecEdgarConfigError` when `SEC_USER_AGENT` unset
  (before any socket); every transport failure returns
  `{"ok": False, "reason": ..., "detail": ...}` with
  `reason in {sec_request_failed, sec_rate_limited, sec_client_error,
  sec_server_error, sec_invalid_json}`; success
  `{"ok": True, "payload": ..., "status_code": 200}`. 429 honors `Retry-After`,
  5xx sleeps 2s, both bounded by `MAX_RETRIES=3`.
- **Payload fidelity is a hard rule**: the client returns provider JSON
  unmodified -- `filed` is never dropped or projected
  (`tests/test_sec_edgar_client.py:212-238, 795-836`).
- `fetch_dera_dataset` (DERA quarterly Financial Statement Data Sets bulk zips) is
  a **named, deliberately unbuilt seam explicitly assigned to THIS change**
  (module docstring). It does not exist yet.
- Not registered in `collector/providers/registry.PROVIDERS` (no `PriceProvider`
  protocol).

### Ingestion audit — `collector/ingestion_audit.py`

`RepositoryIngestionRecorder(repository)` maps every `IngestionRun` field 1:1 to
`LocalPostgresRepository.insert_ingestion_run(...)` from the client's `finally`
block. One row per logical fetch, all exit paths.

### Repository — `collector/local_repository.py` (psycopg3)

- `_upsert_batch(table, rows, conflict_cols)` = `INSERT ... ON CONFLICT DO UPDATE`;
  `_insert_batch` = plain batched insert. `_configure` registers `FloatLoader`
  for `numeric` and `_UUIDStrLoader`.
- Relevant existing methods: `get_asset_identifiers(id_type='cik')` -> rows with
  `asset_id` + `id_value` (CIK stored 10-digit zero-padded);
  `resolve_asset_by_identifier('cik', id_value)`; `insert_ingestion_run(...)`;
  `get_recent_ingestion_runs(source, limit)`; `get_prices(asset_id)`;
  `upsert_features(asset_id, features_df, feature_columns, feature_set, batch_size)`
  -- requires `{timestamp, *feature_columns}` present and runs
  `features.dropna(subset=feature_columns)`, so **a row missing ANY feature column
  is silently dropped**; conflict key `(asset_id, timestamp, feature_set)`;
  `get_features(asset_id, feature_set)` -> `timestamp, features(jsonb)`;
  `get_labels(asset_id, label_method, horizon)`.

### Feature-set seam — `brain/features.py`

- `FEATURE_COLUMNS_BY_SET = {"technical_v1": [...15], "technical_v2": [...25]}`.
  `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS: dict[str,str] = {}` (empty),
  `DEFAULT_BASE_FEATURE_SET = "technical_v2"`.
- `feature_columns_for_set(feature_set, *, asset_class=None)` -- **every current
  call site passes `asset_class=None`**; still raises `ValueError` for unknown
  names. `compose_feature_set(base, overlay_cols)` ->
  `[*feature_columns_for_set(base), *overlay_cols]` (registered under a NEW name;
  `technical_v2` never mutated).
- `build_features(prices)` produces only technical columns from OHLCV, forward-only.

### Materialization + training path

- `brain/materialize_dataset.py::materialize_asset_dataset` -> `build_features`,
  `feature_columns_for_set(config.feature_set)`, `repository.upsert_features(...)`.
  CLI `--feature-set`.
- `brain/datasets.py::build_feature_frame_from_materialized` ->
  `pd.json_normalize(...).reindex(columns=columns).dropna(subset=columns)`;
  `build_dataset_from_materialized` **inner-merges features & labels on
  `timestamp`**. A `fundamental_v1` row trains only if every spine+overlay column
  is non-null AND a same-`timestamp` label row exists.
- `brain/candidate_matrix.py::load_candidate_datasets` iterates
  `repository.get_assets()`; assets with no rows for the requested `feature_set`
  become `skipped_assets` -- so crypto drops out of a `fundamental_v1` run
  automatically (matches "stocks only").
- `brain/scoped_evaluation.py::select_scope_datasets(..., max_scope_assets=...)`
  caps global scope by `(-row_count, ticker)`, target always kept.
- `brain/retraining_job.py` -- `RetrainingJobConfig.feature_set="technical_v2"`,
  `max_auto_targets=8`, `max_global_scope_assets=12`. `run_retraining_job` calls
  `feature_columns_for_set(job_config.feature_set)` (string-keyed).
  `brain/run_retraining_job.py` already exposes `--feature-set`, `--tickers`,
  `--targets-file` (default `config/targets.core.json` =
  `["BTC-USD","ETH-USD","AAPL","MSFT"]`).

### Migrations — `db/migrations/`

- `0001..0005, 0007` present. **0006 is the gap** -> new file is
  `0006_fundamental_facts.sql`. `db/migrate.py` scans lexicographically, applies
  only pending files (each own txn), `verify_no_checksum_drift` makes applied
  files immutable, advisory lock. Promoted spec has "Migration Runner Tolerates
  Non-Contiguous Numbering" -- `0006` applying after `0007` is a solved, tested
  pattern (precedent: `0005`). `0006` must reference only `assets` (from `0001`).
- Style (`0002`/`0005`/`0007`): `create table if not exists`;
  `id bigint primary key generated always as identity` for append tables;
  `timestamptz not null default now()`; `jsonb not null default '{}'::jsonb`;
  FK `references assets(id) on delete cascade`; explicit `unique(...)`;
  `create index if not exists`; no RLS.
- `collector/schema_check.py::REQUIRED_ML_RELATIONS` -- add `"fundamental_facts"`.

### Universe

`config/universe.sp100.json` = 101 stock members, all
`defaults.asset_class = "stock"`. Ticker->CIK resolution is
`collector/run_identifier_resolution.py` (shipped), writing `asset_identifiers`
rows with `id_type='cik'`.

### Inherited seam specs

`openspec/specs/point-in-time-features/spec.md` (Filed-Date Capture; Asset-Class
Feature-Set Resolution Seam), `openspec/specs/external-data-ingestion/spec.md`
(SEC client; ingestion audit), `openspec/specs/local-persistence/spec.md`
(migration runner; repo parity). Charter C1 enforcement wording: a unit test
asserting `max(source_filed_date) <= feature_timestamp` for every generated row,
plus a 1-trading-day safety lag.

## Affected Areas

- `db/migrations/0006_fundamental_facts.sql` -- NEW; owns `fundamental_facts`.
- `collector/local_repository.py` -- NEW `# -- Fundamental facts --` section:
  `upsert_fundamental_facts(rows, batch_size=500)`,
  `get_fundamental_facts(asset_id, concepts=None, as_of_filed_date=None)`.
- `collector/schema_check.py` -- add `"fundamental_facts"`.
- `collector/fundamentals.py` -- NEW; `companyfacts` payload -> fact rows
  (concept allow-list + per-concept tag fallback chains).
- `collector/run_fundamental_ingestion.py` -- NEW; per-CIK `fetch_company_facts`
  loop reusing `SecEdgarClient` + `RepositoryIngestionRecorder`, one job-summary
  `ingestion_runs` row (mirrors `run_identifier_resolution.py`).
- `brain/fundamental_factors.py` -- NEW; Piotroski F-Score, Altman Z-Score,
  Novy-Marx gross profitability, computed point-in-time as-of `filed_date`.
- `brain/features.py` -- register `fundamental_v1` via
  `compose_feature_set("technical_v2", [...])`; `technical_v2` untouched.
- `brain/materialize_fundamentals.py` (or extend `brain/materialize_dataset.py`)
  -- forward-fill the overlay onto the daily technical spine with a 1-trading-day
  lag; write `features_daily` rows under `feature_set='fundamental_v1'`.
- `collector/run_market_data_job.py` / `collector/market_data_job.py` -- optional
  hook for a daily fundamental-materialize step (or keep standalone).
- `brain/run_retraining_job.py` -- no code change for `--feature-set
  fundamental_v1` to flow; may add a stock-only default targets file / docs.
- `tests/` -- `test_local_repository.py`; NEW `test_fundamental_ingestion.py` /
  `test_fundamental_factors.py` (fake session, C1 look-ahead + restatement +
  prior-year); `test_feature_set_resolution.py` (adds `fundamental_v1`);
  `test_brain_pipeline.py` (materialize + train through `fundamental_v1`).

## Approaches considered

### 1. XBRL data source

| Approach | Verdict |
|---|---|
| **A. companyfacts-only** (per-CIK JSON, full history + incremental) | **RECOMMENDED** -- client already supports it; 101 throttled requests (~11s) on backfill; every fact carries its own `filed`/`end`/`fy`/`fp`/`accn`; restatements are extra list entries; no new download/parse infra. |
| B. DERA quarterly bulk zips + companyfacts incremental | Deferred -- charter's stated preference, but needs new zip download + `num/sub/pre/tag.txt` TSV streaming + `adsh`->CIK join; blows the 400-line budget alone; TSV schema drift risk. Keep `fetch_dera_dataset` an unbuilt seam. |
| C. submissions + companyfacts | Adds a request class with no factor-input value. |

### 2. `fundamental_facts` table shape

| Approach | Verdict |
|---|---|
| **A. Tall/narrow** -- one row per `(asset_id, taxonomy, concept, unit, period_end, fiscal_period, filed_date)` | **RECOMMENDED** -- mirrors `companyfacts` JSON 1:1; restatement = new row keyed by a later `filed_date` (naturally point-in-time); new factor inputs need NO migration; `_upsert_batch` fits; ~60k rows for 101 assets x ~20 concepts with a curated allow-list. |
| B. Wide -- column per concept | Every new factor input = migration; sparse NULL columns per filer. |
| C. Raw-JSON blob per filing | No indexable `filed_date`/`concept`. |

### 3. `fundamental_facts` -> `features_daily`

| Approach | Verdict |
|---|---|
| **A. Dense daily forward-fill onto the technical spine** -- overlay on trading day D = factor as-of the latest filing with `filed_date + 1 trading day <= D` | **RECOMMENDED** -- inner-join with daily `labels_daily` yields a full-size training set; step-shaped values are correct; reuses existing `triple_barrier`/`horizon=5` labels. |
| B. Sparse rows only on filing dates (`timestamp = filed_date`) | Inner-join with daily labels -> ~24 training rows per asset over 6 years -- unusable. |

### 4. Registering `fundamental_v1`

| Approach | Verdict |
|---|---|
| **A. `FEATURE_COLUMNS_BY_SET["fundamental_v1"] = compose_feature_set("technical_v2", overlay)` only** | **RECOMMENDED** -- `technical_v2` byte-identical (no caller passes `asset_class`); operator opts in via `--feature-set fundamental_v1`. |
| B. Also `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS["stock"] = "fundamental_v1"` | Only matters once a caller passes `asset_class=`; not needed today. |

## Recommendation

companyfacts-only ingestion (1A); tall `fundamental_facts` via migration `0006`
(2A); point-in-time factor computation as-of `filed_date` with a 1-trading-day
lag; dense daily forward-filled `fundamental_v1` = `technical_v2` + a 3-column
overlay `[piotroski_f_score, altman_z_score, gross_profitability]` (3A);
registered in `FEATURE_COLUMNS_BY_SET` only (4A). DERA bulk-zip support deferred.

### Suggested auto-chained slices (~400-line budget each)

1. `0006_fundamental_facts.sql` + repo methods + `schema_check` + round-trip tests.
2. `collector/fundamentals.py` parser + `collector/run_fundamental_ingestion.py`
   + fake-session tests (no live SEC).
3. `brain/fundamental_factors.py` -- the three factors, point-in-time +
   restatement + prior-year handling + unit tests.
4. `brain/features.py` registration + fundamental materialization (forward-fill +
   1-day lag) + **C1 hard look-ahead test**.
5. Job/retraining wiring + stock-only target config/docs.

### XBRL concept map

- Direct `us-gaap`/`dei` tags: `Assets`, `AssetsCurrent`, `Liabilities`,
  `LiabilitiesCurrent`, `LongTermDebtNoncurrent`(+`LongTermDebt`),
  `NetIncomeLoss`, `NetCashProvidedByUsedInOperatingActivities`, `GrossProfit`,
  `OperatingIncomeLoss`, `InterestExpense`,
  `RetainedEarningsAccumulatedDeficit`, shares outstanding
  (`CommonStockSharesOutstanding` / `dei:EntityCommonStockSharesOutstanding` /
  `WeightedAverageNumberOfSharesOutstandingBasic`). Revenue tag varies
  (`Revenues` | `RevenueFromContractWithCustomerExcludingAssessedTax` |
  `SalesRevenueNet`); cost tag varies (`CostOfRevenue` |
  `CostOfGoodsAndServicesSold` | `CostOfGoodsSold`).
- Derived: ROA, CFO/Assets, gross margin, asset turnover, current ratio, leverage
  ratio, working capital (`AssetsCurrent - LiabilitiesCurrent`), EBIT
  (`OperatingIncomeLoss`; fallback `IncomeBeforeIncomeTaxes + InterestExpense`),
  **market value of equity = `prices.close` at day D x shares-outstanding as-of D**
  (the only factor input coupling fundamentals to `prices`).
- Piotroski F-Score needs current-FY **and** prior-FY values (4 of 9 signals are
  YoY deltas) -> select the two most recent `fp='FY'` facts with
  `filed_date <= D`.

## Risks

- SEC `us-gaap` tag inconsistency across filers -- per-logical-concept fallback
  chains; a missing required input -> NaN factor -> that asset's early rows drop.
- Restatements: a later filing revising an earlier `period_end` MUST create a new
  row keyed by the new `filed_date`, never overwrite; as-of selection takes the
  greatest `filed_date <= D`.
- Missing quarters / late filers -- prior-year lookup must tolerate gaps.
- First ~1 year of each company's XBRL history yields no F-Score.
- Altman Z depends on `prices` coverage at the as-of date.
- Look-ahead bias is the dominant silent failure -- the C1 hard test
  (`max(contributing filed_date) < row.timestamp` for every generated row, plus a
  restatement case) is mandatory.
- `config/targets.core.json` is crypto-heavy; a `fundamental_v1` retrain needs
  explicit stock `--tickers` or a new targets file.
- Inherited survivorship / index-inclusion bias from the S&P 100 snapshot
  (already disclosed by the foundation).

## Ready for Proposal

Yes. Next phase: `sdd-propose`.
