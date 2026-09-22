from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.adapt import Loader
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg.types.numeric import FloatLoader
from psycopg_pool import ConnectionPool

from collector.providers.base import AnalystConsensus


class _UUIDStrLoader(Loader):
    """Load ``uuid`` columns as ``str`` instead of psycopg3's default ``uuid.UUID``.

    Every id-returning repository method returns a plain string, matching
    this module's own public contract regardless of caller.
    """

    def load(self, data: bytes | memoryview) -> str:
        return bytes(data).decode()


@dataclass(frozen=True)
class LocalPostgresConfig:
    dsn: str

    @classmethod
    def from_env(cls) -> "LocalPostgresConfig":
        load_dotenv()
        dsn = os.getenv("LOCAL_DATABASE_URL")
        if dsn:
            return cls(dsn=dsn)

        host = os.getenv("PGHOST")
        dbname = os.getenv("PGDATABASE")
        user = os.getenv("PGUSER")
        if host and dbname and user:
            port = os.getenv("PGPORT", "5432")
            password = os.getenv("PGPASSWORD")
            auth = f"{user}:{password}@" if password else f"{user}@"
            return cls(dsn=f"postgresql://{auth}{host}:{port}/{dbname}")

        raise RuntimeError(
            "LOCAL_DATABASE_URL or PGHOST/PGPORT/PGDATABASE/PGUSER must be set"
        )


class LocalPostgresError(RuntimeError):
    """Raised when a local Postgres operation fails.

    Subclasses ``RuntimeError`` so existing ``except RuntimeError`` call
    sites in ``api/main.py`` keep working unchanged.
    """


# SEC XBRL fact store (db/migrations/0006_fundamental_facts.sql). The natural key
# includes filed_date, so a restatement of an earlier period is a new row (INSERT
# branch) and re-ingesting an unchanged payload is a no-op UPDATE. See design
# decisions 2 (every key column NOT NULL -- the Postgres NULL-in-UNIQUE trap) and
# 3 (upsert, not insert).
FUNDAMENTAL_FACT_COLUMNS: tuple[str, ...] = (
    "asset_id",
    "taxonomy",
    "concept",
    "unit",
    "period_end",
    "fiscal_year",
    "fiscal_period",
    "filed_date",
    "accession",
    "value",
)
FUNDAMENTAL_FACT_KEY: tuple[str, ...] = (
    "asset_id",
    "taxonomy",
    "concept",
    "unit",
    "period_end",
    "fiscal_period",
    "filed_date",
)

# Analyst consensus history (db/migrations/0010_analyst_consensus.sql). Ratings
# and price targets drift every few days, so this is an append-only time series
# keyed by (asset_id, fetched_at) -- the same restatement philosophy as
# FUNDAMENTAL_FACT_KEY above: a new reading is a new row, never an overwrite of
# the last one.
ANALYST_CONSENSUS_COLUMNS: tuple[str, ...] = (
    "asset_id",
    "fetched_at",
    "source",
    "recommendation_key",
    "recommendation_mean",
    "analyst_count",
    "strong_buy",
    "buy",
    "hold",
    "sell",
    "strong_sell",
    "target_mean",
    "target_median",
    "target_high",
    "target_low",
)
ANALYST_CONSENSUS_KEY: tuple[str, ...] = ("asset_id", "fetched_at")


@dataclass
class LocalPostgresRepository:
    """Thin psycopg3 repository for the local Postgres database.

    Accepts either a ``pool`` (production/collector/brain usage) or an
    injected ``connection`` (test usage: the caller manages
    ``BEGIN``/``ROLLBACK`` around the connection for isolation).
    """

    pool: ConnectionPool | None = None
    connection: psycopg.Connection | None = None

    def __post_init__(self) -> None:
        if self.pool is None and self.connection is None:
            raise LocalPostgresError("LocalPostgresRepository requires a pool or connection")

    @staticmethod
    def _configure(conn: psycopg.Connection) -> None:
        # D5: without this, `numeric` columns decode to Decimal and pandas
        # DataFrames silently degrade to object dtype, breaking arithmetic
        # in brain/. Also normalizes `uuid` columns back to str (see
        # _UUIDStrLoader) to match PostgREST's JSON contract.
        conn.adapters.register_loader("numeric", FloatLoader)
        conn.adapters.register_loader("uuid", _UUIDStrLoader)

    @contextmanager
    def _cursor(self) -> Iterator[psycopg.Cursor[dict[str, Any]]]:
        try:
            if self.connection is not None:
                self._configure(self.connection)
                with self.connection.cursor(row_factory=dict_row) as cur:
                    yield cur
            else:
                assert self.pool is not None
                with self.pool.connection() as conn:
                    self._configure(conn)
                    with conn.cursor(row_factory=dict_row) as cur:
                        yield cur
        except psycopg.Error as exc:
            raise LocalPostgresError(str(exc)) from exc

    def _upsert_batch(
        self,
        table: str,
        rows: list[dict[str, Any]],
        conflict_cols: tuple[str, ...],
    ) -> int:
        """INSERT ... ON CONFLICT DO UPDATE, equivalent to PostgREST's
        ``?on_conflict=a,b`` + ``Prefer: resolution=merge-duplicates``, which
        updates every column present in the payload."""
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
        # Preserves today's return semantics: the submitted row count, not
        # the affected-row count.
        return len(rows)

    def _insert_batch(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Plain batched INSERT with no conflict handling (today's behavior
        for backtest trades and paper trading events)."""
        if not rows:
            return 0

        columns = list(rows[0].keys())
        query = sql.SQL("INSERT INTO {table} ({cols}) VALUES ({placeholders})").format(
            table=sql.Identifier(table),
            cols=sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        params = [tuple(row[column] for column in columns) for row in rows]
        with self._cursor() as cur:
            cur.executemany(query, params)
        return len(rows)

    # -- Assets ------------------------------------------------------------

    def get_assets(self) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM assets ORDER BY ticker ASC")
            return cur.fetchall()

    def get_or_create_asset(
        self,
        ticker: str,
        name: str | None = None,
        asset_class: str | None = None,
    ) -> str:
        normalized_ticker = ticker.upper()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO assets (ticker, name, asset_class)
                VALUES (%s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET ticker = EXCLUDED.ticker
                RETURNING id
                """,
                (normalized_ticker, name or normalized_ticker, asset_class or "unknown"),
            )
            row = cur.fetchone()
        return row["id"]

    def get_asset_id(self, ticker: str) -> str:
        normalized_ticker = ticker.upper()
        with self._cursor() as cur:
            cur.execute("SELECT id FROM assets WHERE ticker = %s", (normalized_ticker,))
            row = cur.fetchone()
        if not row:
            raise ValueError(f"Asset not found: {normalized_ticker}")
        return row["id"]

    def get_asset(self, ticker: str) -> dict[str, Any]:
        normalized_ticker = ticker.upper()
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, ticker, name, asset_class FROM assets WHERE ticker = %s",
                (normalized_ticker,),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError(f"Asset not found: {normalized_ticker}")
        return row

    # -- Prices / features / labels -----------------------------------------

    def get_prices(self, asset_id: str, limit: int | None = None, ascending: bool = True) -> pd.DataFrame:
        order = "ASC" if ascending else "DESC"
        query = (
            "SELECT timestamp, open, high, low, close, volume FROM prices "
            f"WHERE asset_id = %s ORDER BY timestamp {order}"
        )
        params: list[Any] = [asset_id]
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return pd.DataFrame(rows)

    def get_latest_price_pairs(self, asset_ids: list[str]) -> pd.DataFrame:
        """Latest close and the prior close for each of ``asset_ids``, in ONE
        query via a window function.

        Built for batch daily %-change computation across many assets at
        once -- e.g. the market heatmap (``api/routers/heatmap.py``), which
        needs a price + change_pct for ~100 tickers per request and would
        otherwise cost ~100 round trips through `get_prices`. Returns at most
        2 rows per asset (today's close and, when one exists, the prior
        close), ordered by asset_id then descending timestamp.
        """
        if not asset_ids:
            return pd.DataFrame(columns=["asset_id", "timestamp", "close"])
        query = """
            SELECT asset_id, timestamp, close
            FROM (
                SELECT asset_id, timestamp, close,
                       row_number() OVER (PARTITION BY asset_id ORDER BY timestamp DESC) AS rn
                FROM prices
                WHERE asset_id = ANY(%s)
            ) ranked
            WHERE rn <= 2
            ORDER BY asset_id, timestamp DESC
        """
        with self._cursor() as cur:
            cur.execute(query, (list(asset_ids),))
            rows = cur.fetchall()
        return pd.DataFrame(rows, columns=["asset_id", "timestamp", "close"])

    def get_features(
        self,
        asset_id: str,
        feature_set: str,
        limit: int | None = None,
        ascending: bool = True,
    ) -> pd.DataFrame:
        order = "ASC" if ascending else "DESC"
        query = (
            "SELECT timestamp, features FROM features_daily "
            f"WHERE asset_id = %s AND feature_set = %s ORDER BY timestamp {order}"
        )
        params: list[Any] = [asset_id, feature_set]
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return pd.DataFrame(rows)

    def get_labels(
        self,
        asset_id: str,
        label_method: str,
        horizon: int,
        limit: int | None = None,
    ) -> pd.DataFrame:
        query = (
            "SELECT timestamp, label, outcome_return, label_exit_timestamp FROM labels_daily "
            "WHERE asset_id = %s AND label_method = %s AND horizon = %s ORDER BY timestamp ASC"
        )
        params: list[Any] = [asset_id, label_method, horizon]
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return pd.DataFrame(rows)

    def upsert_prices(self, asset_id: str, prices: pd.DataFrame, batch_size: int = 500) -> int:
        if prices.empty:
            return 0
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required - set(prices.columns)
        if missing:
            raise ValueError(f"prices DataFrame missing columns: {sorted(missing)}")

        clean = prices.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        rows = [
            {
                "asset_id": asset_id,
                "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]) if pd.notna(row["volume"]) else 0,
            }
            for _, row in clean.iterrows()
        ]

        inserted = 0
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            inserted += self._upsert_batch("prices", chunk, ("asset_id", "timestamp"))
        return inserted

    def upsert_features(
        self,
        asset_id: str,
        features: pd.DataFrame,
        feature_columns: list[str],
        feature_set: str,
        batch_size: int = 500,
    ) -> int:
        required = {"timestamp", *feature_columns}
        missing = required - set(features.columns)
        if missing:
            raise ValueError(f"features DataFrame missing columns: {sorted(missing)}")

        clean = features.dropna(subset=feature_columns)
        rows = [
            {
                "asset_id": asset_id,
                "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                "feature_set": feature_set,
                "features": Jsonb({column: _json_value(row[column]) for column in feature_columns}),
            }
            for _, row in clean.iterrows()
        ]

        inserted = 0
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            inserted += self._upsert_batch("features_daily", chunk, ("asset_id", "timestamp", "feature_set"))
        return inserted

    def upsert_labels(
        self,
        asset_id: str,
        labels: pd.DataFrame,
        label_method: str,
        horizon: int,
        batch_size: int = 500,
    ) -> int:
        required = {"timestamp", "label"}
        missing = required - set(labels.columns)
        if missing:
            raise ValueError(f"labels DataFrame missing columns: {sorted(missing)}")

        clean = labels.dropna(subset=["label"])
        rows = [
            {
                "asset_id": asset_id,
                "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                "label_method": label_method,
                "horizon": horizon,
                "label": str(row["label"]),
                "outcome_return": _json_value(
                    row["outcome_return"] if "outcome_return" in row else row.get("future_return")
                ),
                "label_exit_timestamp": _timestamp_or_none(row.get("label_exit_timestamp")),
                "metadata": Jsonb({}),
            }
            for _, row in clean.iterrows()
        ]

        inserted = 0
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            inserted += self._upsert_batch(
                "labels_daily", chunk, ("asset_id", "timestamp", "label_method", "horizon")
            )
        return inserted

    # -- Fundamental facts -------------------------------------------------

    def upsert_fundamental_facts(
        self,
        rows: list[dict[str, Any]],
        batch_size: int = 500,
    ) -> int:
        """Persist SEC XBRL facts keyed by ``FUNDAMENTAL_FACT_KEY``.

        The conflict target is the full 7-column natural key, which includes
        ``filed_date``: a restatement (a later filing revising an earlier
        ``period_end``) carries a new key and takes the INSERT branch, so the
        earlier row is never mutated. Re-ingesting an unchanged payload hits
        ON CONFLICT and rewrites the non-key columns (``fiscal_year``,
        ``accession``, ``value``) to identical values -- a no-op. The
        point-in-time guarantee is enforced by the key, not by this method.
        """
        if not rows:
            return 0

        expected = set(FUNDAMENTAL_FACT_COLUMNS)
        prepared: list[dict[str, Any]] = []
        for row in rows:
            missing = expected - row.keys()
            if missing:
                raise ValueError(
                    f"fundamental fact row missing columns: {sorted(missing)}"
                )
            prepared.append({column: row[column] for column in FUNDAMENTAL_FACT_COLUMNS})

        upserted = 0
        for start in range(0, len(prepared), batch_size):
            chunk = prepared[start : start + batch_size]
            upserted += self._upsert_batch(
                "fundamental_facts", chunk, FUNDAMENTAL_FACT_KEY
            )
        return upserted

    def get_fundamental_facts(
        self,
        asset_id: str,
        *,
        concepts: list[str] | None = None,
        as_of_filed_date: str | date | None = None,
    ) -> pd.DataFrame:
        """Point-in-time fact read for one asset.

        ``as_of_filed_date`` is applied in SQL (``filed_date <= %s``) so
        ``fundamental_facts_asof_idx`` serves the cutoff and a multi-year
        backtest never pulls future filings into memory. Always returns a
        *typed* empty frame carrying the nine declared columns -- never a
        column-less frame -- because the factor layer indexes columns
        unconditionally and every crypto asset (no CIK) reaches here empty.
        """
        columns = [
            "taxonomy",
            "concept",
            "unit",
            "period_end",
            "fiscal_year",
            "fiscal_period",
            "filed_date",
            "accession",
            "value",
        ]
        query = (
            "SELECT taxonomy, concept, unit, period_end, fiscal_year, fiscal_period, "
            "filed_date, accession, value FROM fundamental_facts WHERE asset_id = %s"
        )
        params: list[Any] = [asset_id]
        if concepts is not None:
            query += " AND concept = ANY(%s)"
            params.append(list(concepts))
        if as_of_filed_date is not None:
            query += " AND filed_date <= %s::date"
            params.append(as_of_filed_date)
        query += " ORDER BY concept ASC, period_end ASC, filed_date ASC"

        with self._cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(rows, columns=columns)

    def upsert_analyst_consensus_snapshot(
        self,
        asset_id: str,
        consensus: AnalystConsensus,
        fetched_at: datetime | None = None,
    ) -> int:
        """Persist one analyst-consensus reading as a new history row.

        Keyed by ``(asset_id, fetched_at)`` (``ANALYST_CONSENSUS_KEY``): a later
        reading is a new row, never an update of the last one -- the same
        restatement philosophy ``upsert_fundamental_facts`` documents. Re-submitting
        the same ``(asset_id, fetched_at)`` pair (e.g. a retried ingestion step)
        hits ON CONFLICT and rewrites the non-key columns to identical values --
        a no-op.
        """
        row = {
            "asset_id": asset_id,
            "fetched_at": fetched_at or datetime.now(tz=UTC),
            "source": consensus.source,
            "recommendation_key": consensus.recommendation_key,
            "recommendation_mean": consensus.recommendation_mean,
            "analyst_count": consensus.analyst_count,
            "strong_buy": consensus.strong_buy,
            "buy": consensus.buy,
            "hold": consensus.hold,
            "sell": consensus.sell,
            "strong_sell": consensus.strong_sell,
            "target_mean": consensus.target_mean,
            "target_median": consensus.target_median,
            "target_high": consensus.target_high,
            "target_low": consensus.target_low,
        }
        return self._upsert_batch(
            "analyst_consensus_snapshots", [row], ANALYST_CONSENSUS_KEY
        )

    def get_latest_analyst_consensus(self, asset_id: str) -> dict[str, Any] | None:
        """Most recent analyst-consensus snapshot for one asset, or ``None``.

        Uses ``analyst_consensus_snapshots_latest_idx`` (``asset_id, fetched_at
        desc``) so this always serves the newest row without sorting the full
        history.
        """
        query = (
            "SELECT source, recommendation_key, recommendation_mean, analyst_count, "
            "strong_buy, buy, hold, sell, strong_sell, target_mean, target_median, "
            "target_high, target_low, fetched_at FROM analyst_consensus_snapshots "
            "WHERE asset_id = %s ORDER BY fetched_at DESC LIMIT 1"
        )
        with self._cursor() as cur:
            cur.execute(query, (asset_id,))
            return cur.fetchone()

    # -- Model runs / predictions --------------------------------------------

    def create_model_run(
        self,
        model_name: str,
        model_version: str,
        feature_set: str,
        label_method: str,
        horizon: int,
        train_start: str | datetime | None = None,
        train_end: str | datetime | None = None,
        params: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        artifact_uri: str | None = None,
    ) -> str:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_runs
                    (model_name, model_version, feature_set, label_method, horizon,
                     train_start, train_end, params, metrics, artifact_uri)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_name, model_version) DO UPDATE SET model_name = EXCLUDED.model_name
                RETURNING id
                """,
                (
                    model_name,
                    model_version,
                    feature_set,
                    label_method,
                    horizon,
                    _timestamp_or_none(train_start),
                    _timestamp_or_none(train_end),
                    Jsonb(_json_safe(params or {})),
                    Jsonb(_json_safe(metrics or {})),
                    artifact_uri,
                ),
            )
            row = cur.fetchone()
        return row["id"]

    def get_model_run(self, model_name: str, model_version: str) -> dict[str, Any]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM model_runs WHERE model_name = %s AND model_version = %s",
                (model_name, model_version),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError(f"Model run not found: {model_name}:{model_version}")
        return row

    def get_model_runs(
        self,
        model_name: str | None = None,
        model_version: str | None = None,
        limit: int | None = None,
        ascending: bool = False,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if model_name:
            conditions.append("model_name = %s")
            params.append(model_name)
        if model_version:
            conditions.append("model_version = %s")
            params.append(model_version)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        order = "ASC" if ascending else "DESC"
        query = f"SELECT * FROM model_runs{where_clause} ORDER BY created_at {order}"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def update_model_run_artifact_uri(self, model_run_id: str, artifact_uri: str) -> dict[str, Any]:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE model_runs SET artifact_uri = %s WHERE id = %s RETURNING *",
                (artifact_uri, model_run_id),
            )
            row = cur.fetchone()
        if not row:
            raise RuntimeError(f"Model run not found: {model_run_id}")
        return row

    def upsert_predictions(
        self,
        asset_id: str,
        model_run_id: str,
        predictions: pd.DataFrame,
        batch_size: int = 500,
    ) -> int:
        required = {"timestamp", "action", "confidence", "probabilities"}
        missing = required - set(predictions.columns)
        if missing:
            raise ValueError(f"predictions DataFrame missing columns: {sorted(missing)}")

        rows = [
            {
                "asset_id": asset_id,
                "model_run_id": model_run_id,
                "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                "action": str(row["action"]),
                "confidence": _json_value(row["confidence"]),
                "expected_return": _json_value(row.get("expected_return")),
                "expected_risk": _json_value(row.get("expected_risk")),
                "probabilities": Jsonb(_json_safe(row["probabilities"])),
                "metadata": Jsonb(_json_safe(row.get("metadata", {}))),
            }
            for _, row in predictions.iterrows()
        ]

        inserted = 0
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            inserted += self._upsert_batch(
                "predictions", chunk, ("asset_id", "model_run_id", "timestamp")
            )
        return inserted

    def get_prediction_feedback(
        self,
        model_name: str | None = None,
        model_version: str | None = None,
        asset_id: str | None = None,
        only_evaluated: bool = True,
        limit: int | None = None,
        ascending: bool = True,
    ) -> pd.DataFrame:
        conditions: list[str] = []
        params: list[Any] = []
        if model_name:
            conditions.append("model_name = %s")
            params.append(model_name)
        if model_version:
            conditions.append("model_version = %s")
            params.append(model_version)
        if asset_id:
            conditions.append("asset_id = %s")
            params.append(asset_id)
        if only_evaluated:
            conditions.append("actual_label IS NOT NULL")
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        order = "ASC" if ascending else "DESC"
        query = f"SELECT * FROM prediction_feedback{where_clause} ORDER BY timestamp {order}"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return pd.DataFrame(rows)

    def get_latest_prediction(
        self,
        asset_id: str,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> dict[str, Any] | None:
        conditions = ["asset_id = %s"]
        params: list[Any] = [asset_id]
        if model_name:
            conditions.append("model_name = %s")
            params.append(model_name)
        if model_version:
            conditions.append("model_version = %s")
            params.append(model_version)
        query = (
            f"SELECT * FROM prediction_feedback WHERE {' AND '.join(conditions)} "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        with self._cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()

    # -- Backtests / paper trading --------------------------------------------

    def create_backtest(
        self,
        name: str,
        model_run_id: str | None,
        asset_id: str | None,
        metrics: dict[str, Any],
        params: dict[str, Any] | None = None,
        started_at: str | datetime | None = None,
        ended_at: str | datetime | None = None,
    ) -> str:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO backtests (name, model_run_id, asset_id, started_at, ended_at, params, metrics)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    name,
                    model_run_id,
                    asset_id,
                    _timestamp_or_none(started_at),
                    _timestamp_or_none(ended_at),
                    Jsonb(_json_safe(params or {})),
                    Jsonb(_json_safe(metrics)),
                ),
            )
            row = cur.fetchone()
        return row["id"]

    def get_backtests(
        self,
        asset_id: str | None = None,
        model_run_id: str | None = None,
        limit: int | None = None,
        ascending: bool = False,
    ) -> pd.DataFrame:
        conditions: list[str] = []
        params: list[Any] = []
        if asset_id:
            conditions.append("b.asset_id = %s")
            params.append(asset_id)
        if model_run_id:
            conditions.append("b.model_run_id = %s")
            params.append(model_run_id)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        order = "ASC" if ascending else "DESC"
        query = (
            "SELECT b.*, "
            "CASE WHEN mr.id IS NULL THEN NULL ELSE jsonb_build_object("
            "'model_name', mr.model_name, 'model_version', mr.model_version, "
            "'feature_set', mr.feature_set, 'label_method', mr.label_method, "
            "'horizon', mr.horizon) END AS model_runs "
            "FROM backtests b LEFT JOIN model_runs mr ON mr.id = b.model_run_id"
            f"{where_clause} ORDER BY b.created_at {order}"
        )
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return pd.DataFrame(rows)

    def insert_backtest_trades(
        self,
        backtest_id: str,
        asset_id: str | None,
        trades: pd.DataFrame,
        batch_size: int = 500,
    ) -> int:
        if trades.empty:
            return 0
        required = {"timestamp", "action", "confidence", "gross_return", "net_return", "cost", "equity"}
        missing = required - set(trades.columns)
        if missing:
            raise ValueError(f"trades DataFrame missing columns: {sorted(missing)}")

        rows = [
            {
                "backtest_id": backtest_id,
                "asset_id": asset_id,
                "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                "action": str(row["action"]),
                "confidence": _json_value(row["confidence"]),
                "gross_return": _json_value(row["gross_return"]),
                "net_return": _json_value(row["net_return"]),
                "cost": _json_value(row["cost"]),
                "equity": _json_value(row["equity"]),
                "metadata": Jsonb(_json_safe(row.get("metadata", {}))),
            }
            for _, row in trades.iterrows()
        ]

        inserted = 0
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            inserted += self._insert_batch("backtest_trades", chunk)
        return inserted

    def create_paper_trading_run(
        self,
        name: str,
        model_run_id: str | None,
        asset_id: str | None,
        metrics: dict[str, Any],
        params: dict[str, Any] | None = None,
        started_at: str | datetime | None = None,
        ended_at: str | datetime | None = None,
    ) -> str:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO paper_trading_runs
                    (name, model_run_id, asset_id, started_at, ended_at, params, metrics)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    name,
                    model_run_id,
                    asset_id,
                    _timestamp_or_none(started_at),
                    _timestamp_or_none(ended_at),
                    Jsonb(_json_safe(params or {})),
                    Jsonb(_json_safe(metrics)),
                ),
            )
            row = cur.fetchone()
        return row["id"]

    def get_paper_trading_runs(
        self,
        asset_id: str | None = None,
        model_run_id: str | None = None,
        limit: int | None = None,
        ascending: bool = False,
    ) -> pd.DataFrame:
        conditions: list[str] = []
        params: list[Any] = []
        if asset_id:
            conditions.append("pr.asset_id = %s")
            params.append(asset_id)
        if model_run_id:
            conditions.append("pr.model_run_id = %s")
            params.append(model_run_id)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        order = "ASC" if ascending else "DESC"
        query = (
            "SELECT pr.*, "
            "CASE WHEN mr.id IS NULL THEN NULL ELSE jsonb_build_object("
            "'model_name', mr.model_name, 'model_version', mr.model_version, "
            "'feature_set', mr.feature_set, 'label_method', mr.label_method, "
            "'horizon', mr.horizon) END AS model_runs "
            "FROM paper_trading_runs pr LEFT JOIN model_runs mr ON mr.id = pr.model_run_id"
            f"{where_clause} ORDER BY pr.created_at {order}"
        )
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return pd.DataFrame(rows)

    def insert_paper_trading_events(
        self,
        paper_trading_run_id: str,
        asset_id: str | None,
        timeline: pd.DataFrame,
        batch_size: int = 500,
    ) -> int:
        if timeline.empty:
            return 0
        required = {
            "timestamp",
            "action",
            "confidence",
            "price",
            "mark_return",
            "exposure",
            "exposure_delta",
            "cost",
            "equity",
            "position_state",
        }
        missing = required - set(timeline.columns)
        if missing:
            raise ValueError(f"timeline DataFrame missing columns: {sorted(missing)}")

        rows = [
            {
                "paper_trading_run_id": paper_trading_run_id,
                "asset_id": asset_id,
                "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                "action": str(row["action"]),
                "confidence": _json_value(row["confidence"]),
                "price": _json_value(row["price"]),
                "mark_return": _json_value(row["mark_return"]),
                "exposure": _json_value(row["exposure"]),
                "exposure_delta": _json_value(row["exposure_delta"]),
                "cost": _json_value(row["cost"]),
                "equity": _json_value(row["equity"]),
                "position_state": str(row["position_state"]),
                "metadata": Jsonb(_json_safe(row.get("metadata", {}))),
            }
            for _, row in timeline.iterrows()
        ]

        inserted = 0
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            inserted += self._insert_batch("paper_trading_events", chunk)
        return inserted

    # -- Risk profiles (scope-only: default / asset_class / ticker) -----------

    def get_default_risk_profile(self) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM risk_profiles WHERE scope_type = %s ORDER BY updated_at DESC LIMIT 1",
                ("default",),
            )
            return cur.fetchone()

    def get_scoped_risk_profile(self, scope_type: str, scope_value: str = "") -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM risk_profiles WHERE scope_type = %s AND scope_value = %s "
                "ORDER BY updated_at DESC LIMIT 1",
                (scope_type, scope_value),
            )
            return cur.fetchone()

    def get_risk_profile_for_asset(
        self,
        ticker: str | None = None,
        asset_class: str | None = None,
    ) -> dict[str, Any] | None:
        if ticker:
            profile = self.get_scoped_risk_profile("ticker", ticker.upper())
            if profile:
                return profile
        if asset_class:
            profile = self.get_scoped_risk_profile("asset_class", asset_class.lower())
            if profile:
                return profile
        return self.get_default_risk_profile()

    def upsert_default_risk_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        return self.upsert_risk_profile(profile, scope_type="default", scope_value="")

    def upsert_risk_profile(
        self,
        profile: dict[str, Any],
        scope_type: str = "default",
        scope_value: str = "",
    ) -> dict[str, Any]:
        payload = {
            **profile,
            "name": profile.get("name") or "default",
            "scope_type": scope_type,
            "scope_value": scope_value,
        }
        columns = list(payload.keys())
        conflict_cols = ("scope_type", "scope_value")
        update_cols = [column for column in columns if column not in conflict_cols]

        insert_cols_sql = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
        placeholders_sql = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
        updates = [
            sql.SQL("{column} = EXCLUDED.{column}").format(column=sql.Identifier(column))
            for column in update_cols
        ]
        updates.append(sql.SQL("updated_at = now()"))
        query = sql.SQL(
            "INSERT INTO risk_profiles ({cols}) VALUES ({placeholders}) "
            "ON CONFLICT (scope_type, scope_value) DO UPDATE SET {updates} "
            "RETURNING *"
        ).format(
            cols=insert_cols_sql,
            placeholders=placeholders_sql,
            updates=sql.SQL(", ").join(updates),
        )
        params = tuple(payload[column] for column in columns)
        with self._cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()

    # -- Notifications -----------------------------------------------------

    def get_active_notification_rules(
        self,
        rule_type: str | None = None,
        channel: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = ["is_active"]
        params: list[Any] = []
        if rule_type:
            conditions.append("rule_type = %s")
            params.append(rule_type)
        if channel:
            conditions.append("channel = %s")
            params.append(channel)
        where_clause = " AND ".join(conditions)
        query = (
            "SELECT id, rule_type, asset_id, channel, params, cooldown_minutes "
            f"FROM notification_rules WHERE {where_clause} "
            "ORDER BY rule_type ASC, asset_id ASC NULLS FIRST"
        )
        with self._cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def notification_already_sent(self, dedupe_key: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM notifications WHERE dedupe_key = %s AND status = 'sent' LIMIT 1",
                (dedupe_key,),
            )
            return cur.fetchone() is not None

    def get_last_notification_fired_at(
        self,
        rule_type: str,
        asset_id: str | None = None,
        scope_key: str = "",
    ) -> datetime | None:
        # Branch on NULL instead of `IS NOT DISTINCT FROM`: btree cannot serve that
        # operator, so the branch is what keeps notifications_cooldown_idx usable.
        if asset_id is None:
            query = (
                "SELECT max(fired_at) AS fired_at FROM notifications "
                "WHERE rule_type = %s AND asset_id IS NULL AND scope_key = %s AND status = 'sent'"
            )
            params: tuple[Any, ...] = (rule_type, scope_key)
        else:
            query = (
                "SELECT max(fired_at) AS fired_at FROM notifications "
                "WHERE rule_type = %s AND asset_id = %s AND scope_key = %s AND status = 'sent'"
            )
            params = (rule_type, asset_id, scope_key)
        with self._cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        return row["fired_at"] if row else None

    def insert_notification(
        self,
        rule_id: str | None,
        rule_type: str,
        asset_id: str | None,
        scope_key: str,
        channel: str,
        dedupe_key: str,
        severity: str,
        title: str,
        body: str,
        status: str,
        error_reason: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Insert a delivery-log row.

        Returns the inserted row, or ``None`` when the partial unique index
        rejected a duplicate *sent* delivery (the caller reports
        ``raced_duplicate``). The index predicate must be restated here for
        Postgres to infer ``notifications_dedupe_sent_key``.
        """
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO notifications
                    (rule_id, rule_type, asset_id, scope_key, channel, dedupe_key,
                     severity, title, body, status, error_reason, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (dedupe_key) WHERE status = 'sent' DO NOTHING
                RETURNING *
                """,
                (
                    rule_id,
                    rule_type,
                    asset_id,
                    scope_key,
                    channel,
                    dedupe_key,
                    severity,
                    title,
                    body,
                    status,
                    error_reason,
                    Jsonb(_json_safe(payload or {})),
                ),
            )
            return cur.fetchone()

    def get_latest_price_timestamps(self) -> list[dict[str, Any]]:
        """One row per asset for the staleness check -- including assets with
        zero prices, distinguished from stale via the LEFT JOIN."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT a.id AS asset_id, a.ticker, max(p.timestamp) AS latest_price_at "
                "FROM assets a LEFT JOIN prices p ON p.asset_id = a.id "
                "GROUP BY a.id, a.ticker ORDER BY a.ticker ASC"
            )
            return cur.fetchall()

    # -- Asset identifiers / ingestion audit --------------------------------

    def upsert_asset_identifiers(self, rows: list[dict[str, Any]], batch_size: int = 500) -> int:
        if not rows:
            return 0

        prepared = [
            {
                "asset_id": row["asset_id"],
                "id_type": row["id_type"],
                "id_value": row["id_value"],
                "source": row["source"],
                "metadata": Jsonb(_json_safe(row.get("metadata", {}))),
            }
            for row in rows
        ]

        upserted = 0
        for start in range(0, len(prepared), batch_size):
            chunk = prepared[start : start + batch_size]
            upserted += self._upsert_batch("asset_identifiers", chunk, ("asset_id", "id_type"))
        return upserted

    def get_asset_identifiers(self, id_type: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM asset_identifiers"
        params: list[Any] = []
        if id_type:
            query += " WHERE id_type = %s"
            params.append(id_type)
        query += " ORDER BY asset_id ASC, id_type ASC"
        with self._cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def resolve_asset_by_identifier(self, id_type: str, id_value: str) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT a.* FROM assets a
                JOIN asset_identifiers ai ON ai.asset_id = a.id
                WHERE ai.id_type = %s AND ai.id_value = %s
                ORDER BY a.ticker ASC
                LIMIT 1
                """,
                (id_type, id_value),
            )
            return cur.fetchone()

    def insert_ingestion_run(
        self,
        source: str,
        endpoint: str,
        target_key: str,
        started_at: str | datetime,
        finished_at: str | datetime | None,
        status: str,
        http_status: int | None = None,
        rows_written: int = 0,
        request_count: int = 0,
        throttle_wait_seconds: float = 0.0,
        max_filed_date: str | datetime | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_runs
                    (source, endpoint, target_key, started_at, finished_at, status,
                     http_status, rows_written, request_count, throttle_wait_seconds,
                     max_filed_date, error, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    source,
                    endpoint,
                    target_key,
                    _timestamp_or_none(started_at),
                    _timestamp_or_none(finished_at),
                    status,
                    http_status,
                    rows_written,
                    request_count,
                    throttle_wait_seconds,
                    _timestamp_or_none(max_filed_date),
                    error,
                    Jsonb(_json_safe(metadata or {})),
                ),
            )
            return cur.fetchone()

    def get_recent_ingestion_runs(
        self,
        source: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if source:
            conditions.append("source = %s")
            params.append(source)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM ingestion_runs{where_clause} ORDER BY started_at DESC LIMIT %s"
        params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    # -- Schema introspection --------------------------------------------------

    def relation_exists(self, name: str) -> bool:
        with self._cursor() as cur:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL AS relation_exists", (name,))
            row = cur.fetchone()
        return bool(row["relation_exists"])

    # -- Personal finance (Telegram inbound ingestion, db/migrations/0008) --

    def get_finance_categories(self) -> list[dict[str, Any]]:
        """Active categories, for ``ops/finance_bot.py``'s free-text matcher
        AND ``api/routers/finance.py``'s ``GET /categories`` (which also
        needs ``emoji`` for display -- the bot never used it, easy to miss).
        list[dict], matching the convention already used for other small
        reference/lookup tables (``get_assets``, ``get_active_notification_rules``)
        rather than the DataFrame shape used for time-series reads."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, slug, name, kind, budget_bucket, emoji FROM finance_categories "
                "WHERE is_active ORDER BY slug ASC"
            )
            return cur.fetchall()

    def get_finance_accounts(self) -> list[dict[str, Any]]:
        """Active accounts, for ``ops/finance_bot.py``'s account-word matcher
        and default-account fallback."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, name, account_type, currency FROM finance_accounts "
                "WHERE is_active ORDER BY name ASC"
            )
            return cur.fetchall()

    def get_finance_sync_cursor(self, source: str) -> int | None:
        """The current high-water mark for ``source`` -- ``max`` over
        non-failed batches only, so a crashed pull never advances it (the
        partial index this mirrors is defined in 0008)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT max(cursor_update_id) AS cursor_update_id FROM finance_sync_batches "
                "WHERE source = %s AND status <> 'failed'",
                (source,),
            )
            row = cur.fetchone()
        return row["cursor_update_id"] if row else None

    def upsert_finance_transactions(self, rows: list[dict[str, Any]]) -> int:
        """Thin wrapper over ``_upsert_batch``: ``client_id`` is the
        idempotency key (deterministically derived by the caller from the
        Telegram ``update_id``), so replaying a batch upserts instead of
        duplicating."""
        return self._upsert_batch("finance_transactions", rows, conflict_cols=("client_id",))

    def insert_finance_sync_batch(
        self,
        *,
        source: str,
        cursor_update_id: int | None,
        received_count: int,
        applied_count: int,
        rejected_count: int,
        status: str,
        error_reason: str | None = None,
        details: dict[str, Any] | None = None,
        started_at: str | datetime,
        finished_at: str | datetime | None = None,
    ) -> None:
        """One audit row per poll -- the audit log IS the cursor (see 0008's
        comment on ``finance_sync_batches``)."""
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO finance_sync_batches
                    (source, cursor_update_id, received_count, applied_count, rejected_count,
                     status, error_reason, details, started_at, finished_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    source,
                    cursor_update_id,
                    received_count,
                    applied_count,
                    rejected_count,
                    status,
                    error_reason,
                    Jsonb(_json_safe(details or {})),
                    _timestamp_or_none(started_at),
                    _timestamp_or_none(finished_at),
                ),
            )

    # -- Personal finance (dashboard reads/writes, db/migrations/0009) ------

    def _upsert_by_id(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        """Update-by-id when the caller supplies one (an edit), else INSERT a
        fresh row. This is the shape for tables with no natural business key
        besides the surrogate ``id`` (recurring bills, goals) -- unlike
        ``client_id`` for transactions or the partial-unique-index pair for
        budgets, there's nothing else to conflict on. Every column present in
        ``row`` is overwritten on update, matching a UI that always submits
        the whole record."""
        payload = dict(row)
        record_id = payload.pop("id", None)
        columns = list(payload.keys())

        with self._cursor() as cur:
            if record_id:
                updates_sql = sql.SQL(", ").join(
                    sql.SQL("{column} = {placeholder}").format(
                        column=sql.Identifier(column), placeholder=sql.Placeholder()
                    )
                    for column in columns
                )
                query = sql.SQL(
                    "UPDATE {table} SET {updates}, updated_at = now() WHERE id = {placeholder} RETURNING *"
                ).format(table=sql.Identifier(table), updates=updates_sql, placeholder=sql.Placeholder())
                cur.execute(query, (*payload.values(), record_id))
                updated = cur.fetchone()
                if updated is None:
                    raise LocalPostgresError(f"{table} row not found: {record_id}")
                return updated

            insert_cols_sql = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
            placeholders_sql = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
            query = sql.SQL(
                "INSERT INTO {table} ({cols}) VALUES ({placeholders}) RETURNING *"
            ).format(table=sql.Identifier(table), cols=insert_cols_sql, placeholders=placeholders_sql)
            cur.execute(query, tuple(payload.values()))
            return cur.fetchone()

    def get_finance_transactions(
        self,
        *,
        month: str | None = None,
        category_id: str | None = None,
        account_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """The ledger feed for the dashboard's transaction list. Always
        excludes tombstoned rows -- a soft-deleted transaction (``deleted_at``
        set) is gone from every normal read, mirroring 0008's partial
        indexes. ``month`` is ``"YYYY-MM"``; the half-open range
        (``>= month-01`` and ``< next month-01``) is what lets Postgres use
        ``finance_transactions_occurred_idx`` instead of a function index on
        ``date_trunc``."""
        conditions = ["deleted_at IS NULL"]
        params: list[Any] = []
        if month:
            month_start = f"{month}-01"
            conditions.append("occurred_at >= %s::date AND occurred_at < (%s::date + interval '1 month')")
            params.extend([month_start, month_start])
        if category_id:
            conditions.append("category_id = %s")
            params.append(category_id)
        if account_id:
            conditions.append("account_id = %s")
            params.append(account_id)
        where_clause = " AND ".join(conditions)
        query = f"SELECT * FROM finance_transactions WHERE {where_clause} ORDER BY occurred_at DESC LIMIT %s"
        params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def upsert_finance_transaction(self, row: dict[str, Any]) -> dict[str, Any]:
        """Single-row wrapper over ``upsert_finance_transactions``'s batch
        upsert, for the dashboard's one-row-at-a-time PUT. Re-reads the row
        afterward because ``_upsert_batch`` returns only a count, matching
        this file's read-after-write convention elsewhere (e.g.
        ``upsert_risk_profile``'s ``RETURNING *``)."""
        self.upsert_finance_transactions([row])
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM finance_transactions WHERE client_id = %s",
                (row["client_id"],),
            )
            return cur.fetchone()

    def get_finance_budgets(self, *, month: str | None = None) -> list[dict[str, Any]]:
        """Effective budget per category for a calendar month, joined to its
        live actual spend. ``effective_budgets`` picks the dated row
        (``period_month`` = that month) over the standing row
        (``period_month IS NULL``) via ``DISTINCT ON``'s tie-break --
        mirroring the two partial unique indexes 0008 defines for exactly
        this dated-overrides-standing relationship. ``actual_cents`` is
        summed at read time, never cached, same principle as net worth
        totals below.

        ``month`` defaults to the current calendar month: "how am I doing on
        budget" is meaningless for an unspecified month.
        """
        month = month or date.today().strftime("%Y-%m")
        month_start = f"{month}-01"

        query = """
            WITH effective_budgets AS (
                SELECT DISTINCT ON (category_id) *
                FROM finance_budgets
                WHERE period_month = %s::date OR period_month IS NULL
                ORDER BY category_id, (period_month IS NOT NULL) DESC
            ),
            month_spend AS (
                SELECT category_id, SUM(amount_cents) AS actual_cents
                FROM finance_transactions
                WHERE kind = 'expense'
                  AND deleted_at IS NULL
                  AND occurred_at >= %s::date
                  AND occurred_at < (%s::date + interval '1 month')
                GROUP BY category_id
            )
            SELECT
                eb.category_id,
                c.name AS category_name,
                c.budget_bucket AS budget_bucket,
                eb.limit_cents,
                eb.percent_of_income,
                COALESCE(ms.actual_cents, 0) AS actual_cents
            FROM effective_budgets eb
            JOIN finance_categories c ON c.id = eb.category_id
            LEFT JOIN month_spend ms ON ms.category_id = eb.category_id
            ORDER BY c.name ASC
        """
        with self._cursor() as cur:
            cur.execute(query, (month_start, month_start, month_start))
            return cur.fetchall()

    def upsert_finance_budget(self, row: dict[str, Any]) -> dict[str, Any]:
        """Upsert a budget row, targeting whichever partial unique index
        (0008's dated-row-vs-standing-row split) matches ``period_month``.
        ``_upsert_batch``'s single ``ON CONFLICT`` target can't express a
        partial index, so this is hand-written, same reason
        ``upsert_risk_profile`` above is hand-written."""
        payload = dict(row)
        period_month = payload.get("period_month")
        columns = list(payload.keys())
        update_cols = [column for column in columns if column not in ("category_id", "period_month")]

        insert_cols_sql = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
        placeholders_sql = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
        updates_sql = sql.SQL(", ").join(
            sql.SQL("{column} = EXCLUDED.{column}").format(column=sql.Identifier(column))
            for column in update_cols
        )
        conflict_target = (
            sql.SQL("(category_id) WHERE period_month IS NULL")
            if period_month is None
            else sql.SQL("(category_id, period_month) WHERE period_month IS NOT NULL")
        )
        query = sql.SQL(
            "INSERT INTO finance_budgets ({cols}) VALUES ({placeholders}) "
            "ON CONFLICT {conflict} DO UPDATE SET {updates}, updated_at = now() "
            "RETURNING *"
        ).format(
            cols=insert_cols_sql,
            placeholders=placeholders_sql,
            conflict=conflict_target,
            updates=updates_sql,
        )
        params = tuple(payload[column] for column in columns)
        with self._cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()

    def get_finance_net_worth_snapshots(self, *, limit: int = 24) -> list[dict[str, Any]]:
        """Snapshots with totals computed at read time via a filtered
        aggregate over ``finance_net_worth_items`` -- 0008 deliberately does
        not store totals on the snapshot row (see its comment), so this is
        the one place that formula lives."""
        query = """
            SELECT
                s.id,
                s.snapshot_date,
                s.notes,
                s.created_at,
                COALESCE(SUM(i.amount_cents) FILTER (WHERE i.is_asset), 0) AS total_assets_cents,
                COALESCE(SUM(i.amount_cents) FILTER (WHERE NOT i.is_asset), 0) AS total_liabilities_cents,
                COALESCE(SUM(i.amount_cents) FILTER (WHERE i.is_asset), 0)
                    - COALESCE(SUM(i.amount_cents) FILTER (WHERE NOT i.is_asset), 0) AS net_worth_cents
            FROM finance_net_worth_snapshots s
            LEFT JOIN finance_net_worth_items i ON i.snapshot_id = s.id
            GROUP BY s.id
            ORDER BY s.snapshot_date DESC
            LIMIT %s
        """
        with self._cursor() as cur:
            cur.execute(query, (limit,))
            snapshots = cur.fetchall()
        if not snapshots:
            return []

        snapshot_ids = [row["id"] for row in snapshots]
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM finance_net_worth_items WHERE snapshot_id = ANY(%s) "
                "ORDER BY snapshot_id, is_asset DESC, label ASC",
                (snapshot_ids,),
            )
            items = cur.fetchall()

        items_by_snapshot: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            items_by_snapshot.setdefault(item["snapshot_id"], []).append(item)
        for row in snapshots:
            row["items"] = items_by_snapshot.get(row["id"], [])
        return snapshots

    def upsert_finance_net_worth_snapshot(
        self,
        *,
        snapshot_date: str,
        notes: str | None,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Upsert one snapshot and REPLACE its item list wholesale, all
        inside one transaction: a single ``_cursor()`` call spans every
        statement here, and the pool commits or rolls back that whole block
        as a unit (see ``_cursor()``'s docstring). Replacing rather than
        diffing items is deliberately simple -- the dashboard always submits
        the full worksheet, matching the book's paper-form workflow, not a
        line-item editor."""
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO finance_net_worth_snapshots (snapshot_date, notes)
                VALUES (%s, %s)
                ON CONFLICT (snapshot_date) DO UPDATE SET notes = EXCLUDED.notes
                RETURNING id, snapshot_date, notes, created_at
                """,
                (snapshot_date, notes),
            )
            snapshot = cur.fetchone()
            snapshot_id = snapshot["id"]

            cur.execute("DELETE FROM finance_net_worth_items WHERE snapshot_id = %s", (snapshot_id,))

            prepared_items: list[dict[str, Any]] = []
            for item in items:
                cur.execute(
                    """
                    INSERT INTO finance_net_worth_items
                        (snapshot_id, is_asset, label, item_type, amount_cents, currency)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        snapshot_id,
                        item["is_asset"],
                        item["label"],
                        item.get("item_type", "other"),
                        item["amount_cents"],
                        item["currency"],
                    ),
                )
                prepared_items.append(cur.fetchone())

        total_assets_cents = sum(item["amount_cents"] for item in prepared_items if item["is_asset"])
        total_liabilities_cents = sum(item["amount_cents"] for item in prepared_items if not item["is_asset"])
        return {
            **snapshot,
            "items": prepared_items,
            "total_assets_cents": total_assets_cents,
            "total_liabilities_cents": total_liabilities_cents,
            "net_worth_cents": total_assets_cents - total_liabilities_cents,
        }

    def get_finance_recurring_bills(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        """Bills joined to their next PENDING occurrence via a ``LATERAL``
        join (equivalent to the ``min(due_date) ... where status = 'pending'``
        read described in 0008's comment on
        ``finance_recurring_bill_payments_pending_idx``, but also carries
        that occurrence's status alongside its date)."""
        where_clause = "" if include_inactive else "WHERE b.is_active"
        query = f"""
            SELECT
                b.*,
                next_payment.due_date AS next_due_date,
                next_payment.status AS next_status
            FROM finance_recurring_bills b
            LEFT JOIN LATERAL (
                SELECT due_date, status
                FROM finance_recurring_bill_payments
                WHERE bill_id = b.id AND status = 'pending'
                ORDER BY due_date ASC
                LIMIT 1
            ) next_payment ON true
            {where_clause}
            ORDER BY b.name ASC
        """
        with self._cursor() as cur:
            cur.execute(query)
            return cur.fetchall()

    def upsert_finance_recurring_bill(self, row: dict[str, Any]) -> dict[str, Any]:
        return self._upsert_by_id("finance_recurring_bills", row)

    def upsert_finance_recurring_bill_payment(self, row: dict[str, Any]) -> dict[str, Any]:
        """Upsert one occurrence by its natural key (``bill_id``,
        ``due_date``) -- the unique index this targets is
        ``finance_recurring_bill_payments_occurrence_key`` from 0008."""
        self._upsert_batch(
            "finance_recurring_bill_payments", [row], conflict_cols=("bill_id", "due_date")
        )
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM finance_recurring_bill_payments WHERE bill_id = %s AND due_date = %s",
                (row["bill_id"], row["due_date"]),
            )
            return cur.fetchone()

    def get_finance_goals(self) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM finance_goals ORDER BY is_achieved ASC, target_date ASC NULLS LAST"
            )
            return cur.fetchall()

    def upsert_finance_goal(self, row: dict[str, Any]) -> dict[str, Any]:
        return self._upsert_by_id("finance_goals", row)


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _timestamp_or_none(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return _json_value(value)
