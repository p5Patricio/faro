# Proposal: Financial Intelligence Expansion

## Intent

The pipeline is price-only: `FEATURE_COLUMNS_BY_SET` holds two OHLCV-derived sets, four
assets are tracked, and nothing branches on `assets.asset_class` even though the column
exists. There is no fundamental data, no institutional-filing data, no push channel, and
no record of what the operator actually owns — so the platform cannot answer "is this
company financially sound", "did anyone credible just buy this", or "did I act on my own
signal". This change opens those four capability lines on a shared, bias-free footing.

## Scope boundary — the decisive decision

**Recommendation: SPLIT.** Do not deliver this as one change.

The exploration sizes the work at ~10x the 400-line review budget across ~20 tables. The
split is not driven by size — size alone selects chained slices, not separate changes. It
is driven by **independence**: the four areas share no data source, no failure mode, and
no reviewer context (SEC XBRL parsing vs. Telegram transport vs. a personal ledger). One
change would force a single `design.md` spanning all four, an all-or-nothing archive, and
a blocked area (e.g. an SEC IP block) stalling everything.

| # | Change | Depends on | Why separate |
|---|---|---|---|
| 1 | `telegram-notifications` | `local-postgres-migration` | Zero data deps; generalizes `ops/notify_operational_job.py` |
| 2 | **`financial-intelligence-expansion`** (this, rescoped) | 1 | Shared foundation — see In Scope |
| 3 | `fundamental-analysis` | 2 | SEC XBRL + factor math |
| 4 | `institutional-consensus` | 2 | 13F/Form 4/13D parsing; Form 4 first |
| 5 | `personal-finance` | `local-postgres-migration` | Ledger + real holdings; fully parallel |
| 6 | `asset-class-profile-overlays` | 3 | yfinance `funds_data` + CoinGecko; weakest evidence |
| 7 | `gemini-optional-assist` | 5 | Owns `llm_extractions`; last, optional |

**This change is rescoped to the shared foundation** everything else builds on, and doubles
as the charter carrying the constraints below into siblings 3-7.

### In Scope

- **Universe widening to ~100 stocks** (see sub-decision) — `config/assets.core.json`,
  the collector job, and an explicit retraining-target policy.
- `asset_identifiers` — ticker to CIK / CUSIP / CoinGecko id. Needed by 3, 4 and 6.
- `ingestion_runs` — audit of every external fetch; makes staleness and rate-limit
  incidents visible instead of silent.
- A rate-limited, `User-Agent`-declaring SEC HTTP client (shared by 3 and 4).
- The `asset_class`-branching feature-set resolution seam in `brain/features.py`,
  shipped behavior-identical with `technical_v2` as the only registered set.
- Migration `0005_shared_ingestion.sql` (additive, after `0004_paper_trading.sql`).

### Out of Scope

- Every table and feature owned by siblings 3-7 (`fundamental_facts`,
  `institutional_holdings`, `finance_transactions`, `llm_extractions`, ...).
- **Real-money copy trading.** eToro/ZuluTrade require a funded brokerage account and
  execute live orders. Permanently out of scope, not deferred.
- Telegram inbound commands (`/signals`, `/portfolio`) — deferred inside change 1.
- EDGAR full-text search (`efts.sec.gov`) as any pipeline dependency: undocumented and
  unversioned.

## Inherited constraints (binding on siblings 3-7)

| # | Constraint | Enforcement |
|---|---|---|
| C1 | `filed_date`, never `period_end`, is the `features_daily.timestamp` for any externally-sourced feature; plus a 1-trading-day safety lag | Unit test asserting `max(source_filed_date) <= feature_timestamp` for every generated row |
| C2 | Feature sets branch on `assets.asset_class`; `feature_columns_for_set` is the single resolution point; no uniform fundamental schema | Distinct named sets (`fundamental_v1`/`fund_profile_v1`/`crypto_onchain_v1`); never NULL-padded columns |
| C3 | The feature is an **Institutional Consensus Tracker**, never "copy trading"; permanent non-dismissible staleness badge `as of {period_end} · filed {filed_date} · {n} days stale`; 13F short-omission disclosed in the UI, not in a doc | Spec requirement in change 4 |
| C4 | The LLM never emits a trading signal. Upstream schema-constrained cached extraction and downstream explanation only; optional, disabled by default | Spec requirement in change 7 |

## Sub-decision: universe widening

| Question | Decision |
|---|---|
| Which list | S&P 100 (OEX), ~101 names, plus the 4 existing assets |
| Source | **Dated static snapshot checked into the repo**, manually refreshed. No free official constituent API exists (S&P DJI licenses it); scraping Wikipedia is unstable and gray |
| Fundamentals backfill | **SEC DERA quarterly Financial Statement Data Sets** (one zip per quarter, ~26 zips for 2020-2026, all filers) for history; `companyfacts` / `submissions` only for incremental updates on the ~100 watched CIKs. A per-company `companyfacts` loop is ~1 GB and re-downloads everything each run |
| Rate ceiling | 10 req/s per IP, declared `User-Agent`; bulk-first keeps the steady-state request count near zero |
| Price cost | ~160k one-time `prices` rows + ~160k `features_daily` rows, then ~100 rows/day. Negligible for local Postgres |
| **Training cost** | **Not negligible.** `run_retraining_job` loops over *every* ticker with a dataset, and each runs the full candidate matrix; `build_scope_training_frame` at `global` scope concatenates all datasets per fold. 4 to 100 assets is ~25x per fit **and** ~25x more targets — up to ~625x on the global-scope portion of a full retrain |
| Consequence | Widening **MUST** ship with an explicit retraining-target policy: a curated target subset rather than "all assets", and a cap or sample on `global` scope. Today's defaults become infeasible |
| **New bias** | Today's S&P 100 membership applied to a 2020-2026 backtest is **survivorship / index-inclusion bias** — constituents are the survivors and post-inclusion winners. Not eliminable from a free static list. Record the snapshot date, and state the bias in the backtest report rather than implying a clean result |

## Capabilities

### New Capabilities

- `market-universe`: tracked asset universe, its constituent snapshot and refresh
  procedure, cross-source identifier mapping, and the documented membership bias.
- `external-data-ingestion`: rate-limited, audited, bulk-preferring retrieval of
  third-party financial data, with staleness and failure visibility.
- `point-in-time-features`: the `filed_date` timestamping rule and the
  `asset_class`-branched feature-set resolution contract (C1 + C2).

### Modified Capabilities

- `local-persistence`: additive migrations from `0005` onward extend the local schema and
  the `LocalPostgresRepository` method contract.

## Approach

Build on `db/migrations/` + `collector/local_repository.py` from
`local-postgres-migration` — never on Supabase. New tables are additive files after
`0004`; existing migrations are never edited. The SEC client is a thin `requests` module
mirroring the injectable-session shape of `ops/notify_operational_job.py`, so the existing
`FakeSession` test pattern applies unchanged. `feature_columns_for_set` gains an
`asset_class` resolution path while keeping `technical_v2` byte-identical, so no promoted
model changes behavior.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `config/assets.core.json` | Modified | 4 to ~105 entries. A literal expansion is ~800 lines of JSON, over budget — design must choose a compact shared-defaults schema or a generator over a checked-in constituent list |
| `db/migrations/0005_shared_ingestion.sql` | New | `asset_identifiers`, `ingestion_runs` |
| `collector/local_repository.py` | Modified | Methods for the two new tables |
| `collector/providers/` | New | Rate-limited SEC client |
| `brain/features.py` | Modified | `feature_columns_for_set` resolution seam |
| `brain/retraining_job.py`, `brain/run_retraining_job.py` | Modified | Explicit retraining-target policy; `global`-scope cap |
| `collector/market_data_job.py` | Modified | Batched multi-ticker collection |
| `tests/` | New/Modified | C1 look-ahead test, rate-limit test, resolution-seam test |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Look-ahead bias** — dominant silent failure; backtests look excellent and mean nothing | High | C1 as a hard test, not a convention. Fundamental features become sparse and step-shaped: correct, not a bug |
| **Survivorship / index-inclusion bias** from a current-membership snapshot | High | Cannot be removed with free data. Disclose in the backtest report; record snapshot date |
| **Training runtime blowup** (up to ~625x) | High | Explicit retraining-target policy shipped with the widening; measure before and after |
| **SEC rate limit / IP block** | Med | DERA bulk first; hard 10 req/s throttle; declared `User-Agent`; every fetch logged to `ingestion_runs`. A block is not reversible on demand |
| **13F omits shorts** — a long-only reading of a market-neutral fund can be the exact inverse of its real bet | Med | C3: disclosed in the UI at the point of use |
| **Gemini breaks local-only** | Med | C4: optional, disabled by default, cache-backed. Text sent to a third party cannot be unsent |
| Over-fragmentation into 7 SDD changes | Med | This proposal is the shared charter; each sibling declares `depends_on` and inherits C1-C4 |
| Siblings drift from C1-C4 | Med | Each sibling's spec MUST restate the constraints it inherits |

## Rollback Plan

Cleanly reversible: new migrations are additive, so rollback is "stop populating, drop
`0005`". `pg_dump` before the migration and before the universe backfill; tag
`pre-financial-intelligence` first. Each sibling change is independently revertible.

**Not cleanly reversible — accept before starting:**

| Item | Why | Containment |
|---|---|---|
| Universe backfill | ~320k `prices` + `features_daily` rows across ~100 new `assets`, which become FK parents of `predictions`/`backtests` once trained | Documented teardown deleting by `asset_id`, run before any training on the new names; otherwise restore the `pg_dump` |
| Models promoted on the widened universe | `model_runs` is append-only; a widened `global`/`asset_class` scope changes model semantics. Reverting requires re-promoting a prior incumbent, not a delete | Do not retrain on the widened universe in the same slice that adds it |
| `feature_columns_for_set` behavior | A promoted `model_runs.feature_set` resolving to a different column list at inference is a silent shape mismatch | Resolution keyed strictly by the stored `feature_set` string; overlays get distinct names, never mutate `technical_v2` |
| Gemini cache (change 7) | Holds third-party-derived data; the source text was sent off-machine | Dropping the table does not unsend it. Disabled by default |
| SEC IP block | Unblocked on SEC's schedule, not ours | Prevention only |

## Dependencies

- **`local-postgres-migration` must land first.** It deletes `supabase/` and establishes
  `db/migrations/` + `LocalPostgresRepository`. Schema work before it lands guarantees
  conflicts in exactly the files that change most.
- `telegram-notifications` (change 1) recommended before this one, so ingestion failures
  and rate-limit incidents are alertable from the first SEC request.

## Success Criteria

- [ ] `py -3.14 -m db.migrate` applies `0005` on a clean database; `collector.schema_check` passes.
- [ ] `config/assets.core.json` carries ~105 assets and the collector backfills them without tripping any provider rate limit.
- [ ] Every external fetch writes an `ingestion_runs` row, success or failure.
- [ ] `asset_identifiers` resolves a CIK for every stock in the universe; unresolved tickers are logged, never silently skipped.
- [ ] `feature_columns_for_set("technical_v2")` returns the identical column list; existing tests pass unchanged.
- [ ] Full-retrain wall time on the widened universe is measured and documented under the retraining-target policy.
- [ ] Sibling changes 3-7 exist as OpenSpec changes with `depends_on` and restated C1-C4.
