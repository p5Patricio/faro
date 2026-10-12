"""Investment ledger API (mounted at ``/api/investments`` by ``api/main.py``).

Like the personal-finance router there is no demo data: an unreachable
database answers 503, and so does a database that has not applied
``db/migrations/0016_investment_ledger.sql`` yet, in clear text. Positions and
realized gains are derived on every read by ``brain/investments/ledger.py``.

Every figure is informational, for reconciling against broker statements;
nothing here computes a tax. Quantities, prices and FX rates travel as strings
in responses so a ``Decimal`` never degrades to a JSON float.

Imports ``get_repository`` from ``api.main`` (circular-import ordering: always
enter through ``api.main``).
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.main import get_repository
from brain.finance.currency import BASE_CURRENCY, BIGINT_MAX, normalize_currency, resolve_fx_and_base
from brain.investments.ledger import LedgerError, compute_ledger, yearly_worksheet
from collector.investment_repository import InvestmentRepository
from collector.local_repository import LocalPostgresRepository

router = APIRouter()

DISCLAIMER = (
    "Informativo: no es un cálculo de impuestos ni asesoría fiscal. Costos sin actualizar por INPC. "
    "Concilia cada cifra contra las constancias de tus intermediarios y revísalas con tu contador."
)

_MISSING_MIGRATION = "El libro de inversiones no está disponible: falta aplicar la migración 0016."


class InvestmentAccountPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    broker: str | None = Field(default=None, max_length=80)
    currency: str = Field(default=BASE_CURRENCY, min_length=3, max_length=3)
    is_active: bool = True


class InvestmentTransactionPayload(BaseModel):
    client_id: uuid.UUID
    account_id: uuid.UUID
    trade_date: date = Field(ge=date(1970, 1, 1), le=date(2100, 12, 31))
    kind: Literal["buy", "sell", "split", "dividend", "fibra_distribution", "capital_return", "interest", "fee"]
    symbol: str = Field(min_length=1, max_length=32)
    instrument_type: Literal["accion_mx", "accion_sic", "etf", "fibra", "fondo", "deuda", "cripto", "otro"] = "otro"
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=28, decimal_places=10)
    price: Decimal | None = Field(default=None, ge=0, max_digits=28, decimal_places=10)
    amount_cents: int = Field(default=0, ge=0, le=BIGINT_MAX)
    fee_cents: int = Field(default=0, ge=0, le=BIGINT_MAX)
    tax_withheld_cents: int = Field(default=0, ge=0, le=BIGINT_MAX)
    currency: str = Field(min_length=3, max_length=3)
    # Send rates as strings ("17.2345") to keep every digit.
    fx_rate_to_mxn: Decimal | None = None
    fx_rate_date: date | None = None
    fx_source: Literal["manual", "banxico_fix", "broker"] | None = None
    source: str = Field(default="manual", max_length=40)
    source_ref: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
    deleted_at: datetime | None = None


def get_investment_repository(
    repository: LocalPostgresRepository | None = Depends(get_repository),
) -> InvestmentRepository:
    if repository is None:
        raise HTTPException(status_code=503, detail="Base de datos no disponible para inversiones")
    investments = InvestmentRepository(pool=repository.pool, connection=repository.connection)
    try:
        ready = investments.tables_exist()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Base de datos no disponible para inversiones") from None
    if not ready:
        raise HTTPException(status_code=503, detail=_MISSING_MIGRATION)
    return investments


def _json(row: dict[str, Any]) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()}


@router.get("/accounts")
def get_accounts(repository: InvestmentRepository = Depends(get_investment_repository)):
    try:
        return repository.get_accounts()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener las cuentas de inversión") from None


@router.put("/accounts")
def put_account(
    payload: InvestmentAccountPayload, repository: InvestmentRepository = Depends(get_investment_repository)
):
    row = payload.model_dump()
    row["name"] = row["name"].strip()
    row["currency"] = normalize_currency(row["currency"])
    try:
        return repository.upsert_account(row)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar la cuenta de inversión") from None


@router.get("/transactions")
def get_transactions(
    account_id: uuid.UUID | None = Query(default=None),
    repository: InvestmentRepository = Depends(get_investment_repository),
):
    try:
        rows = repository.get_transactions(account_id=str(account_id) if account_id else None)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener las operaciones") from None
    return [_json(row) for row in reversed(rows)]


def _validated_row(payload: InvestmentTransactionPayload) -> dict[str, Any]:
    row = payload.model_dump()
    row["client_id"] = str(row["client_id"])
    row["account_id"] = str(row["account_id"])
    row["symbol"] = row["symbol"].strip().upper()
    row["currency"] = normalize_currency(row["currency"])
    if row["kind"] in ("buy", "sell", "split") and row["quantity"] is None:
        raise HTTPException(status_code=422, detail="Las compras, ventas y splits necesitan una cantidad.")
    if row["currency"] == BASE_CURRENCY:
        row["fx_rate_to_mxn"] = Decimal(1)
        return row
    if row["fx_rate_to_mxn"] is None or row["fx_rate_date"] is None:
        raise HTTPException(
            status_code=422,
            detail=f"Una operación en {row['currency']} necesita el tipo de cambio a {BASE_CURRENCY} y su fecha.",
        )
    try:
        row["fx_rate_to_mxn"], _ = resolve_fx_and_base(0, row["currency"], row["fx_rate_to_mxn"])
    except (ValueError, ArithmeticError):
        raise HTTPException(status_code=422, detail="El tipo de cambio debe ser un número mayor que cero.") from None
    return row


@router.put("/transactions")
def put_transaction(
    payload: InvestmentTransactionPayload, repository: InvestmentRepository = Depends(get_investment_repository)
):
    row = _validated_row(payload)
    try:
        if repository.get_account(row["account_id"]) is None:
            raise HTTPException(status_code=422, detail="La cuenta de inversión indicada no existe.")
        # Replay the whole ledger with this operation in place (or removed, for
        # a soft delete) before saving, so it can never be left in a state it
        # cannot compute, e.g. a sale of more units than were bought -- also in
        # the account an edited operation is moved away from.
        others = [t for t in repository.get_transactions() if t["client_id"] != row["client_id"]]
        candidate = others if row["deleted_at"] else [*others, row]
        try:
            compute_ledger(candidate)
        except LedgerError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return _json(repository.upsert_transaction(row))
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar la operación") from None


def _ledger(repository: InvestmentRepository):
    try:
        accounts = {row["id"]: row for row in repository.get_accounts()}
        transactions = repository.get_transactions()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo leer el libro de inversiones") from None
    try:
        return accounts, compute_ledger(transactions)
    except LedgerError as error:
        # Only reachable if rows were edited outside the API.
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.get("/positions")
def get_positions(repository: InvestmentRepository = Depends(get_investment_repository)):
    accounts, result = _ledger(repository)
    positions = [
        {**row, "account_name": accounts.get(row["account_id"], {}).get("name")} for row in result.positions
    ]
    return {"positions": positions, "disclaimer": DISCLAIMER}


_CSV_COLUMNS = (
    "seccion", "fecha", "cuenta", "intermediario", "simbolo", "tipo_instrumento", "concepto", "cantidad",
    "moneda", "tipo_cambio", "fecha_tipo_cambio", "monto_mxn", "costo_mxn", "ganancia_mxn", "retencion_mxn",
)


def _pesos(cents: int | None) -> str:
    return "" if cents is None else f"{Decimal(cents) / 100:.2f}"


def _worksheet_csv(worksheet: dict[str, Any], accounts: dict[str, dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([f"# {DISCLAIMER}"])
    writer.writerow(_CSV_COLUMNS)

    def account_cells(account_id: str) -> list[str]:
        account = accounts.get(account_id, {})
        return [account.get("name") or account_id, account.get("broker") or ""]

    def trace(row: dict[str, Any]) -> list[str]:
        return [row["trade_date"].isoformat(), *account_cells(row["account_id"]), row["symbol"], row["instrument_type"]]

    def fx(row: dict[str, Any]) -> list[str]:
        fx_date = row.get("fx_rate_date")
        return [row["currency"], row["fx_rate_to_mxn"], fx_date.isoformat() if fx_date else ""]

    for row in worksheet["sales"]:
        writer.writerow(
            ["venta", *trace(row), "venta", row["quantity"], *fx(row), _pesos(row["proceeds_mxn_cents"]),
             _pesos(row["cost_mxn_cents"]), _pesos(row["gain_mxn_cents"]), _pesos(row["tax_withheld_mxn_cents"])]
        )
    for row in worksheet["income"]:
        writer.writerow(
            ["ingreso", *trace(row), row["kind"], "", *fx(row), _pesos(row["gross_mxn_cents"]), "", "",
             _pesos(row["tax_withheld_mxn_cents"])]
        )
    for row in worksheet["fees"]:
        writer.writerow(["comision", *trace(row), "comision", "", *fx(row), _pesos(row["fee_mxn_cents"]), "", "", ""])
    for row in worksheet["summary"]:
        writer.writerow(
            ["resumen", "", *account_cells(row["account_id"]), "", "", row["concept"], "", "MXN", "", "",
             _pesos(row["amount_mxn_cents"]), "", "", _pesos(row["tax_withheld_mxn_cents"])]
        )
    return buffer.getvalue()


@router.get("/worksheet")
def get_worksheet(
    year: int = Query(ge=1970, le=2100),
    format: Literal["json", "csv"] = Query(default="json"),
    repository: InvestmentRepository = Depends(get_investment_repository),
):
    """The year's papers for the accountant: every sale with its average cost,
    every dividend/distribution/interest with its withholding, and per-account
    totals by concept, all in MXN."""
    accounts, result = _ledger(repository)
    worksheet = yearly_worksheet(result, year)
    if format == "csv":
        return Response(
            content=_worksheet_csv(worksheet, accounts),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="faro-papeles-de-trabajo-{year}.csv"'},
        )
    return {**worksheet, "disclaimer": DISCLAIMER}
