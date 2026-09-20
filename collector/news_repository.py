"""Repository for the `news_headlines` table
(`db/migrations/0011_news_sentiment.sql`).

A SEPARATE, standalone module rather than new methods on
`collector/local_repository.py::LocalPostgresRepository` -- purely a
work-tree-coordination decision, not an architectural one:
`local_repository.py` is under active concurrent modification (an in-flight
analyst-consensus change) at the time this module was written, so extending
it here would edit a file this change does not own and risk clobbering that
other work. `NewsRepository` deliberately mirrors
`LocalPostgresRepository`'s own shape byte-for-byte where it can (`pool`/
`connection` constructor, `_cursor()` context manager, the
`INSERT ... ON CONFLICT DO UPDATE` batch-upsert pattern) so a future merge
can fold these methods into `LocalPostgresRepository` as a near-mechanical
copy-paste, no behavior change. Callers that already hold a
`LocalPostgresRepository`'s `connection`/`pool` can wrap that SAME
connection/pool in a `NewsRepository` -- both classes are stateless wrappers
around whatever they are given, never opening a connection of their own
outside tests (see `brain/materialize_sentiment.py::main`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pandas as pd
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from collector.providers.finnhub_news_provider import NewsHeadline

# Natural key = one headline from one source at one publish time for one
# asset. Every key column is `not null` on purpose (0011's own comment
# restates the reason: Postgres treats NULLs as distinct in a UNIQUE
# constraint, so a nullable key column would both let duplicate rows in and
# make ON CONFLICT never match).
NEWS_HEADLINE_KEY: tuple[str, ...] = ("asset_id", "source", "published_at", "headline")


class NewsRepositoryError(RuntimeError):
    """Raised when a `NewsRepository` Postgres operation fails."""


@dataclass
class NewsRepository:
    """Thin psycopg3 repository for `news_headlines`, mirroring
    `LocalPostgresRepository`'s constructor shape: accepts either a `pool`
    (production usage) or an injected `connection` (test usage -- the
    caller manages BEGIN/ROLLBACK around the connection for isolation,
    exactly like `tests/conftest.py::db_connection`)."""

    pool: ConnectionPool | None = None
    connection: psycopg.Connection | None = None

    def __post_init__(self) -> None:
        if self.pool is None and self.connection is None:
            raise NewsRepositoryError("NewsRepository requires a pool or connection")

    @contextmanager
    def _cursor(self) -> Iterator[psycopg.Cursor[dict[str, Any]]]:
        try:
            if self.connection is not None:
                with self.connection.cursor(row_factory=dict_row) as cur:
                    yield cur
            else:
                assert self.pool is not None
                with self.pool.connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        yield cur
        except psycopg.Error as exc:
            raise NewsRepositoryError(str(exc)) from exc

    def _upsert_batch(
        self,
        table: str,
        rows: list[dict[str, Any]],
        conflict_cols: tuple[str, ...],
    ) -> int:
        """`INSERT ... ON CONFLICT DO UPDATE`, byte-for-byte the same shape
        as `LocalPostgresRepository._upsert_batch` (see that method's
        docstring) -- duplicated here rather than imported so this module
        never depends on the file it was written to avoid touching."""
        if not rows:
            return 0

        columns = list(rows[0].keys())
        update_cols = [column for column in columns if column not in conflict_cols]

        insert_cols_sql = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
        placeholders_sql = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
        conflict_sql = sql.SQL(", ").join(sql.Identifier(column) for column in conflict_cols)

        if update_cols:
            updates_sql = sql.SQL(", ").join(
                sql.SQL("{column} = EXCLUDED.{column}").format(column=sql.Identifier(column))
                for column in update_cols
            )
            query = sql.SQL(
                "INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
                "ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
            ).format(
                table=sql.Identifier(table),
                cols=insert_cols_sql,
                placeholders=placeholders_sql,
                conflict=conflict_sql,
                updates=updates_sql,
            )
        else:
            query = sql.SQL(
                "INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
                "ON CONFLICT ({conflict}) DO NOTHING"
            ).format(
                table=sql.Identifier(table),
                cols=insert_cols_sql,
                placeholders=placeholders_sql,
                conflict=conflict_sql,
            )

        params = [tuple(row[column] for column in columns) for row in rows]
        with self._cursor() as cur:
            cur.executemany(query, params)
        return len(rows)

    def upsert_news_headlines(
        self,
        asset_id: str,
        headlines: list[NewsHeadline],
        batch_size: int = 500,
    ) -> int:
        """Persist raw headlines keyed by `NEWS_HEADLINE_KEY`. Re-ingesting
        an overlapping date range (the normal shape of a periodic Finnhub
        pull) upserts onto the same natural key instead of duplicating --
        the same restatement philosophy
        `LocalPostgresRepository.upsert_fundamental_facts` documents.

        `sentiment_score`/`sentiment_label` are never included in `rows`
        here on purpose: scoring is a separate step
        (`update_sentiment_scores`), so re-ingesting a headline that was
        already scored can never clobber its score back to NULL -- the
        ON CONFLICT UPDATE only ever touches columns actually present in
        the payload (`source`/`headline`/`published_at`/`summary`/`url`),
        never the sentiment columns, on this path.
        """
        if not headlines:
            return 0

        rows = [
            {
                "asset_id": asset_id,
                "source": headline.source,
                "headline": headline.headline,
                "published_at": headline.published_at.isoformat(),
                "summary": headline.summary or None,
                "url": headline.url or None,
            }
            for headline in headlines
        ]

        upserted = 0
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            upserted += self._upsert_batch("news_headlines", chunk, NEWS_HEADLINE_KEY)
        return upserted

    def get_news_headlines(self, asset_id: str) -> pd.DataFrame:
        """Every stored headline for one asset, oldest first. Always
        returns a *typed* empty frame carrying the declared columns -- never
        a column-less frame -- because `brain/sentiment_factors.py` indexes
        `published_at`/`sentiment_score` unconditionally, mirroring
        `LocalPostgresRepository.get_fundamental_facts`'s same guarantee."""
        columns = [
            "id",
            "source",
            "headline",
            "published_at",
            "summary",
            "url",
            "sentiment_score",
            "sentiment_label",
        ]
        query = (
            "SELECT id, source, headline, published_at, summary, url, "
            "sentiment_score, sentiment_label FROM news_headlines "
            "WHERE asset_id = %s ORDER BY published_at ASC"
        )
        with self._cursor() as cur:
            cur.execute(query, (asset_id,))
            rows = cur.fetchall()

        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(rows, columns=columns)

    def get_unscored_headline_ids(self, asset_id: str) -> pd.DataFrame:
        """`id`/`headline` pairs still awaiting a sentiment score for one
        asset -- what `brain/materialize_sentiment.py`'s scoring step reads
        before calling `brain.sentiment_factors.score_headlines`."""
        query = (
            "SELECT id, headline FROM news_headlines "
            "WHERE asset_id = %s AND sentiment_score IS NULL ORDER BY published_at ASC"
        )
        with self._cursor() as cur:
            cur.execute(query, (asset_id,))
            rows = cur.fetchall()
        if not rows:
            return pd.DataFrame(columns=["id", "headline"])
        return pd.DataFrame(rows, columns=["id", "headline"])

    def update_sentiment_scores(self, scored: list[dict[str, Any]]) -> int:
        """Write a computed `sentiment_score`/`sentiment_label` back onto
        already-stored headline rows, addressed by `id` (each dict:
        `{"id": ..., "sentiment_score": ..., "sentiment_label": ...}`).
        A plain batched UPDATE, not an upsert -- these rows already exist
        (created by `upsert_news_headlines`); this only ever fills in the
        two columns that ingestion deliberately leaves NULL."""
        if not scored:
            return 0

        query = "UPDATE news_headlines SET sentiment_score = %s, sentiment_label = %s WHERE id = %s"
        params = [(row["sentiment_score"], row["sentiment_label"], row["id"]) for row in scored]
        with self._cursor() as cur:
            cur.executemany(query, params)
        return len(scored)
