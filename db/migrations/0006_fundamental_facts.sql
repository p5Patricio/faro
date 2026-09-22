-- Tall XBRL fact store. One row per (asset, taxonomy, concept, unit, period,
-- fiscal_period, FILING). A restatement of an already-reported period is a NEW row
-- at a later filed_date, never an update -- that is what makes the as-of read
-- point-in-time by construction (charter C1). DDL follows 0005/0007: identity PK,
-- `create ... if not exists`, FK to assets on delete cascade, explicit unique, no RLS.

create table if not exists fundamental_facts (
  id bigint primary key generated always as identity,
  asset_id uuid not null references assets(id) on delete cascade,
  taxonomy text not null,          -- 'us-gaap' | 'dei' -- the SEC facts.<taxonomy> key
  concept text not null,           -- the RAW SEC tag ('Assets', 'SalesRevenueNet'), not a logical name
  unit text not null,              -- 'USD' | 'shares' | 'USD/shares' -- the units[] key
  period_end date not null,        -- SEC `end`
  fiscal_year integer,             -- SEC `fy`; nullable because SEC omits it on some entries
  fiscal_period text not null,     -- SEC `fp`: 'FY' | 'Q1'..'Q4'; '' when absent
  filed_date date not null,        -- SEC `filed` -- THE point-in-time axis. Never period_end.
  accession text,                  -- SEC `accn` -- provenance back to the exact filing
  value numeric,                   -- SEC `val`
  created_at timestamptz not null default now(),

  -- Natural key = the SEC identity of a reported number. filed_date IS a key column:
  -- drop it and a restatement would UPDATE the original row and silently rewrite
  -- history. Every key column is `not null` on purpose -- Postgres treats NULLs as
  -- distinct in a UNIQUE constraint, so a nullable fiscal_period would let duplicate
  -- rows in AND make `_upsert_batch`'s ON CONFLICT never match (same trap 0007
  -- documents for notification_rules).
  unique (asset_id, taxonomy, concept, unit, period_end, fiscal_period, filed_date)
);

-- Exact shape of the as-of read:
--   WHERE asset_id = %s AND concept = ANY(%s) AND filed_date <= %s
-- Leading (asset_id, concept) is the filter; filed_date desc serves both the range
-- predicate and the "greatest filed_date <= D wins" selection without a sort.
-- The asset_id-only variant (concepts=None) uses the same index by prefix, so one
-- index is enough on a table whose write path is bulk insert.
create index if not exists fundamental_facts_asof_idx
  on fundamental_facts(asset_id, concept, filed_date desc);
