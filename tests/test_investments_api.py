from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_repository
from collector.investment_repository import InvestmentRepository
from collector.local_repository import LocalPostgresRepository


@pytest.fixture()
def client(repository: LocalPostgresRepository) -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _operation(account_id: str, **fields) -> dict:
    return {"client_id": str(uuid.uuid4()), "account_id": account_id, "symbol": "voo",
            "instrument_type": "etf", "currency": "USD", "fx_rate_to_mxn": "17.25",
            "fx_rate_date": "2026-01-05", "fx_source": "banxico_fix", **fields}


def test_runtime_scenario_buy_sell_dividend_and_yearly_worksheet(client: TestClient) -> None:
    account = client.put("/api/investments/accounts", json={"name": "GBM SIC", "broker": "GBM"}).json()
    buy = _operation(account["id"], trade_date="2026-01-05", kind="buy", quantity="4", amount_cents=200_000)

    assert client.put("/api/investments/transactions", json=buy).status_code == 200
    # Replaying the same client_id edits instead of duplicating.
    assert client.put("/api/investments/transactions", json=buy).json()["fx_rate_to_mxn"] == "17.25000000"
    sell = _operation(account["id"], trade_date="2026-03-02", kind="sell", quantity="1", amount_cents=60_000,
                      fx_rate_to_mxn="18", fx_rate_date="2026-03-01")
    assert client.put("/api/investments/transactions", json=sell).status_code == 200
    dividend = _operation(account["id"], trade_date="2026-03-20", kind="dividend", amount_cents=1_000,
                          tax_withheld_cents=100, fx_rate_to_mxn="18", fx_rate_date="2026-03-19")
    assert client.put("/api/investments/transactions", json=dividend).status_code == 200

    positions = client.get("/api/investments/positions").json()["positions"]
    assert positions == [{"account_id": account["id"], "account_name": "GBM SIC", "symbol": "VOO",
                          "instrument_type": "etf", "quantity": "3", "cost_basis_mxn_cents": 2_587_500,
                          "average_cost_mxn_cents": "862500.0000"}]

    worksheet = client.get("/api/investments/worksheet", params={"year": 2026}).json()
    assert worksheet["sales"][0]["gain_mxn_cents"] == 1_080_000 - 862_500
    csv_text = client.get("/api/investments/worksheet", params={"year": 2026, "format": "csv"}).text
    assert "venta,2026-03-02,GBM SIC,GBM,VOO,etf,venta,1,USD,18.00000000,2026-03-01,10800.00,8625.00,2175.00" in csv_text
    assert "resumen,,GBM SIC,GBM,,,dividend,,MXN,,,180.00,,,18.00" in csv_text


def test_overselling_and_undated_foreign_rates_are_rejected(client: TestClient) -> None:
    account = client.put("/api/investments/accounts", json={"name": "Bitso"}).json()
    sell = _operation(account["id"], trade_date="2026-01-05", kind="sell", quantity="1", amount_cents=100)
    assert client.put("/api/investments/transactions", json=sell).status_code == 422

    buy = _operation(account["id"], trade_date="2026-01-05", kind="buy", quantity="1", amount_cents=100)
    del buy["fx_rate_date"]
    assert client.put("/api/investments/transactions", json=buy).status_code == 422


def test_unapplied_migration_answers_503_in_clear_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(InvestmentRepository, "tables_exist", lambda self: False)

    response = client.get("/api/investments/positions")

    assert response.status_code == 503
    assert "0016" in response.json()["detail"]


def test_deleting_a_buy_that_a_later_sale_needs_is_rejected(client: TestClient) -> None:
    account = client.put("/api/investments/accounts", json={"name": "Kuspit"}).json()
    buy = _operation(account["id"], trade_date="2026-01-05", kind="buy", quantity="1", amount_cents=100)
    client.put("/api/investments/transactions", json=buy)
    client.put("/api/investments/transactions",
               json=_operation(account["id"], trade_date="2026-02-05", kind="sell", quantity="1", amount_cents=150))

    response = client.put("/api/investments/transactions", json={**buy, "deleted_at": "2026-03-01T00:00:00Z"})

    assert response.status_code == 422
