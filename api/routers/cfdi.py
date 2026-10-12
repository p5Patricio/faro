"""CFDI 4.0 import (mounted at ``/api/finance/cfdi`` by ``api/main.py``).

``PUT`` takes one invoice's XML as text (the SAT portal's download, one file
at a time) and stores it once per UUID. ``GET`` lists a year's invoices with
deduction hints and a summary by ``UsoCFDI``. No demo data: 503 in clear text
while the database or migration 0017 is missing. Informational only: whether
an expense is deductible is the accountant's call.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.main import get_repository
from brain.finance.cfdi import MAX_XML_BYTES, CfdiError, deduction_hints, parse_cfdi
from collector.cfdi_repository import CfdiRepository
from collector.local_repository import LocalPostgresRepository

router = APIRouter()

DISCLAIMER = (
    "Informativo: Faro no decide qué es deducible. Revisa con tu contador el uso del CFDI, el medio de pago "
    "y los topes del año (art. 151 LISR)."
)


class CfdiUploadPayload(BaseModel):
    xml: str = Field(min_length=1, max_length=MAX_XML_BYTES)
    filename: str | None = Field(default=None, max_length=255)


def get_cfdi_repository(
    repository: LocalPostgresRepository | None = Depends(get_repository),
) -> CfdiRepository:
    unavailable = HTTPException(status_code=503, detail="Base de datos no disponible para facturas")
    if repository is None:
        raise unavailable
    cfdi = CfdiRepository(pool=repository.pool, connection=repository.connection)
    try:
        ready = cfdi.table_exists()
    except RuntimeError:
        raise unavailable from None
    if not ready:
        raise HTTPException(status_code=503, detail="Las facturas no están disponibles: falta aplicar la migración 0017.")
    return cfdi


@router.put("")
def put_cfdi(payload: CfdiUploadPayload, repository: CfdiRepository = Depends(get_cfdi_repository)):
    try:
        document = parse_cfdi(payload.xml.encode("utf-8"))
    except CfdiError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    document["source_filename"] = payload.filename
    try:
        created = repository.insert_document(document)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar la factura") from None
    return {"uuid": document["uuid"], "created": created, **deduction_hints(document)}


@router.get("")
def get_cfdis(year: int = Query(ge=2000, le=2100), repository: CfdiRepository = Depends(get_cfdi_repository)):
    try:
        documents = [{**row, **deduction_hints(row)} for row in repository.get_documents(year)]
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener las facturas") from None

    summary: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"count": 0, "total_cents": 0})
    for document in documents:
        if document["personal_deduction_use"]:
            bucket = summary[(document["uso_cfdi"], document["currency"])]
            bucket.update(use_label=document["use_label"], use_label_status=document["use_label_status"])
            bucket["count"] += 1
            bucket["total_cents"] += document["total_cents"]
    return {
        "year": year,
        "documents": documents,
        "personal_deductions_by_use": [
            {"uso_cfdi": use, "currency": currency, **values} for (use, currency), values in sorted(summary.items())
        ],
        "paid_in_cash_count": sum(1 for d in documents if d["personal_deduction_use"] and d["paid_in_cash"]),
        "disclaimer": DISCLAIMER,
    }
