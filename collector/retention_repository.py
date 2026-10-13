"""Repository for ``retention_documents`` (``db/migrations/0018_retention_documents.sql``),
a ``LocalPostgresRepository`` subclass like ``collector/cfdi_repository.py``."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from collector.local_repository import LocalPostgresRepository

# The scalar columns; ``details`` (the whole parsed document) and ``xml`` are stored beside them.
SUMMARY_COLUMNS = (
    "uuid", "year", "month_start", "month_end", "concept", "cve_retenc", "emitter_rfc", "receiver_rfc",
    "receiver_nationality", "receiver_is_generic", "operation_cents", "taxable_cents", "exempt_cents",
    "withheld_cents",
)


class RetentionRepository(LocalPostgresRepository):
    def table_exists(self) -> bool:
        return self.relation_exists("retention_documents")

    def insert_document(self, document: dict[str, Any], xml: str) -> bool:
        """Insert once per UUID; returns False when it was already imported."""
        columns = (*SUMMARY_COLUMNS, "details", "xml")
        values = [*(document[c] for c in SUMMARY_COLUMNS), Jsonb(document), xml]
        with self._cursor() as cur:
            cur.execute(
                f"INSERT INTO retention_documents ({', '.join(columns)}) "
                f"VALUES ({', '.join(['%s'] * len(columns))}) ON CONFLICT (uuid) DO NOTHING",
                values,
            )
            return cur.rowcount == 1

    def get_documents(self, year: int) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(SUMMARY_COLUMNS)}, details, imported_at FROM retention_documents "
                "WHERE year = %s ORDER BY month_start, concept, uuid",
                (year,),
            )
            return cur.fetchall()
