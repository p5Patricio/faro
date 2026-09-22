-- Wall Street analyst consensus history: one row per (asset, fetch). Ratings
-- and price targets drift every few days, so -- exactly like
-- 0006_fundamental_facts.sql's restatement philosophy -- this is an
-- append-only time series, never a single row overwritten per ticker. A new
-- reading is a new row keyed by when it was fetched, not upserted over the
-- last one, so `SELECT ... ORDER BY fetched_at DESC LIMIT 1` always serves
-- the current view while history stays intact for trend/drift analysis later.
--
-- Every key column is `not null` for the same reason 0006 calls out: Postgres
-- treats NULLs as distinct in a UNIQUE constraint, so a nullable key column
-- would both let duplicate (asset_id, fetched_at) rows in AND make the
-- upsert's ON CONFLICT never match.

create table if not exists analyst_consensus_snapshots (
  id bigint primary key generated always as identity,
  asset_id uuid not null references assets(id) on delete cascade,
  fetched_at timestamptz not null,
  source text not null,
  recommendation_key text not null,
  recommendation_mean numeric not null,
  analyst_count integer not null,
  strong_buy integer not null,
  buy integer not null,
  hold integer not null,
  sell integer not null,
  strong_sell integer not null,
  target_mean numeric not null,
  target_median numeric not null,
  target_high numeric not null,
  target_low numeric not null,
  created_at timestamptz not null default now(),

  unique (asset_id, fetched_at)
);

-- Serves "latest snapshot per ticker" (GET /api/analyst-consensus/{ticker})
-- without sorting the full history: leading asset_id is the filter,
-- fetched_at desc lets `ORDER BY fetched_at DESC LIMIT 1` use the index
-- directly instead of a sort.
create index if not exists analyst_consensus_snapshots_latest_idx
  on analyst_consensus_snapshots(asset_id, fetched_at desc);
