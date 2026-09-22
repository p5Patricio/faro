-- Raw news headlines + a computed sentiment score, one row per (asset,
-- source, published_at, headline). Exactly the same restatement philosophy
-- as 0006_fundamental_facts.sql and 0010_analyst_consensus.sql: this is an
-- append-only time series, never a single row overwritten per ticker --
-- re-fetching an overlapping date range upserts onto the same natural key
-- instead of duplicating.
--
-- `published_at` is THE point-in-time axis (mirrors 0006's `filed_date`
-- comment): `brain/sentiment_factors.py` filters every read by
-- `published_at <= cutoff`, never `ingested_at`. `ingested_at` only records
-- when this database learned about the headline -- typically a day or more
-- AFTER `published_at` for a batch job, and occasionally BEFORE it for a
-- provider that backfills same-day intraday news ahead of this table's own
-- nightly run. Gating on `ingested_at` instead of `published_at` would leak
-- exactly the kind of future information this table exists to keep out.
--
-- `sentiment_score`/`sentiment_label` are nullable: a headline is stored the
-- moment it is fetched from Finnhub, before `brain/sentiment_factors.py`
-- (lazy FinBERT) has necessarily scored it -- see that module's docstring
-- for why scoring is a separate, optional step from ingestion.
--
-- DDL follows 0006/0010: bigint identity PK, `asset_id` FK to `assets`, all
-- key columns `not null` (Postgres treats NULLs as distinct in a UNIQUE
-- constraint, so a nullable key column would both let duplicate rows in and
-- make the upsert's ON CONFLICT never match -- same trap 0006/0007 call
-- out), `create ... if not exists`, no RLS.

create table if not exists news_headlines (
  id bigint primary key generated always as identity,
  asset_id uuid not null references assets(id) on delete cascade,
  source text not null,             -- 'finnhub' | ... -- the provider name
  headline text not null,
  published_at timestamptz not null,-- THE point-in-time axis. Never ingested_at.
  summary text,
  url text,
  sentiment_score double precision, -- null until scored; typically [-1, 1]
  sentiment_label text,             -- null until scored; 'positive' | 'neutral' | 'negative'
  ingested_at timestamptz not null default now(),

  unique (asset_id, source, published_at, headline)
);

-- Exact shape of the as-of read (mirrors fundamental_facts_asof_idx):
--   WHERE asset_id = %s AND published_at <= %s
-- Leading asset_id is the filter; published_at desc serves both the range
-- predicate and the trailing-window read without a sort.
create index if not exists news_headlines_asof_idx
  on news_headlines(asset_id, published_at desc);
