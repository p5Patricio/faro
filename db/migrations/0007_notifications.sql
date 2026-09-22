-- Rule-driven outbound alerting: persisted rules + a delivery log.
-- DDL follows 0004_paper_trading.sql: uuid/identity PKs, timestamptz,
-- jsonb default '{}', `create ... if not exists`, no RLS.
--
-- rule_type naming: job_failure, signal_transition, model_degradation,
-- stale_data -- matching the operational-notifications spec's Four-Trigger
-- Rule Catalog requirement wording exactly.

create table if not exists notification_rules (
  id uuid primary key default gen_random_uuid(),
  rule_type text not null,
  asset_id uuid references assets(id) on delete cascade,   -- null = global rule
  channel text not null default 'telegram',
  params jsonb not null default '{}'::jsonb,
  cooldown_minutes integer not null default 1440,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Two partial indexes, not `unique (rule_type, asset_id, channel)`: Postgres treats
-- NULLs as distinct in a UNIQUE constraint, so two identical *global* rules would both
-- be allowed. `unique nulls not distinct` needs PG15+; partial indexes work on any version.
create unique index if not exists notification_rules_scoped_key
  on notification_rules(rule_type, asset_id, channel) where asset_id is not null;
create unique index if not exists notification_rules_global_key
  on notification_rules(rule_type, channel) where asset_id is null;
create index if not exists notification_rules_active_idx
  on notification_rules(rule_type) where is_active;

create table if not exists notifications (
  id bigint primary key generated always as identity,
  rule_id uuid references notification_rules(id) on delete set null,
  rule_type text not null,          -- denormalized: log survives rule deletion,
  asset_id uuid references assets(id) on delete set null,  -- and cooldown needs no join
  scope_key text not null default '',   -- sub-asset cooldown scope (model_name, job_mode)
  channel text not null,
  dedupe_key text not null,
  severity text not null default 'info',
  title text not null,
  body text not null,
  status text not null,             -- 'sent' | 'failed'
  error_reason text,
  payload jsonb not null default '{}'::jsonb,
  fired_at timestamptz not null default now()
);

-- PARTIAL unique: only *delivered* messages dedupe. A plain `unique(dedupe_key)` would let
-- one failed attempt permanently block the retry of that same alert -- a Telegram outage would
-- silently swallow a P0 forever. Failures accumulate as history; exactly one send survives.
create unique index if not exists notifications_dedupe_sent_key
  on notifications(dedupe_key) where status = 'sent';

-- Exact shape of the cooldown read. Partial on 'sent' for the same reason: a failed
-- delivery must not start a cooldown window.
create index if not exists notifications_cooldown_idx
  on notifications(rule_type, asset_id, scope_key, fired_at desc) where status = 'sent';

insert into notification_rules (rule_type, channel, params, cooldown_minutes) values
  ('job_failure',        'telegram', '{"min_failed": 1}'::jsonb, 0),
  ('signal_transition',  'telegram', '{"min_confidence": 0.55, "actions": ["BUY", "SELL"]}'::jsonb, 0),
  ('model_degradation',  'telegram', '{"min_feedback_samples": 20, "min_accuracy": 0.45, "min_mean_outcome_return": 0.0}'::jsonb, 1440),
  ('stale_data',         'telegram', '{"max_price_age_hours": 72.0}'::jsonb, 1440)
on conflict do nothing;
