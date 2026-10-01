-- Align the four default accounts seeded by 0008 with the ledger's base
-- currency (MXN). Data-only: no schema change, so no code path fails
-- because this file is unapplied. It does change behavior, though: until it
-- is applied, a database whose seed accounts are still USD makes the
-- Telegram bot reject messages booked to those accounts, and a transaction
-- to a USD account needs an FX rate.
--
-- Why: 0008 seeded 'Efectivo', 'Tarjeta debito', 'Tarjeta credito' and
-- 'Ahorro' as USD, but the ledger's base currency is MXN. Since a
-- transaction's currency must equal its account's (the API answers 422
-- otherwise, and the Telegram bot books into 'Efectivo' by default), a
-- freshly migrated database would start with accounts in which no peso
-- expense could be recorded.
--
-- Only untouched seed rows are converted. An account is left alone as soon
-- as any transaction or recurring bill references it: re-labelling an
-- account that already holds movements would silently change what those
-- rows mean. The statement is a no-op on a database whose accounts were
-- already edited to MXN, and it is idempotent.

update finance_accounts a
   set currency = 'MXN',
       updated_at = now()
 where a.currency = 'USD'
   and a.name in ('Efectivo', 'Tarjeta debito', 'Tarjeta credito', 'Ahorro')
   and not exists (select 1 from finance_transactions t where t.account_id = a.id)
   and not exists (select 1 from finance_recurring_bills b where b.account_id = a.id);
