-- Macro series for Mexico and the US (inflation and interest rates):
-- `macro_series` is the catalog (one row per series, seeded from
-- `collector/macro_catalog.py` by `collector/run_macro_job.py`) and
-- `macro_observations` holds one dated reading per series.
--
-- Unlike the append-only restatement tables (0006, 0010, 0011), an upsert here
-- OVERWRITES: re-fetching a (series_id, observation_date) that already exists
-- replaces its `value` (and refreshes `fetched_at`), because a macro agency's
-- revised figure is the correct one and no point-in-time read depends on the
-- old value.
--
-- What happens BEFORE this migration is applied (the scheduled jobs run this
-- working tree before the migration is applied by hand; there is no migration
-- runner outside `py -3.14 -m db.migrate`):
--   * `collector.run_macro_job` checks that both tables exist, logs that it is
--     skipping, writes a report with `"status": "skipped"` and exits 0. It never
--     creates the tables and never makes the scheduler step fail.
--   * `GET /api/macro/overview` answers 503 with a plain-text Spanish message
--     (the repository wraps the "relation does not exist" error as a
--     RuntimeError and the router turns it into an HTTPException). It never
--     answers 500 and never serves demo data.
-- What happens AFTER it is applied:
--   * The next `collector.run_macro_job` run seeds `macro_series` and upserts
--     the observations it could fetch (Banxico series stay out until
--     `BANXICO_TOKEN` is set in `.env`).
--   * `GET /api/macro/overview` answers 200 right away; every series without
--     rows reports `status: "no_data"` (or `"not_configured"` for a Banxico
--     series while the token is missing) until the first job run fills it.
--
-- DDL follows 0010/0011: `create ... if not exists`, key columns `not null`, no RLS.

create table if not exists macro_series (
  id text primary key,       -- stable key, e.g. 'mx_cetes_28d', 'us_cpi_yoy'
  country text not null,     -- 'MX' | 'US'
  label text not null,       -- display name (es-MX)
  unit text not null,        -- 'percent'
  frequency text not null,   -- 'monthly' | 'weekly' | 'daily'
  source text not null       -- human-readable provenance, e.g. 'INEGI vía Banxico'
);

create table if not exists macro_observations (
  series_id text not null references macro_series(id),
  observation_date date not null,
  value numeric not null,
  fetched_at timestamptz not null default now(),

  primary key (series_id, observation_date)
);
