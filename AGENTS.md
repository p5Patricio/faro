# AGENTS.md — Faro

Context for AI coding agents (Claude Code, Codex CLI, etc.) working in this repository.

## What this is

Faro is a personal finance + stock-market decision app for a single user (Patricio). Two
mostly-independent halves share one FastAPI backend, one Postgres database, and one React
frontend:

1. **Market intelligence** — price collection, an ML pipeline (feature engineering, training,
   inference, backtesting, paper trading), and third-party market data (analyst consensus,
   news sentiment) for a tracked universe of tickers (`config/universe.sp100.json`, S&P 100 +
   selected crypto).
2. **Personal finance ledger** — transactions, budgets, net worth, recurring bills, and goals,
   fed by a Telegram bot for quick expense logging.

## Architecture map

| Layer | Path | Notes |
|---|---|---|
| API | `api/main.py` | Ticker-scoped market-data routes (`/api/prices/{ticker}`, `/api/analysis/{ticker}`, `/api/analyst-consensus/{ticker}`, ...). Has a **demo-data fallback** for every route: if Postgres is unreachable, or `ALLOW_DEMO_FALLBACK=true` (dev default) and the repo raises, it serves synthetic data instead of a 500. |
| API | `api/routers/finance.py` | Personal-finance-ledger routes, mounted at `/api/finance`. **No demo fallback** — a personal ledger has no meaningful demo mode; always 503s in clear text when the DB is down. |
| API | `api/routers/heatmap.py` | `/api/heatmap` — S&P-100 treemap tiles. |
| DB | `db/migrations/*.sql` | Sequential, hand-written SQL, applied manually (there is no migration runner — see Gotchas). |
| DB access | `collector/local_repository.py` | `LocalPostgresRepository`, thin `psycopg3` wrapper. Time-series tables (prices, fundamentals, analyst consensus) follow a **restatement-is-a-new-row** philosophy: never overwrite a historical reading, key on `(asset_id, timestamp/fetched_at)`, read the latest with `ORDER BY ... DESC LIMIT 1`. |
| Data collection | `collector/providers/` | One class per data source (`yfinance_provider.py`, `binance_provider.py`, `stooq_provider.py`), a shared `PriceProvider` protocol in `base.py`, and a `registry.py` to look providers up by name. |
| ML pipeline | `brain/` | `features.py` (feature-set registry: `technical_v2`, `fundamental_v1`, `technical_alpha_v1`, `sentiment_v1`, composed via `compose_feature_set`), `backtesting.py`, `inference_job.py`, `portfolio_risk.py`. |
| Ops | `ops/` | Scheduled/CLI jobs (retraining, materialization batches, the Telegram bot, `run_local_app.ps1`/`register_local_app.ps1` for the always-on local dashboard). |
| Frontend | `ui/src/App.tsx` | The market-intelligence dashboard (single large component): ticker picker, ML "signal" (`ModelPanel`), risk panel, analyst-consensus panel, price chart, backtests, paper trading. Tab-switches into `ui/src/features/heatmap/` and `ui/src/features/finance/` for those two separate feature areas. |
| Frontend | `ui/src/lib/apiBase.ts` | Single source of truth for `API_BASE_URL` (env var `VITE_API_BASE_URL`, default `http://localhost:8000/api`). |

## Running it locally

- **Ad hoc dev**: `uvicorn api.main:app --reload` (backend) + `npm run dev` in `ui/` (frontend, port 5173).
- **Always-on local dashboard** (what actually runs on this machine, at Windows logon):
  `ops/run_local_app.ps1` starts uvicorn **without** `--reload` on `127.0.0.1:47318` and a
  **production build** of the frontend (`npm run build && npm run preview`) on
  `127.0.0.1:47319` — deliberately outside both the common dev-port range and Windows'
  ephemeral port range, so it never collides with other local projects. It's idempotent (a
  server already listening is left alone), registered via `ops/register_local_app.ps1` as the
  Windows Task Scheduler task `Faro\LocalAppServers` (ONLOGON trigger, current user, no
  elevation), and opens the dashboard in the default browser once the frontend is actually
  reachable. `-Status` / `-Stop` flags are supported. **After changing backend or frontend
  code, `-Stop` then re-run** — this mode does not hot-reload.
- Both modes read `VITE_API_BASE_URL` from the root `.env` (`ui/vite.config.ts` has
  `envDir: '..'`) — it must match whichever port the API is actually running on, baked in at
  Vite's build/start time (not runtime).

## Conventions worth knowing before editing

- **Two CORS/demo philosophies, by domain**: ticker/market-data routes assume synthetic data is
  fine to show when the DB is down (`api/main.py`); the personal ledger does not
  (`api/routers/finance.py`). Don't port one convention onto the other's routes.
- **Feature sets are additive overlays**: `FEATURE_COLUMNS_BY_SET[name] = compose_feature_set("technical_v2", OVERLAY_COLUMNS)` never mutates the base list. A feature set's column list is
  declared independently of the module that computes those columns (no import), kept in sync by
  a contract test in `tests/test_feature_set_resolution.py` — update both when adding a factor.
- **Analyst consensus** (`collector/providers/yfinance_provider.py::fetch_analyst_consensus`):
  yfinance's `info["numberOfAnalystOpinions"]` can disagree with the sum of
  `recommendations_summary`'s buckets (different analyst panels for price-target vs. rating
  coverage) — the bucket sum is what's used, since that's what public finance widgets display.
- **Windows shell**: ops scripts are PowerShell (`.ps1`), invoked via `cmd.exe /c` from within
  them for the actual long-running process so `Start-Process -WindowStyle Hidden` works cleanly.

## Gotchas

- A migration file existing in `db/migrations/` does **not** mean it's applied — there is no
  migration runner. Apply new ones manually against the local Postgres instance
  (`LOCAL_DATABASE_URL` in `.env`) before the feature that needs the table will work (it falls
  back to demo data / a clean error otherwise, not a crash).
- `vite build`'s bundler (Rolldown, via Vite 8) resolves some CJS packages' default exports
  differently than the `npm run dev` server's esbuild pre-bundling does. `optimizeDeps.include`
  does **not** fix this for the production build (it only affects dev pre-bundling) — see
  `ui/src/features/heatmap/HeatmapDashboard.tsx`'s `unwrapDefault` helper for the pattern used
  to defensively unwrap a CJS default export regardless of how many times it's wrapped.
- `.env` is gitignored and holds real secrets (DB password, Telegram bot token) — never print
  its contents back in full; touch only the specific lines a task actually needs.
- Several `.py` files import optional/heavy dependencies (`pypfopt`, `transformers`, `torch`)
  lazily, inside the function that needs them, specifically so a plain `pytest` run never
  requires them importable. If a test file fails to *collect* with a `ModuleNotFoundError` for
  one of these, that's a local environment gap (package not `pip install`-ed), not a code bug —
  check `requirements.txt` before assuming the dependency is missing from the project.
- `.agents/`, `.claude/`, `.atl/`, `skills-lock.json` are local AI-tooling cache/config
  (vendored skill packages, session lock files, IDE launch config) — not application source.
  Don't commit them.

## Tests

- Backend: `python -m pytest tests/ -q`. A few files (`test_portfolio_risk.py`,
  `test_brain_pipeline.py`, `test_crypto_feature_set.py`) require `pypfopt`/`torch`/
  `transformers` to even *collect* — see the Gotchas note above if they error out locally.
- Frontend: `npm test` (or `npm run test`) inside `ui/`, via Vitest.
