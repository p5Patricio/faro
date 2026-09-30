from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.main import app, get_repository
from api.routers import finance as finance_router
from collector.local_repository import LocalPostgresRepository

MakeAccount = Callable[[str, str], str]


@pytest.fixture()
def finance_client(repository: LocalPostgresRepository) -> Iterator[TestClient]:
    """A TestClient wired to the REAL repository fixture (session test DB,
    per-test rolled-back transaction from conftest.py) -- exercises the
    actual SQL in collector/local_repository.py, not a FakeRepository stand-in,
    since this suite's job is to prove the PUT/GET round trip really persists."""
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _category_id(repository: LocalPostgresRepository, slug: str) -> str:
    match = next(c for c in repository.get_finance_categories() if c["slug"] == slug)
    return match["id"]


# -- Reference data (seeded by 0008, so not literally empty) -----------------


def test_get_categories_returns_seeded_categories(finance_client: TestClient) -> None:
    response = finance_client.get("/api/finance/categories")

    assert response.status_code == 200
    slugs = {category["slug"] for category in response.json()}
    assert "alimentacion" in slugs
    assert "sueldo" in slugs


def test_get_accounts_returns_seeded_accounts(finance_client: TestClient) -> None:
    response = finance_client.get("/api/finance/accounts")

    assert response.status_code == 200
    names = {account["name"] for account in response.json()}
    assert "Efectivo" in names


# -- Transactions --------------------------------------------------------


def test_get_transactions_returns_empty_list_when_none_exist(finance_client: TestClient) -> None:
    response = finance_client.get("/api/finance/transactions")

    assert response.status_code == 200
    assert response.json() == []


def test_put_transaction_then_get_reflects_it(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    client_id = str(uuid.uuid4())

    put_response = finance_client.put(
        "/api/finance/transactions",
        json={
            "client_id": client_id,
            "account_id": make_finance_account("Cuenta MXN de prueba", "MXN"),
            "category_id": _category_id(repository, "alimentacion"),
            "kind": "expense",
            "amount_cents": 15000,
            "currency": "MXN",
            "occurred_at": "2026-09-10T12:00:00+00:00",
            "notes": "almuerzo",
        },
    )

    assert put_response.status_code == 200
    assert put_response.json()["client_id"] == client_id
    assert put_response.json()["amount_cents"] == 15000

    get_response = finance_client.get("/api/finance/transactions", params={"month": "2026-09"})
    assert get_response.status_code == 200
    matches = [row for row in get_response.json() if row["client_id"] == client_id]
    assert len(matches) == 1
    assert matches[0]["notes"] == "almuerzo"


def test_put_transaction_soft_delete_omits_deleted_row_from_get(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    client_id = str(uuid.uuid4())
    account_id = make_finance_account("Cuenta MXN de prueba", "MXN")
    category_id = _category_id(repository, "alimentacion")

    finance_client.put(
        "/api/finance/transactions",
        json={
            "client_id": client_id,
            "account_id": account_id,
            "category_id": category_id,
            "kind": "expense",
            "amount_cents": 5000,
            "currency": "MXN",
            "occurred_at": "2026-09-10T12:00:00+00:00",
        },
    )

    delete_response = finance_client.put(
        "/api/finance/transactions",
        json={
            "client_id": client_id,
            "account_id": account_id,
            "category_id": category_id,
            "kind": "expense",
            "amount_cents": 5000,
            "currency": "MXN",
            "occurred_at": "2026-09-10T12:00:00+00:00",
            "deleted_at": "2026-09-11T00:00:00+00:00",
        },
    )
    assert delete_response.status_code == 200

    get_response = finance_client.get("/api/finance/transactions", params={"month": "2026-09"})
    assert all(row["client_id"] != client_id for row in get_response.json())


# -- Budgets -----------------------------------------------------------


def test_get_budgets_returns_empty_list_when_none_exist(finance_client: TestClient) -> None:
    response = finance_client.get("/api/finance/budgets", params={"month": "2026-09"})

    assert response.status_code == 200
    assert response.json() == []


def test_put_budget_then_get_reflects_it(
    finance_client: TestClient, repository: LocalPostgresRepository
) -> None:
    category_id = _category_id(repository, "entretenimiento")

    put_response = finance_client.put(
        "/api/finance/budgets",
        json={
            "category_id": category_id,
            "period_month": "2026-09-01",
            "limit_cents": 500_00,
            "percent_of_income": 10.0,
            "currency": "MXN",
        },
    )
    assert put_response.status_code == 200
    assert put_response.json()["limit_cents"] == 500_00

    get_response = finance_client.get("/api/finance/budgets", params={"month": "2026-09"})
    assert get_response.status_code == 200
    matches = [row for row in get_response.json() if row["category_id"] == category_id]
    assert len(matches) == 1
    assert matches[0]["limit_cents"] == 500_00
    assert matches[0]["actual_cents"] == 0


# -- Net worth -----------------------------------------------------------


def test_get_net_worth_returns_empty_list_when_none_exist(finance_client: TestClient) -> None:
    response = finance_client.get("/api/finance/net-worth")

    assert response.status_code == 200
    assert response.json() == []


def test_put_net_worth_then_get_reflects_computed_totals(finance_client: TestClient) -> None:
    put_response = finance_client.put(
        "/api/finance/net-worth",
        json={
            "snapshot_date": "2026-09-15",
            "notes": "prueba",
            "items": [
                {"is_asset": True, "label": "Efectivo", "item_type": "cash", "amount_cents": 100_000, "currency": "MXN"},
                {"is_asset": False, "label": "Tarjeta", "item_type": "credit_card", "amount_cents": 30_000, "currency": "MXN"},
            ],
        },
    )

    assert put_response.status_code == 200
    payload = put_response.json()
    assert payload["total_assets_cents"] == 100_000
    assert payload["total_liabilities_cents"] == 30_000
    assert payload["net_worth_cents"] == 70_000

    get_response = finance_client.get("/api/finance/net-worth")
    assert get_response.status_code == 200
    snapshots = get_response.json()
    assert len(snapshots) == 1
    assert snapshots[0]["net_worth_cents"] == 70_000
    assert len(snapshots[0]["items"]) == 2


# -- Recurring bills -------------------------------------------------------


def test_get_recurring_bills_returns_empty_list_when_none_exist(finance_client: TestClient) -> None:
    response = finance_client.get("/api/finance/recurring-bills")

    assert response.status_code == 200
    assert response.json() == []


def test_put_recurring_bill_then_get_reflects_it(finance_client: TestClient) -> None:
    put_response = finance_client.put(
        "/api/finance/recurring-bills",
        json={
            "name": "Netflix",
            "amount_cents": 199_00,
            "currency": "MXN",
            "frequency": "monthly",
            "anchor_due_date": "2026-09-05",
        },
    )

    assert put_response.status_code == 200
    assert put_response.json()["name"] == "Netflix"

    get_response = finance_client.get("/api/finance/recurring-bills")
    assert get_response.status_code == 200
    names = [row["name"] for row in get_response.json()]
    assert "Netflix" in names


def test_put_recurring_bill_payment_marks_it_paid_with_timestamp(finance_client: TestClient) -> None:
    bill = finance_client.put(
        "/api/finance/recurring-bills",
        json={
            "name": "Luz",
            "amount_cents": 80_00,
            "currency": "MXN",
            "frequency": "monthly",
            "anchor_due_date": "2026-09-05",
        },
    ).json()

    payment_response = finance_client.put(
        "/api/finance/recurring-bills/payments",
        json={"bill_id": bill["id"], "due_date": "2026-09-05", "status": "paid"},
    )

    assert payment_response.status_code == 200
    payload = payment_response.json()
    assert payload["status"] == "paid"
    assert payload["paid_at"] is not None


# -- Goals -------------------------------------------------------------


def test_get_goals_returns_empty_list_when_none_exist(finance_client: TestClient) -> None:
    response = finance_client.get("/api/finance/goals")

    assert response.status_code == 200
    assert response.json() == []


def test_put_goal_then_get_reflects_it(finance_client: TestClient) -> None:
    put_response = finance_client.put(
        "/api/finance/goals",
        json={
            "name": "Fondo de emergencia",
            "target_amount_cents": 60_000_00,
            "currency": "MXN",
        },
    )

    assert put_response.status_code == 200
    assert put_response.json()["name"] == "Fondo de emergencia"

    get_response = finance_client.get("/api/finance/goals")
    assert get_response.status_code == 200
    names = [row["name"] for row in get_response.json()]
    assert "Fondo de emergencia" in names


# -- Summary ---------------------------------------------------------------


def test_get_summary_degrades_gracefully_with_no_data(
    finance_client: TestClient, pin_today: Callable[[date], None]
) -> None:
    """The exact payload a brand-new user gets. The frontend fixture in
    `ui/src/features/finance/FinanceDashboard.test.tsx` mirrors it, so the UI
    is tested against what production returns, not an invented shape."""
    response = finance_client.get("/api/finance/summary", params={"month": "2026-09"})

    assert response.status_code == 200
    assert response.json() == {
        "month": "2026-09",
        # No converted transaction this month: not sufficient (it used to be hard-coded true).
        "monthly_summary": {
            "data_sufficient": False,
            "income_cents": 0,
            "expense_cents": 0,
            "spending_cents": 0,
            "saved_cents": 0,
            "net_cents": 0,
            "savings_rate_pct": 0.0,
            "buckets": {
                "necesidad": {"actual_cents": 0, "target_cents": 0},
                "deseo": {"actual_cents": 0, "target_cents": 0},
                "ahorro_inversion": {"actual_cents": 0, "target_cents": 0},
                "sin_categoria": {"actual_cents": 0},
            },
            "converted_transactions": 0,
            "unconverted_transactions": 0,
        },
        "category_breakdown": [],
        "history": {
            "months_used": 0,
            "months_considered": 3,
            "min_transactions_per_month": 5,
            "unconverted_transactions": 0,
        },
        "net_worth": {
            "data_sufficient": False,
            "snapshot_date": None,
            "total_assets_cents": None,
            "total_liabilities_cents": None,
            "net_worth_cents": None,
            "liquid_net_worth_cents": None,
        },
        "emergency_fund": {
            "data_sufficient": False,
            "months_covered": None,
            "target_min_months": 3,
            "target_max_months": 6,
            "status": "below",
        },
        "fire_number": {"data_sufficient": False, "target_cents": 0, "progress_pct": None},
        "investable_surplus": {
            "data_sufficient": False,
            "surplus_cents": 0,
            "reason": "building_emergency_fund",
            "available_cents": 0,
            "shortfall_cents": 0,
            "income_cents": 0,
            "spending_cents": 0,
            "saved_cents": 0,
        },
        # No subscriptions is a true zero, not a data gap, so this stays sufficient.
        "subscriptions": {
            "data_sufficient": True,
            "annual_total_cents": 0,
            "monthly_average_cents": 0,
            "bills": [],
            "unconverted_bills": 0,
        },
        "cash_flow_forecast": {
            "data_sufficient": False,
            "horizon_days": 30,
            "income_data_sufficient": False,
            "expected_income_cents": None,
            "committed_bills_cents": 0,
            "overdue_bills_cents": 0,
            "overdue_bills_count": 0,
            "projected_net_cents": None,
        },
    }


# -- Currency rules (decision D1: base currency MXN) --------------------------

TRANSACTIONS_URL = "/api/finance/transactions"


def _tx_body(account_id: str, category_id: str, **overrides: Any) -> dict[str, Any]:
    """A USD 50.00 expense booked at 17.5 MXN per USD (= MXN 875.00)."""
    body: dict[str, Any] = {
        "client_id": str(uuid.uuid4()),
        "account_id": account_id,
        "category_id": category_id,
        "kind": "expense",
        "amount_cents": 5_000,
        "currency": "USD",
        "fx_rate_to_base": 17.5,
        "occurred_at": "2026-09-10T12:00:00+00:00",
    }
    body.update(overrides)
    return body


def test_put_transaction_in_base_currency_stores_rate_one_and_base_amount(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    mxn = make_finance_account("Cuenta MXN de prueba", "MXN")
    body = _tx_body(mxn, _category_id(repository, "alimentacion"), currency="MXN", amount_cents=15_000)
    del body["fx_rate_to_base"]

    response = finance_client.put(TRANSACTIONS_URL, json=body)

    assert response.status_code == 200
    row = response.json()
    assert row["fx_rate_to_base"] == 1
    assert row["amount_base_cents"] == 15_000


def test_put_transaction_ignores_a_client_sent_rate_for_the_base_currency(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    mxn = make_finance_account("Cuenta MXN de prueba", "MXN")
    body = _tx_body(mxn, _category_id(repository, "alimentacion"), currency="MXN", fx_rate_to_base=99.0)

    row = finance_client.put(TRANSACTIONS_URL, json=body).json()

    assert row["fx_rate_to_base"] == 1
    assert row["amount_base_cents"] == 5_000


def test_put_transaction_computes_the_base_amount_server_side(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")

    response = finance_client.put(TRANSACTIONS_URL, json=_tx_body(usd, _category_id(repository, "alimentacion")))

    assert response.status_code == 200
    row = response.json()
    assert row["currency"] == "USD"
    assert row["fx_rate_to_base"] == 17.5
    assert row["amount_base_cents"] == 87_500


def test_put_transaction_never_trusts_a_client_sent_base_amount(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    mxn = make_finance_account("Cuenta MXN de prueba", "MXN")
    category_id = _category_id(repository, "alimentacion")

    foreign = finance_client.put(
        TRANSACTIONS_URL, json=_tx_body(usd, category_id, amount_base_cents=1)
    ).json()
    base = finance_client.put(
        TRANSACTIONS_URL,
        json=_tx_body(mxn, category_id, currency="MXN", amount_base_cents=1, fx_rate_to_base=None),
    ).json()

    assert foreign["amount_base_cents"] == 87_500
    assert base["amount_base_cents"] == 5_000


def test_put_transaction_normalizes_lowercase_currency(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")

    response = finance_client.put(
        TRANSACTIONS_URL, json=_tx_body(usd, _category_id(repository, "alimentacion"), currency="usd")
    )

    assert response.status_code == 200
    assert response.json()["currency"] == "USD"


def test_put_transaction_rejects_a_currency_that_differs_from_its_account(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    mxn = make_finance_account("Cuenta MXN de prueba", "MXN")

    response = finance_client.put(TRANSACTIONS_URL, json=_tx_body(mxn, _category_id(repository, "alimentacion")))

    assert response.status_code == 422
    assert "USD" in response.json()["detail"]
    assert "MXN" in response.json()["detail"]
    assert finance_client.get(TRANSACTIONS_URL).json() == []


def test_put_transaction_rejects_a_base_currency_payload_on_a_foreign_account(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    body = _tx_body(usd, _category_id(repository, "alimentacion"), currency="MXN")

    assert finance_client.put(TRANSACTIONS_URL, json=body).status_code == 422


@pytest.mark.parametrize("fx_rate", [None, 0, -3.5])
def test_put_transaction_in_a_foreign_currency_requires_a_positive_rate(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    fx_rate: float | None,
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    body = _tx_body(usd, _category_id(repository, "alimentacion"), fx_rate_to_base=fx_rate)
    if fx_rate is None:
        del body["fx_rate_to_base"]

    response = finance_client.put(TRANSACTIONS_URL, json=body)

    assert response.status_code == 422
    assert "MXN" in response.json()["detail"]
    assert finance_client.get(TRANSACTIONS_URL).json() == []


def test_put_transaction_rejects_an_unknown_account_with_422_not_503(
    finance_client: TestClient, repository: LocalPostgresRepository
) -> None:
    body = _tx_body(str(uuid.uuid4()), _category_id(repository, "alimentacion"), currency="MXN")

    response = finance_client.put(TRANSACTIONS_URL, json=body)

    assert response.status_code == 422


def test_put_transaction_notes_only_edit_keeps_stored_rate_and_base_amount(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    category_id = _category_id(repository, "alimentacion")
    body = _tx_body(usd, category_id)
    assert finance_client.put(TRANSACTIONS_URL, json=body).status_code == 200

    # The edit omits the rate and the optional category entirely: only the
    # fields the client sent may change.
    edit = {k: v for k, v in body.items() if k not in ("fx_rate_to_base", "category_id")}
    edit["notes"] = "solo cambia la nota"
    response = finance_client.put(TRANSACTIONS_URL, json=edit)

    assert response.status_code == 200
    row = response.json()
    assert row["notes"] == "solo cambia la nota"
    assert row["category_id"] == category_id
    assert row["fx_rate_to_base"] == 17.5
    assert row["amount_base_cents"] == 87_500


def test_put_transaction_soft_delete_keeps_the_base_amount_of_a_foreign_row(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    body = _tx_body(usd, _category_id(repository, "alimentacion"))
    finance_client.put(TRANSACTIONS_URL, json=body)

    tombstone = {k: v for k, v in body.items() if k != "fx_rate_to_base"}
    tombstone["deleted_at"] = "2026-09-11T00:00:00+00:00"
    assert finance_client.put(TRANSACTIONS_URL, json=tombstone).status_code == 200

    stored = repository.get_finance_transaction_by_client_id(body["client_id"])
    assert stored is not None
    assert stored["deleted_at"] is not None
    assert stored["amount_base_cents"] == 87_500


def test_put_transaction_amount_only_edit_reuses_the_stored_rate(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    body = _tx_body(usd, _category_id(repository, "alimentacion"))
    finance_client.put(TRANSACTIONS_URL, json=body)

    edit = {k: v for k, v in body.items() if k != "fx_rate_to_base"}
    edit["amount_cents"] = 10_000
    row = finance_client.put(TRANSACTIONS_URL, json=edit).json()

    assert row["fx_rate_to_base"] == 17.5
    assert row["amount_base_cents"] == 175_000


def test_put_transaction_new_rate_recomputes_the_base_amount(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    body = _tx_body(usd, _category_id(repository, "alimentacion"))
    finance_client.put(TRANSACTIONS_URL, json=body)

    row = finance_client.put(TRANSACTIONS_URL, json={**body, "fx_rate_to_base": 20.0}).json()

    assert row["fx_rate_to_base"] == 20.0
    assert row["amount_base_cents"] == 100_000


def test_put_transaction_editing_a_row_without_a_stored_rate_needs_one_only_when_money_changes(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    db_connection: psycopg.Connection,
) -> None:
    """A row written before base amounts existed (foreign currency, NULL
    rate) must stay deletable/annotatable, but re-stating its amount without a
    rate cannot silently invent a base amount."""
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    category_id = _category_id(repository, "alimentacion")
    body = _tx_body(usd, category_id)
    db_connection.execute(
        "INSERT INTO finance_transactions (client_id, account_id, category_id, kind, amount_cents, currency, occurred_at) "
        "VALUES (%s, %s, %s, 'expense', 5000, 'USD', '2026-09-10T12:00:00+00:00')",
        (body["client_id"], usd, category_id),
    )
    no_rate = {k: v for k, v in body.items() if k != "fx_rate_to_base"}

    annotated = finance_client.put(TRANSACTIONS_URL, json={**no_rate, "notes": "legacy"})
    restated = finance_client.put(TRANSACTIONS_URL, json={**no_rate, "amount_cents": 6_000})

    assert annotated.status_code == 200
    assert annotated.json()["amount_base_cents"] is None
    assert restated.status_code == 422


# -- Base-currency-only records (bills, goals, budgets) ------------------------


def test_put_recurring_bill_rejects_a_non_base_currency(finance_client: TestClient) -> None:
    response = finance_client.put(
        "/api/finance/recurring-bills",
        json={
            "name": "iCloud",
            "amount_cents": 999,
            "currency": "USD",
            "frequency": "monthly",
            "anchor_due_date": "2026-09-05",
        },
    )

    assert response.status_code == 422
    assert "MXN" in response.json()["detail"]
    assert finance_client.get("/api/finance/recurring-bills").json() == []


def test_put_recurring_bill_accepts_the_base_currency_in_any_case(finance_client: TestClient) -> None:
    response = finance_client.put(
        "/api/finance/recurring-bills",
        json={
            "name": "Luz",
            "amount_cents": 8_000,
            "currency": "mxn",
            "frequency": "monthly",
            "anchor_due_date": "2026-09-05",
        },
    )

    assert response.status_code == 200
    assert response.json()["currency"] == "MXN"


def test_put_goal_rejects_a_non_base_currency(finance_client: TestClient) -> None:
    response = finance_client.put(
        "/api/finance/goals",
        json={"name": "Viaje", "target_amount_cents": 100_000, "currency": "USD"},
    )

    assert response.status_code == 422
    assert "MXN" in response.json()["detail"]
    assert finance_client.get("/api/finance/goals").json() == []


def test_put_budget_rejects_a_non_base_currency(
    finance_client: TestClient, repository: LocalPostgresRepository
) -> None:
    response = finance_client.put(
        "/api/finance/budgets",
        json={
            "category_id": _category_id(repository, "entretenimiento"),
            "period_month": "2026-09-01",
            "limit_cents": 50_000,
            "currency": "USD",
        },
    )

    assert response.status_code == 422
    assert "MXN" in response.json()["detail"]
    assert finance_client.get("/api/finance/budgets", params={"month": "2026-09"}).json() == []


# -- Net worth in the base currency ----------------------------------------------


def test_put_net_worth_totals_are_computed_from_base_amounts(finance_client: TestClient) -> None:
    put_response = finance_client.put(
        "/api/finance/net-worth",
        json={
            "snapshot_date": "2026-09-15",
            "items": [
                {"is_asset": True, "label": "Dolares", "amount_cents": 10_000, "currency": "USD", "fx_rate_to_base": 17.5},
                {"is_asset": True, "label": "Efectivo", "amount_cents": 100_000, "currency": "MXN"},
                {"is_asset": False, "label": "Tarjeta", "amount_cents": 30_000, "currency": "MXN"},
            ],
        },
    )

    assert put_response.status_code == 200
    payload = put_response.json()
    # USD 100.00 at 17.5 = MXN 1,750.00; not the raw 100.00 + 1,000.00 - 300.00.
    assert payload["total_assets_cents"] == 175_000 + 100_000
    assert payload["total_liabilities_cents"] == 30_000
    assert payload["net_worth_cents"] == 245_000

    stored = finance_client.get("/api/finance/net-worth").json()[0]
    assert stored["net_worth_cents"] == 245_000
    dollars = next(item for item in stored["items"] if item["label"] == "Dolares")
    assert dollars["fx_rate_to_base"] == 17.5
    assert dollars["amount_base_cents"] == 175_000
    cash = next(item for item in stored["items"] if item["label"] == "Efectivo")
    assert cash["fx_rate_to_base"] == 1
    assert cash["amount_base_cents"] == 100_000


def test_put_net_worth_rejects_a_foreign_item_without_a_rate(finance_client: TestClient) -> None:
    response = finance_client.put(
        "/api/finance/net-worth",
        json={
            "snapshot_date": "2026-09-15",
            "items": [{"is_asset": True, "label": "Dolares", "amount_cents": 10_000, "currency": "USD"}],
        },
    )

    assert response.status_code == 422
    assert "Dolares" in response.json()["detail"]
    assert finance_client.get("/api/finance/net-worth").json() == []


# -- Boundary validation: amounts must fit bigint cents -----------------------------

BIGINT_MAX = 9_223_372_036_854_775_807


def test_put_transaction_rejects_an_amount_beyond_bigint_with_422(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")

    response = finance_client.put(
        TRANSACTIONS_URL,
        json=_tx_body(usd, _category_id(repository, "alimentacion"), amount_cents=10**70),
    )

    assert response.status_code == 422
    assert finance_client.get(TRANSACTIONS_URL).json() == []


def test_put_transaction_rejects_a_converted_amount_beyond_bigint_with_422(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    """Each factor is individually valid (amount within bigint, rate below the
    numeric(18,8) ceiling); only their product overflows the base column."""
    usd = make_finance_account("Cuenta USD de prueba", "USD")

    response = finance_client.put(
        TRANSACTIONS_URL,
        json=_tx_body(
            usd,
            _category_id(repository, "alimentacion"),
            amount_cents=BIGINT_MAX,
            fx_rate_to_base=9_999_999_999.0,
        ),
    )

    assert response.status_code == 422
    assert finance_client.get(TRANSACTIONS_URL).json() == []


def test_put_transaction_accepts_the_largest_bigint_amount_and_rejects_one_more(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    mxn = make_finance_account("Cuenta MXN de prueba", "MXN")
    category_id = _category_id(repository, "alimentacion")

    at_limit = finance_client.put(
        TRANSACTIONS_URL,
        json=_tx_body(mxn, category_id, currency="MXN", amount_cents=BIGINT_MAX, fx_rate_to_base=None),
    )
    over_limit = finance_client.put(
        TRANSACTIONS_URL,
        json=_tx_body(mxn, category_id, currency="MXN", amount_cents=BIGINT_MAX + 1, fx_rate_to_base=None),
    )

    assert at_limit.status_code == 200
    assert at_limit.json()["amount_base_cents"] == BIGINT_MAX
    assert over_limit.status_code == 422


def test_put_net_worth_rejects_a_converted_amount_beyond_bigint_with_422(finance_client: TestClient) -> None:
    response = finance_client.put(
        "/api/finance/net-worth",
        json={
            "snapshot_date": "2026-09-15",
            "items": [
                {
                    "is_asset": True,
                    "label": "Dolares",
                    "amount_cents": BIGINT_MAX,
                    "currency": "USD",
                    "fx_rate_to_base": 9_999_999_999.0,
                }
            ],
        },
    )

    assert response.status_code == 422
    assert finance_client.get("/api/finance/net-worth").json() == []


def test_amount_fields_beyond_bigint_are_422_on_every_write_endpoint(
    finance_client: TestClient, repository: LocalPostgresRepository
) -> None:
    too_big = 10**70
    bodies = {
        "/api/finance/net-worth": {
            "snapshot_date": "2026-09-15",
            "items": [{"is_asset": True, "label": "Efectivo", "amount_cents": too_big, "currency": "MXN"}],
        },
        "/api/finance/recurring-bills": {
            "name": "Luz",
            "amount_cents": too_big,
            "currency": "MXN",
            "frequency": "monthly",
            "anchor_due_date": "2026-09-05",
        },
        "/api/finance/goals": {"name": "Viaje", "target_amount_cents": too_big, "currency": "MXN"},
        "/api/finance/budgets": {
            "category_id": _category_id(repository, "entretenimiento"),
            "period_month": "2026-09-01",
            "limit_cents": too_big,
            "currency": "MXN",
        },
    }

    for url, body in bodies.items():
        assert finance_client.put(url, json=body).status_code == 422, url

    current_too_big = {"name": "Viaje", "target_amount_cents": 1_000, "current_amount_cents": too_big, "currency": "MXN"}
    assert finance_client.put("/api/finance/goals", json=current_too_big).status_code == 422


# -- Runtime scenario: the summary of a mixed-currency month -----------------------


def test_runtime_scenario_summary_of_a_mixed_currency_month_uses_base_amounts(
    finance_client: TestClient, repository: LocalPostgresRepository, make_finance_account: MakeAccount
) -> None:
    """End to end through the real HTTP stack and SQL: a USD expense and an
    MXN expense are PUT, then /summary and /budgets must total them in pesos
    (the USD 50.00 at 17.5 plus MXN 1,000.00 is 187,500 cents, not the 1,050.00
    a sum of raw amounts would report)."""
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    mxn = make_finance_account("Cuenta MXN de prueba", "MXN")
    food = _category_id(repository, "alimentacion")
    salary = _category_id(repository, "sueldo")

    puts = [
        _tx_body(usd, food),
        _tx_body(mxn, food, currency="MXN", amount_cents=100_000, fx_rate_to_base=None),
        _tx_body(mxn, salary, kind="income", currency="MXN", amount_cents=500_000, fx_rate_to_base=None),
    ]
    for body in puts:
        if body["fx_rate_to_base"] is None:
            del body["fx_rate_to_base"]
        assert finance_client.put(TRANSACTIONS_URL, json=body).status_code == 200
    assert (
        finance_client.put(
            "/api/finance/budgets",
            json={"category_id": food, "period_month": "2026-09-01", "limit_cents": 300_000, "currency": "MXN"},
        ).status_code
        == 200
    )

    summary = finance_client.get("/api/finance/summary", params={"month": "2026-09"}).json()["monthly_summary"]
    budgets = finance_client.get("/api/finance/budgets", params={"month": "2026-09"}).json()

    assert summary["expense_cents"] == 187_500
    assert summary["income_cents"] == 500_000
    assert summary["net_cents"] == 312_500
    assert summary["buckets"]["necesidad"]["actual_cents"] == 187_500
    assert summary["unconverted_transactions"] == 0
    assert next(b for b in budgets if b["category_id"] == food)["actual_cents"] == 187_500


def test_summary_counts_but_does_not_add_a_foreign_transaction_without_a_base_amount(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    db_connection: psycopg.Connection,
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    mxn = make_finance_account("Cuenta MXN de prueba", "MXN")
    food = _category_id(repository, "alimentacion")
    finance_client.put(
        TRANSACTIONS_URL,
        json=_tx_body(mxn, food, currency="MXN", amount_cents=100_000, fx_rate_to_base=None),
    )
    # Written before base amounts existed: foreign currency, NULL base columns.
    db_connection.execute(
        "INSERT INTO finance_transactions (client_id, account_id, category_id, kind, amount_cents, currency, occurred_at) "
        "VALUES (%s, %s, %s, 'expense', 5000, 'USD', '2026-09-12T12:00:00+00:00')",
        (str(uuid.uuid4()), usd, food),
    )

    summary = finance_client.get("/api/finance/summary", params={"month": "2026-09"}).json()["monthly_summary"]

    assert summary["expense_cents"] == 100_000
    assert summary["unconverted_transactions"] == 1


# -- Recurring-bill lifecycle and forecast ------------------------------------------

BILLS_URL = "/api/finance/recurring-bills"
PAYMENTS_URL = "/api/finance/recurring-bills/payments"
SUMMARY_URL = "/api/finance/summary"


@pytest.fixture()
def pin_today(monkeypatch: pytest.MonkeyPatch) -> Callable[[date], None]:
    """Pin the router's machine-local clock (a Tuesday by default). Returns a
    function that moves it, so one test can walk through several days."""

    def _pin(day: date) -> None:
        monkeypatch.setattr(finance_router, "_today", lambda: day)

    _pin(date(2026, 9, 29))
    return _pin


def _put_bill(client: TestClient, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Netflix",
        "amount_cents": 19_900,
        "currency": "MXN",
        "frequency": "monthly",
        "anchor_due_date": "2026-01-05",
    }
    body.update(overrides)
    response = client.put(BILLS_URL, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _put_payment(client: TestClient, bill_id: str, due_date: str, status: str) -> dict[str, Any]:
    response = client.put(PAYMENTS_URL, json={"bill_id": bill_id, "due_date": due_date, "status": status})
    assert response.status_code == 200, response.text
    return response.json()


def _listed_bill(client: TestClient, bill_id: str, **params: Any) -> dict[str, Any]:
    return next(row for row in client.get(BILLS_URL, params=params).json() if row["id"] == bill_id)


def _occurrence_rows(db_connection: psycopg.Connection, bill_id: str) -> list[tuple[str, str]]:
    rows = db_connection.execute(
        "SELECT due_date, status FROM finance_recurring_bill_payments WHERE bill_id = %s ORDER BY due_date",
        (bill_id,),
    ).fetchall()
    return [(row[0].isoformat(), row[1]) for row in rows]


def _forecast(client: TestClient) -> dict[str, Any]:
    return client.get(SUMMARY_URL, params={"month": "2026-09"}).json()["cash_flow_forecast"]


def test_creating_a_bill_generates_its_pending_occurrence(
    finance_client: TestClient, db_connection: psycopg.Connection, pin_today: Callable[[date], None]
) -> None:
    bill = _put_bill(finance_client)

    # Anchor Jan 5 is long past: the first pending row is the next occurrence, not a stale overdue one.
    assert bill["next_due_date"] == "2026-10-05"
    assert bill["next_status"] == "pending"
    listed = _listed_bill(finance_client, bill["id"])
    assert listed["next_due_date"] == "2026-10-05"
    assert listed["next_status"] == "pending"
    assert _occurrence_rows(db_connection, bill["id"]) == [("2026-10-05", "pending")]


def test_editing_the_schedule_replaces_a_stale_pending_row_but_not_paid_history(
    finance_client: TestClient, db_connection: psycopg.Connection, pin_today: Callable[[date], None]
) -> None:
    bill = _put_bill(finance_client)
    _put_payment(finance_client, bill["id"], "2026-09-05", "paid")

    edited = finance_client.put(
        BILLS_URL,
        json={
            "id": bill["id"],
            "name": "Netflix",
            "amount_cents": 19_900,
            "currency": "MXN",
            "frequency": "monthly",
            "anchor_due_date": "2026-01-12",
        },
    )

    assert edited.status_code == 200
    assert edited.json()["next_due_date"] == "2026-10-12"
    assert _occurrence_rows(db_connection, bill["id"]) == [("2026-09-05", "paid"), ("2026-10-12", "pending")]


def test_editing_an_annual_bill_to_monthly_moves_its_payment_into_the_forecast_window(
    finance_client: TestClient, pin_today: Callable[[date], None]
) -> None:
    body = {
        "name": "Seguro",
        "amount_cents": 90_000,
        "currency": "MXN",
        "frequency": "annual",
        "anchor_due_date": "2026-01-15",
    }
    bill = finance_client.put(BILLS_URL, json=body).json()
    assert bill["next_due_date"] == "2027-01-15"
    assert _forecast(finance_client)["committed_bills_cents"] == 0

    edited = finance_client.put(BILLS_URL, json={**body, "id": bill["id"], "frequency": "monthly"}).json()

    assert edited["next_due_date"] == "2026-10-15"
    assert _forecast(finance_client)["committed_bills_cents"] == 90_000


def test_marking_paid_creates_exactly_one_next_pending_occurrence_and_repeating_it_changes_nothing(
    finance_client: TestClient, db_connection: psycopg.Connection, pin_today: Callable[[date], None]
) -> None:
    bill = _put_bill(finance_client)

    first = _put_payment(finance_client, bill["id"], "2026-10-05", "paid")
    second = _put_payment(finance_client, bill["id"], "2026-10-05", "paid")

    assert first["status"] == "paid"
    assert first["paid_at"] is not None
    assert second["paid_at"] == first["paid_at"]
    assert _occurrence_rows(db_connection, bill["id"]) == [("2026-10-05", "paid"), ("2026-11-05", "pending")]
    assert _listed_bill(finance_client, bill["id"])["next_due_date"] == "2026-11-05"


def test_marking_skipped_behaves_like_paid_for_the_next_occurrence(
    finance_client: TestClient, db_connection: psycopg.Connection, pin_today: Callable[[date], None]
) -> None:
    bill = _put_bill(finance_client)

    first = _put_payment(finance_client, bill["id"], "2026-10-05", "skipped")
    _put_payment(finance_client, bill["id"], "2026-10-05", "skipped")

    assert first["paid_at"] is None
    assert _occurrence_rows(db_connection, bill["id"]) == [("2026-10-05", "skipped"), ("2026-11-05", "pending")]


def test_settling_a_past_occurrence_leaves_the_next_one_visible_as_overdue(
    finance_client: TestClient, pin_today: Callable[[date], None]
) -> None:
    pin_today(date(2026, 7, 1))
    bill = _put_bill(finance_client, anchor_due_date="2026-07-15")
    pin_today(date(2026, 9, 29))

    _put_payment(finance_client, bill["id"], "2026-07-15", "paid")

    # Aug 15 is past but was never paid: it is the bill's pending occurrence, overdue.
    assert _listed_bill(finance_client, bill["id"])["next_due_date"] == "2026-08-15"


def test_marking_a_bill_paid_creates_no_ledger_transaction(
    finance_client: TestClient, pin_today: Callable[[date], None]
) -> None:
    bill = _put_bill(finance_client)

    _put_payment(finance_client, bill["id"], "2026-10-05", "paid")

    assert finance_client.get(TRANSACTIONS_URL).json() == []


def test_a_deactivated_bill_leaves_the_list_and_the_forecast(
    finance_client: TestClient, pin_today: Callable[[date], None]
) -> None:
    bill = _put_bill(finance_client)
    assert _forecast(finance_client)["committed_bills_cents"] == 19_900

    deactivated = finance_client.put(
        BILLS_URL,
        json={
            "id": bill["id"],
            "name": "Netflix",
            "amount_cents": 19_900,
            "currency": "MXN",
            "frequency": "monthly",
            "anchor_due_date": "2026-01-05",
            "is_active": False,
        },
    )

    assert deactivated.status_code == 200
    assert all(row["id"] != bill["id"] for row in finance_client.get(BILLS_URL).json())
    assert _listed_bill(finance_client, bill["id"], include_inactive=True)["is_active"] is False
    assert _forecast(finance_client)["committed_bills_cents"] == 0
    summary = finance_client.get(SUMMARY_URL, params={"month": "2026-09"}).json()
    assert summary["subscriptions"]["bills"] == []


def test_the_payment_route_returns_404_for_an_unknown_bill(finance_client: TestClient) -> None:
    response = finance_client.put(
        PAYMENTS_URL, json={"bill_id": str(uuid.uuid4()), "due_date": "2026-10-05", "status": "paid"}
    )

    assert response.status_code == 404


@pytest.mark.parametrize("bad_date", ["not-a-date", "2026-13-40", ""])
def test_recurring_bill_routes_reject_an_invalid_date_with_422(
    finance_client: TestClient, pin_today: Callable[[date], None], bad_date: str
) -> None:
    bill = _put_bill(finance_client)

    bad_anchor = finance_client.put(
        BILLS_URL,
        json={
            "name": "Luz",
            "amount_cents": 8_000,
            "currency": "MXN",
            "frequency": "monthly",
            "anchor_due_date": bad_date,
        },
    )
    bad_due = finance_client.put(
        PAYMENTS_URL, json={"bill_id": bill["id"], "due_date": bad_date, "status": "paid"}
    )

    assert bad_anchor.status_code == 422
    assert bad_due.status_code == 422


def test_an_active_bill_without_a_pending_row_still_has_a_next_due_date_and_can_be_paid(
    finance_client: TestClient, db_connection: psycopg.Connection, pin_today: Callable[[date], None]
) -> None:
    """A bill written before occurrences were generated (or inserted by hand):
    the list and the forecast derive its next date read-only, and paying that
    date persists it and creates the next one."""
    bill_id = str(
        db_connection.execute(
            "INSERT INTO finance_recurring_bills (name, amount_cents, currency, frequency, anchor_due_date) "
            "VALUES ('Legado', 5000, 'MXN', 'monthly', '2026-01-05') RETURNING id"
        ).fetchone()[0]
    )

    assert _listed_bill(finance_client, bill_id)["next_due_date"] == "2026-10-05"
    assert _forecast(finance_client)["committed_bills_cents"] == 5_000
    assert _occurrence_rows(db_connection, bill_id) == []

    _put_payment(finance_client, bill_id, "2026-10-05", "paid")

    assert _occurrence_rows(db_connection, bill_id) == [("2026-10-05", "paid"), ("2026-11-05", "pending")]
    assert _listed_bill(finance_client, bill_id)["next_due_date"] == "2026-11-05"


# -- Forecast through the API ----------------------------------------------------------


def test_summary_forecast_counts_a_monthly_bill_once_and_an_annual_bill_outside_the_horizon_zero_times(
    finance_client: TestClient, pin_today: Callable[[date], None]
) -> None:
    _put_bill(finance_client, name="Netflix", amount_cents=19_900, frequency="monthly", anchor_due_date="2026-01-05")
    _put_bill(finance_client, name="Seguro", amount_cents=900_000, frequency="annual", anchor_due_date="2026-03-01")

    forecast = _forecast(finance_client)

    assert forecast["committed_bills_cents"] == 19_900
    assert forecast["overdue_bills_cents"] == 0
    assert forecast["overdue_bills_count"] == 0


def test_summary_forecast_reports_overdue_bills_separately_and_includes_them_in_committed(
    finance_client: TestClient, pin_today: Callable[[date], None]
) -> None:
    pin_today(date(2026, 8, 20))
    _put_bill(finance_client, name="Renta", amount_cents=100_000, frequency="monthly", anchor_due_date="2026-01-15")
    pin_today(date(2026, 9, 29))

    forecast = _forecast(finance_client)

    # Sep 15 is overdue (owed once) and Oct 15 falls inside the 30-day window.
    assert forecast["overdue_bills_cents"] == 100_000
    assert forecast["overdue_bills_count"] == 1
    assert forecast["committed_bills_cents"] == 200_000
    # No income history: the projection is unknown (null), not a made-up $0 income.
    assert forecast["income_data_sufficient"] is False
    assert forecast["expected_income_cents"] is None
    assert forecast["projected_net_cents"] is None


def test_summary_forecast_payload_is_integer_cents(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    pin_today: Callable[[date], None],
) -> None:
    """With an income history every figure is integer cents; without one the
    two income-dependent figures are null and the bill figures stay integers."""
    _put_bill(finance_client, amount_cents=33_333, frequency="weekly", anchor_due_date="2026-09-02")
    bill_keys = ("committed_bills_cents", "overdue_bills_cents", "overdue_bills_count")
    income_keys = ("expected_income_cents", "projected_net_cents")

    without_income = _forecast(finance_client)
    assert all(type(without_income[key]) is int for key in bill_keys)
    assert all(without_income[key] is None for key in income_keys)

    _seed_month(finance_client, repository, make_finance_account("Cuenta MXN de prueba", "MXN"), "2026-08", COVERED_MONTH)
    with_income = _forecast(finance_client)

    assert all(type(with_income[key]) is int for key in (*bill_keys, *income_keys))


def test_runtime_scenario_a_weekly_bill_flows_through_the_forecast_and_advances_when_paid(
    finance_client: TestClient, db_connection: psycopg.Connection, pin_today: Callable[[date], None]
) -> None:
    """End to end through the real HTTP stack and SQL, with the clock pinned
    to Tuesday 2026-09-29 (30-day horizon ends 2026-10-29): create a weekly
    bill, read the forecast, pay the pending occurrence, and watch the next
    due date move exactly one week."""
    amount_cents = 15_000
    bill = _put_bill(
        finance_client, name="Gimnasio", amount_cents=amount_cents, frequency="weekly", anchor_due_date="2026-09-02"
    )

    # Wednesdays: Sep 30, Oct 7, 14, 21, 28 -> five occurrences inside the horizon.
    assert bill["next_due_date"] == "2026-09-30"
    assert _forecast(finance_client)["committed_bills_cents"] == 5 * amount_cents

    _put_payment(finance_client, bill["id"], "2026-09-30", "paid")

    assert _listed_bill(finance_client, bill["id"])["next_due_date"] == "2026-10-07"
    assert _occurrence_rows(db_connection, bill["id"]) == [("2026-09-30", "paid"), ("2026-10-07", "pending")]
    # Oct 7, 14, 21, 28 remain.
    assert _forecast(finance_client)["committed_bills_cents"] == 4 * amount_cents


# -- Summary semantics: spending vs saving, coverage rule, truthful empty states -------

# (kind, category slug or None for "no category", amount in MXN cents). Five converted
# transactions, so a trailing month holding these exactly meets the coverage rule (D2).
COVERED_MONTH: list[tuple[str, str | None, int]] = [
    ("income", "sueldo", 1_000_000),
    ("expense", "alimentacion", 200_000),  # necesidad
    ("expense", "entretenimiento", 100_000),  # deseo
    ("expense", "ahorro-inversion", 150_000),  # ahorro_inversion: saved, not spent
    ("expense", None, 50_000),  # uncategorized
]


def _seed_month(
    client: TestClient,
    repository: LocalPostgresRepository,
    account_id: str,
    month: str,
    entries: list[tuple[str, str | None, int]],
) -> None:
    """PUT each entry as an MXN transaction booked mid-month (well away from a month boundary)."""
    for kind, slug, cents in entries:
        body: dict[str, Any] = {
            "client_id": str(uuid.uuid4()),
            "account_id": account_id,
            "kind": kind,
            "amount_cents": cents,
            "currency": "MXN",
            "occurred_at": f"{month}-10T12:00:00+00:00",
        }
        if slug is not None:
            body["category_id"] = _category_id(repository, slug)
        response = client.put(TRANSACTIONS_URL, json=body)
        assert response.status_code == 200, response.text


def _summary(client: TestClient, month: str = "2026-09") -> dict[str, Any]:
    response = client.get(SUMMARY_URL, params={"month": month})
    assert response.status_code == 200, response.text
    return response.json()


def _put_net_worth_cash(client: TestClient, cents: int) -> None:
    response = client.put(
        "/api/finance/net-worth",
        json={
            "snapshot_date": "2026-09-01",
            "items": [{"is_asset": True, "label": "Efectivo", "item_type": "cash", "amount_cents": cents, "currency": "MXN"}],
        },
    )
    assert response.status_code == 200, response.text


def test_runtime_scenario_spending_saving_and_the_uncategorized_bucket_through_the_summary(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    pin_today: Callable[[date], None],
) -> None:
    """End to end through the real HTTP stack and SQL, clock pinned to
    2026-09-29: an income plus one expense in each bucket plus one with no
    category are PUT, then /summary must tell spending from saving, keep the
    uncategorized money in its own bucket, and break the month down by
    category without losing a cent. An untouched month then reports itself as
    insufficient instead of showing $0.00 as if it were data."""
    account = make_finance_account("Cuenta MXN de prueba", "MXN")
    _seed_month(finance_client, repository, account, "2026-09", COVERED_MONTH)

    payload = _summary(finance_client)
    month = payload["monthly_summary"]

    assert month["data_sufficient"] is True
    assert month["income_cents"] == 1_000_000
    assert month["expense_cents"] == 500_000  # raw total: 200k + 100k + 150k saved + 50k uncategorized
    assert month["spending_cents"] == 350_000  # everything except the savings bucket
    assert month["saved_cents"] == 150_000
    assert month["net_cents"] == 650_000  # income - spending: saving is NOT counted as spent
    assert month["savings_rate_pct"] == 15.0
    assert month["converted_transactions"] == 5
    assert month["buckets"] == {
        "necesidad": {"actual_cents": 200_000, "target_cents": 500_000},
        "deseo": {"actual_cents": 100_000, "target_cents": 300_000},
        "ahorro_inversion": {"actual_cents": 150_000, "target_cents": 200_000},
        "sin_categoria": {"actual_cents": 50_000},
    }
    assert sum(bucket["actual_cents"] for bucket in month["buckets"].values()) == month["expense_cents"]

    # Ungated: the money left unspent is reported even though the emergency fund gates the investable figure.
    surplus = payload["investable_surplus"]
    assert (surplus["available_cents"], surplus["shortfall_cents"]) == (650_000, 0)
    assert (surplus["income_cents"], surplus["spending_cents"], surplus["saved_cents"]) == (1_000_000, 350_000, 150_000)
    assert (surplus["surplus_cents"], surplus["reason"]) == (0, "building_emergency_fund")
    assert surplus["data_sufficient"] is False

    breakdown = payload["category_breakdown"]
    assert sum(row["actual_cents"] for row in breakdown) == month["expense_cents"]
    assert {row["category_name"]: row["actual_cents"] for row in breakdown} == {
        "Alimentacion": 200_000,
        "Entretenimiento": 100_000,
        "Ahorro e Inversion": 150_000,
        "Sin categoría": 50_000,
    }
    assert breakdown[-1]["category_id"] is None
    assert breakdown[-1]["bucket"] == "sin_categoria"

    empty = _summary(finance_client, month="2026-07")
    assert empty["monthly_summary"]["data_sufficient"] is False
    assert empty["monthly_summary"]["converted_transactions"] == 0
    assert empty["category_breakdown"] == []
    assert empty["investable_surplus"]["data_sufficient"] is False
    assert empty["history"]["months_used"] == 0


def test_summary_of_a_month_with_only_unconverted_rows_is_not_data_sufficient_but_counts_them(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    db_connection: psycopg.Connection,
    pin_today: Callable[[date], None],
) -> None:
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    db_connection.execute(
        "INSERT INTO finance_transactions (client_id, account_id, category_id, kind, amount_cents, currency, occurred_at) "
        "VALUES (%s, %s, %s, 'expense', 5000, 'USD', '2026-09-12T12:00:00+00:00')",
        (str(uuid.uuid4()), usd, _category_id(repository, "alimentacion")),
    )

    month = _summary(finance_client)["monthly_summary"]

    assert month["data_sufficient"] is False
    assert month["unconverted_transactions"] == 1


def test_summary_category_breakdown_carries_budgets_and_adds_up_to_the_expense(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    pin_today: Callable[[date], None],
) -> None:
    account = make_finance_account("Cuenta MXN de prueba", "MXN")
    _seed_month(finance_client, repository, account, "2026-09", COVERED_MONTH)
    for slug, limit in (("alimentacion", 300_000), ("vivienda", 400_000)):  # vivienda: budgeted, nothing spent
        response = finance_client.put(
            "/api/finance/budgets",
            json={
                "category_id": _category_id(repository, slug),
                "period_month": "2026-09-01",
                "limit_cents": limit,
                "currency": "MXN",
            },
        )
        assert response.status_code == 200

    payload = _summary(finance_client)
    rows = {row["category_name"]: row for row in payload["category_breakdown"]}

    assert sum(row["actual_cents"] for row in rows.values()) == payload["monthly_summary"]["expense_cents"] == 500_000
    assert (rows["Alimentacion"]["budget_cents"], rows["Alimentacion"]["actual_cents"]) == (300_000, 200_000)
    assert rows["Alimentacion"]["bucket"] == "necesidad"
    assert (rows["Vivienda"]["budget_cents"], rows["Vivienda"]["actual_cents"]) == (400_000, 0)
    # Unbudgeted spend is listed too: nothing vanishes for lack of a budget.
    assert rows["Entretenimiento"]["budget_cents"] is None
    assert rows["Sin categoría"]["actual_cents"] == 50_000
    # The dedicated budgets endpoint is untouched: still only the budgeted categories.
    budgets = finance_client.get("/api/finance/budgets", params={"month": "2026-09"}).json()
    assert {budget["category_name"] for budget in budgets} == {"Alimentacion", "Vivienda"}


def test_summary_trailing_month_needs_five_transactions_to_count(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    pin_today: Callable[[date], None],
) -> None:
    """Decision D2 through the API: a net-worth snapshot is there, and the only
    trailing month has four transactions, then five."""
    account = make_finance_account("Cuenta MXN de prueba", "MXN")
    _put_net_worth_cash(finance_client, 700_000)
    _seed_month(finance_client, repository, account, "2026-08", COVERED_MONTH[:4])

    four = _summary(finance_client)

    assert four["history"]["months_used"] == 0
    assert four["history"]["months_considered"] == 3
    assert four["history"]["min_transactions_per_month"] == 5
    for section in ("emergency_fund", "fire_number", "investable_surplus"):
        assert four[section]["data_sufficient"] is False, section

    _seed_month(finance_client, repository, account, "2026-08", COVERED_MONTH[4:])
    five = _summary(finance_client)

    assert five["history"]["months_used"] == 1
    for section in ("emergency_fund", "fire_number", "investable_surplus"):
        assert five[section]["data_sufficient"] is True, section


def test_summary_skips_a_month_of_only_unconverted_rows_and_reports_how_many_were_left_out(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    db_connection: psycopg.Connection,
    pin_today: Callable[[date], None],
) -> None:
    account = make_finance_account("Cuenta MXN de prueba", "MXN")
    usd = make_finance_account("Cuenta USD de prueba", "USD")
    food = _category_id(repository, "alimentacion")
    _seed_month(finance_client, repository, account, "2026-08", COVERED_MONTH)
    # June: six foreign rows with no base amount (written before base amounts existed).
    for _ in range(6):
        db_connection.execute(
            "INSERT INTO finance_transactions (client_id, account_id, category_id, kind, amount_cents, currency, occurred_at) "
            "VALUES (%s, %s, %s, 'expense', 5000, 'USD', '2026-06-12T12:00:00+00:00')",
            (str(uuid.uuid4()), usd, food),
        )

    history = _summary(finance_client)["history"]

    # June is skipped (nothing converted) rather than averaged in as a zero month; July is empty.
    assert history["months_used"] == 1
    assert history["months_considered"] == 3
    assert history["unconverted_transactions"] == 6


def test_summary_uses_spending_and_essential_baselines_from_the_trailing_months(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    pin_today: Callable[[date], None],
) -> None:
    """The wiring of the baselines: FIRE is 25 x 12 x the average monthly
    SPENDING (savings left out), the emergency fund is measured against the
    average necesidad expense, and once covered the surplus is what the
    month left unspent."""
    account = make_finance_account("Cuenta MXN de prueba", "MXN")
    _seed_month(finance_client, repository, account, "2026-08", COVERED_MONTH)
    _put_net_worth_cash(finance_client, 700_000)
    _seed_month(
        finance_client,
        repository,
        account,
        "2026-09",
        [("income", "sueldo", 500_000), ("expense", "alimentacion", 200_000)],
    )

    payload = _summary(finance_client)

    # August: spending 350k (200k necesidad + 100k deseo + 50k uncategorized); the 150k saved is excluded.
    assert payload["fire_number"]["target_cents"] == 350_000 * 12 * 25
    assert payload["fire_number"]["progress_pct"] == pytest.approx(700_000 / (350_000 * 12 * 25) * 100)
    assert payload["emergency_fund"]["months_covered"] == 3.5  # 700k against 200k of essentials
    assert payload["emergency_fund"]["status"] == "within"
    surplus = payload["investable_surplus"]
    assert surplus["data_sufficient"] is True
    assert surplus["reason"] == "emergency_fund_covered"
    assert (surplus["available_cents"], surplus["surplus_cents"]) == (300_000, 300_000)


def test_summary_forecast_shows_committed_and_overdue_bills_without_any_income_history(
    finance_client: TestClient, pin_today: Callable[[date], None]
) -> None:
    pin_today(date(2026, 8, 20))
    _put_bill(finance_client, name="Renta", amount_cents=100_000, frequency="monthly", anchor_due_date="2026-01-15")
    pin_today(date(2026, 9, 29))

    forecast = _forecast(finance_client)

    # The bills are facts from the schedule: shown, not hidden because income history is missing.
    assert forecast["data_sufficient"] is True
    assert forecast["income_data_sufficient"] is False
    assert forecast["overdue_bills_count"] == 1
    assert forecast["overdue_bills_cents"] == 100_000
    assert forecast["committed_bills_cents"] == 200_000
    assert forecast["expected_income_cents"] is None
    assert forecast["projected_net_cents"] is None


def test_summary_forecast_projects_income_once_a_covered_month_exists(
    finance_client: TestClient,
    repository: LocalPostgresRepository,
    make_finance_account: MakeAccount,
    pin_today: Callable[[date], None],
) -> None:
    _put_bill(finance_client, name="Renta", amount_cents=100_000, frequency="monthly", anchor_due_date="2026-01-15")
    _seed_month(finance_client, repository, make_finance_account("Cuenta MXN de prueba", "MXN"), "2026-08", COVERED_MONTH)

    forecast = _forecast(finance_client)

    assert forecast["income_data_sufficient"] is True
    assert forecast["expected_income_cents"] == 1_000_000
    assert forecast["projected_net_cents"] == 1_000_000 - forecast["committed_bills_cents"]


def test_summary_forecast_is_not_sufficient_with_no_bills_and_no_income_history(
    finance_client: TestClient, pin_today: Callable[[date], None]
) -> None:
    forecast = _forecast(finance_client)

    assert forecast["data_sufficient"] is False
    assert forecast["income_data_sufficient"] is False


def test_summary_forecast_excludes_and_counts_a_legacy_non_base_bill(
    finance_client: TestClient, db_connection: psycopg.Connection, pin_today: Callable[[date], None]
) -> None:
    """A bill written in another currency before bills became base-only has
    no base amount: adding its face value would treat dollars as pesos. It
    stays out of the forecast and out of the subscription total, and is
    counted (`subscriptions.unconverted_bills`) instead of silently vanishing."""
    _put_bill(finance_client, name="Netflix", amount_cents=19_900, frequency="monthly", anchor_due_date="2026-01-05")
    db_connection.execute(
        "INSERT INTO finance_recurring_bills (name, amount_cents, currency, frequency, anchor_due_date) "
        "VALUES ('iCloud', 999, 'USD', 'monthly', '2026-01-05')"
    )

    payload = _summary(finance_client)

    assert payload["cash_flow_forecast"]["committed_bills_cents"] == 19_900
    assert payload["subscriptions"]["unconverted_bills"] == 1
    assert [bill["name"] for bill in payload["subscriptions"]["bills"]] == ["Netflix"]


# -- repository is None -> 503 (matching PUT /api/risk-profile's pattern) ----


def test_categories_endpoint_returns_503_when_repository_unavailable() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)
    try:
        response = client.get("/api/finance/categories")
        assert response.status_code == 503
        assert "detail" in response.json()
    finally:
        app.dependency_overrides.clear()


def test_put_transaction_returns_503_when_repository_unavailable() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)
    try:
        response = client.put(
            "/api/finance/transactions",
            json={
                "client_id": str(uuid.uuid4()),
                "account_id": str(uuid.uuid4()),
                "kind": "expense",
                "amount_cents": 1000,
                "currency": "MXN",
                "occurred_at": "2026-09-10T12:00:00+00:00",
            },
        )
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_summary_endpoint_returns_503_when_repository_unavailable() -> None:
    app.dependency_overrides[get_repository] = lambda: None
    client = TestClient(app)
    try:
        response = client.get("/api/finance/summary")
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()
