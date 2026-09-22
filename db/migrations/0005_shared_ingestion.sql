-- Cross-source identifier map + external-fetch audit. DDL follows 0004/0007:
-- uuid/identity PKs, timestamptz, jsonb default '{}', create ... if not exists, no RLS.

create table if not exists asset_identifiers (
  id uuid primary key default gen_random_uuid(),
  asset_id uuid not null references assets(id) on delete cascade,
  id_type text not null,        -- 'cik' | 'cusip' | 'coingecko_id' | 'isin'
  id_value text not null,
  source text not null,         -- 'sec_company_tickers' | 'manual'
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (asset_id, id_type)    -- upsert conflict target
);

-- Deliberately NOT unique: share classes (GOOG/GOOGL) share one CIK, so the
-- reverse lookup is one-to-many. A unique index here would reject valid data.
create index if not exists asset_identifiers_lookup_idx
  on asset_identifiers(id_type, id_value);

create table if not exists ingestion_runs (
  id bigint primary key generated always as identity,
  source text not null,         -- 'sec_edgar' | 'yfinance' | 'coingecko'
  endpoint text not null,       -- 'company_tickers' | 'companyfacts' | 'submissions'
  target_key text not null default '',   -- CIK/ticker; '' for universe-wide fetches
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null,         -- 'success' | 'failure' (spec wording; note this
                                -- deliberately differs from notifications.status 'failed')
  http_status integer,
  rows_written integer not null default 0,
  request_count integer not null default 0,
  throttle_wait_seconds numeric not null default 0,
  -- Point-in-time audit: the newest source filing date this run made available.
  -- A first-class column, not a jsonb key, because "which filing dates were
  -- available for this run" is a spec-required query.
  max_filed_date timestamptz,
  error text,                   -- never contains SEC_USER_AGENT (operator email)
  metadata jsonb not null default '{}'::jsonb  -- {unresolved_tickers: [...], failure_kind: 'rate_limited'|...}
);

-- Append-only audit: no unique constraint, so _insert_batch applies.
create index if not exists ingestion_runs_source_started_idx
  on ingestion_runs(source, endpoint, started_at desc);
-- Partial index = the incident/staleness read, mirroring 0007's cooldown index.
create index if not exists ingestion_runs_failures_idx
  on ingestion_runs(started_at desc) where status <> 'success';
