from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_repository
from api.routers.retentions import _warnings
from brain.investments.retenciones import RetencionesError, parse_retenciones, reconcile_year
from collector.local_repository import LocalPostgresRepository

FIXTURES = Path(__file__).parent / "fixtures"
INTEREST = (FIXTURES / "retenciones20_intereses.xml").read_bytes()
DIVIDENDS = (FIXTURES / "retenciones20_dividendos.xml").read_bytes()
SALE = (FIXTURES / "retenciones20_enajenacion.xml").read_bytes()


def test_parses_the_interest_complement_into_cents() -> None:
    document = parse_retenciones(INTEREST)

    assert (document["uuid"], document["concept"], document["year"]) == (
        "1a2b3c4d-0000-4000-8000-000000000001", "intereses", 2025)
    assert (document["operation_cents"], document["withheld_cents"]) == (125_050, 1_234)
    assert document["withholdings"] == [
        {"base_cents": 125_050, "tax": "001", "amount_cents": 1_234, "payment_type": "Pago definitivo"}]
    assert document["complement"] == {"nominal_cents": 125_050, "real_cents": 100_025, "loss_cents": 0}
    assert document["receiver_nationality"] == "Nacional" and not document["receiver_is_generic"]


def test_parses_dividends_and_sale_gain_and_loss() -> None:
    dividends = parse_retenciones(DIVIDENDS)["complement"]
    sale = parse_retenciones(SALE)["complement"]

    assert (dividends["accumulable_mx_cents"], dividends["accumulable_foreign_cents"]) == (50_000, 12_075)
    assert (dividends["isr_creditable_foreign_cents"], dividends["dividend_type"]) == (150, "06")
    assert (sale["gain_cents"], sale["loss_cents"], sale["contract"]) == (80_000, 15_025, "CTR-TEST-1")


def test_flags_a_constancia_issued_to_the_generic_rfc() -> None:
    document = parse_retenciones(INTEREST.replace(b"BBB010101BBB", b"XAXX010101000"))

    assert document["receiver_is_generic"] is True


@pytest.mark.parametrize(
    "xml",
    [
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>',
        INTEREST.replace(b'Version="2.0"', b'Version="1.0"'),
        INTEREST.replace(b'UUID="1A2B3C4D-0000-4000-8000-000000000001"', b""),
        INTEREST + b" " * 2_000_000,
    ],
    ids=["doctype", "version", "no-uuid", "oversize"],
)
def test_rejects_documents_it_cannot_trust(xml: bytes) -> None:
    with pytest.raises(RetencionesError):
        parse_retenciones(xml)


def test_reconcile_year_reports_each_status() -> None:
    documents = [parse_retenciones(xml) for xml in (INTEREST, DIVIDENDS, SALE)]
    summary = [
        {"account_id": "a", "concept": "interest", "amount_mxn_cents": 125_100, "tax_withheld_mxn_cents": 1_234},
        {"account_id": "a", "concept": "dividend", "amount_mxn_cents": 50_000, "tax_withheld_mxn_cents": 0},
    ]
    rows = {row["concept"]: row for row in reconcile_year(documents, {"summary": summary})}

    assert rows["interest"]["status"] == "coincide" and rows["interest"]["constancia_real_cents"] == 100_025
    assert rows["interest"]["constancia_loss_cents"] == 0
    assert rows["interest_withheld"]["status"] == "coincide"
    # Compared on the dividend paid (MontoTotOperacion), not the grossed-up accumulable amount.
    assert (rows["dividends"]["status"], rows["dividends"]["difference_cents"]) == ("difiere", 12_075)
    assert rows["dividends"]["constancia_accumulable_cents"] == 62_075
    assert (rows["sale"]["status"], rows["sale"]["constancia_cents"]) == ("sin_libro", 64_975)
    assert [r["status"] for r in reconcile_year([], {"summary": summary})] == ["sin_constancia"] * 3


def test_generic_rfc_warning_is_grouped_per_issuer_and_year() -> None:
    generic = b"XAXX010101000"
    interest = parse_retenciones(INTEREST.replace(b"BBB010101BBB", generic))
    dividends = parse_retenciones(DIVIDENDS.replace(b"BBB010101BBB", generic))
    other_year = {**interest, "year": 2024}

    grouped = _warnings([interest, dividends])
    assert len(grouped) == 1 and "intereses" in grouped[0] and "dividendos" in grouped[0]
    assert len(_warnings([interest, other_year])) == 2
    assert _warnings([parse_retenciones(INTEREST)]) == []


@pytest.fixture()
def client(repository: LocalPostgresRepository) -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_runtime_scenario_import_twice_and_reconcile_the_year(client: TestClient) -> None:
    url = "/api/investments/retentions"
    first = client.put(url, json={"xml": INTEREST.decode()})
    again = client.put(url, json={"xml": INTEREST.decode()})
    assert first.json()["created"] is True and again.json()["created"] is False
    generic = DIVIDENDS.replace(b"BBB010101BBB", b"XAXX010101000").decode()
    assert len(client.put(url, json={"xml": generic}).json()["warnings"]) == 1
    assert client.put(url, json={"xml": "<x/>"}).status_code == 422

    account = client.put("/api/investments/accounts", json={"name": "GBM Test", "broker": "GBM"}).json()
    interest = {"client_id": "5f0c0c1e-0000-4000-8000-000000000001", "account_id": account["id"],
                "trade_date": "2025-06-30", "kind": "interest", "symbol": "GBM", "currency": "MXN",
                "amount_cents": 125_050, "tax_withheld_cents": 1_234}
    assert client.put("/api/investments/transactions", json=interest).status_code == 200

    year = client.get(url, params={"year": 2025}).json()
    assert len(year["documents"]) == 2 and len(year["warnings"]) == 1
    rows = {row["concept"]: row for row in year["reconciliation"]}
    assert (rows["interest"]["status"], rows["interest"]["difference_cents"]) == ("coincide", 0)
    assert rows["dividends"]["status"] == "sin_libro"
    assert client.get(url, params={"year": 2024}).json()["documents"] == []
