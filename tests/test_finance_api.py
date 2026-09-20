from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_repository
from collector.local_repository import LocalPostgresRepository


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


def _account_id(repository: LocalPostgresRepository) -> str:
    return repository.get_finance_accounts()[0]["id"]


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
    finance_client: TestClient, repository: LocalPostgresRepository
) -> None:
    client_id = str(uuid.uuid4())

    put_response = finance_client.put(
        "/api/finance/transactions",
        json={
            "client_id": client_id,
            "account_id": _account_id(repository),
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
    finance_client: TestClient, repository: LocalPostgresRepository
) -> None:
    client_id = str(uuid.uuid4())
    account_id = _account_id(repository)
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


def test_get_summary_degrades_gracefully_with_no_data(finance_client: TestClient) -> None:
    response = finance_client.get("/api/finance/summary")

    assert response.status_code == 200
    payload = response.json()

    assert payload["monthly_summary"]["data_sufficient"] is True
    assert payload["monthly_summary"]["income_cents"] == 0
    assert payload["monthly_summary"]["expense_cents"] == 0

    assert payload["net_worth"]["data_sufficient"] is False
    assert payload["net_worth"]["net_worth_cents"] is None

    assert payload["emergency_fund"]["data_sufficient"] is False
    assert payload["emergency_fund"]["months_covered"] is None

    assert payload["fire_number"]["data_sufficient"] is False

    assert payload["investable_surplus"] == {
        "data_sufficient": False,
        "surplus_cents": 0,
        "reason": "building_emergency_fund",
    }

    assert payload["subscriptions"] == {
        "data_sufficient": True,
        "annual_total_cents": 0,
        "monthly_average_cents": 0,
        "bills": [],
    }

    assert payload["cash_flow_forecast"]["data_sufficient"] is False


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
