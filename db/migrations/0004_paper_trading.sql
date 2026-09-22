-- Paper trading runs and event timeline.
-- Ported from supabase/migrations/20260707000300_paper_trading_runs.sql,
-- minus the two `enable row level security` lines: this deployment is
-- single-operator/local-only and had zero RLS policies defined for these
-- tables, so RLS only ever worked via Supabase's service-role bypass.

create table if not exists paper_trading_runs (
  id uuid primary key default gen_random_uuid(),
  model_run_id uuid references model_runs(id) on delete set null,
  asset_id uuid references assets(id) on delete cascade,
  name text not null,
  started_at timestamptz,
  ended_at timestamptz,
  params jsonb default '{}'::jsonb,
  metrics jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);

create index if not exists paper_trading_runs_model_asset_idx
  on paper_trading_runs(model_run_id, asset_id);

create index if not exists paper_trading_runs_asset_created_idx
  on paper_trading_runs(asset_id, created_at desc);

create table if not exists paper_trading_events (
  id bigint primary key generated always as identity,
  paper_trading_run_id uuid references paper_trading_runs(id) on delete cascade,
  asset_id uuid references assets(id) on delete cascade,
  timestamp timestamptz not null,
  action text not null,
  confidence numeric,
  price numeric,
  mark_return numeric,
  exposure numeric,
  exposure_delta numeric,
  cost numeric,
  equity numeric,
  position_state text,
  metadata jsonb default '{}'::jsonb
);

create index if not exists paper_trading_events_run_timestamp_idx
  on paper_trading_events(paper_trading_run_id, timestamp);
