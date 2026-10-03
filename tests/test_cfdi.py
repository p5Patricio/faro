from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_repository
from brain.finance.cfdi import CfdiError, deduction_hints, parse_cfdi
from collector.local_repository import LocalPostgresRepository

FIXTURE = (Path(__file__).parent / "fixtures" / "cfdi40_honorarios.xml").read_bytes()


def test_parses_a_stamped_cfdi_40_into_cents_and_hints() -> None:
    document = parse_cfdi(FIXTURE)

    assert document["uuid"] == "0f1e2d3c-4b5a-4978-8695-a4b3c2d1e0f9"
    assert (document["total_cents"], document["currency"], document["uso_cfdi"]) == (100_000, "MXN", "D01")
    assert document["concepts"] == [
        {"clave_prod_serv": "85121600", "descripcion": "Consulta médica", "importe_cents": 100_000}
    ]
    hints = deduction_hints(document)
    assert hints["personal_deduction_use"] and not hints["paid_in_cash"]
    assert hints["use_label_status"] == "verificado"


@pytest.mark.parametrize(
    "xml",
    [
        FIXTURE.replace(b"http://www.sat.gob.mx/cfd/4", b"http://www.sat.gob.mx/cfd/3"),
        FIXTURE.replace(b'UUID="0F1E2D3C-4B5A-4978-8695-A4B3C2D1E0F9"', b""),
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>',
        b"not xml",
    ],
)
def test_rejects_documents_it_cannot_trust(xml: bytes) -> None:
    with pytest.raises(CfdiError):
        parse_cfdi(xml)


@pytest.fixture()
def client(repository: LocalPostgresRepository) -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_runtime_scenario_import_twice_and_review_the_year(client: TestClient) -> None:
    cash = FIXTURE.replace(b'FormaPago="03"', b'FormaPago="01"')
    first = client.put("/api/finance/cfdi", json={"xml": cash.decode(), "filename": "consulta.xml"})
    again = client.put("/api/finance/cfdi", json={"xml": cash.decode()})

    assert first.json()["created"] is True and again.json()["created"] is False
    year = client.get("/api/finance/cfdi", params={"year": 2026}).json()
    assert len(year["documents"]) == 1
    assert year["personal_deductions_by_use"] == [
        {"uso_cfdi": "D01", "currency": "MXN", "count": 1, "total_cents": 100_000,
         "use_label": "Honorarios médicos, dentales y gastos hospitalarios", "use_label_status": "verificado"}
    ]
    assert year["paid_in_cash_count"] == 1
    assert client.put("/api/finance/cfdi", json={"xml": "<x/>"}).status_code == 422
