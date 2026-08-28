# Tasks: Financial Intelligence Expansion (shared foundation)

Scope: migration `0005` + repo methods, S&P 100 universe file + loader + disclosure,
retraining-target policy + global-scope cap, SEC EDGAR client + audit recorder, and the
`asset_class` feature-set resolution seam. Siblings 3-7 (`fundamental-analysis`,
`institutional-consensus`, `personal-finance`, `asset-class-profile-overlays`,
`gemini-optional-assist`) and `dependency-pinning` are explicitly OUT of scope here.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,700-2,050 total (additions + deletions) across 7 work units / ~16 files |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 → PR 4 → PR 5 → PR 6 → PR 7 |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

Design's original slice (4) "SEC client + audit recorder" is split into PR 4 (client only)
and PR 5 (recorder + identifier-resolution job) — combined it would sit ~600-650 lines,
clearly over budget; split, each stays closer to it, mirroring how `telegram-notifications`
split its dispatch slice into 6a/6b. Design's slice (2) is kept as its own PR per design's
explicit "must not be merged with any other slice" note: the ~101-entry ticker data and the
loader code are reviewed together but never alongside migration or policy changes. PR 7
(API endpoint + rollout confirmation) is new versus design's 5-slice list because
`GET /api/universe` and the full-suite/build gate are real File-Changes/Migration-Rollout
items that need their own reviewable unit. PR 4 and PR 6 have no dependency on each other or
on PR 1-3 landing first and may be developed in parallel.

### Suggested Work Units

| # | Goal | PR | Est. lines | Risk | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|---|---|
| 1 | `db/migrations/0005_shared_ingestion.sql` + 5 `LocalPostgresRepository` methods + `collector/schema_check.py` relations | PR 1 | ~300-380 | Medium | `py -3.14 -m pytest tests/test_local_repository.py tests/test_schema_check.py` | `py -3.14 -m db.migrate` against `TEST_DATABASE_URL`, then `py -3.14 -m collector.schema_check` | Drop `ingestion_runs` then `asset_identifiers`, delete the `0005` row from `schema_migrations`; revert `local_repository.py`/`schema_check.py` |
| 2 | `config/universe.sp100.json` (verified ticker list) + `collector/universe.py` (loader + disclosure) + `collector/main.py`'s `expand_universe_document`/`isinstance` branch | PR 2 | ~350-400 | Medium-High | `py -3.14 -m pytest tests/test_universe_config.py` | `py -3.14 -m collector.main --assets-file config/universe.sp100.json --start 2020-01-01 --end 2020-01-05` against `TEST_DATABASE_URL` for a 5-ticker subset | Delete `config/universe.sp100.json`, `collector/universe.py`; revert `collector/main.py`'s `isinstance(raw, dict)` branch — `config/assets.core.json` path is untouched |
| 3 | `config/targets.core.json` + `brain/retraining_job.py` target-policy kwargs + `brain/run_retraining_job.py` CLI flags + `brain/scoped_evaluation.py` global-scope cap | PR 3 (independent of PR 1/2) | ~300-360 | Medium | `py -3.14 -m pytest tests/test_brain_pipeline.py tests/test_collector_job.py -k "target or scope"` | `py -3.14 -m brain.run_retraining_job --targets-file config/targets.core.json --max-auto-targets 8 --max-global-scope-assets 12` against `TEST_DATABASE_URL` | Revert the keyword-only kwargs (default `None`/unset preserves today's behavior) and the 3 CLI flags; delete `config/targets.core.json` |
| 4 | `collector/providers/sec_edgar_client.py` (throttled, two-tier-failure, audited client) | PR 4 (independent) | ~350-420 | High | `py -3.14 -m pytest tests/test_sec_edgar_client.py` | N/A — "No test may reach the real SEC API" (design.md). Optional operator smoke: one manual `fetch_company_tickers()` call against real `data.sec.gov` with a real `SEC_USER_AGENT`, once | Delete `collector/providers/sec_edgar_client.py` + its test; not registered in `registry.PROVIDERS`, not yet called by anything |
| 5 | `collector/ingestion_audit.py` (`RepositoryIngestionRecorder`) + `collector/run_identifier_resolution.py` | PR 5 (after PR 1, PR 4) | ~150-220 | Medium | `py -3.14 -m pytest tests/test_sec_edgar_client.py -k identifier` | Real `TEST_DATABASE_URL` round-trip: `run_identifier_resolution` against a small fixture universe with an injected `SecEdgarClient` (fake session, no live SEC call) | Delete both files + their tests; PR 4's client stays inert with no caller |
| 6 | `brain/features.py` additive functions (`feature_set_for_asset_class`, `compose_feature_set`, `feature_columns_for_set`'s `asset_class` kwarg) | PR 6 (independent) | ~100-130 | Low | `py -3.14 -m pytest tests/test_feature_set_resolution.py brain/` | N/A — stdlib-only pure functions, no I/O; parametrized unit tests are the complete proof | Revert the 3 additive functions and the keyword-only `asset_class` param (default `None` preserves every existing call site); delete the test file |
| 7 | `api/main.py`'s `GET /api/universe` + full-suite/build confirmation + wall-time/doc write-up | PR 7 (after PR 2, PR 3) | ~90-130 | Low | `py -3.14 -m pytest tests/test_api.py -k universe` | `uvicorn api.main:app` + `curl http://localhost:8000/api/universe`, confirm `snapshot_date`/`membership_bias` present | Revert the route in `api/main.py`; delete its test |

## Phase 1: Foundation — Migration + Repository + Schema Check (Req: Shared Ingestion Audit and Asset Identifier Tables)

- [ ] 1.1 Write `db/migrations/0005_shared_ingestion.sql` using design.md's verbatim DDL: `asset_identifiers` (unique `(asset_id, id_type)`, non-unique `(id_type, id_value)` lookup index — GOOG/GOOGL share one CIK) and `ingestion_runs` (append-only, `source`/`endpoint`/`started_at` index, partial `status <> 'success'` failure index).
- [ ] 1.2 `collector/local_repository.py`: add a `# -- Asset identifiers / ingestion audit --` section (before `# -- Schema introspection --`) with `upsert_asset_identifiers(rows, batch_size=500)` via `_upsert_batch(..., ("asset_id", "id_type"))`, `get_asset_identifiers(id_type=None)`, `resolve_asset_by_identifier(id_type, id_value)`, `insert_ingestion_run(source, endpoint, target_key, started_at, finished_at, status, http_status=None, rows_written=0, request_count=0, throttle_wait_seconds=0.0, max_filed_date=None, error=None, metadata=None)` with `Jsonb(_json_safe(metadata or {}))`, `get_recent_ingestion_runs(source=None, limit=50)`.
- [ ] 1.3 `collector/schema_check.py`: add `"asset_identifiers"` and `"ingestion_runs"` to `REQUIRED_ML_RELATIONS`.
- [ ] 1.4 `tests/test_local_repository.py`: upsert same `(asset_id, 'cik')` twice → one row (spec "Identifier upsert is idempotent"); `resolve_asset_by_identifier` round-trips; `insert_ingestion_run` persists a `success` row and, separately, a `failure` row with error detail — never dropped (spec "A failed fetch is still persisted"); `get_recent_ingestion_runs` filters by `source` and orders by `started_at desc`.
- [ ] 1.5 Run `py -3.14 -m db.migrate` against `TEST_DATABASE_URL`, then `py -3.14 -m collector.schema_check` — confirm both pass on a fresh DB (spec "Fresh database bootstrap includes the new tables").

## Phase 2: S&P 100 Universe Snapshot (Req: S&P 100 Universe Snapshot; Survivorship Bias Disclosure)

- [x] 2.1 **Verified** (orchestrator, 2026-08-28): the ticker recorded as `HONA` in the sourced list was a scraping artifact. Confirmed via SEC EDGAR filings (CIK 0000773840) and independent quote sources (Nasdaq, Bloomberg, Investing.com) that Honeywell International Inc. trades as `HON`. Use `HON` in `config/universe.sp100.json` — no further verification needed.
- [ ] 2.2 Build `config/universe.sp100.json` per design.md's compact schema: `"index": "S&P 100 (OEX)"`, `"snapshot_date": "2025-09-22"` (the source article's own citation date — record this honestly, not today's date, per the "never backdated" ADR meaning never claim a *later* date than the data actually reflects), `"source"` naming Wikipedia's S&P 100 article retrieved 2026-08-28, `"membership_bias"` caveat text verbatim from design.md, `"defaults": {"provider": "yfinance", "asset_class": "stock", "interval": "1d", "start": "2020-01-01"}`, and `"members"` built from the Appendix ticker list below.
- [ ] 2.3 **Normalize every `.`-containing ticker to `-`** when building the `members` array (`BRK.B` → `BRK-B`) — `yfinance` uses hyphens, not periods, for share-class suffixes. Apply this as a transformation step, not a one-off manual edit, so any future snapshot refresh gets it automatically.
- [ ] 2.4 `tests/test_universe_config.py`: assert `config/universe.sp100.json` parses; `BRK-B` (never `BRK.B`) is present; no member ticker contains `"."`; `member_count == 101`.
- [ ] 2.5 `collector/universe.py` (new): `UniverseDocument` frozen dataclass (`index`, `snapshot_date`, `source`, `membership_bias`, `defaults`, `members`); `load_universe_document(path)` raising `ValueError` when `snapshot_date` or `membership_bias` is missing/blank (spec "Missing snapshot date blocks disclosure-bearing output" — fail at load, not at report time); `universe_disclosure(doc)` returning `index`/`snapshot_date`/`source`/`membership_bias`/`member_count`. Must NOT import `AssetCollectionConfig`.
- [ ] 2.6 `collector/main.py`: add `expand_universe_document(raw)` building one `AssetCollectionConfig` per member using `defaults` for `provider`/`asset_class`/`interval`/`start`, member `ticker` as both `ticker` and `asset_ticker`, member `name` as `name`. Wire the `isinstance(raw, dict)` branch into `load_asset_configs`, keeping the existing list-form path byte-identical.
- [ ] 2.7 `tests/test_universe_config.py`: a 3-member fixture doc expands to 3 `AssetCollectionConfig` with `defaults` applied correctly; a report generator given no universe document emits `{"universe": {"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}}` rather than omitting the key.
- [ ] 2.8 `tests/test_universe_config.py`: `load_universe_document` raises `ValueError` for a fixture doc missing `snapshot_date` or `membership_bias`.
- [ ] 2.9 Prove the full 101-member config expands and every entry resolves via `get_or_create_asset` without a configuration error (spec "Widened universe collects without error") — a unit test with a fake `provider_factory` iterating the full expansion is sufficient; the runtime-harness command in the table above proves it against real `yfinance` for a subset.

## Phase 3: Bounded Retraining-Target Policy + Global-Scope Cap (Req: Bounded Retraining-Target Policy)

- [ ] 3.1 Create `config/targets.core.json`: `["BTC-USD", "ETH-USD", "AAPL", "MSFT"]` — identical to today's `config/assets.core.json` tickers; widening the universe changes nothing about what trains by default.
- [ ] 3.2 `brain/retraining_job.py`: extend `resolve_target_tickers(datasets, tickers, *, default_targets=None, max_auto_targets=None)`. Existing 2-positional-arg call sites are untouched. New behavior: `tickers` given → today's intersect-with-available result; no `tickers`, `default_targets` given → intersect `default_targets` with available; no `tickers`, no `default_targets`, `len(available) <= max_auto_targets` → `sorted(available)` (today's behavior); over the cap → `ValueError` naming `--tickers`/`--targets-file`/`--max-auto-targets` (never silently truncate — truncation would drop names invisibly and make `model_runs` unreproducible).
- [ ] 3.3 `RetrainingJobConfig`: add `default_targets: list[str] | None = None`, `max_auto_targets: int = 8`, `max_global_scope_assets: int = 12`.
- [ ] 3.4 `brain/run_retraining_job.py`: add `--targets-file` (default `config/targets.core.json`), `--max-auto-targets`, `--max-global-scope-assets` CLI flags; `--tickers` still wins over the file. Embed `universe_disclosure(doc)` under the JSON report's `"universe"` key, falling back to the `disclosure_status: "incomplete"` shape when no universe document is configured.
- [ ] 3.5 `brain/scoped_evaluation.py`: add `max_scope_assets: int | None = None` to `select_scope_datasets`; over the cap, keep the target dataset and rank the rest by `(-row_count, ticker)` — deterministic, so a re-run reproduces the same model. Thread the kwarg through `run_scoped_walk_forward_backtest` (already reports the chosen set via `participating_assets`); `build_scope_training_frame` consumes the already-capped `scope_datasets` list, no separate change needed there.
- [ ] 3.6 `tests/test_brain_pipeline.py` / `tests/test_collector_job.py`: 100 fake datasets + no `tickers` + `max_auto_targets=8` → `ValueError`; with `default_targets` set → exactly those; explicit `tickers` → today's unchanged result.
- [ ] 3.7 `tests/test_brain_pipeline.py`: 40 fake datasets, `max_scope_assets=12` on `global` scope → 12 selected, target always included, stable/deterministic across two runs with the same input.
- [ ] 3.8 **Operational, not a code diff**: after PR 2 lands and the universe is backfilled (outside this PR sequence, per design's rollout order), run `brain.run_retraining_job` once on today's ~4-asset baseline and once on the widened universe with `max_auto_targets=8`/`max_global_scope_assets=12`, and record the real wall-clock numbers. If the measurement contradicts the proposal's ~25x-per-target/~625x-global-scope estimate, adjust these two defaults before closing the change. Numbers get written up in Phase 7 task 7.5.

## Phase 4: SEC EDGAR Client (Req: SEC EDGAR Rate-Limited Client; Ingestion Run Audit Trail)

- [ ] 4.1 `collector/providers/sec_edgar_client.py` (new, NOT registered in `collector/providers/registry.py`'s `PROVIDERS` — it does not satisfy `PriceProvider`): `SecEdgarConfig` frozen dataclass with `from_env()` (`SEC_USER_AGENT`; `None` when blank), `SecEdgarConfigError(RuntimeError)`, `IngestionRun` frozen dataclass, `IngestionRunRecorder` `Protocol` with `record(run)`, `pad_cik(value)` (`"320193"` → `"CIK0000320193"`), `SecEdgarClient` dataclass with injectable `session=requests`, `sleep=time.sleep`, `monotonic=time.monotonic`, `recorder=None`, `min_interval=0.11`, and `fetch_company_tickers()`/`fetch_company_facts(cik)`/`fetch_submissions(cik)`.
- [ ] 4.2 Two-tier failure contract: `config is None` → **raise** `SecEdgarConfigError` before any socket opens (spec "Missing User-Agent fails loudly"). Transport failures (network, 403, 429, 5xx, bad JSON) → **never raise**, return `{"ok": False, "reason": ..., "detail": ...}` with `reason` in `sec_request_failed | sec_rate_limited | sec_client_error | sec_server_error | sec_invalid_json`; success → `{"ok": True, "payload": ..., "status_code": 200}`. Return provider JSON unmodified — never flatten or project XBRL facts.
- [ ] 4.3 Throttle: `min_interval=0.11s` between request starts. 429 backs off via `sleep` (honoring `Retry-After` when present) up to `MAX_RETRIES=3`, recording `metadata.failure_kind = "rate_limited"` (spec "429 triggers backoff, not silent failure").
- [ ] 4.4 Every method writes exactly one `IngestionRun` from a `finally` block, including the `SecEdgarConfigError` path when a `recorder` is attached. **Non-matrix security requirement**: `SEC_USER_AGENT` (operator name + email) must never be copied into `error`, `detail`, `metadata`, or any returned dict — assert this explicitly in tests, not just by code review.
- [ ] 4.5 `fetch_company_tickers` uses the single bulk `company_tickers.json` file for ~105-ticker CIK resolution — never a 105-iteration `submissions` loop (spec "bulk-preferring"). `fetch_dera_dataset` stays an unbuilt, named seam for the `fundamental-analysis` sibling — do not implement it here.
- [ ] 4.6 `tests/test_sec_edgar_client.py`: extend the `FakeSession` pattern from `tests/test_collector_providers.py:23` with `headers` capture; cover success/403/429/5xx/bad-JSON; assert `User-Agent` is sent on every request.
- [ ] 4.7 `tests/test_sec_edgar_client.py`: injected `monotonic` counter + recording `sleep` (the `sleep: Any = time.sleep` pattern from `ops/telegram_notifier.py:155`); assert waits `>= min_interval` between request starts, zero real wall-clock time.
- [ ] 4.8 `tests/test_sec_edgar_client.py`: fake `IngestionRunRecorder` collects exactly one `IngestionRun` per exit path — one for success, one per distinct failure reason.
- [ ] 4.9 `tests/test_sec_edgar_client.py`: `monkeypatch.delenv("SEC_USER_AGENT")`; assert `from_env() is None`, `pytest.raises(SecEdgarConfigError)`, and `FakeSession.requests == []` (no socket opened).
- [ ] 4.10 `tests/test_sec_edgar_client.py`: assert `SEC_USER_AGENT`/the operator email never appears in any returned dict, error string, or recorded `IngestionRun` field across every case in 4.6-4.9 (closes task 4.4's non-matrix requirement).

## Phase 5: Ingestion Audit Recorder + Identifier Resolution Job (Req: Ingestion Run Audit Trail; Asset Identifier Resolution; Filed-Date Capture for Externally-Sourced Facts)

- [ ] 5.1 `collector/ingestion_audit.py` (new): `RepositoryIngestionRecorder(repository)` implementing `IngestionRunRecorder` over `repository.insert_ingestion_run`, mapping every `IngestionRun` field 1:1.
- [ ] 5.2 `collector/run_identifier_resolution.py` (new): fetch `company_tickers.json` once via `SecEdgarClient`, upsert `(asset_id, 'cik')` for every matched universe ticker via `repository.upsert_asset_identifiers`, return `{"resolved": [...], "unresolved": [...]}`. Unresolved tickers are written to `ingestion_runs.metadata.unresolved_tickers` and printed — never omitted (spec "Unresolved ticker is logged, not skipped").
- [ ] 5.3 **Non-matrix security requirement**: confirm the universe path used by `collector.universe.load_universe_document` and the targets-file path used by `brain.run_retraining_job` are always module constants or CLI arguments, never derived from an inbound HTTP request — grep both call chains and note the confirmation in the PR description.
- [ ] 5.4 `tests/test_sec_edgar_client.py` (identifier-resolution section): `RepositoryIngestionRecorder` — one `insert_ingestion_run` call per `.record(run)` call.
- [ ] 5.5 `tests/test_sec_edgar_client.py`: a fake `company_tickers` payload missing one universe ticker → that ticker appears in both the job's `unresolved` list and `ingestion_runs.metadata.unresolved_tickers` (spec "Unresolved ticker is logged, not skipped").
- [ ] 5.6 `tests/test_sec_edgar_client.py`: a resolved ticker's `asset_identifiers` row is queryable by ticker and returns its CIK (spec "Ticker resolves to CIK"); the XBRL fact's `filed` date, when later parsed by a sibling, is retrievable independently of `period_end` because the client returned the payload unmodified (spec "Ingested fact retains both dates" — proven here at the transport-fidelity level, full XBRL parsing is sibling scope).
- [ ] 5.7 Integration: real repository round-trip against `TEST_DATABASE_URL` — `run_identifier_resolution` against a small fixture universe with an injected `SecEdgarClient` (fake session, no live SEC call); confirm `asset_identifiers` and `ingestion_runs` rows persist as expected.

## Phase 6: Asset-Class Feature-Set Resolution Seam (Req: Asset-Class Feature-Set Resolution Seam)

- [ ] 6.1 `brain/features.py`: add `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS: dict[str, str] = {}` (empty here; siblings register) and `DEFAULT_BASE_FEATURE_SET = "technical_v2"`; add `feature_set_for_asset_class(asset_class, base_feature_set=DEFAULT_BASE_FEATURE_SET)` — never raises, unmapped class → `base_feature_set`.
- [ ] 6.2 `brain/features.py`: add keyword-only `asset_class: str | None = None` to `feature_columns_for_set`. Resolve via `feature_set_for_asset_class` only when `asset_class is not None`; all 28 existing call sites pass no `asset_class`, so behavior stays strictly string-keyed and byte-identical, including the existing `ValueError` for an unknown name.
- [ ] 6.3 `brain/features.py`: add `compose_feature_set(base_feature_set, overlay_columns)` returning `[*feature_columns_for_set(base_feature_set), *overlay_columns]` — siblings register the result under a **new** name; `technical_v2` is never mutated.
- [ ] 6.4 `tests/test_feature_set_resolution.py`: `feature_columns_for_set("technical_v2")` returns the pre-change `FEATURE_COLUMNS_TECHNICAL_V2` list unchanged (spec "technical_v2 remains behavior-identical"); `feature_columns_for_set("technical_v2", asset_class="crypto"/"unknown"/None)` returns the same list without raising (spec "Asset class without an overlay falls back cleanly").
- [ ] 6.5 `tests/test_feature_set_resolution.py`: monkeypatch a fake entry into `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS` and confirm resolution returns the composed spine+overlay set (spec "Asset class with a registered overlay resolves the composed set").
- [ ] 6.6 Run `py -3.14 -m pytest` and confirm every existing test touching `feature_columns_for_set`'s 28 call sites passes unchanged (spec "existing tests pass unchanged").

## Phase 7: API Endpoint + Rollout Confirmation (Req: Survivorship Bias Disclosure; proposal Success Criteria)

- [ ] 7.1 `api/main.py`: add `GET /api/universe` reading `collector.universe.load_universe_document` from its module-constant `config/universe.sp100.json` path, returning `universe_disclosure(doc)`. On a missing/unreadable file, return `{"universe": {"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}}` (never a 500) — do **not** add this to `GET /api/assets`, which stays a bare `Asset[]` list per design's explicit decision.
- [ ] 7.2 `tests/test_api.py`: `GET /api/universe` returns `snapshot_date`/`source`/`membership_bias`/`member_count` for the checked-in file; confirm the endpoint never accepts a request-supplied path (closes task 5.3 for this call site too).
- [ ] 7.3 `tests/test_brain_pipeline.py`: confirm `run_retraining_job`'s JSON report embeds `universe_disclosure(doc)` under `"universe"` (spec "Backtest report discloses snapshot bias").
- [ ] 7.4 Run `py -3.14 -m pytest` (full suite) and `cd ui && npm run build` — both green with the widened universe wired in but **not backfilled or retrained** in this change (design: "Do not retrain on the widened universe in the slice that adds it").
- [ ] 7.5 Update `PLAN_MEJORAS_PROFESIONALES.md`/`README.md` (or the proposal's own success-criteria checklist) with: the verified ticker source and the `HON`/`HONA` correction outcome from task 2.1, and the real wall-clock numbers from task 3.8. Explicitly note that "sibling changes 3-7 exist as OpenSpec changes with `depends_on` and restated C1-C4" is OUT of scope for this tasks.md — it is proposal.md's own success criterion for future sibling `sdd-propose` runs, not implementation work here.

## Appendix: S&P 100 Ticker Reference (source: Wikipedia "S&P 100" article, retrieved 2026-08-28; constituent snapshot dated 2025-09-22 per the article's own citation)

Transcribe verbatim into `config/universe.sp100.json`'s `members` array per task 2.2-2.3.
Format `TICKER=Name`; normalize `BRK.B` → `BRK-B` (task 2.3); verify `HONA` → likely `HON`
(task 2.1) before committing.

AAPL=Apple Inc.; ABBV=AbbVie; ABT=Abbott Laboratories; ACN=Accenture; ADBE=Adobe Inc.;
AMAT=Applied Materials; AMD=Advanced Micro Devices; AMGN=Amgen; AMT=American Tower;
AMZN=Amazon; AVGO=Broadcom; AXP=American Express; BA=Boeing; BAC=Bank of America;
BKNG=Booking Holdings; BLK=BlackRock; BMY=Bristol Myers Squibb; BNY=BNY Mellon;
BRK-B=Berkshire Hathaway (Class B); C=Citigroup; CAT=Caterpillar Inc.; CL=Colgate-Palmolive;
CMCSA=Comcast; COF=Capital One; COP=ConocoPhillips; COST=Costco; CRM=Salesforce;
CSCO=Cisco; CVS=CVS Health; CVX=Chevron Corporation; DE=Deere & Company;
DHR=Danaher Corporation; DIS=Walt Disney Company; DUK=Duke Energy; EMR=Emerson Electric;
FDX=FedEx; GD=General Dynamics; GE=GE Aerospace; GEV=GE Vernova; GILD=Gilead Sciences;
GM=General Motors; GOOG=Alphabet Inc. (Class C); GOOGL=Alphabet Inc. (Class A);
GS=Goldman Sachs; HD=Home Depot; HON=Honeywell International (verified via SEC EDGAR,
task 2.1); IBM=IBM; INTC=Intel; INTU=Intuit; ISRG=Intuitive Surgical;
JNJ=Johnson & Johnson; JPM=JPMorgan Chase; KO=Coca-Cola Company; LIN=Linde plc;
LLY=Eli Lilly and Company; LMT=Lockheed Martin; LOW=Lowe's; LRCX=Lam Research; MA=Mastercard;
MCD=McDonald's; MDLZ=Mondelez International; MDT=Medtronic; META=Meta Platforms; MMM=3M;
MO=Altria; MRK=Merck & Co.; MS=Morgan Stanley; MSFT=Microsoft; MU=Micron Technology;
NEE=NextEra Energy; NFLX=Netflix, Inc.; NKE=Nike, Inc.; NOW=ServiceNow; NVDA=Nvidia;
ORCL=Oracle Corporation; PEP=PepsiCo; PFE=Pfizer; PG=Procter & Gamble;
PLTR=Palantir Technologies; PM=Philip Morris International; QCOM=Qualcomm;
RTX=RTX Corporation; SBUX=Starbucks; SCHW=Charles Schwab Corporation; SO=Southern Company;
SPG=Simon Property Group; T=AT&T; TMO=Thermo Fisher Scientific; TMUS=T-Mobile US;
TSLA=Tesla, Inc.; TXN=Texas Instruments; UBER=Uber; UNH=UnitedHealth Group;
UNP=Union Pacific Corporation; UPS=United Parcel Service; USB=U.S. Bancorp; V=Visa Inc.;
VZ=Verizon; WFC=Wells Fargo; WMT=Walmart; XOM=ExxonMobil.

101 tickers. `AAPL` also exists in `config/assets.core.json` — `get_or_create_asset`'s
`ON CONFLICT (ticker) DO UPDATE` makes the overlap safe, no dedupe logic needed.

## Key Learnings

1. `collector/main.py`'s `DEFAULT_ASSETS` fallback (BTC-USD/AAPL/SPY, used only when no `--assets-file` is given) differs from `config/assets.core.json`'s actual 4 tracked assets (BTC-USD/ETH-USD/AAPL/MSFT) — the proposal's "4 existing assets" refers to the latter, which design.md leaves untouched.
2. `collector/schema_check.py`'s `REQUIRED_ML_RELATIONS` already includes `notification_rules`/`notifications` from migration `0007`, confirming design's note that `0005` safely applies after `0007` since it only references `assets` from `0001`.
3. `brain/retraining_job.py`'s `resolve_target_tickers(datasets, tickers)` today takes exactly 2 positional args and returns `sorted(available)` when `tickers` is falsy — the widened-universe risk (~25x targets) is real and current, not hypothetical.
4. `brain/scoped_evaluation.py`'s `select_scope_datasets` has no existing test coverage (per codegraph blast-radius), so the new `max_scope_assets` kwarg's tests in task 3.7 are this function's first ones.
5. Splitting design's single "(4) SEC client + audit recorder" slice into two PRs (client-only, then recorder+job) keeps each near/under the 400-line budget, following the same pattern `telegram-notifications` used for its dispatch slice.
