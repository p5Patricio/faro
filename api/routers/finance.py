"""Personal finance dashboard API (mounted at ``/api/finance`` by
``api/main.py``). No demo-data fallback here, unlike the market-data
endpoints in ``api/main.py`` -- a personal ledger has no meaningful "demo
mode", so every route requires a live repository and returns 503 (Spanish
``detail``) when the database is unavailable, matching the existing
``PUT /api/risk-profile`` pattern exactly.

Import-order note: this module imports ``get_repository`` from
``api.main`` to avoid redefining the same dependency twice. ``api/main.py``
imports THIS module only after ``get_repository`` is already defined in its
own body (see the comment there), which is what keeps this a one-directional
import instead of a circular one. Always enter through ``api.main`` (as
every existing test in this repo already does) rather than importing this
module directly first.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.main import get_repository
from brain.finance.analytics import (
    compute_cash_flow_forecast,
    compute_emergency_fund_status,
    compute_fire_number,
    compute_investable_surplus,
    compute_monthly_summary,
    compute_subscription_total,
)
from collector.local_repository import LocalPostgresRepository

router = APIRouter()


def _require_repository(repository: LocalPostgresRepository | None) -> LocalPostgresRepository:
    if repository is None:
        raise HTTPException(
            status_code=503, detail="Base de datos no disponible para finanzas personales"
        )
    return repository


# -- Payload models ----------------------------------------------------------


class FinanceTransactionPayload(BaseModel):
    client_id: str
    account_id: str
    category_id: str | None = None
    kind: Literal["expense", "income", "transfer"]
    amount_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    occurred_at: str
    merchant: str | None = None
    notes: str | None = None
    source: str = "ui"
    fx_rate_to_base: float | None = None
    amount_base_cents: int | None = None
    deleted_at: str | None = None


class FinanceBudgetPayload(BaseModel):
    category_id: str
    period_month: str | None = None
    limit_cents: int = Field(ge=0)
    percent_of_income: float | None = Field(default=None, ge=0, le=100)
    currency: str = Field(min_length=3, max_length=3)


class FinanceNetWorthItemPayload(BaseModel):
    is_asset: bool
    label: str
    item_type: str = "other"
    amount_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)


class FinanceNetWorthSnapshotPayload(BaseModel):
    snapshot_date: str
    notes: str | None = None
    items: list[FinanceNetWorthItemPayload] = Field(default_factory=list)


class FinanceRecurringBillPayload(BaseModel):
    id: str | None = None
    name: str
    category_id: str | None = None
    account_id: str | None = None
    amount_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    frequency: Literal[
        "weekly", "biweekly", "monthly", "bimonthly", "quarterly", "semiannual", "annual"
    ]
    anchor_due_date: str
    reminder_days_before: int = Field(default=3, ge=0)
    is_active: bool = True
    notes: str | None = None


class FinanceRecurringBillPaymentPayload(BaseModel):
    bill_id: str
    due_date: str
    status: Literal["pending", "paid", "skipped"] = "pending"
    transaction_id: str | None = None


class FinanceGoalPayload(BaseModel):
    id: str | None = None
    name: str
    target_amount_cents: int = Field(gt=0)
    current_amount_cents: int = Field(default=0, ge=0)
    currency: str = Field(min_length=3, max_length=3)
    target_date: str | None = None
    purpose_note: str | None = None
    is_achieved: bool = False


# -- Reference data ------------------------------------------------------


@router.get("/categories")
def get_categories(repository: LocalPostgresRepository | None = Depends(get_repository)):
    repository = _require_repository(repository)
    try:
        return repository.get_finance_categories()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener las categorias") from None


@router.get("/accounts")
def get_accounts(repository: LocalPostgresRepository | None = Depends(get_repository)):
    repository = _require_repository(repository)
    try:
        return repository.get_finance_accounts()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener las cuentas") from None


# -- Transactions ----------------------------------------------------------


@router.get("/transactions")
def get_transactions(
    month: str | None = Query(default=None),
    category_id: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    try:
        return repository.get_finance_transactions(
            month=month, category_id=category_id, account_id=account_id, limit=limit
        )
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener las transacciones") from None


@router.put("/transactions")
def put_transaction(
    payload: FinanceTransactionPayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    # exclude_unset (not exclude_none): a routine edit that doesn't mention
    # `deleted_at` or `category_id` must not clobber their current value on
    # conflict -- `_upsert_batch`'s ON CONFLICT DO UPDATE only touches
    # columns present in the payload. Soft-delete is an explicit PUT that
    # sets `deleted_at`, never an implicit side effect of an unrelated edit.
    row = payload.model_dump(exclude_unset=True)
    row.setdefault("source", "ui")
    try:
        return repository.upsert_finance_transaction(row)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar la transaccion") from None


# -- Budgets -----------------------------------------------------------


@router.get("/budgets")
def get_budgets(
    month: str | None = Query(default=None),
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    try:
        return repository.get_finance_budgets(month=month)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener los presupuestos") from None


@router.put("/budgets")
def put_budget(
    payload: FinanceBudgetPayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    try:
        return repository.upsert_finance_budget(payload.model_dump())
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar el presupuesto") from None


# -- Net worth -----------------------------------------------------------


@router.get("/net-worth")
def get_net_worth(
    limit: int = Query(default=24, ge=1, le=200),
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    try:
        return repository.get_finance_net_worth_snapshots(limit=limit)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener los patrimonios") from None


@router.put("/net-worth")
def put_net_worth(
    payload: FinanceNetWorthSnapshotPayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    try:
        return repository.upsert_finance_net_worth_snapshot(
            snapshot_date=payload.snapshot_date,
            notes=payload.notes,
            items=[item.model_dump() for item in payload.items],
        )
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar el patrimonio") from None


# -- Recurring bills -----------------------------------------------------


@router.get("/recurring-bills")
def get_recurring_bills(
    include_inactive: bool = Query(default=False),
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    try:
        return repository.get_finance_recurring_bills(include_inactive=include_inactive)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener los pagos recurrentes") from None


@router.put("/recurring-bills")
def put_recurring_bill(
    payload: FinanceRecurringBillPayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    try:
        return repository.upsert_finance_recurring_bill(payload.model_dump())
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar el pago recurrente") from None


@router.put("/recurring-bills/payments")
def put_recurring_bill_payment(
    payload: FinanceRecurringBillPaymentPayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    row = payload.model_dump(exclude_unset=True)
    row.setdefault("status", "pending")
    if row.get("status") == "paid" and "paid_at" not in row:
        # Business-level default, not a payload field: the caller only
        # states the fact ("this got paid"); the timestamp is this router's
        # job, not something a client should have to compute itself.
        row["paid_at"] = datetime.now(UTC).isoformat()
    try:
        return repository.upsert_finance_recurring_bill_payment(row)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar el pago") from None


# -- Goals -------------------------------------------------------------


@router.get("/goals")
def get_goals(repository: LocalPostgresRepository | None = Depends(get_repository)):
    repository = _require_repository(repository)
    try:
        return repository.get_finance_goals()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener las metas") from None


@router.put("/goals")
def put_goal(
    payload: FinanceGoalPayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    try:
        return repository.upsert_finance_goal(payload.model_dump())
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar la meta") from None


# -- Summary (overview screen composition) --------------------------------


def _trailing_months(month: str, *, count: int) -> list[str]:
    """The `count` calendar months strictly BEFORE `month`, oldest first --
    never includes the still-in-progress current month, so a trailing
    average is only ever built from completed months."""
    year, mon = (int(part) for part in month.split("-"))
    months: list[str] = []
    for _ in range(count):
        mon -= 1
        if mon == 0:
            mon = 12
            year -= 1
        months.append(f"{year:04d}-{mon:02d}")
    return list(reversed(months))


def _average(values: list[int]) -> int:
    return int(sum(values) / len(values)) if values else 0


@router.get("/summary")
def get_summary(
    month: str | None = Query(default=None),
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    """One composed payload for the dashboard's overview screen. Degrades
    gracefully section-by-section (never a 500) when there isn't enough
    history yet: each section carries its own `data_sufficient` flag rather
    than the whole endpoint failing for a brand-new user with zero data."""
    repository = _require_repository(repository)
    target_month = month or date.today().strftime("%Y-%m")

    try:
        categories = repository.get_finance_categories()
        transactions = repository.get_finance_transactions(month=target_month, limit=10_000)
        monthly_summary = compute_monthly_summary(transactions, categories)

        # Trailing averages (necesidad spend, total expense, income) over the
        # 3 completed months before `target_month`. A month with zero
        # transactions is skipped entirely rather than counted as a $0
        # data point -- a month nobody logged anything in isn't evidence of
        # $0 spending, it's an absence of data.
        necesidad_totals: list[int] = []
        total_expense_totals: list[int] = []
        income_totals: list[int] = []
        for trailing_month in _trailing_months(target_month, count=3):
            trailing_transactions = repository.get_finance_transactions(month=trailing_month, limit=10_000)
            if not trailing_transactions:
                continue
            trailing_summary = compute_monthly_summary(trailing_transactions, categories)
            necesidad_totals.append(trailing_summary["buckets"]["necesidad"]["actual_cents"])
            total_expense_totals.append(trailing_summary["expense_cents"])
            income_totals.append(trailing_summary["income_cents"])

        history_sufficient = len(necesidad_totals) > 0
        avg_necesidad_cents = _average(necesidad_totals)
        avg_total_expense_cents = _average(total_expense_totals)
        avg_income_cents = _average(income_totals)

        snapshots = repository.get_finance_net_worth_snapshots(limit=1)
        latest_snapshot = snapshots[0] if snapshots else None
        net_worth_sufficient = latest_snapshot is not None
        # Simplification: "liquid" net worth is stood in by TOTAL net worth
        # (assets - liabilities). Splitting out only genuinely liquid items
        # (cash, not real estate/retirement accounts) would need a fixed
        # `item_type` taxonomy that 0008 deliberately left freeform --
        # out of scope here.
        liquid_net_worth_cents = latest_snapshot["net_worth_cents"] if latest_snapshot else 0

        emergency_fund_status = compute_emergency_fund_status(liquid_net_worth_cents, avg_necesidad_cents)
        # Naive annualization: 12x the trailing monthly average, ignoring
        # seasonality -- consistent with this module's "genuinely simple"
        # mandate.
        fire_number = compute_fire_number(liquid_net_worth_cents, avg_total_expense_cents * 12)
        investable_surplus = compute_investable_surplus(monthly_summary, emergency_fund_status)

        recurring_bills = repository.get_finance_recurring_bills(include_inactive=False)
        subscriptions = compute_subscription_total(recurring_bills)
        # Only each bill's NEXT scheduled occurrence feeds the forecast --
        # 0008's own design has the app generate one pending row at a time
        # per bill, so this is normally the complete near-term picture.
        pending_bill_payments = [
            {"due_date": bill["next_due_date"], "amount_cents": bill["amount_cents"]}
            for bill in recurring_bills
            if bill.get("next_due_date") is not None
        ]
        cash_flow_forecast = compute_cash_flow_forecast(pending_bill_payments, avg_income_cents, horizon_days=30)

        combined_sufficient = net_worth_sufficient and history_sufficient

        return {
            "month": target_month,
            "monthly_summary": {"data_sufficient": True, **monthly_summary},
            "net_worth": {
                "data_sufficient": net_worth_sufficient,
                "snapshot_date": latest_snapshot["snapshot_date"] if latest_snapshot else None,
                "total_assets_cents": latest_snapshot["total_assets_cents"] if latest_snapshot else None,
                "total_liabilities_cents": latest_snapshot["total_liabilities_cents"] if latest_snapshot else None,
                "net_worth_cents": latest_snapshot["net_worth_cents"] if latest_snapshot else None,
                "liquid_net_worth_cents": liquid_net_worth_cents if latest_snapshot else None,
            },
            "emergency_fund": {"data_sufficient": combined_sufficient, **emergency_fund_status},
            "fire_number": {"data_sufficient": combined_sufficient, **fire_number},
            "investable_surplus": {"data_sufficient": combined_sufficient, **investable_surplus},
            "subscriptions": {"data_sufficient": True, **subscriptions},
            "cash_flow_forecast": {"data_sufficient": history_sufficient, **cash_flow_forecast},
        }
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo calcular el resumen financiero") from None
