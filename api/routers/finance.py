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
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.main import get_repository
from brain.finance.analytics import (
    MIN_TRANSACTIONS_PER_TRAILING_MONTH,
    TRAILING_MONTHS_CONSIDERED,
    compute_cash_flow_forecast,
    compute_category_breakdown,
    compute_emergency_fund_status,
    compute_fire_number,
    compute_investable_surplus,
    compute_monthly_summary,
    compute_subscription_total,
    compute_trailing_baseline,
)
from brain.finance.currency import (
    BASE_CURRENCY,
    BIGINT_MAX,
    base_amount_cents,
    normalize_currency,
    resolve_fx_and_base,
)
from brain.finance.recurrence import occurrence_on_or_after
from collector.local_repository import LocalPostgresRepository

router = APIRouter()

# Every `*_cents` payload field lands in a `bigint` column: an amount beyond
# it is a client error (422 from validation), never a database error (503).
_MAX_CENTS = BIGINT_MAX


def _require_repository(repository: LocalPostgresRepository | None) -> LocalPostgresRepository:
    if repository is None:
        raise HTTPException(
            status_code=503, detail="Base de datos no disponible para finanzas personales"
        )
    return repository


def _require_base_currency(currency: str, *, subject: str) -> str:
    """Bills, goals and budgets are base-currency only in v1: they have no
    FX-rate column and their totals are summed as plain base cents, so any
    other currency is refused up front instead of being summed at face value.
    Returns the normalized (upper-case) code."""
    normalized = normalize_currency(currency)
    if normalized != BASE_CURRENCY:
        raise HTTPException(
            status_code=422,
            detail=f"{subject} solo admiten {BASE_CURRENCY} por ahora (se recibió {normalized}).",
        )
    return normalized


# -- Payload models ----------------------------------------------------------


class FinanceTransactionPayload(BaseModel):
    client_id: str
    account_id: str
    category_id: str | None = None
    kind: Literal["expense", "income", "transfer"]
    amount_cents: int = Field(ge=0, le=_MAX_CENTS)
    currency: str = Field(min_length=3, max_length=3)
    occurred_at: str
    merchant: str | None = None
    notes: str | None = None
    source: str = "ui"
    fx_rate_to_base: float | None = None
    # No `amount_base_cents`: the base amount is always computed server-side
    # (see `_apply_transaction_base_amounts`). Pydantic drops unknown keys, so
    # a client that still sends one is silently ignored, never trusted.
    deleted_at: str | None = None


class FinanceBudgetPayload(BaseModel):
    category_id: str
    period_month: str | None = None
    limit_cents: int = Field(ge=0, le=_MAX_CENTS)
    percent_of_income: float | None = Field(default=None, ge=0, le=100)
    currency: str = Field(min_length=3, max_length=3)


class FinanceNetWorthItemPayload(BaseModel):
    is_asset: bool
    label: str
    item_type: str = "other"
    amount_cents: int = Field(ge=0, le=_MAX_CENTS)
    currency: str = Field(min_length=3, max_length=3)
    fx_rate_to_base: float | None = None


class FinanceNetWorthSnapshotPayload(BaseModel):
    snapshot_date: str
    notes: str | None = None
    items: list[FinanceNetWorthItemPayload] = Field(default_factory=list)


class FinanceRecurringBillPayload(BaseModel):
    id: str | None = None
    name: str
    category_id: str | None = None
    account_id: str | None = None
    amount_cents: int = Field(ge=0, le=_MAX_CENTS)
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
    target_amount_cents: int = Field(gt=0, le=_MAX_CENTS)
    current_amount_cents: int = Field(default=0, ge=0, le=_MAX_CENTS)
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


def _fx_required_detail(currency: str) -> str:
    return (
        f"Una transacción en {currency} necesita un tipo de cambio a {BASE_CURRENCY} mayor que cero, "
        f"y su monto convertido no puede exceder el límite permitido."
    )


def _apply_transaction_base_amounts(
    row: dict[str, Any], *, account: dict[str, Any] | None, existing: dict[str, Any] | None
) -> None:
    """Validate ``row``'s currency against its account and set the
    materialized ``fx_rate_to_base`` / ``amount_base_cents`` on ``row``.

    Rules (decision D1): the transaction's currency must be its account's;
    the base currency always gets rate 1; a foreign currency needs a
    positive rate. The base amount is computed here, never taken from the
    client.

    ``row`` only holds the fields the client sent (``exclude_unset``), and
    ``amount_cents`` / ``currency`` are always among them. So "the edit does
    not touch the money" is decided by comparing them with the stored row: a
    foreign-currency edit that leaves amount and currency unchanged and sends
    no rate (a notes edit, a soft-delete) leaves the stored rate and base
    amount untouched instead of failing or clobbering them. An amount-only
    edit reuses the stored rate; a new row must carry its own.
    """
    if account is None:
        raise HTTPException(status_code=422, detail="La cuenta indicada no existe.")
    currency = row["currency"]
    account_currency = normalize_currency(account["currency"])
    if currency != account_currency:
        raise HTTPException(
            status_code=422,
            detail=f"La moneda de la transacción ({currency}) debe ser la de la cuenta ({account_currency}).",
        )

    fx_rate = row.get("fx_rate_to_base")
    if currency != BASE_CURRENCY and fx_rate is None and existing is not None:
        if normalize_currency(existing["currency"]) == currency:
            if existing["amount_cents"] == row["amount_cents"]:
                row.pop("fx_rate_to_base", None)
                return
            fx_rate = existing.get("fx_rate_to_base")

    try:
        stored_rate, base_cents = resolve_fx_and_base(row["amount_cents"], currency, fx_rate)
    except (ValueError, ArithmeticError):
        # decimal.InvalidOperation is an ArithmeticError, not a ValueError.
        raise HTTPException(status_code=422, detail=_fx_required_detail(currency)) from None
    row["fx_rate_to_base"] = stored_rate
    row["amount_base_cents"] = base_cents


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
    row["currency"] = normalize_currency(row["currency"])
    try:
        account = repository.get_finance_account(row["account_id"])
        existing = repository.get_finance_transaction_by_client_id(row["client_id"])
        _apply_transaction_base_amounts(row, account=account, existing=existing)
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
    row = payload.model_dump()
    row["currency"] = _require_base_currency(row["currency"], subject="Los presupuestos")
    try:
        return repository.upsert_finance_budget(row)
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


def _resolve_net_worth_item(item: FinanceNetWorthItemPayload) -> dict[str, Any]:
    """One worksheet line with its materialized base amount. The base
    currency gets rate 1; a foreign currency must bring a positive rate
    (422 naming the offending line, so a mixed worksheet is never summed at
    face value)."""
    data = item.model_dump()
    data["currency"] = normalize_currency(data["currency"])
    try:
        data["fx_rate_to_base"], data["amount_base_cents"] = resolve_fx_and_base(
            data["amount_cents"], data["currency"], data["fx_rate_to_base"]
        )
    except (ValueError, ArithmeticError):
        raise HTTPException(
            status_code=422,
            detail=(
                f"El concepto «{data['label']}» está en {data['currency']}: "
                f"indica un tipo de cambio a {BASE_CURRENCY} mayor que cero "
                f"y un monto que no exceda el límite."
            ),
        ) from None
    return data


@router.put("/net-worth")
def put_net_worth(
    payload: FinanceNetWorthSnapshotPayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    items = [_resolve_net_worth_item(item) for item in payload.items]
    try:
        return repository.upsert_finance_net_worth_snapshot(
            snapshot_date=payload.snapshot_date,
            notes=payload.notes,
            items=items,
        )
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar el patrimonio") from None


# -- Recurring bills -----------------------------------------------------


def _today() -> date:
    """The machine-local calendar date every "due today / overdue" decision
    is made against. One seam so tests can pin the clock."""
    return date.today()


def _parse_date_field(value: str, *, detail: str) -> date:
    """A payload date string as a ``date``; 422 with ``detail`` when it is not
    a valid ISO date (the recurrence math needs a real date, so a bad value
    must not reach it as a 500)."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=detail) from None


def _with_next_due_date(bills: list[dict[str, Any]], *, today: date) -> list[dict[str, Any]]:
    """Every ACTIVE bill gets a next due date. Saving a bill persists its
    pending occurrence, so this only fills in for a bill that has none (one
    written before occurrences were generated, or inserted by hand): its next
    due date is derived, read-only, as the earliest schedule date on or after
    ``today``. Marking that date paid upserts the row, so the derived date
    behaves like a stored one."""
    completed: list[dict[str, Any]] = []
    for bill in bills:
        if bill["is_active"] and bill.get("next_due_date") is None:
            bill = {
                **bill,
                "next_due_date": occurrence_on_or_after(bill["anchor_due_date"], bill["frequency"], today),
                "next_status": "pending",
            }
        completed.append(bill)
    return completed


@router.get("/recurring-bills")
def get_recurring_bills(
    include_inactive: bool = Query(default=False),
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    repository = _require_repository(repository)
    try:
        bills = repository.get_finance_recurring_bills(include_inactive=include_inactive)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudieron obtener los pagos recurrentes") from None
    return _with_next_due_date(bills, today=_today())


@router.put("/recurring-bills")
def put_recurring_bill(
    payload: FinanceRecurringBillPayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    """Create or edit a bill. An active bill always ends up with a pending
    occurrence (see ``upsert_finance_recurring_bill``); ``today`` is the
    machine-local date, matching every other date default in this module."""
    repository = _require_repository(repository)
    row = payload.model_dump()
    row["currency"] = _require_base_currency(row["currency"], subject="Los pagos recurrentes")
    row["anchor_due_date"] = _parse_date_field(
        row["anchor_due_date"], detail="La fecha del primer vencimiento no es válida (usa AAAA-MM-DD)."
    )
    try:
        return repository.upsert_finance_recurring_bill(row, today=_today())
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar el pago recurrente") from None


@router.put("/recurring-bills/payments")
def put_recurring_bill_payment(
    payload: FinanceRecurringBillPaymentPayload,
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    """Record an occurrence's status. Settling it (``paid`` / ``skipped``)
    also creates the bill's next pending occurrence; no ledger transaction is
    created (``transaction_id`` stays an optional link)."""
    repository = _require_repository(repository)
    row = payload.model_dump(exclude_unset=True)
    row.setdefault("status", "pending")
    row["due_date"] = _parse_date_field(
        row["due_date"], detail="La fecha de vencimiento no es válida (usa AAAA-MM-DD)."
    )
    # `paid_at` is a business-level value, not a payload field: the caller
    # only states the fact ("this got paid"); the timestamp is this router's
    # job, not something a client should have to compute itself. Any other
    # status clears it so a paid -> skipped correction leaves no stale time.
    row["paid_at"] = datetime.now(UTC).isoformat() if row["status"] == "paid" else None
    try:
        payment = repository.upsert_finance_recurring_bill_payment(row)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo guardar el pago") from None
    if payment is None:
        raise HTTPException(status_code=404, detail="El pago recurrente indicado no existe.")
    return payment


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
    row = payload.model_dump()
    row["currency"] = _require_base_currency(row["currency"], subject="Las metas")
    try:
        return repository.upsert_finance_goal(row)
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


@router.get("/summary")
def get_summary(
    month: str | None = Query(default=None),
    repository: LocalPostgresRepository | None = Depends(get_repository),
):
    """One composed payload for the dashboard's overview screen. Degrades
    gracefully section-by-section (never a 500) when there isn't enough
    history yet: each section carries its own `data_sufficient` flag rather
    than the whole endpoint failing for a brand-new user with zero data.

    What each flag means. Every ``data_sufficient`` is derived from data except
    ``subscriptions``, which is always true: having no subscriptions is a true
    zero, not a gap in the data.

    * ``monthly_summary`` -- the month has at least one converted
      income/expense transaction. ``net_cents`` there is income minus
      ``spending_cents`` (savings are not spending); see
      ``compute_monthly_summary``.
    * ``emergency_fund`` / ``fire_number`` / ``investable_surplus`` -- there
      is a net-worth snapshot AND at least one trailing month met the
      coverage rule (decision D2: 5+ converted transactions). ``history``
      reports how many of the 3 trailing months counted, and how many of
      their rows were unconverted, so the UI can say "Estimado con N meses".
    * ``cash_flow_forecast`` -- shown whenever there are bills committed in
      the window or overdue, even with no income history: the bills are facts
      from the schedule. ``income_data_sufficient`` says separately whether
      an income projection exists (a covered trailing month with income).
    """
    repository = _require_repository(repository)
    today = _today()
    target_month = month or today.strftime("%Y-%m")

    try:
        categories = repository.get_finance_categories()
        transactions = repository.get_finance_transactions(month=target_month, limit=10_000)
        monthly_summary = compute_monthly_summary(transactions, categories)
        budget_limits = {
            budget["category_id"]: budget["limit_cents"]
            for budget in repository.get_finance_budgets(month=target_month)
        }
        category_breakdown = compute_category_breakdown(transactions, categories, budget_limits)

        # Baselines over the completed months before `target_month`. Only a
        # month that meets the coverage rule counts (decision D2); the rest
        # are skipped, not averaged in as zeros, and their unconverted rows
        # are still reported through `history`.
        baseline = compute_trailing_baseline(
            [
                compute_monthly_summary(
                    repository.get_finance_transactions(month=trailing_month, limit=10_000), categories
                )
                for trailing_month in _trailing_months(target_month, count=TRAILING_MONTHS_CONSIDERED)
            ]
        )
        history_sufficient = baseline["months_used"] > 0

        snapshots = repository.get_finance_net_worth_snapshots(limit=1)
        latest_snapshot = snapshots[0] if snapshots else None
        net_worth_sufficient = latest_snapshot is not None
        # Simplification: "liquid" net worth is stood in by TOTAL net worth
        # (assets - liabilities). Splitting out only genuinely liquid items
        # (cash, not real estate/retirement accounts) would need a fixed
        # `item_type` taxonomy that 0008 deliberately left freeform --
        # out of scope here.
        liquid_net_worth_cents = latest_snapshot["net_worth_cents"] if latest_snapshot else 0

        # Emergency fund: essential (necesidad) expenses; FIRE: spending
        # without the savings bucket (decision D3).
        emergency_fund_status = compute_emergency_fund_status(
            liquid_net_worth_cents, baseline["avg_necesidad_cents"]
        )
        # Naive annualization: 12x the trailing monthly average, ignoring
        # seasonality -- consistent with this module's "genuinely simple"
        # mandate.
        fire_number = compute_fire_number(liquid_net_worth_cents, baseline["avg_spending_cents"] * 12)
        investable_surplus = compute_investable_surplus(monthly_summary, emergency_fund_status)

        recurring_bills = _with_next_due_date(
            repository.get_finance_recurring_bills(include_inactive=False), today=today
        )
        subscriptions = compute_subscription_total(recurring_bills)
        # Each bill's NEXT pending occurrence seeds the forecast (0008's
        # design keeps one pending row per bill), and the forecast expands the
        # bill's later occurrences inside the horizon from its anchor.
        # Amounts go in as BASE cents; a bill that cannot be converted
        # (legacy non-base row) is left out, same as in the subscription total.
        pending_bill_payments: list[dict[str, Any]] = []
        for bill in recurring_bills:
            bill_base_cents = base_amount_cents(bill)
            if bill.get("next_due_date") is None or bill_base_cents is None:
                continue
            pending_bill_payments.append(
                {
                    "due_date": bill["next_due_date"],
                    "amount_cents": bill_base_cents,
                    "anchor_due_date": bill["anchor_due_date"],
                    "frequency": bill["frequency"],
                }
            )
        # No income projection without an income baseline: `None`, never a
        # made-up $0 (a covered month that logged only expenses says nothing
        # about what comes in).
        income_baseline_cents = baseline["avg_income_cents"] if baseline["avg_income_cents"] > 0 else None
        cash_flow_forecast = compute_cash_flow_forecast(
            pending_bill_payments, income_baseline_cents, horizon_days=30, today=today
        )
        forecast_has_bills = (
            cash_flow_forecast["committed_bills_cents"] > 0 or cash_flow_forecast["overdue_bills_count"] > 0
        )

        combined_sufficient = net_worth_sufficient and history_sufficient

        return {
            "month": target_month,
            "monthly_summary": {
                "data_sufficient": monthly_summary["converted_transactions"] > 0,
                **monthly_summary,
            },
            "category_breakdown": category_breakdown,
            "history": {
                "months_used": baseline["months_used"],
                "months_considered": baseline["months_considered"],
                "min_transactions_per_month": MIN_TRANSACTIONS_PER_TRAILING_MONTH,
                "unconverted_transactions": baseline["unconverted_transactions"],
            },
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
            "cash_flow_forecast": {
                "data_sufficient": forecast_has_bills or cash_flow_forecast["income_data_sufficient"],
                **cash_flow_forecast,
            },
        }
    except RuntimeError:
        raise HTTPException(status_code=503, detail="No se pudo calcular el resumen financiero") from None
