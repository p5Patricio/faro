-- Investment ledger: brokerage/exchange accounts and their operations (buys,
-- sells, splits, dividends, FIBRA distributions, capital returns, interest,
-- fees). The positions, average cost and realized gains are NOT stored: they
-- are derived on every read by `brain/investments/ledger.py`, so a corrected
-- operation can never leave a stale derived figure behind.
--
-- Money conventions (same as the personal ledger, 0008/0012): every amount is
-- `bigint` cents in the operation's own currency; quantities and unit prices
-- are `numeric` (fractional shares and crypto). An operation in a currency other
-- than MXN carries the rate it was converted with AND that rate's date and
-- source, because a figure for an accountant is only useful if the rate can be
-- traced (CFF art. 20 talks about the FIX published the day before).
--
-- What happens BEFORE this migration is applied (the API and the scheduled jobs
-- run this working tree before the migration is applied by hand with
-- `py -3.14 -m db.migrate`):
--   * Every `/api/investments/*` route answers 503 with the text "falta aplicar
--     la migración 0016" instead of failing with a database error. Nothing else
--     in the app reads these tables.
-- What happens AFTER it is applied:
--   * Two empty tables. Nothing is backfilled; the ledger starts empty.
--
-- Idempotent: `create table if not exists` / `create index if not exists`.

create table if not exists investment_accounts (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  broker text,
  currency char(3) not null default 'MXN',
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists investment_transactions (
  id uuid primary key default gen_random_uuid(),
  -- Idempotency key: the UI generates it; an importer derives it
  -- deterministically (CFDI UUID, CSV row hash), so a re-import is a no-op.
  client_id uuid not null unique,
  account_id uuid not null references investment_accounts(id),
  trade_date date not null,
  kind text not null check (kind in (
    'buy', 'sell', 'split', 'dividend', 'fibra_distribution', 'capital_return', 'interest', 'fee'
  )),
  symbol text not null,
  instrument_type text not null default 'otro' check (instrument_type in (
    'accion_mx', 'accion_sic', 'etf', 'fibra', 'fondo', 'deuda', 'cripto', 'otro'
  )),
  -- Units bought/sold, or the split factor (2 = two-for-one). Null otherwise.
  quantity numeric(28, 10) check (quantity is null or quantity > 0),
  price numeric(28, 10) check (price is null or price >= 0),
  amount_cents bigint not null default 0 check (amount_cents >= 0),
  fee_cents bigint not null default 0 check (fee_cents >= 0),
  tax_withheld_cents bigint not null default 0 check (tax_withheld_cents >= 0),
  currency char(3) not null,
  fx_rate_to_mxn numeric(18, 8) not null check (fx_rate_to_mxn > 0),
  fx_rate_date date,
  fx_source text,
  source text not null default 'manual',
  source_ref text,
  notes text,
  created_at timestamptz not null default now(),
  deleted_at timestamptz,
  check (kind not in ('buy', 'sell', 'split') or quantity is not null)
);

create index if not exists investment_transactions_account_date_idx
  on investment_transactions (account_id, trade_date);
