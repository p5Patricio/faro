-- Two independent changes to the personal-finance tables, kept in one file
-- because both are small and both were deferred out of earlier review rounds:
--
--   1. finance_net_worth_items.is_liquid -- which assets count toward the
--      emergency fund.
--   2. finance_recurring_bill_payments -- the database itself now allows only
--      one PENDING occurrence per bill (0008 only said "the app is
--      responsible for it").
--
-- BEFORE this file is applied (the code in this repository is written to
-- keep running against a database that does not have it yet):
--   * Net-worth items have no `is_liquid` column. Reads still work; a write
--     that carries `is_liquid` is stored without it and logs a warning.
--   * GET /api/finance/summary reports `liquidity_flags_available: false`.
--     Because no asset can be identified as liquid, the emergency fund is
--     reported as "unclassified" (no months figure) and the investable
--     surplus stays gated with reason "liquidity_unclassified". This differs
--     from the earlier behavior, which stood in TOTAL net worth for "liquid"
--     assets; that stand-in is gone whether or not this file is applied.
--   * The one-pending-row rule is enforced by the application only:
--     PUT /api/finance/recurring-bills/payments answers 422 for a `pending`
--     status on a different date than the bill's current pending row.
--
-- AFTER this file is applied:
--   * `is_liquid` is read and written. true = counts toward the emergency
--     fund, false = classified as not liquid, NULL = not classified yet.
--     Liabilities are always NULL (the flag does not apply to them).
--   * Existing rows are backfilled conservatively: only ASSET rows whose
--     `item_type` is clearly cash-like (cash, checking, savings, efectivo,
--     ahorro) become true. Every other existing row stays NULL, so the
--     emergency fund reports "unclassified" until the user classifies at
--     least one asset in the Patrimonio tab; nothing is guessed.
--     brain/finance/liquidity.py holds the same cash-like list.
--   * A second pending row for the same bill is rejected by the database.
--
-- Data changes this file makes:
--   * Sets `is_liquid = true` on the cash-like asset rows described above
--     (only rows where it is still NULL, so it never overwrites a choice).
--   * Deletes surplus pending occurrence rows so the unique index can be
--     built. Per bill, the EARLIEST pending row is kept. A surplus pending
--     row is deleted only when it has no `transaction_id`; rows linked to a
--     ledger transaction, and every paid or skipped row, are never touched.
--     If a bill still has more than one pending row afterwards (its extra
--     rows are linked to transactions), the file stops with an error that
--     names the bills and, because each migration runs in one transaction,
--     changes nothing. Settle or unlink those rows, then apply it again.
--
-- The whole file is idempotent: re-running it changes nothing further.

-- -- 1. Liquidity flag ----------------------------------------------------

alter table finance_net_worth_items
  add column if not exists is_liquid boolean;

comment on column finance_net_worth_items.is_liquid is
  'true = counts toward the emergency fund; false = classified as not liquid; null = not classified yet (legacy row or unknown item type). Always null for liabilities.';

update finance_net_worth_items
   set is_liquid = true
 where is_liquid is null
   and is_asset
   and lower(btrim(item_type)) in ('cash', 'checking', 'savings', 'efectivo', 'ahorro');

-- -- 2. One pending occurrence per bill ----------------------------------

with ranked as (
  select id,
         row_number() over (
           partition by bill_id
           order by due_date asc, created_at asc, id asc
         ) as position
    from finance_recurring_bill_payments
   where status = 'pending'
)
delete from finance_recurring_bill_payments p
 using ranked r
 where p.id = r.id
   and r.position > 1
   and p.transaction_id is null;

do $$
declare
  offending text;
begin
  select string_agg(bill_id::text, ', ' order by bill_id::text)
    into offending
    from (
      select bill_id
        from finance_recurring_bill_payments
       where status = 'pending'
       group by bill_id
      having count(*) > 1
    ) duplicated;

  if offending is not null then
    raise exception
      'finance_recurring_bill_payments: bill(s) % still have more than one pending occurrence and the extra rows are linked to ledger transactions, so this migration will not delete them. Settle or unlink them, then apply it again.',
      offending;
  end if;
end
$$;

create unique index if not exists finance_recurring_bill_payments_one_pending_key
  on finance_recurring_bill_payments(bill_id)
  where status = 'pending';
