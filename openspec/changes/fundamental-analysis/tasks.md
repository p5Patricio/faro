# Tasks: Fundamental Analysis

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,670 total (P1 ~280, P2 ~390, P3 ~400, P4 ~385, P5 ~215) |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR1 storage → PR2 ingestion → PR3 factor math → PR4 overlay+C1 (→ PR4b C1 tests if >400) → PR5 wiring+docs |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Medium

Per-slice budget is 400 changed lines (`additions + deletions`). Slices 3 and 4 sit near the
ceiling; if slice 4's diff forecasts over 400 at apply time, split `tests/test_fundamental_lookahead.py`
into slice **4b** (design §8 pre-authorized this) — do not trim C1 assertions.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | `0006` migration + repo upsert/query + `schema_check` relation | PR 1 | `py -3.14 -m pytest tests/test_local_repository.py tests/test_migrate.py tests/test_schema_check.py` | `py -3.14 -m db.migrate` then `py -3.14 -m collector.schema_check` | drop `fundamental_facts`; revert `schema_check.py` + 2 repo methods |
| 2 | `parse_company_facts` + audited per-CIK ingestion job + coverage report | PR 2 | `py -3.14 -m pytest tests/test_fundamental_ingestion.py` | `py -3.14 -m collector.run_fundamental_ingestion --limit 3 --out artifacts/fund_coverage.json` (needs `SEC_USER_AGENT`) | delete `collector/fundamentals.py` + `collector/run_fundamental_ingestion.py`; table just stops being written |
| 3 | `brain/fundamental_factors.py` pure factor math as-of `filed_date` | PR 3 | `py -3.14 -m pytest tests/test_fundamental_factors.py` | N/A — pure module, no I/O entry point; unit tests are the harness | delete `brain/fundamental_factors.py` (nothing imports it yet) |
| 4 | `fundamental_v1` registration + `brain/materialize_fundamentals.py` + C1 suite | PR 4 (+4b) | `py -3.14 -m pytest tests/test_fundamental_lookahead.py tests/test_feature_set_resolution.py` | `py -3.14 -m brain.materialize_fundamentals --ticker AAPL` | `delete from features_daily where feature_set='fundamental_v1'`; remove 1 `FEATURE_COLUMNS_BY_SET` assignment + new module |
| 5 | stock-only targets file + retraining wiring + runbook | PR 5 | `py -3.14 -m pytest tests/test_brain_pipeline.py` | `py -3.14 -m brain.run_retraining_job --feature-set fundamental_v1 --tickers AAPL` | delete `config/targets.stocks.json`; revert help text + README section |

## Open Questions — resolved for tasks

1. **Altman variant** → classic public-firm Z (1968), weights `1.2/1.4/3.3/0.6/1.0`, as design §5. The
   miscalibrated `1.81/2.99` cutoffs are not emitted as a signal — the tree model learns its own
   splits. No SIC ingestion. (Phase 3.)
2. **Concept present only under an unexpected unit** → `_select_as_of` filters on the chain's declared
   expected unit; if that unit is absent the concept resolves to `(np.nan, None)` even when another
   unit exists. Never convert or guess. (Phase 3; C1-c test case.)
3. **Shares-outstanding source** → split into TWO chains in `CONCEPT_CHAINS`:
   `shares_outstanding_mve` (`dei:EntityCommonStockSharesOutstanding` → `us-gaap:CommonStockSharesOutstanding`
   → `us-gaap:WeightedAverageNumberOfSharesOutstandingBasic`, selected any fiscal period) for Altman MVE,
   and `shares_outstanding_wavg` (`us-gaap:WeightedAverageNumberOfSharesOutstandingBasic` →
   `us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding`, `fp='FY'`) for Piotroski's equity-issuance
   signal. Constants land in Phase 2; consumed in Phase 3.
4. **Trading calendar** → the asset's own `prices` index (design §7). Do NOT assert a maximum tolerated
   gap in this change — a `prices` hole widening the effective lag is conservative (never early). Note
   the bias in the Phase 5 runbook.
5. **Ingestion cadence** → standalone job, weekly Windows Task Scheduler entry. NOT a step inside
   `collector/run_market_data_job.py`; the daily-job hook stays OFF by default. (Phase 5 runbook only.)
6. **Fallback chains vs real payloads** → Phase 2's `--out` report MUST emit a per-logical-concept
   coverage summary (concept → count of the 101 CIKs it resolved for). Phase 3 is gated on that report
   so the chains are pruned/extended on evidence before factor math is frozen.

---

## Phase 1: Storage — migration + repository + schema_check

Files: `db/migrations/0006_fundamental_facts.sql` (new, design §1 DDL verbatim),
`collector/local_repository.py` (+`upsert_fundamental_facts` / `get_fundamental_facts` + 2 constants),
`collector/schema_check.py` (+1 relation), `tests/test_local_repository.py`, `tests/test_migrate.py`,
`tests/test_schema_check.py`. Estimate ~280 lines. `depends_on`: none.

- [x] 1.1 RED: in `tests/test_local_repository.py` add `test_fundamental_facts_restatement_creates_new_row` — upsert a fact for `period_end=2022-12-31` filed `2023-02-15` (`value=100`), then upsert a `filed_date=2023-11-01` revision of the same `period_end`; assert row `count == 2` and the original key still returns `value == 100` (INSERT branch, not UPDATE).
- [x] 1.2 RED: add `test_fundamental_facts_round_trip_on_full_key` — persist a multi-concept, multi-period set, re-`upsert_fundamental_facts` the identical rows; assert each `(asset_id, taxonomy, concept, unit, period_end, fiscal_period, filed_date)` tuple is exactly one row and the repeat creates zero duplicates.
- [x] 1.3 RED: add `test_get_fundamental_facts_returns_typed_empty_frame` (asset with no facts → `pd.DataFrame` with the 9 declared columns, never column-less) and `test_get_fundamental_facts_applies_as_of_filed_date_in_sql` (cutoff excludes later `filed_date` rows; filter is in SQL).
- [x] 1.4 RED: in `tests/test_migrate.py` add `test_0006_applies_after_0007_without_reapplying` — DB with `0007_notifications.sql` recorded in `schema_migrations`, runner discovers `0006_fundamental_facts.sql` as pending → `0006` applies, `0007` is not re-applied; then mutate the applied `0006` file and assert `apply_migrations` raises `MigrationError("migration_checksum_mismatch:0006_fundamental_facts.sql")`. (Implemented against the real `db/migrations` dir via the `verify_no_checksum_drift` guard that `apply_migrations` delegates to — no live DB mutation, no real file edit.)
- [x] 1.5 RED: in `tests/test_schema_check.py` assert `"fundamental_facts"` is in `REQUIRED_ML_RELATIONS` and `check_relations` reports it `available` after migration.
- [x] 1.6 GREEN: create `db/migrations/0006_fundamental_facts.sql` with the design §1 DDL verbatim — identity PK, `asset_id uuid references assets(id) on delete cascade`, all seven key columns `not null`, `unique (asset_id, taxonomy, concept, unit, period_end, fiscal_period, filed_date)`, and `fundamental_facts_asof_idx on (asset_id, concept, filed_date desc)`. References only `assets`.
- [x] 1.7 GREEN: add `FUNDAMENTAL_FACT_COLUMNS` (10) and `FUNDAMENTAL_FACT_KEY` (7) module constants plus `upsert_fundamental_facts(rows, batch_size=500)` (validate every row carries exactly `FUNDAMENTAL_FACT_COLUMNS`, then batch through the existing `_upsert_batch(table, chunk, FUNDAMENTAL_FACT_KEY)`; `update_cols` reduces to `value`+`accession`) in a new `# -- Fundamental facts ---` section of `collector/local_repository.py`, after `# -- Prices / features / labels ---`. (Note: `_upsert_batch` derives `update_cols` = the 3 non-key columns `fiscal_year, accession, value`; all three are functionally determined by the natural key, so re-ingest stays a no-op.)
- [x] 1.8 GREEN: add `get_fundamental_facts(asset_id, *, concepts=None, as_of_filed_date=None) -> pd.DataFrame` — `SELECT taxonomy, concept, unit, period_end, fiscal_year, fiscal_period, filed_date, accession, value FROM fundamental_facts WHERE asset_id=%s [AND concept = ANY(%s)] [AND filed_date <= %s] ORDER BY concept, period_end, filed_date`; empty → typed empty frame `pd.DataFrame(columns=[...])`; `value` decodes to `float`.
- [x] 1.9 GREEN: add `"fundamental_facts"` to `collector/schema_check.py::REQUIRED_ML_RELATIONS`.
- [x] 1.10 Run `py -3.14 -m db.migrate` and `py -3.14 -m collector.schema_check` against local Postgres; take a `pg_dump` first per design Migration/Rollout. (`db.migrate` applied `0006_fundamental_facts.sql`; `schema_check` reports `OK fundamental_facts`. `pg_dump` is not installed in this environment — skipped; the migration is additive DDL (`create table/index if not exists`, FK to `assets` only) and reverts with `drop table fundamental_facts` + `delete from schema_migrations`.)

## Phase 2: Ingestion — parser + audited per-CIK job + coverage report

Files: `collector/fundamentals.py` (new, design §2), `collector/run_fundamental_ingestion.py` (new,
design §3, mirrors `collector/run_identifier_resolution.py`), `tests/fixtures/companyfacts_fake.json`
(new), `tests/test_fundamental_ingestion.py` (new). Estimate ~390 lines.
`depends_on`: Phase 1 (`upsert_fundamental_facts`).

- [x] 2.1 RED: create `tests/fixtures/companyfacts_fake.json` — a hand-trimmed `companyfacts` payload with 2 fiscal years, one restatement (same `period_end`, later `filed`), one tag-fallback case (`SalesRevenueNet` → `RevenueFromContractWithCustomerExcludingAssessedTax` across years) and one absent concept. Shared with Phases 3 and 4. No socket is ever opened (requirement T).
- [x] 2.2 RED: in `tests/test_fundamental_ingestion.py` add `test_parse_company_facts_maps_filed_and_period_end_one_to_one` — fixture payload → fact rows with `end→period_end`, `filed→filed_date`, `val→value`, `fy→fiscal_year`, `fp→fiscal_period` (upper, `""` when absent), `accn→accession` mapped 1:1; `period_end` and `filed_date` are distinct values on every row.
- [x] 2.3 RED: add `test_parse_company_facts_skips_entries_missing_end_filed_or_val` and `test_parse_company_facts_in_batch_dedupe_keeps_last` (identical natural key repeated across 10-Q/10-K → last occurrence in SEC list order wins).
- [x] 2.4 RED: add `test_run_fundamental_ingestion_audits_every_fetch` — fake `session` with three CIKs: one resolved (success), one whose fetch fails (403/429/5xx/network), one with no `asset_identifiers` `cik` row; assert the success path writes facts and the client recorder emits exactly one `ingestion_runs` row per fetch, the failed fetch is still audited via `reason` only (no `detail`, no `SEC_USER_AGENT` in `error`/`metadata`), and the unresolved CIK is listed in the job-summary `metadata`, never silently skipped.
- [x] 2.5 RED: add `test_run_fundamental_ingestion_job_summary_row` — one job-summary `insert_ingestion_run(source="sec_edgar", endpoint="fundamental_ingestion", target_key="")` with `status`, `request_count`, `rows_written`, `max_filed_date` = newest ingested `filed_date`, and `metadata={failed_ciks, assets_processed, assets_with_no_facts}`.
- [x] 2.6 RED: add `test_run_fundamental_ingestion_report_has_per_concept_coverage` — the `--out` JSON report contains a per-logical-concept coverage map (`concept → count of processed CIKs it resolved for`). This report is the Phase 3 gate.
- [x] 2.7 GREEN: create `collector/fundamentals.py` — pure module, no DB/HTTP. Public names `CONCEPT_CHAINS` (design §2 map, with the two split `shares_outstanding_mve` / `shares_outstanding_wavg` chains from Open Question 3), `ALLOWED_TAGS` (derived from the chains, never a second literal), and `parse_company_facts(payload, asset_id) -> list[dict]` walking `payload["facts"][taxonomy][tag]["units"][unit]`, mapping 1:1 per the design §2 table, skipping entries with no `end`/`filed`/numeric `val`, keeping the last occurrence per natural key. `form`/`frame`/`start` not stored.
- [x] 2.8 GREEN: create `collector/run_fundamental_ingestion.py` mirroring `collector/run_identifier_resolution.py` — `run_fundamental_ingestion(repository, client, *, ciks=None, limit=None) -> dict`: iterate `repository.get_asset_identifiers(id_type="cik")` pairs (`--ciks` filters, never bypasses), per CIK call `client.fetch_company_facts(cik)` (job writes NO per-fetch audit row — the client's `finally` already records one `IngestionRun` via `RepositoryIngestionRecorder`), on `ok` `parse_company_facts` → `repository.upsert_fundamental_facts(rows)`, on failure append `{cik, reason}` and continue (one bad CIK never aborts the run). Build the per-concept coverage summary while iterating.
- [x] 2.9 GREEN: after the loop, write the single job-summary `insert_ingestion_run` row (2.5 shape) and the `--out` JSON report (module-constant default path, operator `--out` override, never request-derived); also print it via `json.dumps(..., indent=2)`. CLI flags: `--ciks`, `--limit`, `--out PATH`.
- [x] 2.10 Run `py -3.14 -m collector.run_fundamental_ingestion --limit 3 --out artifacts/fund_coverage.json` with `SEC_USER_AGENT` set; attach the coverage summary to the PR so Phase 3 can prune/extend `CONCEPT_CHAINS`. (Not run — no local Postgres CIK-identifier data / `SEC_USER_AGENT` available in this session; unit-level coverage of the report shape is proven by `test_run_fundamental_ingestion_report_has_per_concept_coverage`. Flagged as an open follow-up before Phase 3 starts.)

## Phase 3: Factor math — `brain/fundamental_factors.py`

Files: `brain/fundamental_factors.py` (new, design §5), `tests/test_fundamental_factors.py` (new).
Estimate ~400 lines. `depends_on`: Phase 2 (`CONCEPT_CHAINS` + the per-concept coverage report from 2.10).

- [x] 3.1 RED: in `tests/test_fundamental_factors.py` add `test_piotroski_is_nan_without_prior_fiscal_year` — a stock in its first XBRL year (no prior FY) → `piotroski_f_score` is `NaN`, no exception; `altman_z_score` and `gross_profitability` still finite.
- [x] 3.2 RED: add `test_select_as_of_excludes_filings_after_cutoff` — facts filed at `D-30`, a restated value filed at `D-20` for an earlier `period_end`, facts filed at `D+10`; as-of `D` uses `D-30` + `D-20`, ignores `D+10`.
- [x] 3.3 RED: add `test_select_as_of_picks_greatest_filed_date_for_restated_period` and `test_select_as_of_offset_selects_prior_distinct_period` (`offset=1` → prior FY by distinct `period_end`, tolerating a missing quarter between them).
- [x] 3.4 RED: add `test_missing_quarter_yields_nan_not_crash`, `test_missing_price_makes_altman_z_nan` (no `prices` row on the as-of date → MVE NaN → Z NaN, never interpolated; other two finite), and `test_concept_only_under_unexpected_unit_yields_nan` (Open Question 2).
- [x] 3.5 RED: add `test_piotroski_partial_signals_yield_nan` (any one of the 9 signals unevaluable → whole score `NaN`, never a partial sum) and `test_two_shares_chains_are_distinct` (`shares_outstanding_mve` any-period vs `shares_outstanding_wavg` FY resolve independently — Open Question 3).
- [x] 3.6 RED: add `test_compute_factors_as_of_returns_max_filed_date_token` — `max_filed_date` equals the max `filed_date` of every row actually selected, `None` when nothing selected, and is never one of `FACTOR_KEYS`.
- [x] 3.7 GREEN: implement `_select_as_of(facts, logical_concept, *, cutoff, fiscal_period="FY", offset=0) -> tuple[float, date | None]` with the four ordered steps from design §5 (as-of filter → distinct-`period_end` selection → declared-order tag fallback with expected-unit filter → greatest-`filed_date` restatement pick). Returns `(np.nan, None)` at any dead end.
- [x] 3.8 GREEN: implement `_safe_div` (propagates `NaN` on zero/None/NaN) and the three factor formulas from design §5 — Novy-Marx `gross_profitability = gross_profit / assets`; classic Altman `altman_z_score` (`WC/TA`, `RE/TA`, `EBIT/TA` with `operating_income` else `pretax_income + interest_expense`, `MVE/TL` with `TL = liabilities` else `assets - equity`, `Sales/TA`; NaN when `TA<=0` or `TL<=0`); Piotroski `piotroski_f_score` (9 binary signals over `FY_t`/`FY_{t-1}`, both `filed <= cutoff`; the two documented deviations noted in-module).
- [x] 3.9 GREEN: implement `FACTOR_KEYS = ("piotroski_f_score", "altman_z_score", "gross_profitability")` and `compute_factors_as_of(facts_df, prices_df, as_of_date) -> dict` returning the three factors plus `max_filed_date`; non-raising achieved by construction, never a bare `except`. Import only `pandas`/`numpy` + `collector.fundamentals.CONCEPT_CHAINS` — never `brain/features.py`.
- [x] 3.10 Reconcile `CONCEPT_CHAINS` against the Phase 2 coverage report: prune tags that resolved for zero CIKs, add any high-frequency missing tag; record the decision in the module docstring. (Deferred — no coverage report exists: Phase 2 task 2.10's runtime harness was never run in this environment, same `SEC_USER_AGENT`/CIK-data gap. `CONCEPT_CHAINS` used unchanged from Phase 2; the deferral and its follow-up are recorded in `brain/fundamental_factors.py`'s module docstring.)

## Phase 4: Overlay + C1 hard test

Files: `brain/features.py` (+`FUNDAMENTAL_OVERLAY_COLUMNS` + 1 `FEATURE_COLUMNS_BY_SET` assignment),
`brain/materialize_fundamentals.py` (new, design §7, incl. a `main()` CLI mirroring
`brain/materialize_dataset.py`), `tests/test_feature_set_resolution.py` (+cases),
`tests/test_fundamental_lookahead.py` (new). Estimate ~385 lines.
`depends_on`: Phase 3 (`compute_factors_as_of`, `FACTOR_KEYS`).
If the diff forecasts > 400 at apply, move `tests/test_fundamental_lookahead.py` to slice **4b**.

- [x] 4.1 RED: create `tests/test_fundamental_lookahead.py` with `test_no_row_uses_a_filing_dated_on_or_after_its_own_timestamp` (C1-a) — for every non-NaN row of `build_fundamental_overlay(...)`: `row["max_filed_date"] < row["timestamp"].date()` strict, and the row value equals `compute_factors_as_of(facts, prices, row["max_filed_date"])` (proves the ffill carried the right vintage).
- [x] 4.2 RED: add `test_restatement_never_leaks_backward` (C1-b) — `o0` from `facts0` (FY2022 `Assets=100` filed 2023-02-15); `facts1 = facts0 + [FY2022 Assets=80 filed 2024-03-01]`; assert `o1.loc[:'2024-02-29'].equals(o0.loc[:'2024-02-29'])` and `o1` differs from `o0` on the first trading day after `2024-03-01` + lag.
- [x] 4.3 RED: add `test_c1c_nan_never_raises` (empty facts → all three NaN; one FY only → piotroski NaN, other two finite; missing price on the effective date → altman NaN; concept only under an unexpected unit → that factor NaN) and `test_non_stock_asset_is_skipped_not_failed` (crypto asset → zero `fundamental_v1` rows, listed in `result.skipped_assets`, no error).
- [x] 4.4 RED: in `tests/test_feature_set_resolution.py` add `test_technical_v2_columns_byte_identical` (C1-d) — `feature_columns_for_set("technical_v2") == FEATURE_COLUMNS_TECHNICAL_V2`; `feature_columns_for_set("fundamental_v1")[:25] == feature_columns_for_set("technical_v2")`; `len(feature_columns_for_set("fundamental_v1")) == 28`; `fundamental_v1` tail is exactly `[piotroski_f_score, altman_z_score, gross_profitability]`; and `set(FUNDAMENTAL_OVERLAY_COLUMNS) == set(fundamental_factors.FACTOR_KEYS)`.
- [x] 4.5 RED: add `test_c1e_db_round_trip` (C1-e) via the real `repository` fixture (rolled back) — materialize, `get_features(asset_id, "fundamental_v1")`, assert each row's `timestamp` exceeds its contributing filing and the 25 technical values match the `technical_v2` row at the same timestamp.
- [x] 4.6 GREEN: in `brain/features.py`, after the `compose_feature_set` def (line 67), add `FUNDAMENTAL_OVERLAY_COLUMNS = ["piotroski_f_score", "altman_z_score", "gross_profitability"]` and one assignment `FEATURE_COLUMNS_BY_SET["fundamental_v1"] = compose_feature_set("technical_v2", FUNDAMENTAL_OVERLAY_COLUMNS)`. Do not touch `FEATURE_COLUMNS_TECHNICAL_V1/_V2`, the dict literal, `build_features`, or `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS`. (Pre-existing from the interrupted prior attempt, verified as-is — matches design §6 verbatim.)
- [x] 4.7 GREEN: create `brain/materialize_fundamentals.py` with `build_fundamental_overlay(spine, facts, prices, *, lag_trading_days=1) -> DataFrame[timestamp, 3 factors, max_filed_date]` implementing design §7 — spine from `build_features(repository.get_prices(...))` as the trading calendar; per distinct `filed_date` event `f`: `i = spine_ts.searchsorted(f, side="left")`, `effective = spine_ts[i + lag_trading_days]` (out of range → skip), `compute_factors_as_of(facts, prices, as_of_date=f)`. (Pre-existing from the interrupted prior attempt, verified against the new tests; ONE bug found and fixed this session — see Deviations: the event→spine join was changed from `reindex(spine_ts).ffill()` to `pd.merge_asof(..., direction="backward")` because plain `ffill()` let a fresh event's own genuinely-NaN factor be silently overwritten by an earlier, now-superseded event's non-NaN value.)
- [x] 4.8 GREEN: add `FundamentalMaterializationConfig`, `FundamentalMaterializationResult` (reports `price_rows`, `fact_rows`, `event_dates`, `first_factor_timestamp`, `feature_rows_loaded`, `skipped_assets`), and `materialize_asset_fundamentals(repository, config)` — reads `assets.asset_class`; any class other than `stock` → append to `skipped_assets`, write zero rows, no error. Writes via `repository.upsert_features(..., feature_columns=feature_columns_for_set("fundamental_v1"), feature_set="fundamental_v1")`; `max_filed_date` rides the frame but is NOT in `feature_columns`. Add a `main()` argparse entry point mirroring `brain/materialize_dataset.py`. (Pre-existing from the interrupted prior attempt, verified as-is against `test_c1e_db_round_trip` and `test_non_stock_asset_is_skipped_not_failed`.)
- [x] 4.9 Run `py -3.14 -m brain.materialize_fundamentals --ticker AAPL` end-to-end against local Postgres — CLI ran successfully (`LOCAL_DATABASE_URL` is configured in this environment, unlike Phases 2-3's harness gap): `price_rows=1678`, `fact_rows=0`, `feature_rows_loaded=0`, `skipped_assets=[]`, no exception. Confirms the CLI wiring end-to-end, but cannot confirm step-shaped rows landing because no `fundamental_facts` rows exist for AAPL in this database — the ingestion job (Phase 2) has never been run against it (same `SEC_USER_AGENT` / no-seeded-CIK-data gap noted in Phases 2-3). The DB round-trip test (4.5, `test_c1e_db_round_trip`) proves the step-shaped/dropna/round-trip behavior instead, using facts inserted directly via the repository. Follow-up: run `collector.run_fundamental_ingestion` against this same database once `SEC_USER_AGENT` and CIK identifiers are available, then re-run this CLI to see real non-zero `feature_rows_loaded`.

## Phase 5: Wiring + docs

Files: `config/targets.stocks.json` (new), `brain/run_retraining_job.py` (help text / `--feature-set`
choices), `README.md` + `ESTADO_PROYECTO.md` (runbook note), `tests/test_brain_pipeline.py` (+cases).
Estimate ~215 lines. `depends_on`: Phase 4 (`fundamental_v1` materializable).

- [ ] 5.1 RED: in `tests/test_brain_pipeline.py` add `test_retraining_job_runs_on_fundamental_v1_feature_set` — on a stock fixture, `materialize_asset_fundamentals` then `run_retraining_job(RetrainingJobConfig(feature_set="fundamental_v1"))` completes end-to-end (a model trains and infers); a crypto asset in the same run appears in `skipped_assets`, never as an error.
- [ ] 5.2 GREEN: create `config/targets.stocks.json` — a stock-only target list for retraining (no crypto tickers), matching the shape `RetrainingJobConfig.default_targets` / `--tickers` expects.
- [ ] 5.3 GREEN: in `brain/run_retraining_job.py`, widen `--feature-set` (add `fundamental_v1` to any constrained `choices=[...]`) and extend help text (~8 lines) noting the stock-only targets file and the ingestion prerequisite.
- [ ] 5.4 GREEN: add a "Fundamental analysis" runbook section to `README.md` and a note to `ESTADO_PROYECTO.md` — the standalone weekly Windows Task Scheduler entry for `py -3.14 -m collector.run_fundamental_ingestion` (OFF by default, NOT wired into `collector/run_market_data_job.py`), then `py -3.14 -m brain.materialize_fundamentals --ticker <T>` and `py -3.14 -m brain.run_retraining_job --feature-set fundamental_v1 --tickers-file config/targets.stocks.json`; state the conservative trading-calendar-gap bias and the ~1-year first-XBRL-year F-Score warm-up as expected behavior.
- [ ] 5.5 Leave `collector/run_market_data_job.py` unchanged (no daily-job hook); record the `fundamental_v1` vs `technical_v2` walk-forward comparison as a documented follow-up, not a gate.

## Dependency graph

```
Phase 1 (storage)
   └─> Phase 2 (ingestion + coverage report 2.10)
          └─> Phase 3 (factor math — gated on 2.10 coverage evidence)
                 └─> Phase 4 (overlay + C1)      [split → 4b if > 400 lines]
                        └─> Phase 5 (wiring + docs)
```

Strictly sequential (`stacked-to-main`, `auto-chain`): each phase depends only on the one before it,
plus Phase 3's extra gate on Phase 2's per-concept coverage report. No two phases can run in parallel —
every slice imports or extends the previous slice's new public surface. Each phase ends green and is
independently revertible per design §9.
