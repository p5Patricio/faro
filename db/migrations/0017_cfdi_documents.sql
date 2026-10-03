-- Imported CFDI 4.0 invoices (the XML the SAT portal lets a taxpayer download),
-- kept so personal deductions can be reviewed and handed to an accountant.
-- One row per stamped invoice, keyed by the Timbre Fiscal Digital UUID, so
-- importing the same XML twice is a no-op. Amounts are bigint cents in the
-- invoice's own currency (`Moneda`), with the invoice's `TipoCambio` when it
-- has one; `concepts` keeps each line (ClaveProdServ, Descripcion, Importe).
--
-- What happens BEFORE this migration is applied (applied by hand with
-- `py -3.14 -m db.migrate`):
--   * `/api/finance/cfdi` answers 503 "falta aplicar la migración 0017". Nothing
--     else reads this table.
-- What happens AFTER it is applied:
--   * One empty table; nothing is backfilled.
--
-- Idempotent: `create table if not exists`.

create table if not exists cfdi_documents (
  uuid uuid primary key,
  version text not null,
  issued_at timestamp not null,          -- `Fecha`: local time of the issuer, no zone in the XML
  invoice_type text not null,            -- `TipoDeComprobante`
  issuer_rfc text not null,
  issuer_name text,
  receiver_rfc text not null,
  uso_cfdi text,
  payment_form text,                     -- `FormaPago` (c_FormaPago)
  payment_method text,                   -- `MetodoPago` (PUE / PPD)
  currency char(3) not null,
  exchange_rate numeric(18, 6),
  subtotal_cents bigint not null,
  total_cents bigint not null,
  concepts jsonb not null default '[]'::jsonb,
  source_filename text,
  imported_at timestamptz not null default now()
);

create index if not exists cfdi_documents_issued_at_idx on cfdi_documents (issued_at);
