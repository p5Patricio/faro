# Feature: faro-macro-finance-expansion

- Created: 2026-09-29
- Branch: `codex/macro-finance-expansion` (from `origin/main` @ 5e55511)
- Engram mirror: topic `odd/faro-macro-finance-expansion/tasks` (project `faro`)
- Status: in progress (P0: T0.1 and T0.2 done and committed locally, nothing pushed)

## Objective

Turn Faro from "ML signals + a personal ledger" into a decision dashboard for a first-time investor in Mexico:
correct the personal-finance module, track the main stock indices / FX / commodities of MX, US, CA, CN,
add a macro module (inflation, policy rates, CETES and yield curves, release calendar, term comparison),
and add the investment-side features the audits found missing (holdings ledger, trust layer, alerts,
readiness checklist, backup/export).

## Problem and why

- The personal-finance audit (2026-09-29) found confirmed bugs and design flaws while the ledger is still
  EMPTY, so they can be fixed before real data enters: multi-currency sums ignore currency, the Telegram bot
  defaults to USD while accounts are MXN, nothing generates recurring-bill occurrences, the cash-flow
  forecast drops overdue and weekly bills, "investable surplus" and "liquid" are mislabelled estimates,
  dates render one day early, a poison bot message blocks ingestion, es-MX product shows voseo copy.
- There is no inflation/rates/CETES/yield-curve code at all, and no holdings table.
- Index coverage research: yfinance works for US/MX/CA/HK/SSE/SZSE, CSI 300 (`000300.SS`) is broken,
  Asian indices deliver a NaN close for the current day, `stooq_provider` is dead (404 / bot challenge).
- `api/main.py` silently serves demo data when the database fails; nothing tells the user.

## Scope

In: phases P0-P4 below plus docs (T5.1).
Out (deliberately, from product research): custody, order execution, broker connections, personalized
"buy X" advice, tax-owed calculation or filing, public per-ticker signal feed, CSI 300 constituents
(deferred), INEGI direct API, M-bono/Udibono price-to-yield curves, Truflation/PriceStats, money-market
funds data, AFORE projection, earnings/dividend calendars, DCA/Monte-Carlo, allocation/benchmark views
(candidates for a later round).

## Authorized scope

Allowed: edits under `brain/`, `api/`, `collector/`, `ops/`, `ui/`, `db/migrations/`, `config/`, `tests/`,
`AGENTS.md`, `odd/`; local work-unit commits on the feature branch; running tests, lint and builds;
read-only public HTTP requests to verify data sources.

Not authorized without a new explicit user OK: `git push`, opening/merging PRs, applying migrations to the
user's real database (including running `python -m db.migrate` directly), creating accounts or requesting API tokens, reading or editing `.env`, any
off-machine transfer, touching `.atl/`, `.agents/`, `.claude/`, `skills-lock.json`.

## Decisions and assumptions (product defaults; user can override)

- D1 Base currency is MXN. A transaction's currency must equal its account's currency (API 422 on mismatch).
  Aggregates use `amount_base_cents`; a non-base row requires `fx_rate_to_base` (manual, or filled from the
  FX series once T1.3 lands).
- D2 A trailing month counts toward averages only with at least 5 transactions; the UI shows how many
  months were used.
- D3 Investable surplus = income minus non-savings expense; saving is not booked as spending in Neto.
- D4 Macro endpoints never fall back to synthetic data: they answer with `data_sufficient: false` + reason.
- D5 `stooq_provider` is not repaired (it would mean bypassing a bot challenge); it is marked unavailable.
- D6 CSI 300 deferred. Overview uses ASHR as a USD proxy. Heatmap markets this round: us, mx, ca, hk.
- D7 `akshare` is an optional, lazily imported dependency (optional requirements file); China macro
  degrades gracefully when it is absent.
- D8 Banxico data via env var `BANXICO_TOKEN` (free token the user must request). Keyless sources first;
  a missing token yields a typed "not configured" state, never a crash.
- D9 Informational calculators only: no "best term for you"; every rates/term view carries the disclaimer
  "Informational only, not investment advice; indicative, past rates; excludes taxes, fees, liquidity, FX."
- D10 UI copy is neutral es-MX ("tú"); code, comments, tests and docs are English.
- D11 New migrations start at 0012 (check the highest number at write time) and are only WRITTEN by tasks;
  the user applies them with `py -3.14 -m db.migrate`.
- D12 Backups stay on the local machine.
- D13 Development happens in the main checkout on the feature branch, and the scheduled jobs (Telegram bot
  every 15 min, daily 06:20 cycle, weekly retrain) execute this same working tree. So: (a) code that reads
  new tables/columns must degrade gracefully while its migration is unapplied (schema check, skip with a
  clear log line, no crash); (b) wiring new jobs into the scheduled cycles (T1.3, T1.4, T2.6) is guarded by
  that same check; (c) agents never run `python -m db.migrate` directly, because it targets the real
  database through `.env`; the pytest session applies migrations only to the dedicated test database
  (`TEST_DATABASE_URL`, default `ia_inversiones_test`) inside rolled-back transactions.

## Effective settings

- TDD: off. Source: no project/session configuration or user choice found (Engram `sdd-init/faro`
  absent); tests present do not enable TDD. Functional checks still run per task. User can enable it.
- Test runners: backend `py -3.14 -m pytest -q`; frontend (in `ui/`) `npm run lint`, `npm test`
  (vitest), `npm run build`. CI (`.github/workflows/ci.yml`) runs pytest after `python -m db.migrate`,
  and lint + build for the UI, on push to `main`/`codex/**` and on pull requests.
- RDD (native review): off, decided by clone-local setting. No review lifecycle is started.
- Verification gate (RDD off): after each writer returns, the parent runs `gentle-ai review assess` over
  the diff: passive = structural readback; medium = writer self-verification; high or assessment failure =
  writer self-verification plus one independent verifier. The parent re-runs one reported command per task.
- Route for every task: delegated writer, single writer thread, sequential (shared hotspots:
  `api/main.py`, `collector/local_repository.py`, `ui/src/App.tsx`, migrations). Triggers: Writer
  (2+ non-trivial files) and Preparation (reads that prepare the write). No SDD artifacts.
- Delivery strategy: `ask-on-risk`. Forecast about 13,850 authored changed lines (additions plus
  deletions, tests included), above the ~400 budget, so PRs are chained. Chain strategy: `stacked-to-main`
  (user choice, 2026-09-29): slices merge to main in order; slice branches are cut at commit boundaries.
- Planned slices (one PR each): S1 = T0.1-T0.6; S2 = T1.1-T1.4; S3 = T1.5-T1.7; S4 = T2.1-T2.6;
  S5 = T2.7-T2.9; S6 = T2.10-T2.12; S7 = T3.1-T3.2; S8 = T3.3-T3.4; S9 = T4.1-T4.3 + T5.1.
  Slices are functionally coherent, so each is well above 400 lines; the ~400 figure is only a planning
  heuristic per task.

## Blocked on the user

- B1 (resolved 2026-09-29): chain strategy = `stacked-to-main`.
- B2 (before T2.4 runs live): request the free Banxico SIE token and put `BANXICO_TOKEN` in `.env`.
- B3 (before the new UI shows real data): run `py -3.14 -m db.migrate` against the real database.

## Checklist

Each task closes with tests and docs alongside the behavior and a Conventional Commit. Record the commit
id and evidence under Progress.

### P0 Personal-finance correctness (slice S1)

- [x] T0.1 (commit 0888cbf) Currency correctness end to end (~350 lines): D1 rules in API, repository, analytics, UI form
      and net-worth totals; bot uses the account's currency (drop the hard-coded USD default); mixed-currency
      regression tests. Files: `brain/finance/analytics.py`, `api/routers/finance.py`,
      `collector/local_repository.py`, `ops/finance_bot.py`, `ui/src/features/finance/**`.
- [x] T0.2 (commit 46141d3) Recurring-bill lifecycle and forecast (~300): generate the next pending occurrence on save and on
      paid; `compute_cash_flow_forecast` takes `today`, includes overdue bills, expands weekly/biweekly
      occurrences inside the horizon, returns integer cents; panel states updated.
- [ ] T0.3 Surplus and liquidity semantics (~450): D2 and D3; migration 0013 adds `is_liquid` to net-worth
      items; emergency fund uses liquid items; "Sin categoría" bucket and full category breakdown; truthful
      `data_sufficient` and live empty states; "estimado" labels.
- [ ] T0.4 Ingestion and API robustness (~400): bot amount cap, confirm only after the write, failed-batch
      logging and cursor policy, parse `$120` and `120 mxn`, confirmation shows kind and currency,
      ambiguous-keyword handling; API payloads typed (UUID/date) so bad input is 422 not 503; pin the
      Postgres session timezone to America/Mexico_City for month boundaries; `api/main.py` `__main__` binds
      127.0.0.1.
- [ ] T0.5 UI correctness and copy (~350): neutral es-MX copy; date-only strings parsed as local dates
      (`format.ts`, net-worth panel); fetch abort/sequence guard; inline error states for bills, goals,
      transactions.
- [ ] T0.6 UI design, accessibility, editing (~350): budget flow diagram drawn from real ratios with HTML
      labels; contrast tokens, labelled inputs, tab-bar affordance, drawer focus trap; transactions table
      shows notes, responsive columns, no raw UUID in confirms, visible list-cap message; edit/deactivate UI
      for bills and goals.

### P1 Trust layer and market trackers (slices S2, S3)

- [ ] T1.1 Trust layer (~350): API marks demo responses (header or payload flag) on ticker/market routes;
      `DataSourceBadge` (source, as-of, stale), loud DEMO banner, "not financial advice" footer.
- [ ] T1.2 Asset metadata and market-cap storage (~350): migration adds nullable currency, exchange,
      country, timezone to `assets` and a restatement-style `asset_market_caps` table keyed by
      `(asset_id, fetched_at)`; repository methods; universe format gains `yahoo_ticker`.
- [ ] T1.3 Index, FX, commodity, yield ingestion (~600): universe file with about 20 tickers (US/MX/CA/CN/HK
      indices, MXN=X, CNY=X, CAD=X, CL=F, GC=F, ^TNX, ^IRX, ^FVX, ^TYX), asset classes `index`, `fx`,
      `commodity`, `yield`; keep them out of the ticker picker and ML training; ASHR proxy for CSI 300;
      keep NaN-close rows from silently lagging Asian series; schedule after Asian close and next morning;
      per-ticker health check into `ingestion_runs`; mark `stooq_provider` unavailable (D5).
- [ ] T1.4 Real market caps (~350): weekly job with `fast_info.marketCap` and `.info` fallback (store market
      cap, not shares outstanding); heatmap uses real values, placeholder only when missing and flagged.
- [ ] T1.5 Multi-market heatmap backend (~500): universe snapshots for IPC, S&P/TSX 60, Hang Seng under
      `config/`, per-market sector maps, `GET /api/heatmap?market=us|mx|ca|hk`, currency labels.
- [ ] T1.6 Markets overview API (~350): `GET /api/markets/overview` (index cards with last, change %,
      freshness; FX; commodities; yields).
- [ ] T1.7 Markets UI (~400): "Mercados" view with cards, sparklines, badges; market switcher in the heatmap.

### P2 Macro module (slices S4, S5, S6)

- [ ] T2.1 Macro storage (~350): migration for `macro_series` and `macro_observations`
      (restatement-as-new-row, `observation_date`, `release_date`, `fetched_at`); repository methods;
      freshness query.
- [ ] T2.2 US providers, keyless (~400): Treasury par/real/bill CSV, FRED `fredgraph.csv` (T10YIE, T5YIE,
      DFF, DFEDTARU/L, CPI/PCE series), BLS v1 CPI; fixtures; mockable HTTP; typed errors.
- [ ] T2.3 Canada providers, keyless (~300): Bank of Canada Valet (policy rate, yields, CPI trim/median/
      common), Statistics Canada WDS CPI.
- [ ] T2.4 Banxico provider (~450): `BANXICO_TOKEN`; series SP30578, SP74662, SF61745, SF43783,
      SF43936/39/42/45, SF45470-73, SF349889, FIX SF43718; 200-per-5-minutes limit handling; fixtures;
      typed "not configured".
- [ ] T2.5 China provider (~400): lazy optional `akshare` (CPI, PPI, LPR, government bond yields),
      last-date freshness assertion and stale flag; optional requirements file.
- [ ] T2.6 Macro ingestion job and scheduling (~400): `collector/run_macro_job.py`, daily cadence plus
      release-day polling, freshness assertions, `ingestion_runs`, `--job macro` in `ops/run_local_scheduler.py`
      and the daily cycle, stale-data notification.
- [ ] T2.7 Pure analytics (~450): real rate, term comparison with day-count normalization (CETES 360 simple
      vs Treasury bond-equivalent), inversion indicators (3M-10Y, 2s10s, CETES 28d vs 364d), breakeven
      proxies (US T10YIE, MX Bono10y vs Udibono10y, CA long minus RRB), CETES vs T-bill breakeven
      depreciation; known-value tests.
- [ ] T2.8 Release calendar seed (~250): `config/macro_calendar.yaml` (Banxico, FOMC, BoC, PBoC LPR on the
      20th, INEGI/BLS/StatCan where dates are published; unverified dates marked), loader, tests.
- [ ] T2.9 Macro API (~500): `/api/macro/*` (inflation, rates, curves, calendar, term-comparison) with
      freshness and source attribution ("Fuente: INEGI / Banxico / FRED / ..."); D4 behavior; documented in
      `AGENTS.md`.
- [ ] T2.10 Inflation tracker UI (~600): MX/US/CA/CN last official print, YoY, core, next release date,
      market-implied proxy chart; explicit note that official inflation is biweekly/monthly.
- [ ] T2.11 Rates and curves UI (~600): policy rates, CETES primary/secondary table, yield-curve charts
      (US, CA, MX CETES), inversion badges.
- [ ] T2.12 Term calculator and calendar UI (~500): user-entered amount and term, real rate, CETES vs
      T-bill in MXN with FX risk, disclaimer (D9), release calendar panel.

### P3 Investment ledger (slices S7, S8)

- [ ] T3.1 Ledger schema and pure analytics (~700): migration for investment accounts and transactions
      (buy, sell, dividend, distribution, fee) with `numeric` quantity/price, native currency, FX at trade
      date, `client_id` idempotency; average cost including commissions; realized/unrealized P&L in native
      currency and MXN; dividends received.
- [ ] T3.2 Investments API (~500): accounts, transactions (soft delete), positions, P&L, dividends;
      validation; tests.
- [ ] T3.3 Investments UI (~600): positions table, transaction form, P&L summary, currency and freshness
      labels.
- [ ] T3.4 CSV import/export and yearly worksheet (~450): idempotent import; yearly realized gains,
      dividends, distributions, interest by source as a record for an accountant (no tax computed, explicit
      disclaimer).

### P4 Product extras (slice S9)

- [ ] T4.1 Server-side watchlist and price / percent-move alerts (~600): new notification rule types with
      cooldown and dedupe on the existing pipeline; UI watchlist replacing local pins.
- [ ] T4.2 Investment-readiness checklist (~350): facts, not verdicts (liquid emergency-fund months,
      liabilities, consecutive surplus months, goal horizon, risk profile set).
- [ ] T4.3 Backup and export (~250): `ops/backup_db.ps1` writing `pg_dump` to a user-chosen local folder
      with retention; JSON/CSV exports; no off-machine copy (D12).

### Docs

- [ ] T5.1 `AGENTS.md` (~100): migration runner exists (`python -m db.migrate`), macro no-silent-demo
      convention, new asset classes, es-MX copy convention, trust layer.

Task count: 33 (P0 6, P1 7, P2 12, P3 4, P4 3, docs 1).

## Acceptance criteria

- P0: mixed-currency data cannot corrupt totals; a new bill produces a pending occurrence and appears in
  the forecast; estimates are labelled; date-only values never shift a day; no untyped input yields 503.
- P1: every tracked index/FX/commodity/yield has a health status; heatmap tiles use real market caps or
  visibly flagged placeholders; demo data is always visibly labelled.
- P2: every macro figure shows source, as-of date and staleness; no synthetic macro data; calculators carry
  the D9 disclaimer; missing token or optional dependency degrades gracefully.
- P3: positions and P&L reproduce hand-computed fixtures; import is idempotent.
- P4: alerts respect cooldowns; checklist states facts only; backup restores into an empty database.
- All: full backend suite and frontend lint/test/build green at each task close; CI green before any push.

## Applicable checks

Backend `py -3.14 -m pytest -q` (baseline measured by T0.1 before edits; last known full-suite result 611
passed); frontend `npm run lint`, `npm test`, `npm run build` in `ui/`; migrations exercised by the test
database via `db.migrate`; data-source claims verified with live read-only requests.

## Progress

- 2026-09-29: audits and research complete; plan written; branch created. No source writes.
- 2026-09-29: added D13 after confirming the scheduled jobs run this working tree and that
  `tests/conftest.py` isolates tests in a separate database while a bare `db.migrate` hits the real one.

## Verification evidence

- T0.1 (commit 0888cbf, branch codex/macro-finance-expansion, not pushed):
  - Baseline before edits: backend 611 passed; ui lint ok, 36 vitest, build ok.
  - After: backend 682 passed (`py -3.14 -m pytest -q`, writer); ui 53 vitest, lint and build ok (writer, before the follow-up fixes, which touched no `ui/` file).
  - Parent spot check: 5 finance test files, 150 passed.
  - Runtime scenario: `test_runtime_scenario_summary_of_a_mixed_currency_month_uses_base_amounts` (TestClient PUTs USD + MXN transactions, reads `/summary` and `/budgets`; expense 187500 base cents, unconverted 0).
  - Risk gate: assess returned high (untracked files unassessable); independent verifier verdict OK TO COMMIT; its MAJOR/MINOR fixes applied (migration header, bot reply, bigint bounds + ArithmeticError to 422, `upper(trim(currency))`).
  - Rollback boundary: revert commit 0888cbf; migration 0012 is data-only and can be dropped alone.
  - Real database check (read-only API): the four accounts are already MXN, so 0012 is a no-op there.

## Decisions updated

- Chain strategy resolved 2026-09-29: `stacked-to-main` (supersedes the "PENDING" text above); B1 is closed.
- T0.3's migration is now 0013 (0012 is taken by the data-only account-currency migration).
- Deferred to later tasks: per-trailing-month unconverted counts and skipping months with zero converted rows (T0.3), `unconverted_bills` warning and error detail text in the UI (T0.5/T0.6), soft-delete of a legacy row whose currency differs from its account (residual, legacy-only).
- Editing 0012's header changed its checksum; only the test database had recorded the old one (its `schema_migrations` row was updated). Any other database that applied the earlier 0012 would fail the drift check (the real database never applied it).
- Engram mirror resynced at T0.2 closure (this file remains the source of truth).

## T0.2 evidence and decisions

- Commit 46141d3 (not pushed). Baseline 682 backend / 53 vitest; after 798 / 69, lint and build ok (writer). Parent spot checks: 184 passed before, 120 passed after a docstring-only fix (recurrence, repository, analytics files).
- Runtime scenario: `test_runtime_scenario_a_weekly_bill_flows_through_the_forecast_and_advances_when_paid` (clock pinned 2026-09-29): committed = 5 x 15,000 for Sep 30, Oct 7/14/21/28; after paying Sep 30 the next due date is Oct 7 and committed = 4 x 15,000.
- Risk gate: assess unassessable (untracked files) = high; independent verifier: OK TO COMMIT (6,000-case fuzz of the recurrence math against a brute-force implementation, 0 mismatches; tree integrity confirmed, stash list empty).
- Rollback boundary: revert 46141d3; no schema change.
- D14 First pending = earliest occurrence on or after today; on paid/skipped the next pending = earliest occurrence strictly after the settled due date (may be overdue); no automatic ledger transaction.
- D15 Forecast counts an overdue pending row once plus every later occurrence in [today, today + horizon] (inclusive, so 31 calendar days against income scaled 30/30; add a docstring line in T0.3).
- D16 Reactivating a bill keeps its old pending row (overdue until skipped); docstring corrected. Revisit in T0.6 when edit/deactivate UI makes it reachable.

## Deferred from the T0.2 review

- T0.3: migration 0013 adds a partial unique index (one pending row per bill) and the repository keeps the earliest unlinked pending row (a PUT `pending` on another date can currently add a second one); test that a legacy non-base bill is excluded from the forecast; forecast panel must show committed/overdue bills even without income history (truthful `data_sufficient`); docstring on the 31-day window.
- T0.4: typed UUID/date payloads (unknown bill `id` gives 503; a 9999-12-31 due date overflows to 500); restrict or validate the `pending` status on the payment PUT.
- T0.6: on reactivation drop stale unlinked overdue rows or make the UI clear them; edit/deactivate UI.
- Inactive-bill upsert response returns `next_due_date: None` while the list shows the surviving pending row (NIT).

## Next step

T0.3 (surplus and liquidity semantics, migration 0013) with one delegated writer; then T0.4-T0.6, then open the S1 PR (needs the user's OK to push).
