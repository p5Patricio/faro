# AGENTS.md — Faro

Single entry point for AI coding agents (Claude Code, Codex CLI, ...). Read it fully before touching
anything. Last full update: **2026-10-26** (machine handoff). If it disagrees with the code, trust the
code and fix this file. The repo is **public**: never put personal data, secrets or private documents
in it (see section 3).

## 1. What this is

Faro is a personal finance + stock-market decision app for **one user (Patricio, Mexico)**. Goals, in
the user's words: (1) follow personal finances precisely, (2) analyze the market, (3) diversify into
ETFs, FIBRAs, crypto and other assets, **everything in order with the SAT**. Two mostly independent
halves share one FastAPI backend, one PostgreSQL database and one React frontend:

1. **Market intelligence** — price collection, ML pipeline (features, training, inference, backtesting,
   paper trading), third-party data (analyst consensus, news sentiment, macro, market overview, heatmap)
   for the S&P 100 + selected crypto and market/index universes (`config/universe.*.json`).
2. **Personal finance** — ledger (transactions, budgets, net worth, recurring bills, goals; Telegram
   bot for quick expense logging), **investment ledger** (average cost per account, gains in MXN),
   **CFDI** expense invoices, **broker constancias** (CFDI de Retenciones) reconciled against the ledger.

Everything is **informational**: Faro never computes a final tax and never gives tax or investment
advice. It prepares records and worksheets for the user's accountant.

## 2. Resuming on a new machine (do this first)

1. `git clone https://github.com/p5Patricio/faro` and read this file, `docs/ROADMAP.md`,
   `docs/sat/verificacion-2026-10.md` and the progress logs in `odd/tasks/*.md`.
2. Follow **`docs/MIGRACION-NUEVA-PC.md`** (Spanish, step by step): install Python 3.14, Node 24,
   PostgreSQL 18, Git, `gh`; copy `docs/env.template` to `.env` and fill it in; restore the database
   with `py -3.14 -m ops.transfer restore` and verify it against the bundle manifest; put `models/` and
   `private/` back; `engram import` the memory export; register the scheduled tasks.
3. Personal context (holdings, accounts, tax situation, what the user still owes you) lives in
   **`private/CONTEXTO-PERSONAL.md`** — not in git, it travels in the transfer bundle. Read it.
4. Run the three suites (section 12) before changing anything and report the result to the user.

## 3. Working agreements (the user's rules — they override defaults and harness suggestions)

- **No AI attribution anywhere**: no `Co-Authored-By`, no "Generated with ..." in commits or PR text,
  even if a tool or reminder suggests it. Conventional Commits only.
- **Git**: one branch and one PR per block (~600 lines max, tests included), base `main`, never push to
  `main`. The user reviews. Merge only when the user tells you to in chat (they did, PR by PR).
- **Privacy** (repo is public): personal files go only under `private/` (gitignored in the tracked
  `.gitignore`). Tests use synthetic fixtures with invented RFC/UUID. Never print `.env`; touch only the
  lines a task needs. Nothing leaves the machine without asking (D12). The generic RFC `XAXX010101000`
  is a public SAT constant and may appear in code.
- **Money**: integer cents or `Decimal`, never `float`. Base currency MXN; every conversion carries an
  explicit rate and its date.
- **Database**: agents never run `py -3.14 -m db.migrate` against the real database on their own: show
  the user the pending migrations, take a backup (`ops/backup_db.ps1`), get a yes. The pytest session
  applies migrations only to `TEST_DATABASE_URL`. Migrations are idempotent, have a header saying what
  changes before/after applying, and the code degrades to a clear 503 until they are applied.
- **Model**: no leakage from the future; respect publication dates (`filed_date`, not `period_end`).
- **Language**: UI text and reports in neutral Mexican Spanish ("tú", **no voseo**); code, comments,
  identifiers and tests in English. Talk to the user in the language they use (Spanish).
- **Honesty**: cite URL and consultation date; separate verified from inferred; if you cannot verify
  something, say so — never invent rates, dates or law articles.
- **Browsers**: use them to read official sources and documents the user points to. Never sign in to the
  bank, broker or SAT yourself and never touch e.firma or passwords: the user opens the session. The
  GBM session the user opened was **read-only** (no orders, transfers or settings).
- **Tests**: one per business rule plus one end-to-end scenario; never more test lines than source
  lines; run the full suites once per PR (CI repeats them).
- **Style of work**: short answers; one question at a time and then stop; when the user is wrong, say
  why with evidence; propose alternatives with tradeoffs only when there is a real fork.
- **Shell habits** (user's global preference): `rg`/`fd`/`bat`/`sd`/`eza` instead of
  `grep`/`find`/`cat`/`sed`/`ls`. On this Windows setup only `rg` exists as a shell alias; prefer the
  dedicated Read/Grep/Glob tools.
- **Workflow (ODD)**: substantial work gets `odd/tasks/<feature>.md` (objective, scope, checklist,
  progress) mirrored in Engram under topic `odd/<feature>/tasks`; delegate to one writer when a block
  touches 2+ non-trivial files; TDD is off by default; verify before checking items off.

## 4. Architecture map

| Layer | Path | Notes |
|---|---|---|
| API | `api/main.py` | Ticker-scoped market-data routes (`/api/prices/{ticker}`, `/api/analysis/{ticker}`, `/api/predictions/{ticker}`, ...). **Demo-data fallback** on every route: if Postgres is unreachable, or `ALLOW_DEMO_FALLBACK=true` and the repo raises, it serves synthetic data. Rejects unexpected `Host` headers. ~1,300 lines (split pending, B23). |
| API | `api/routers/finance.py` | Personal ledger at `/api/finance`. **No demo fallback**; 503 in clear text when the DB is down. |
| API | `api/routers/cfdi.py` | CFDI 4.0 expense invoices at `/api/finance/cfdi` (`PUT` XML as text, idempotent by stamp UUID; `GET ?year=` with personal-deduction hints by `UsoCFDI`). Parser `brain/finance/cfdi.py` is stdlib-only, refuses DOCTYPE. Labels verified against the official catalog `config/sat/cat-cfdi-4.json`. 503 until `0017`. Hints only. |
| API | `api/routers/investments.py` | Investment ledger at `/api/investments` (accounts, idempotent operations, positions, yearly worksheet JSON/CSV). Math in pure `brain/investments/ledger.py`: **average cost per account**, MXN with dated FX, commissions + IVA added to the cost (LISR art. 129). 503 until `0016`. No INPC cost update. |
| API | `api/routers/retentions.py` | CFDI de Retenciones 2.0 at `/api/investments/retentions` (broker constancias: interest, dividends, sale of shares; `PUT` XML, `GET ?year=` → documents + reconciliation vs ledger + warnings, e.g. issued to the generic RFC). Pure parser/`reconcile_year` in `brain/investments/retenciones.py`. 503 until `0018`. |
| API | `api/routers/heatmap.py`, `markets.py`, `macro.py` | `/api/heatmap?market=us\|mx\|ca` (real market caps), `/api/markets/overview` (Panorama; carries `is_demo`), `/api/macro/overview` (**never synthetic**: `data_sufficient:false` + reason). |
| DB | `db/migrations/*.sql` | Hand-written SQL `0001`–`0018` (next: **0019**), applied by `py -3.14 -m db.migrate` (checksummed in `schema_migrations`; CRLF-insensitive; `.gitattributes` keeps `*.sql` LF). |
| DB access | `collector/local_repository.py` (+ `investment_`, `cfdi_`, `retention_`, `macro_`, `news_repository.py`) | Thin `psycopg3` wrappers. Time series follow **restatement-is-a-new-row**: never overwrite history; read the latest with `ORDER BY ... DESC LIMIT 1`. |
| Data collection | `collector/providers/` | `yfinance`, `binance`, `stooq` (**broken**), `fred`, `banxico`, `finnhub_news`, `sec_edgar_client`; shared `PriceProvider` protocol (`base.py`) and `registry.py`. |
| ML | `brain/` | `features.py` (sets `technical_v2`, `fundamental_v1`, `technical_alpha_v1`, `sentiment_v1`, composed with `compose_feature_set`), `models.py` (walk-forward with `embargo_rows`), `backtesting.py` (real `buy_and_hold` baseline, per-stride Sharpe), `inference_job.py`, `promotion.py`, `portfolio_risk.py`. Trained models are `.joblib` files in `models/` (**outside git**); `model_runs.artifact_uri` stores relative paths. |
| Finance math | `brain/finance/` | `analytics.py`, `currency.py` (FX/cents rules), `liquidity.py`, `recurrence.py`, `cfdi.py`. |
| Tax data | `config/tax/2025.yaml`, `2026.yaml`, `calendario-2026.yaml`; `config/sat/cat-cfdi-4.json` | Parameters with `status` (`verificado` carries `evidence` + `verified_on`), calendar with `checked`. **Not read by any code yet** (B15/B7). |
| Ops | `ops/` | `backup_db.py`/`.ps1`, `transfer.py` + `prepare_transfer.ps1` (machine move), `run_local_scheduler.py`, `retrain_batched.py`, `finance_bot.py` + Telegram modules, notification rules/dispatch, `run_local_app.ps1`, `register_*.ps1`, `harden_scheduled_tasks.ps1`, `run_hidden.vbs`. |
| Frontend | `ui/src/App.tsx` (2,200+ lines, split pending) | Market dashboard (ticker picker, signal, risk, consensus, chart, backtests, paper trading). Tabs: Mercados, Panorama (`features/markets`), Macro (`features/macro`), Mapa de calor (`features/heatmap`), Finanzas (`features/finance`, incl. **Facturas** tab = `CfdiPanel`), Inversiones (`features/investments`, incl. **Constancias** panel). Shared `components/ui/XmlImportForm.tsx`. |
| Frontend | `ui/src/lib/apiBase.ts` | Single source of `API_BASE_URL` (`VITE_API_BASE_URL`, default `http://localhost:8000/api`). |
| Docs | `docs/` | `ROADMAP.md` (blocks B1–B24), `audit/` (30 findings), `research/analisis-de-brechas.md`, `sat/` (Mexico tax research, `verificacion-2026-10.md` = verified parameters + accountant questions), `MIGRACION-NUEVA-PC.md`, `env.template`. `odd/tasks/*.md` = per-feature plans and progress logs. Older root docs (`HANDOFF.md`, `ESTADO_PROYECTO.md`, `PLAN_*`, `INVESTIGACION_*`) are historical. |

## 5. Running it locally

- **Ad hoc dev**: `uvicorn api.main:app --reload` + `npm run dev` in `ui/` (port 5173).
- **Always-on dashboard** (what really runs, at Windows logon): `ops/run_local_app.ps1` starts uvicorn
  *without* reload on `127.0.0.1:47318` and a production build of the UI on `127.0.0.1:47319`
  (ports chosen outside the dev and ephemeral ranges). Idempotent; `-Status` / `-Stop`. **After changing
  code: `-Stop`, then run it again** — no hot reload. Registered as `Faro\LocalAppServers`.
- `VITE_API_BASE_URL` comes from the root `.env` (`ui/vite.config.ts` has `envDir: '..'`) and is baked in
  at Vite build/start time.
- **Scheduled tasks** (Windows Task Scheduler; `schtasks /Create` defaults to "AC power only" and no
  catch-up, which silently skipped runs on this laptop, so every `register_*.ps1` ends with
  `harden_scheduled_tasks.ps1`; all actions go through `run_hidden.vbs` so no console window flashes):
  `Faro\DailyOperationalCycle` 06:20 (`run_local_scheduler --job full`), `Faro\WeeklyRetrainingCycle`
  Sun 06:40, `FaroFundamentalIngestionWeekly` Mon 05:40, `Faro\FinanceBotSync` every 15 min,
  `Faro\DailyBackup` 21:00, `Faro\LocalAppServers` at logon. Two old one-shot retrain tasks
  (`FaroRetrain*`) are obsolete: do not re-register them.
- **Backups**: `ops/backup_db.ps1` → `pg_dump -Fc` + JSON export of the personal tables into
  `FARO_BACKUP_DIR` (keep 14). Postgres 18's `pg_dump` is not on PATH: `PG_DUMP_PATH` in `.env`.
  The user syncs that folder to **their own** Google Drive (not shared) for an off-disk copy.

## 6. Decisions taken (and why)

| Date | Decision | Why |
|---|---|---|
| 2026-08 | Supabase removed; local PostgreSQL only; models as local `.joblib` | Single local operator, no auth, D12 "nothing leaves the machine" |
| 2026-09 | Ledger **average cost per account** (as each broker computes it), not global per issuer | Each constancia can be reconciled line by line; the accountant may prefer another criterion (open) |
| 2026-10 | Commission + IVA go in `fee_cents` and **add to the cost** | LISR art. 129 adds them to the acquisition cost; GBM's displayed average cost excludes them |
| 2026-10 | INPC cost update **not applied** | Needs a verified series (Banxico SIE `SP1`, needs `BANXICO_TOKEN`) |
| 2026-10 | Tax parameters verified against official full texts; every `verificado` carries the quoted article | Phase 3 had only search snippets; see `docs/sat/verificacion-2026-10.md` |
| 2026-10 | Stock losses carry forward **10 years** (art. 129); FIBRA retention is creditable (art. 188 V); foreign dividends pay a definitive 10 % by the 17th of the next month (art. 142 V); bank payments due on a Friday move to the next business day (CFF 12); FX rule: acquisition rate first, else DOF rate of the previous day (CFF 20) | Read in the official texts |
| 2026-10 | Retention reconciliation compares dividends on `MontoTotOperacion` (paid), not the grossed-up `MontDivAcumNal` (×1.4286, art. 140) | The accumulable amount can never match the ledger |
| 2026-10 | Monthly interest is booked **nominal** from statements; the constancia reports **real** interest (lower) | Reconcile when the annual constancia exists; shown separately |
| 2026-10 | `c_UsoCFDI` restricts which receiver regimes may use each use (`regimen_receptor` in the catalog) | Check it before telling the user which use to request on an invoice |
| 2026-10 | Migration checksums ignore CRLF; `.gitattributes` forces `*.sql` LF | `core.autocrlf=true` on Windows made `db.migrate` refuse every migration |
| 2026-10 | Scheduled tasks hardened (run if missed, run on battery) and daily backup at 21:00 | Daily/weekly cycles had been silently refused for weeks (0x800710E0) |
| 2026-10 | `/api/predictions` NaN → `null` (PR #29) | Un-evaluated predictions returned NaN → 500, which the browser reported as CORS |
| 2026-10 | `private/` ignored in the **tracked** `.gitignore` | The old rule lived in `.git/info/exclude`, which a clone does not have |
| 2026-10 | Market value of positions: **mix** of A (Yahoo for listed tickers, USD→MXN with `MXN=X`) and B (manual price for funds without a public feed) | Decided with the user; **not implemented yet** |
| 2026-10 | Machine move via a verified bundle (`ops/prepare_transfer.ps1`), `.env` carried by hand, nothing uploaded | Public repo; personal data; DB dump (178 MB) exceeds GitHub limits |

## 7. Tools used (and their quirks)

- **Runtime**: Python 3.14 (`py -3.14`), Node 24, Vite 8 (Rolldown), React + TypeScript + Tailwind,
  PostgreSQL **18.4** local (CI uses 16 only for tests), FastAPI + psycopg3, pandas/scikit-learn.
- **Quality**: pytest, ruff, ESLint, Vitest + Testing Library, GitHub Actions (backend tests after
  `db.migrate`; UI lint + build), Dependabot (PRs #9–#11 are open and unreviewed).
- **Agent tooling**: Claude Code (desktop), Engram memory (`engram export/import`), CodeGraph
  (`.codegraph/`, ignored; `gentle-ai codegraph init`), `gh` CLI. Browsers: the in-app browser and
  *Claude in Chrome*, which on this machine drives **Microsoft Edge**.
- **Ad hoc**: `winget` (Google Drive for desktop), poppler `pdftotext` (use `-raw` for GBM statements;
  `-layout` misaligns columns), `xlrd` (read the SAT `.xls` catalog; not in `requirements.txt`).
- **Official sources that worked**: diputados.gob.mx PDFs (LISR, CFF, LIF; LIF 2025 is under
  `LeyesBiblio/abro/lif_2025/`), inegi.org.mx (UMA, INPC pages), banxico.org.mx, federalreserve.gov,
  stats.gov.cn, SAT Anexo 20 `catCFDI_V_4_*.xls`. `dof.gob.mx` refused the in-app browser.

## 8. Gotchas

- A migration file in `db/migrations/` does **not** mean it is applied to the real DB.
  `db.migrate --dry-run` still creates `schema_migrations` if it does not exist.
- `pytest` needs `APP_ENV=test` (`tests/conftest.py` sets it with `setdefault`); a real `.env` with
  `APP_ENV=development` exported into the process breaks the Host guard (`testserver` rejected).
- Test ids built from XML text crash `PYTEST_CURRENT_TEST` on Windows: give parametrized cases `ids=`.
- Several `.py` files import `pypfopt`/`transformers`/`torch` lazily; a collection error with
  `ModuleNotFoundError` is a local environment gap, not a bug.
- `vite build` (Rolldown) unwraps CJS default exports differently than the dev server: see
  `unwrapDefault` in `ui/src/features/heatmap/HeatmapDashboard.tsx`.
- The built-in browser cannot render PDFs (it opens a save dialog). Download with the user's approval and
  read with `pdftotext`. Edge marks XML downloads as "Unconfirmed .crdownload": the user must press
  "Conservar". Programmatic JS clicks do not trigger downloads; real clicks do.
- GBM web: only 60 days of history; monthly statements and annual constancias are under
  *Documentos*. On constancias the first click generates the file and the second downloads it.
- `py -I` ignores `PYTHONIOENCODING`: write output files explicitly as UTF-8.
- Changing a scheduled task created from an elevated prompt needs an elevated prompt
  (`Faro\LocalAppServers` was one: re-register it on the new machine from a normal prompt).
- `.agents/`, `.claude/`, `.atl/`, `skills-lock.json` are local AI-tooling cache: do not commit them.
- Windows `git` may warn about LF→CRLF; harmless, `.gitattributes` handles `*.sql`.

## 9. Status by phase (local plan, Phases A–F)

- **A — catch up: done.** PRs #16–#22 merged, migrations `0010`–`0018` applied to the real DB, daily
  backup + restore test, scheduled tasks hardened.
- **B — tax verification: done.** 40/48 parameters and 35/44 calendar dates verified with quotes;
  official CFDI catalog extracted; 8 questions for the accountant in `docs/sat/verificacion-2026-10.md`.
- **C — the user's real data: mostly done.** CFDI importer + UI, broker constancia importer + UI +
  reconciliation, GBM operations/dividends/interest captured in the investment ledger (accounts: Trading
  MX and Smart Cash). **Pending: the bank statement importers** (see section 10).
- **D — new features: not started.** **E — model and data: not started.** **F — quality: not started.**
- Open PRs: **#29** (NaN fix + quantity format — merge before relying on it), Dependabot **#9–#11**.
- Tests at last count: ~980 backend, 151 UI; lint and build clean.

## 10. Pending tasks

**Agent-owned, in order**

1. **Bank statement importers** (the user's two banks; names in `private/CONTEXTO-PERSONAL.md`): YAML
   mapping profile per bank built from a **real** file (never invent columns), preview, per-row
   fingerprint against duplicates, reconcile against CFDI. Waiting for the user's files.
2. **Market value and unrealized P/L in positions** (mix A+B, section 6). Design: A = add the listed
   tickers and `MXN=X` to the collector (they are not tracked today); B = manual price table
   (migration `0019`), API and a small form; show source and date of each price.
3. **GBM statements importer** (repeatable): the capture was done with throwaway scripts that were not
   kept. Parse `pdftotext -raw` output of the monthly statements (operations, dividends, ISR, reporto
   interest). Statements missing locally: Smart Cash 2023–2025, October 2026 onward.
4. **Annual constancia 2026** (issued ~Jan–Feb 2027): import via UI, reconcile real vs nominal interest.
5. **Phase D** (one PR each): server-side watchlist + price/%-move alerts via the Telegram bot (B8);
   fiscal + macro calendar in the app (B7, loads `config/tax/calendario-2026.yaml`, needs `PyYAML`);
   TWR/XIRR and comparison vs S&P 500, IPC, CETES, inflation (B12); assisted FIBRA distributions (B13);
   crypto positions/lots with Koinly/CoinTracker CSV import, no API keys in the repo (B14); allocation
   X-ray and rebalancing (B24).
6. **Phase E**: retrain with the embargo fix and compare against `buy_and_hold`; confidence calibration
   (Brier, reliability curve by decile, isotonic/Platt per fold, M-4); yfinance retries with backoff,
   `change_pct` null with a single bar, incremental download with weekly full refresh (B20); evaluate a
   price API with clear terms as Yahoo backup (`stooq_provider` stays broken).
7. **Phase F**: axe accessibility pass on every view, contrast/focus/responsive table (B22); then split
   `api/main.py` and `ui/src/App.tsx` without changing behavior (B23).
8. Smaller blocks in `docs/ROADMAP.md`: B9 readiness checklist, B11 dated FX in the personal ledger and
   FIRE on investable assets, B15 tax parameters in the app, B17 China macro (optional `akshare`),
   B18 term calculator, B19 more markets.

**User-owned**

- Bring the bank statements (CSV/Excel/PDF) to `private/estados-de-cuenta/`; download expense CFDIs from
  the SAT portal (received, 2026) and upload them in Finanzas → Facturas; have the **accountant** answer
  the 8 questions; optionally email the broker (`Corrección de datos fiscales`) to reissue the 2024
  constancias, which went to the generic RFC.
- Decide: crypto cost method (average / FIFO / specific ID) and the 3-salaries-per-year exemption for
  crypto; when to apply the INPC cost update and with which series.
- Configure `BANXICO_TOKEN`, `FINNHUB_API_KEY`, `SEC_USER_AGENT` (features say "no configurado" until then).
- Keep an off-disk copy of the backups (Google Drive sync is set up) and review Dependabot PRs.

## 11. Improvement proposals not implemented

- Encrypt database backups before they reach the cloud folder (`--encrypt` in `ops/backup_db.py`).
- Align CI with local PostgreSQL (CI runs 16, the machine runs 18; `pg_dump` 18 dumps cannot be restored
  by `pg_restore` 16).
- Show the **real interest loss** (LISR art. 134, carried forward 5 years) as its own tracked figure.
- Make the tax YAML a first-class input (loader + UI status badges) so no number is hard-coded.
- A sentinel opt-in that logs any console window that appears, if the user still sees terminal flashes
  (all Faro tasks were measured clean on 2026-10-20: none spawned a visible console).
- Positions view: allocation by class/country/currency, and a "what changed" panel per month.
- Model governance: survivorship bias (M-5), `adj_close` / total-return labels (M-6), `fundamental_v1`
  covers ~66 of 101 stocks (financials, utilities and quarterly-only filers need sector variants).

## 12. Tests and checks

- Backend: `py -3.14 -m pytest -q` (a few files need `pypfopt`/`torch`/`transformers` to collect).
- Frontend (in `ui/`): `npm run lint`, `npm test`, `npm run build`.
- CI (`.github/workflows/ci.yml`) runs pytest after `python -m db.migrate`, then UI lint + build, on push
  and pull requests.
- Real-app checks after a change: `ops/run_local_app.ps1 -Stop` then run it again; open
  `http://127.0.0.1:47319`; `GET http://localhost:47318/api/health`.
