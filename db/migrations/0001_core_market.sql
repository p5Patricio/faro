-- Core market reference data: assets and historical OHLCV prices.
-- Ported from supabase/migrations/20260515183844_initial_schema.sql.
-- The `signals` table is dropped: confirmed unused by any repository
-- method or caller (proposal "Decisions").

create table if not exists assets (
  id uuid primary key default gen_random_uuid(),
  ticker text unique not null,
  name text,
  asset_class text -- 'stock', 'crypto', 'etf'
);

create table if not exists prices (
  id bigint primary key generated always as identity,
  asset_id uuid references assets(id) on delete cascade,
  timestamp timestamptz not null,
  open numeric,
  high numeric,
  low numeric,
  close numeric,
  volume bigint,
  unique(asset_id, timestamp)
);
