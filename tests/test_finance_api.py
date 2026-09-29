from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.main import app, get_repository
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
        "unconverted_bills": 0,
    }
    assert payload["monthly_summary"]["unconverted_transactions"] == 0

    assert payload["cash_flow_forecast"]["data_sufficient"] is False


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
