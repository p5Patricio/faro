"""Repository for ``macro_series`` / ``macro_observations``
(``db/migrations/0014_macro_series.sql``).

A subclass of ``LocalPostgresRepository`` in its own module, so the macro
queries do not grow ``local_repository.py`` while still sharing its
``_cursor`` (pool or injected connection, ``numeric`` decoded as float, any
``psycopg.Error`` re-raised as ``LocalPostgresError``, a ``RuntimeError``) and
``_upsert_batch``. A missing table therefore surfaces as a ``RuntimeError``,
which ``api/routers/macro.py`` turns into a 503.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from collector.local_repository import LocalPostgresRepository

MACRO_TABLES: tuple[str, ...] = ("macro_series", "macro_observations")


class MacroRepository(LocalPostgresRepository):
    def tables_exist(self) -> bool:
        return all(self.relation_exists(table) for table in MACRO_TABLES)

    def upsert_series(self, rows: list[dict[str, str]]) -> int:
        """Seed/refresh the catalog (``collector.macro_catalog.catalog_rows()``)."""
        return self._upsert_batch("macro_series", rows, ("id",))

    def upsert_observations(self, series_id: str, observations: Sequence[tuple[date, float]]) -> int:
        """Insert readings; an existing ``(series_id, observation_date)`` has its
        ``value`` overwritten and ``fetched_at`` refreshed."""
        fetched_at = datetime.now(tz=UTC)
        rows = [
            {"series_id": series_id, "observation_date": day, "value": value, "fetched_at": fetched_at}
            for day, value in observations
        ]
        return self._upsert_batch("macro_observations", rows, ("series_id", "observation_date"))

    def get_recent_observations(
        self, series_ids: Sequence[str], limit: int
    ) -> dict[str, list[tuple[date, float]]]:
        """The newest ``limit`` observations of each series, ascending by date.
        Series without rows are absent from the result."""
        query = (
            "SELECT series_id, observation_date, value FROM ("
            "  SELECT series_id, observation_date, value,"
            "         row_number() OVER (PARTITION BY series_id ORDER BY observation_date DESC) AS rn"
            "  FROM macro_observations WHERE series_id = ANY(%s)"
            ") ranked WHERE rn <= %s ORDER BY series_id, observation_date ASC"
        )
        with self._cursor() as cur:
            cur.execute(query, (list(series_ids), limit))
            rows = cur.fetchall()

        recent: dict[str, list[tuple[date, float]]] = {}
        for row in rows:
            recent.setdefault(row["series_id"], []).append((row["observation_date"], float(row["value"])))
        return recent
