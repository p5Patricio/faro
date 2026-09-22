-- Personal finance goals: named savings/purchase targets (the book's own
-- worksheet, e.g. "fondo de emergencia", "enganche de casa", "viaje").
-- Follows 0008_personal_finance.sql's conventions: uuid PK, timestamptz,
-- `create ... if not exists`, money as bigint cents, no RLS.
--
-- `current_amount_cents` is MANUALLY updated by the user periodically. It is
-- deliberately NOT auto-derived from linked transactions -- matching the same
-- "not real-time, periodic snapshot" philosophy 0008 already uses for net
-- worth (`finance_net_worth_snapshots` / `finance_net_worth_items`, whose
-- totals are also computed/entered at a point in time, never a live tally).
-- Building a transaction-to-goal allocation system (tagging which ledger
-- rows count toward which goal, splitting partial allocations, handling
-- reassignment) is real double-entry-adjacent complexity nobody asked for --
-- a goal is a target amount plus a hand-entered progress number, nothing
-- more, until that proves insufficient in practice.

create table if not exists finance_goals (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  target_amount_cents bigint not null check (target_amount_cents > 0),
  current_amount_cents bigint not null default 0 check (current_amount_cents >= 0),
  currency char(3) not null,
  target_date date,
  purpose_note text,
  is_achieved boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists finance_goals_active_idx
  on finance_goals(is_achieved, target_date);
