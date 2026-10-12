"""Repository for ``cfdi_documents`` (``db/migrations/0017_cfdi_documents.sql``),
a ``LocalPostgresRepository`` subclass like ``collector/macro_repository.py``."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from collector.local_repository import LocalPostgresRepository

_COLUMNS = (
    "uuid", "version", "issued_at", "invoice_type", "issuer_rfc", "issuer_name", "receiver_rfc", "uso_cfdi",
    "payment_form", "payment_method", "currency", "exchange_rate", "subtotal_cents", "total_cents", "concepts",
    "source_filename",
)


class CfdiRepository(LocalPostgresRepository):
    def table_exists(self) -> bool:
        return self.relation_exists("cfdi_documents")

    def insert_document(self, document: dict[str, Any]) -> bool:
        """Insert once per UUID; returns False when it was already imported."""
        values = [Jsonb(document[c]) if c == "concepts" else document.get(c) for c in _COLUMNS]
        with self._cursor() as cur:
            cur.execute(
                f"INSERT INTO cfdi_documents ({', '.join(_COLUMNS)}) "
                f"VALUES ({', '.join(['%s'] * len(_COLUMNS))}) ON CONFLICT (uuid) DO NOTHING",
                values,
            )
            return cur.rowcount == 1

    def get_documents(self, year: int) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT uuid, issued_at, invoice_type, issuer_rfc, issuer_name, receiver_rfc, uso_cfdi, "
                "payment_form, payment_method, currency, exchange_rate::text AS exchange_rate, subtotal_cents, "
                "total_cents, concepts, source_filename FROM cfdi_documents "
                "WHERE issued_at >= make_date(%s, 1, 1) AND issued_at < make_date(%s + 1, 1, 1) ORDER BY issued_at",
                (year, year),
            )
            rows = cur.fetchall()
        for row in rows:
            row["currency"] = row["currency"].strip()
        return rows
