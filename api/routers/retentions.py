"""CFDI de Retenciones 2.0 import (mounted at ``/api/investments/retentions`` by ``api/main.py``).

``PUT`` takes one constancia's XML as text (the broker's annual download, one
file at a time) and stores it once per stamp UUID. ``GET`` lists a year's
constancias and reconciles their totals against the investment ledger. No demo
data: 503 in clear text while the database or migration 0018 is missing; if
migration 0016 is missing the ledger side is simply empty. Informational only:
a difference is a question for the broker or the accountant, never a verdict.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.main import get_repository
from brain.investments.ledger import LedgerError, compute_ledger, yearly_worksheet
from brain.investments.retenciones import GENERIC_RFC, MAX_XML_BYTES, RetencionesError, parse_retenciones, reconcile_year
from collector.investment_repository import InvestmentRepository
from collector.local_repository import LocalPostgresRepository
from collector.retention_repository import SUMMARY_COLUMNS, RetentionRepository

router = APIRouter()

DISCLAIMER = (
    "Informativo: Faro solo compara lo que tu intermediario reportó al SAT con tu libro de inversiones. "
    "No calcula impuestos ni dice qué declarar; revisa cualquier diferencia con tu intermediario y tu contador."
)


class RetentionUploadPayload(BaseModel):
    xml: str = Field(min_length=1, max_length=MAX_XML_BYTES)


def get_retention_repository(
    repository: LocalPostgresRepository | None = Depends(get_repository),
) -> RetentionRepository:
    unavailable = HTTPException(status_code=503, detail="Base de datos no disponible para constancias de retenciones")
    if repository is None:
        raise unavailable
    retentions = RetentionRepository(pool=repository.pool, connection=repository.connection)
    try:
        ready = retentions.table_exists()
    except RuntimeError:
        raise unavailable from None
    if not ready:
        raise HTTPException(
            status_code=503, detail="Las constancias de retenciones no están disponibles: falta aplicar la migración 0018."
        )
    return retentions


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    return {column: row[column] for column in SUMMARY_COLUMNS}


def _warnings(documents: list[dict[str, Any]]) -> list[str]:
    return [
        f"La constancia de {d['emitter_rfc']} ({d['concept']}, {d['month_start']}-{d['month_end']}/{d['year']}) "
        f"se emitió al RFC genérico {GENERIC_RFC}: el SAT no la vincula con tu RFC. "
        "Pide a tu intermediario que la reexpida con tu RFC."
        for d in documents
        if d["receiver_is_generic"]
    ]


def _ledger_worksheet(retentions: RetentionRepository, year: int) -> dict[str, Any]:
    investments = InvestmentRepository(pool=retentions.pool, connection=retentions.connection)
    try:
        if not investments.tables_exist():
            return {"summary": []}
        transactions = investments.get_transactions()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo leer el libro de inversiones") from None
    try:
        return yearly_worksheet(compute_ledger(transactions), year)
    except LedgerError as error:
        # Only reachable if rows were edited outside the API.
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.put("")
def put_retention(payload: RetentionUploadPayload, repository: RetentionRepository = Depends(get_retention_repository)):
    try:
        document = parse_retenciones(payload.xml.encode("utf-8"))
    except RetencionesError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    try:
        created = repository.insert_document(document, payload.xml)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar la constancia") from None
    return {**_summary(document), "created": created, "warnings": _warnings([document])}


@router.get("")
def get_retentions(year: int = Query(ge=2000, le=2100), repository: RetentionRepository = Depends(get_retention_repository)):
    try:
        rows = repository.get_documents(year)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener las constancias") from None
    worksheet = _ledger_worksheet(repository, year)
    return {
        "year": year,
        "documents": [{**_summary(row), "imported_at": row["imported_at"]} for row in rows],
        "reconciliation": reconcile_year([row["details"] for row in rows], worksheet),
        "warnings": _warnings(rows),
        "disclaimer": DISCLAIMER,
    }
