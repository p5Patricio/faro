-- Real market capitalization history: one row per (asset, fetch), in the
-- asset's trading currency (USD for the S&P 100, MXN for the IPC, CAD for the
-- S&P/TSX 60). Like 0010_analyst_consensus.sql this is an append-only time
-- series: a new reading is a new row keyed by when it was fetched, never an
-- overwrite, and `ORDER BY fetched_at DESC LIMIT 1` (per asset) serves the
-- current figure. `collector.run_market_cap_job` fills it from yfinance as the
-- last, non-fatal step of the weekly cycle (`--job full_retrain`).
--
-- What happens BEFORE this migration is applied (the scheduled jobs and the API
-- run this working tree before the migration is applied by hand; there is no
-- migration runner outside `py -3.14 -m db.migrate`):
--   * `GET /api/heatmap` keeps working for us/mx/ca: no real market cap can be
--     read, so every tile uses the old deterministic placeholder estimate
--     (price x a per-ticker pseudo share count) and is flagged with
--     `market_cap_estimated: true`. It never answers 500 or 503 because of the
--     missing table.
--   * `collector.run_market_cap_job` checks that the table exists, logs that it
--     is skipping, writes a report with `"status": "skipped"` and exits 0. It
--     never creates the table and never makes the scheduler step fail.
-- What happens AFTER it is applied:
--   * The table starts empty, so the heatmap still shows the flagged placeholder
--     estimate until the first `collector.run_market_cap_job` run (or the next
--     weekly cycle) stores caps.
--   * From then on each tile uses the latest stored real market cap with
--     `market_cap_estimated: false`; a ticker with no stored value keeps the
--     flagged estimate.
--
-- Every key column is `not null` for the same reason 0006 calls out: Postgres
-- treats NULLs as distinct in a UNIQUE constraint. The primary key doubles as
-- the "latest per asset" index (asset_id first, fetched_at scanned backwards).

create table if not exists asset_market_caps (
  asset_id uuid not null references assets(id) on delete cascade,
  fetched_at timestamptz not null default now(),
  market_cap numeric not null check (market_cap > 0),
  currency char(3) not null,  -- 'USD' | 'MXN' | 'CAD'
  source text not null,       -- e.g. 'yfinance'

  primary key (asset_id, fetched_at)
);
