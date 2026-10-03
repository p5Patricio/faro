"""Repository for ``investment_accounts`` / ``investment_transactions``
(``db/migrations/0016_investment_ledger.sql``).

A ``LocalPostgresRepository`` subclass in its own module, like
``collector/macro_repository.py``. The base cursor decodes ``numeric`` as
``float``, which must never reach a quantity, a price or an FX rate here, so
those columns are selected as ``text`` and turned into ``Decimal``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from collector.local_repository import LocalPostgresRepository

INVESTMENT_TABLES: tuple[str, ...] = ("investment_accounts", "investment_transactions")

_DECIMAL_COLUMNS = ("quantity", "price", "fx_rate_to_mxn")

_TRANSACTION_COLUMNS = """
    id, client_id, account_id, trade_date, kind, symbol, instrument_type,
    quantity::text AS quantity, price::text AS price, amount_cents, fee_cents,
    tax_withheld_cents, currency, fx_rate_to_mxn::text AS fx_rate_to_mxn,
    fx_rate_date, fx_source, source, source_ref, notes, created_at, deleted_at
"""


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    for column in _DECIMAL_COLUMNS:
        if row.get(column) is not None:
            row[column] = Decimal(row[column])
    row["currency"] = row["currency"].strip()
    return row


class InvestmentRepository(LocalPostgresRepository):
    def tables_exist(self) -> bool:
        return all(self.relation_exists(table) for table in INVESTMENT_TABLES)

    def get_accounts(self) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM investment_accounts ORDER BY name")
            rows = cur.fetchall()
        for row in rows:
            row["currency"] = row["currency"].strip()
        return rows

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM investment_accounts WHERE id = %s", (account_id,))
            return cur.fetchone()

    def upsert_account(self, row: dict[str, Any]) -> dict[str, Any]:
        """Keyed by ``name``: saving the same name again edits that account."""
        self._upsert_batch("investment_accounts", [row], ("name",))
        with self._cursor() as cur:
            cur.execute("SELECT * FROM investment_accounts WHERE name = %s", (row["name"],))
            return cur.fetchone()

    def get_transactions(
        self, *, account_id: str | None = None, include_deleted: bool = False
    ) -> list[dict[str, Any]]:
        """In ledger replay order: ``trade_date`` then insertion time."""
        conditions = []
        params: list[Any] = []
        if account_id is not None:
            conditions.append("account_id = %s")
            params.append(account_id)
        if not include_deleted:
            conditions.append("deleted_at IS NULL")
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._cursor() as cur:
            cur.execute(
                f"SELECT {_TRANSACTION_COLUMNS} FROM investment_transactions{where} "
                "ORDER BY trade_date, created_at, id",
                params,
            )
            return [_decode(row) for row in cur.fetchall()]

    def upsert_transaction(self, row: dict[str, Any]) -> dict[str, Any]:
        """Idempotent on ``client_id``: replaying the same operation edits it."""
        self._upsert_batch("investment_transactions", [row], ("client_id",))
        with self._cursor() as cur:
            cur.execute(
                f"SELECT {_TRANSACTION_COLUMNS} FROM investment_transactions WHERE client_id = %s",
                (row["client_id"],),
            )
            return _decode(cur.fetchone())
