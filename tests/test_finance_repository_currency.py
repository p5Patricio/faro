"""DB-backed checks (real SQL, rolled-back per-test transaction) that the
personal-finance repository persists base amounts and that every SQL
aggregate reads them -- including rows written before base amounts were
materialized, which have a NULL ``amount_base_cents``."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import psycopg

from collector.local_repository import LocalPostgresRepository

MakeAccount = Callable[[str, str], str]


def _category_id(repository: LocalPostgresRepository, slug: str) -> str:
    return next(c["id"] for c in repository.get_finance_categories() if c["slug"] == slug)


def _insert_transaction(
    db_connection: psycopg.Connection,
    *,
    account_id: str,
    category_id: str,
    amount_cents: int,
    currency: str,
    fx_rate_to_base: float | None = None,
    amount_base_cents: int | None = None,
    kind: str = "expense",
    occurred_at: str = "2026-09-10T12:00:00+00:00",
) -> None:
    """Raw INSERT: lets a test write the legacy shape (NULL base columns)
    that the API no longer produces."""
    db_connection.execute(
        "INSERT INTO finance_transactions "
        "(client_id, account_id, category_id, kind, amount_cents, currency, fx_rate_to_base, "
        "amount_base_cents, occurred_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            str(uuid.uuid4()),
            account_id,
            category_id,
            kind,
            amount_cents,
            currency,
            fx_rate_to_base,
            amount_base_cents,
            occurred_at,
        ),
    )


def _transaction_row(account_id: str, category_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "client_id": str(uuid.uuid4()),
        "account_id": account_id,
        "category_id": category_id,
        "kind": "expense",
        "amount_cents": 5_000,
        "currency": "USD",
        "fx_rate_to_base": 17.5,
        "amount_base_cents": 87_500,
        "occurred_at": "2026-09-10T12:00:00+00:00",
    }
    row.update(overrides)
    return row


# -- Reads used by the currency rules ------------------------------------------


def test_get_finance_account_returns_the_account_with_its_currency(
    repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    account_id = make_finance_account("Cuenta USD de prueba", "USD")

    account = repository.get_finance_account(account_id)

    assert account is not None
    assert account["id"] == account_id
    assert account["currency"] == "USD"


def test_get_finance_account_finds_a_retired_account_and_none_for_an_unknown_id(
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    db_connection: psycopg.Connection,
) -> None:
    account_id = make_finance_account("Cuenta retirada", "MXN")
    db_connection.execute("UPDATE finance_accounts SET is_active = false WHERE id = %s", (account_id,))

    retired = repository.get_finance_account(account_id)

    assert retired is not None
    assert retired["is_active"] is False
    assert repository.get_finance_account(str(uuid.uuid4())) is None


def test_get_finance_transaction_by_client_id_returns_the_stored_row_or_none(
    repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    row = _transaction_row(make_finance_account("Cuenta USD de prueba", "USD"), _category_id(repository, "alimentacion"))
    repository.upsert_finance_transaction(row)

    stored = repository.get_finance_transaction_by_client_id(row["client_id"])

    assert stored is not None
    assert stored["amount_cents"] == 5_000
    assert repository.get_finance_transaction_by_client_id(str(uuid.uuid4())) is None


# -- Persistence ------------------------------------------------------------------


def test_upsert_finance_transaction_persists_rate_and_base_amount(
    repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    row = _transaction_row(make_finance_account("Cuenta USD de prueba", "USD"), _category_id(repository, "alimentacion"))

    stored = repository.upsert_finance_transaction(row)

    assert stored["fx_rate_to_base"] == 17.5
    assert stored["amount_base_cents"] == 87_500


def test_upsert_finance_transaction_edit_without_base_columns_leaves_them_untouched(
    repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    row = _transaction_row(make_finance_account("Cuenta USD de prueba", "USD"), _category_id(repository, "alimentacion"))
    repository.upsert_finance_transaction(row)

    edit = {k: v for k, v in row.items() if k not in ("fx_rate_to_base", "amount_base_cents")}
    edit["notes"] = "solo la nota"
    stored = repository.upsert_finance_transaction(edit)

    assert stored["notes"] == "solo la nota"
    assert stored["fx_rate_to_base"] == 17.5
    assert stored["amount_base_cents"] == 87_500


# -- Budget actuals ----------------------------------------------------------------


def test_budget_actuals_sum_base_amounts_including_legacy_base_currency_rows(
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    db_connection: psycopg.Connection,
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    mxn = make_finance_account("Cuenta MXN de prueba", "MXN")
    food = _category_id(repository, "alimentacion")
    repository.upsert_finance_budget(
        {"category_id": food, "period_month": "2026-09-01", "limit_cents": 300_000, "currency": "MXN"}
    )
    # Converted foreign expense: counts at its base value, not at 5,000.
    _insert_transaction(
        db_connection, account_id=usd, category_id=food, amount_cents=5_000, currency="USD",
        fx_rate_to_base=17.5, amount_base_cents=87_500,
    )
    # Base-currency expense written before base amounts existed (NULL column): still counts.
    _insert_transaction(db_connection, account_id=mxn, category_id=food, amount_cents=100_000, currency="MXN")
    # Foreign expense with no base amount: excluded rather than added raw.
    _insert_transaction(db_connection, account_id=usd, category_id=food, amount_cents=999_999, currency="USD")
    # Income never counts toward a budget's spend.
    _insert_transaction(
        db_connection, account_id=mxn, category_id=food, amount_cents=777_777, currency="MXN", kind="income"
    )

    budget = next(b for b in repository.get_finance_budgets(month="2026-09") if b["category_id"] == food)

    assert budget["actual_cents"] == 187_500
    assert isinstance(budget["actual_cents"], int)


def test_base_currency_match_is_case_insensitive_for_legacy_rows_in_budget_actuals(
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    db_connection: psycopg.Connection,
) -> None:
    """`currency` is char(3): a legacy row can hold 'mxn'. With a NULL base
    amount it must still count as its own base amount."""
    mxn = make_finance_account("Cuenta MXN de prueba", "MXN")
    food = _category_id(repository, "alimentacion")
    repository.upsert_finance_budget(
        {"category_id": food, "period_month": "2026-09-01", "limit_cents": 300_000, "currency": "MXN"}
    )
    _insert_transaction(db_connection, account_id=mxn, category_id=food, amount_cents=40_000, currency="mxn")
    _insert_transaction(db_connection, account_id=mxn, category_id=food, amount_cents=60_000, currency="MXN")

    budget = next(b for b in repository.get_finance_budgets(month="2026-09") if b["category_id"] == food)

    assert budget["actual_cents"] == 100_000


# -- Net worth -----------------------------------------------------------------------


def test_base_currency_match_is_case_insensitive_for_legacy_net_worth_items(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    snapshot_id = str(
        db_connection.execute(
            "INSERT INTO finance_net_worth_snapshots (snapshot_date) VALUES ('2026-09-15') RETURNING id"
        ).fetchone()[0]
    )
    for is_asset, label, amount_cents, currency in [
        (True, "Efectivo minusculas", 100_000, "mxn"),
        (True, "Efectivo", 50_000, "MXN"),
        (False, "Tarjeta minusculas", 30_000, "mxn"),
    ]:
        db_connection.execute(
            "INSERT INTO finance_net_worth_items (snapshot_id, is_asset, label, amount_cents, currency) "
            "VALUES (%s, %s, %s, %s, %s)",
            (snapshot_id, is_asset, label, amount_cents, currency),
        )

    latest = repository.get_finance_net_worth_snapshots(limit=1)[0]

    assert latest["total_assets_cents"] == 150_000
    assert latest["total_liabilities_cents"] == 30_000
    assert latest["net_worth_cents"] == 120_000


def test_upsert_net_worth_snapshot_persists_item_rates_and_returns_base_totals(
    repository: LocalPostgresRepository,
) -> None:
    snapshot = repository.upsert_finance_net_worth_snapshot(
        snapshot_date="2026-09-15",
        notes=None,
        items=[
            {
                "is_asset": True, "label": "Dolares", "amount_cents": 10_000, "currency": "USD",
                "fx_rate_to_base": 17.5, "amount_base_cents": 175_000,
            },
            {
                "is_asset": False, "label": "Tarjeta", "amount_cents": 30_000, "currency": "MXN",
                "fx_rate_to_base": 1, "amount_base_cents": 30_000,
            },
        ],
    )

    dollars = next(item for item in snapshot["items"] if item["label"] == "Dolares")
    assert dollars["fx_rate_to_base"] == 17.5
    assert dollars["amount_base_cents"] == 175_000
    assert snapshot["total_assets_cents"] == 175_000
    assert snapshot["total_liabilities_cents"] == 30_000
    assert snapshot["net_worth_cents"] == 145_000


def test_net_worth_snapshot_totals_read_base_amounts_including_legacy_base_currency_items(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    snapshot_id = str(
        db_connection.execute(
            "INSERT INTO finance_net_worth_snapshots (snapshot_date) VALUES ('2026-09-15') RETURNING id"
        ).fetchone()[0]
    )
    items = [
        # (is_asset, label, amount_cents, currency, fx_rate_to_base, amount_base_cents)
        (True, "Dolares", 10_000, "USD", 17.5, 175_000),  # converted
        (True, "Efectivo", 100_000, "MXN", None, None),  # legacy base row, NULL columns
        (True, "Sin tasa", 999_999, "USD", None, None),  # foreign, no base amount: excluded
        (False, "Tarjeta", 30_000, "MXN", None, None),  # legacy base liability
    ]
    for is_asset, label, amount_cents, currency, fx_rate, base_cents in items:
        db_connection.execute(
            "INSERT INTO finance_net_worth_items "
            "(snapshot_id, is_asset, label, amount_cents, currency, fx_rate_to_base, amount_base_cents) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (snapshot_id, is_asset, label, amount_cents, currency, fx_rate, base_cents),
        )

    latest = repository.get_finance_net_worth_snapshots(limit=1)[0]

    assert latest["total_assets_cents"] == 275_000
    assert latest["total_liabilities_cents"] == 30_000
    assert latest["net_worth_cents"] == 245_000
    assert isinstance(latest["net_worth_cents"], int)
