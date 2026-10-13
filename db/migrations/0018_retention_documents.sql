-- Imported CFDI de Retenciones 2.0 (the annual constancias a broker issues for
-- interest, dividends and sale of shares), kept so their totals can be
-- reconciled against the investment ledger before filing.
-- One row per stamped document, keyed by the Timbre Fiscal Digital UUID, so
-- importing the same XML twice is a no-op. Amounts are bigint cents in MXN;
-- `details` keeps the whole parsed document (complement amounts, withholdings)
-- and `xml` the original text.
--
-- What happens BEFORE this migration is applied (applied by hand with
-- `py -3.14 -m db.migrate`):
--   * `/api/investments/retentions` answers 503 "falta aplicar la migración 0018".
--     Nothing else reads this table.
-- What happens AFTER it is applied:
--   * One empty table; nothing is backfilled.
--
-- Idempotent: `create table if not exists`.

create table if not exists retention_documents (
  uuid uuid primary key,
  year integer not null,                 -- `Periodo/@Ejercicio`
  month_start smallint not null,
  month_end smallint not null,
  concept text not null,                 -- intereses | dividendos | enajenacion | otro
  cve_retenc text not null,              -- `CveRetenc` (c_Retenciones)
  emitter_rfc text not null,
  receiver_rfc text,                     -- null for a foreign receiver
  receiver_nationality text,
  receiver_is_generic boolean not null default false,  -- issued to the generic RFC, not linked to the user
  operation_cents bigint not null,       -- `MontoTotOperacion`
  taxable_cents bigint not null,         -- `MontoTotGrav`
  exempt_cents bigint not null,          -- `MontoTotExent`
  withheld_cents bigint not null,        -- `MontoTotRet`
  details jsonb not null,
  xml text not null,
  imported_at timestamptz not null default now()
);

create index if not exists retention_documents_year_idx on retention_documents (year);
