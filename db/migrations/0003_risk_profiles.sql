-- Scope-only risk profiles: no authentication, no `user_id`, no RLS.
-- Rewritten from supabase/migrations/20260707000100_user_risk_profiles.sql
-- and 20260707000200_scoped_user_risk_profiles.sql: this repository is
-- single-operator/local-only, so the scope check constraint and the
-- (scope_type, scope_value) uniqueness are folded directly here instead of
-- a follow-up ALTER (no rows exist on a fresh database to migrate around).
-- This table MUST start empty (spec "Scope-Only Risk Profiles Start Empty").

create table if not exists risk_profiles (
  id uuid primary key default gen_random_uuid(),
  name text not null default 'default',
  scope_type text not null default 'default',
  scope_value text not null default '',
  max_position_size numeric not null default 0.10,
  min_confidence_to_trade numeric not null default 0.60,
  max_expected_risk numeric not null default 0.05,
  stop_loss numeric not null default 0.02,
  take_profit numeric not null default 0.04,
  allow_short boolean not null default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  constraint risk_profiles_scope_check check (
    (scope_type = 'default' and scope_value = '')
    or (scope_type in ('asset_class', 'ticker') and scope_value <> '')
  ),
  unique (scope_type, scope_value)
);
