"""Pure personal-finance analytics: every function here takes already-fetched
rows/dicts and returns a computed dict. No I/O, no hidden state -- matches
``brain/feedback.py``/``brain/risk.py``'s house style.

This is basic personal-finance VISIBILITY, not a forecasting model. Every
formula is deliberately naive; each simplification is called out inline
rather than silently overreached.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


# The book's 50/30/20 rule: every expense category is bucketed into exactly
# one of these three, each with its own target percentage of income.
BUCKET_TARGET_PERCENT: dict[str, int] = {
    "necesidad": 50,
    "deseo": 30,
    "ahorro_inversion": 20,
}

# Occurrences per year for each `finance_recurring_bills.frequency` value
# (0008's CHECK constraint enumerates the same seven values).
FREQUENCY_OCCURRENCES_PER_YEAR: dict[str, int] = {
    "weekly": 52,
    "biweekly": 26,
    "monthly": 12,
    "bimonthly": 6,
    "quarterly": 4,
    "semiannual": 2,
    "annual": 1,
}


def compute_monthly_summary(transactions: list[dict[str, Any]], categories: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up one month's already-filtered transactions into income/expense
    totals and the book's 50/30/20 bucket actuals vs. targets.

    Simplification: `kind='transfer'` transactions are ignored entirely -- a
    transfer between the user's own accounts is neither income nor expense,
    and there is no cross-account netting logic here (that would need real
    double-entry bookkeeping, out of scope).
    """
    bucket_by_category_id = {category["id"]: category.get("budget_bucket") for category in categories}

    income_cents = sum(t["amount_cents"] for t in transactions if t["kind"] == "income")
    expense_cents = sum(t["amount_cents"] for t in transactions if t["kind"] == "expense")
    net_cents = income_cents - expense_cents

    buckets: dict[str, dict[str, int]] = {
        bucket: {
            # Integer division keeps target_cents a whole number of cents;
            # the rounding error is at most 1 cent per bucket, immaterial at
            # these amounts.
            "actual_cents": 0,
            "target_cents": income_cents * percent // 100,
        }
        for bucket, percent in BUCKET_TARGET_PERCENT.items()
    }
    for t in transactions:
        if t["kind"] != "expense":
            continue
        bucket = bucket_by_category_id.get(t.get("category_id"))
        if bucket in buckets:
            buckets[bucket]["actual_cents"] += t["amount_cents"]

    savings_rate_pct = (
        buckets["ahorro_inversion"]["actual_cents"] / income_cents * 100 if income_cents > 0 else 0.0
    )

    return {
        "income_cents": income_cents,
        "expense_cents": expense_cents,
        "net_cents": net_cents,
        "savings_rate_pct": savings_rate_pct,
        "buckets": buckets,
    }


def compute_emergency_fund_status(
    liquid_net_worth_cents: int, avg_monthly_fixed_expense_cents: int
) -> dict[str, Any]:
    """The book's 3-6 month cash-cushion rule. When there's no expense
    baseline yet (a brand-new user), ``months_covered`` is ``None`` rather
    than raising ``ZeroDivisionError``; ``status`` conservatively reports
    "below" in that case since coverage can't be verified."""
    if avg_monthly_fixed_expense_cents <= 0:
        return {
            "months_covered": None,
            "target_min_months": 3,
            "target_max_months": 6,
            "status": "below",
        }

    months_covered = liquid_net_worth_cents / avg_monthly_fixed_expense_cents
    if months_covered < 3:
        status = "below"
    elif months_covered <= 6:
        status = "within"
    else:
        status = "above"

    return {
        "months_covered": months_covered,
        "target_min_months": 3,
        "target_max_months": 6,
        "status": status,
    }


def compute_fire_number(net_worth_cents: int, avg_annual_expense_cents: int) -> dict[str, Any]:
    """The book's 4% safe-withdrawal rule: 25x annual expenses is the FIRE
    target. Guards a zero/negative expense baseline instead of dividing by
    zero for ``progress_pct``."""
    if avg_annual_expense_cents <= 0:
        return {"target_cents": 0, "progress_pct": None}

    target_cents = avg_annual_expense_cents * 25
    progress_pct = net_worth_cents / target_cents * 100
    return {"target_cents": target_cents, "progress_pct": progress_pct}


def compute_investable_surplus(monthly_summary: dict[str, Any], emergency_fund_status: dict[str, Any]) -> dict[str, Any]:
    """The book's own stated priority: fully fund the emergency cushion
    before any 'ahorro e inversion' bucket spend counts as investable
    surplus. Exactly ``target_min_months`` (3.0) counts as COVERED, not
    below -- the boundary is inclusive."""
    months_covered = emergency_fund_status.get("months_covered")
    target_min_months = emergency_fund_status.get("target_min_months", 3)

    if months_covered is None or months_covered < target_min_months:
        return {"surplus_cents": 0, "reason": "building_emergency_fund"}

    return {
        "surplus_cents": monthly_summary["buckets"]["ahorro_inversion"]["actual_cents"],
        "reason": "emergency_fund_covered",
    }


def annualize_recurring_bill_amount(amount_cents: int, frequency: str) -> int:
    """Naive annualization: occurrences/year times amount, ignoring calendar
    drift (e.g. 52 weeks/year isn't exactly a calendar year)."""
    return amount_cents * FREQUENCY_OCCURRENCES_PER_YEAR[frequency]


def compute_subscription_total(recurring_bills: list[dict[str, Any]]) -> dict[str, Any]:
    """Sums annualized cost across ACTIVE bills only -- a cancelled
    (inactive) subscription shouldn't inflate the total."""
    bills: list[dict[str, Any]] = []
    annual_total_cents = 0
    for bill in recurring_bills:
        if not bill.get("is_active", True):
            continue
        annual_cents = annualize_recurring_bill_amount(bill["amount_cents"], bill["frequency"])
        annual_total_cents += annual_cents
        bills.append({"name": bill["name"], "annual_cents": annual_cents})

    return {
        "annual_total_cents": annual_total_cents,
        "monthly_average_cents": annual_total_cents // 12,
        "bills": bills,
    }


def compute_cash_flow_forecast(
    pending_bill_payments: list[dict[str, Any]],
    avg_monthly_income_cents: int,
    horizon_days: int = 30,
) -> dict[str, Any]:
    """A NAIVE LINEAR projection, not a real forecasting model: income is
    smeared evenly across the horizon (``avg_monthly_income_cents *
    horizon_days / 30``), and only bills with an already-scheduled pending
    payment inside the horizon count as committed outflow -- discretionary
    spending is not projected at all, by design (this is a bills-committed
    view, not a full budget forecast)."""
    expected_income_cents = avg_monthly_income_cents * horizon_days / 30

    today = date.today()
    horizon_end = today + timedelta(days=horizon_days)
    committed_bills_cents = 0
    for payment in pending_bill_payments:
        due_date = payment["due_date"]
        if isinstance(due_date, str):
            due_date = date.fromisoformat(due_date)
        if today <= due_date <= horizon_end:
            committed_bills_cents += payment["amount_cents"]

    projected_net_cents = expected_income_cents - committed_bills_cents
    return {
        "horizon_days": horizon_days,
        "expected_income_cents": expected_income_cents,
        "committed_bills_cents": committed_bills_cents,
        "projected_net_cents": projected_net_cents,
    }


def compute_category_trend(current_month_cents: int, trailing_avg_cents: int) -> dict[str, Any]:
    """``is_anomaly`` flags a >30% spike over the trailing average -- a
    fixed threshold, not a statistical outlier test. Good enough for a
    personal dashboard's yellow-flag, not a monitoring system."""
    if trailing_avg_cents <= 0:
        return {"delta_pct": None, "is_anomaly": False}

    delta_pct = (current_month_cents - trailing_avg_cents) / trailing_avg_cents * 100
    return {"delta_pct": delta_pct, "is_anomaly": delta_pct > 30}
