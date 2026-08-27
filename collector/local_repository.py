from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
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

    # -- Schema introspection --------------------------------------------------

    def relation_exists(self, name: str) -> bool:
        with self._cursor() as cur:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL AS relation_exists", (name,))
            row = cur.fetchone()
        return bool(row["relation_exists"])


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
