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

from brain.finance.currency import base_amount_cents
from brain.finance.recurrence import occurrences_between


# The book's 50/30/20 rule: every expense category is bucketed into exactly
# one of these three, each with its own target percentage of income.
BUCKET_TARGET_PERCENT: dict[str, int] = {
    "necesidad": 50,
    "deseo": 30,
    "ahorro_inversion": 20,
}

# The bucket for an expense row whose category is missing (or inactive, or has
# no `budget_bucket`). It has an actual amount but NO target: the 50/30/20 rule
# says nothing about money nobody classified. Having it means every converted
# expense row lands in exactly one bucket, so the bucket actuals always add up
# to the month's total expense instead of quietly losing the unclassified part.
UNCATEGORIZED_BUCKET = "sin_categoria"

# The bucket whose expenses are "saved", not "spent" (decision D3).
SAVINGS_BUCKET = "ahorro_inversion"

# Decision D2: a trailing month only counts toward an average when it holds at
# least this many converted income/expense rows. A month with a handful of
# entries is a partly-logged month, not evidence of what a month costs.
MIN_TRANSACTIONS_PER_TRAILING_MONTH = 5

# How many completed months before the target month feed the averages.
TRAILING_MONTHS_CONSIDERED = 3

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

    Every figure is in the BASE currency (see ``brain/finance/currency.py``):
    summing raw ``amount_cents`` across currencies would add pesos to
    dollars. An income/expense row with no usable base amount (a foreign
    currency without an FX rate) is left out of every total and counted in
    ``unconverted_transactions`` so the caller can warn instead of silently
    under-reporting.

    Spending versus saving (decision D3). Putting money into the
    ``ahorro_inversion`` bucket is not spending it, so the expense side is
    split three ways:

    * ``expense_cents`` -- the RAW total of every converted expense row
      (savings included);
    * ``saved_cents`` -- the expenses in the ``ahorro_inversion`` bucket;
    * ``spending_cents`` -- everything else: ``necesidad`` + ``deseo`` +
      ``sin_categoria``. So ``spending_cents + saved_cents == expense_cents``.

    ``net_cents`` is income minus ``spending_cents``: the money that was NOT
    spent, saved or not. It used to be income minus ``expense_cents``, which
    booked saving as if it were spending and made a month of pure saving read
    as a loss; every consumer of ``net_cents`` now means "not spent".
    ``savings_rate_pct`` is ``saved_cents`` over income.

    Buckets: every converted expense row lands in exactly one, so the bucket
    actuals sum to ``expense_cents``. A row whose category is missing, is not
    among the given (active) ``categories``, or has no ``budget_bucket`` goes
    to ``sin_categoria``, which carries an actual amount and no target.

    ``converted_transactions`` counts the converted income/expense rows: it
    is what decides whether the month has data at all and, for a trailing
    month, whether it meets the coverage rule (D2).

    Simplification: `kind='transfer'` transactions are ignored entirely -- a
    transfer between the user's own accounts is neither income nor expense,
    and there is no cross-account netting logic here (that would need real
    double-entry bookkeeping, out of scope).
    """
    bucket_by_category_id = {category["id"]: category.get("budget_bucket") for category in categories}

    converted: list[tuple[dict[str, Any], int]] = []
    unconverted_transactions = 0
    for t in transactions:
        if t["kind"] not in ("income", "expense"):
            continue
        base_cents = base_amount_cents(t)
        if base_cents is None:
            unconverted_transactions += 1
            continue
        converted.append((t, base_cents))

    income_cents = sum(cents for t, cents in converted if t["kind"] == "income")
    expense_cents = sum(cents for t, cents in converted if t["kind"] == "expense")

    actual_by_bucket: dict[str, int] = {bucket: 0 for bucket in (*BUCKET_TARGET_PERCENT, UNCATEGORIZED_BUCKET)}
    for t, cents in converted:
        if t["kind"] != "expense":
            continue
        bucket = bucket_by_category_id.get(t.get("category_id"))
        actual_by_bucket[bucket if bucket in BUCKET_TARGET_PERCENT else UNCATEGORIZED_BUCKET] += cents

    saved_cents = actual_by_bucket[SAVINGS_BUCKET]
    spending_cents = sum(actual for bucket, actual in actual_by_bucket.items() if bucket != SAVINGS_BUCKET)
    net_cents = income_cents - spending_cents

    buckets: dict[str, dict[str, int]] = {
        bucket: {
            # Integer division keeps target_cents a whole number of cents;
            # the rounding error is at most 1 cent per bucket, immaterial at
            # these amounts.
            "actual_cents": actual_by_bucket[bucket],
            "target_cents": income_cents * percent // 100,
        }
        for bucket, percent in BUCKET_TARGET_PERCENT.items()
    }
    buckets[UNCATEGORIZED_BUCKET] = {"actual_cents": actual_by_bucket[UNCATEGORIZED_BUCKET]}

    savings_rate_pct = saved_cents / income_cents * 100 if income_cents > 0 else 0.0

    return {
        "income_cents": income_cents,
        "expense_cents": expense_cents,
        "spending_cents": spending_cents,
        "saved_cents": saved_cents,
        "net_cents": net_cents,
        "savings_rate_pct": savings_rate_pct,
        "buckets": buckets,
        "converted_transactions": len(converted),
        "unconverted_transactions": unconverted_transactions,
    }


def compute_category_breakdown(
    transactions: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    budget_limits: dict[Any, int],
) -> list[dict[str, Any]]:
    """Every expense category with spend in the month, as
    ``compute_monthly_summary`` counts it (base amounts, unconverted rows
    excluded), plus a "Sin categoría" row for the expenses with no usable
    category. The rows always add up to that summary's ``expense_cents``.

    ``budget_limits`` maps a category id to its effective monthly limit in
    base cents. A category with a budget is listed even with no spend (a
    budget with nothing spent against it is still worth showing); one without
    a budget carries ``budget_cents: None``. Rows are ordered by spend (then
    name), the uncategorized row last.

    An expense whose category is not among the given (active) ``categories``
    is reported as uncategorized rather than under a name we cannot resolve --
    the same rule ``compute_monthly_summary`` applies to its buckets, so the
    two views never disagree.
    """
    category_by_id = {category["id"]: category for category in categories}

    actual_by_category: dict[Any, int] = {}
    uncategorized_cents = 0
    for t in transactions:
        if t["kind"] != "expense":
            continue
        cents = base_amount_cents(t)
        if cents is None:
            continue
        category_id = t.get("category_id")
        if category_id in category_by_id:
            actual_by_category[category_id] = actual_by_category.get(category_id, 0) + cents
        else:
            uncategorized_cents += cents

    rows: list[dict[str, Any]] = []
    for category_id in {*actual_by_category, *(cid for cid in budget_limits if cid in category_by_id)}:
        category = category_by_id[category_id]
        bucket = category.get("budget_bucket")
        rows.append(
            {
                "category_id": category_id,
                "category_name": category["name"],
                "slug": category.get("slug"),
                "emoji": category.get("emoji"),
                "bucket": bucket if bucket in BUCKET_TARGET_PERCENT else UNCATEGORIZED_BUCKET,
                "actual_cents": actual_by_category.get(category_id, 0),
                "budget_cents": budget_limits.get(category_id),
            }
        )
    rows.sort(key=lambda row: (-row["actual_cents"], row["category_name"]))

    if uncategorized_cents > 0:
        rows.append(
            {
                "category_id": None,
                "category_name": "Sin categoría",
                "slug": None,
                "emoji": None,
                "bucket": UNCATEGORIZED_BUCKET,
                "actual_cents": uncategorized_cents,
                "budget_cents": None,
            }
        )
    return rows


def compute_trailing_baseline(trailing_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """The averages every "estimated" figure is built from, over the completed
    months before the target month (each entry is one month's
    ``compute_monthly_summary`` result).

    Coverage rule (decision D2): a month counts only when it has at least
    ``MIN_TRANSACTIONS_PER_TRAILING_MONTH`` converted transactions. A month
    with fewer -- including one whose rows are all unconverted, or that is
    empty -- is skipped, never averaged in as a zero: a month nobody logged
    properly is an absence of data, not evidence of $0 spending.

    * ``months_used`` / ``months_considered`` -- how many months counted out
      of how many were looked at, so the UI can say "Estimado con N meses";
    * ``unconverted_transactions`` -- unconverted rows across ALL the
      considered months (skipped ones included), so they are reported instead
      of vanishing;
    * ``avg_spending_cents`` -- mean monthly ``spending_cents`` (savings
      excluded): the FIRE baseline;
    * ``avg_necesidad_cents`` -- mean monthly ``necesidad`` bucket: the
      emergency-fund baseline (essential expenses);
    * ``avg_income_cents`` -- mean monthly income: the forecast's baseline.

    All averages are 0 when ``months_used`` is 0. They are rounded half up in
    integer cents.
    """
    used = [
        summary
        for summary in trailing_summaries
        if summary["converted_transactions"] >= MIN_TRANSACTIONS_PER_TRAILING_MONTH
    ]

    def average(values: list[int]) -> int:
        return _round_half_up_div(sum(values), len(values)) if values else 0

    return {
        "months_used": len(used),
        "months_considered": len(trailing_summaries),
        "unconverted_transactions": sum(
            summary["unconverted_transactions"] for summary in trailing_summaries
        ),
        "avg_spending_cents": average([summary["spending_cents"] for summary in used]),
        "avg_necesidad_cents": average([summary["buckets"]["necesidad"]["actual_cents"] for summary in used]),
        "avg_income_cents": average([summary["income_cents"] for summary in used]),
    }


def compute_emergency_fund_status(
    liquid_net_worth_cents: int, avg_monthly_fixed_expense_cents: int
) -> dict[str, Any]:
    """The book's 3-6 month cash-cushion rule. When there's no expense
    baseline yet (a brand-new user), ``months_covered`` is ``None`` rather
    than raising ``ZeroDivisionError``; ``status`` conservatively reports
    "below" in that case since coverage can't be verified.

    The baseline is the trailing monthly average of ESSENTIAL expenses (the
    ``necesidad`` bucket): a cushion has to cover what cannot be cut, not
    the discretionary spending."""
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
    zero for ``progress_pct``.

    The annual baseline is 12 x the trailing average monthly SPENDING
    (``spending_cents``, savings excluded): money moved into savings is not
    a cost of living that the portfolio has to cover."""
    if avg_annual_expense_cents <= 0:
        return {"target_cents": 0, "progress_pct": None}

    target_cents = avg_annual_expense_cents * 25
    progress_pct = net_worth_cents / target_cents * 100
    return {"target_cents": target_cents, "progress_pct": progress_pct}


def compute_investable_surplus(monthly_summary: dict[str, Any], emergency_fund_status: dict[str, Any]) -> dict[str, Any]:
    """What the month left unspent, and how much of it is free to invest.

    Two separate figures, so the UI can tell the truth about each:

    * ``available_cents`` -- UNGATED: income minus ``spending_cents`` (decision
      D3: everything except the savings bucket). It is what was left over,
      whatever the emergency fund looks like, and it may be negative;
      ``shortfall_cents`` is the amount by which spending exceeded income
      (``>= 0``, zero when nothing was overspent).
    * ``surplus_cents`` -- GATED: the book's own stated priority is to fully
      fund the emergency cushion first, so it is 0 with ``reason``
      ``building_emergency_fund`` while coverage is below ``target_min_months``
      or unknown (a brand-new user). Once covered (exactly
      ``target_min_months`` counts as covered -- the boundary is inclusive) it
      is ``max(available_cents, 0)`` with ``reason``
      ``emergency_fund_covered``. ``reason`` therefore only describes the
      emergency-fund gate; a month that overspent has ``shortfall_cents > 0``
      under either reason and the caller should say so first.

    ``income_cents``, ``spending_cents`` and ``saved_cents`` are echoed so a
    caller can tell "nothing was logged this month" from "everything was
    spent" from "only savings were logged" (which is neither income nor
    spending, so the first two are both zero).
    """
    income_cents = monthly_summary["income_cents"]
    spending_cents = monthly_summary["spending_cents"]
    saved_cents = monthly_summary["saved_cents"]
    available_cents = income_cents - spending_cents
    shortfall_cents = max(-available_cents, 0)

    months_covered = emergency_fund_status.get("months_covered")
    target_min_months = emergency_fund_status.get("target_min_months", 3)
    if months_covered is None or months_covered < target_min_months:
        surplus_cents, reason = 0, "building_emergency_fund"
    else:
        surplus_cents, reason = max(available_cents, 0), "emergency_fund_covered"

    return {
        "surplus_cents": surplus_cents,
        "reason": reason,
        "available_cents": available_cents,
        "shortfall_cents": shortfall_cents,
        "income_cents": income_cents,
        "spending_cents": spending_cents,
        "saved_cents": saved_cents,
    }


def annualize_recurring_bill_amount(amount_cents: int, frequency: str) -> int:
    """Naive annualization: occurrences/year times amount, ignoring calendar
    drift (e.g. 52 weeks/year isn't exactly a calendar year)."""
    return amount_cents * FREQUENCY_OCCURRENCES_PER_YEAR[frequency]


def compute_subscription_total(recurring_bills: list[dict[str, Any]]) -> dict[str, Any]:
    """Sums annualized cost across ACTIVE bills only -- a cancelled
    (inactive) subscription shouldn't inflate the total.

    Base currency only: bills are base-currency-only in v1 (the API enforces
    it), so a bill in another currency can only be a legacy row. It is left
    out of the total and counted in ``unconverted_bills`` rather than being
    added at face value."""
    bills: list[dict[str, Any]] = []
    annual_total_cents = 0
    unconverted_bills = 0
    for bill in recurring_bills:
        if not bill.get("is_active", True):
            continue
        base_cents = base_amount_cents(bill)
        if base_cents is None:
            unconverted_bills += 1
            continue
        annual_cents = annualize_recurring_bill_amount(base_cents, bill["frequency"])
        annual_total_cents += annual_cents
        bills.append({"name": bill["name"], "annual_cents": annual_cents})

    return {
        "annual_total_cents": annual_total_cents,
        "monthly_average_cents": annual_total_cents // 12,
        "bills": bills,
        "unconverted_bills": unconverted_bills,
    }


def _as_date(value: date | str) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _round_half_up_div(numerator: int, denominator: int) -> int:
    """``numerator / denominator`` rounded half up, in integers only -- money
    never goes through a float on its way to a cents figure."""
    return (2 * numerator + denominator) // (2 * denominator)


def compute_cash_flow_forecast(
    pending_bill_payments: list[dict[str, Any]],
    avg_monthly_income_cents: int | None,
    horizon_days: int = 30,
    *,
    today: date,
) -> dict[str, Any]:
    """A NAIVE LINEAR projection, not a real forecasting model: income is
    smeared evenly across the horizon (``avg_monthly_income_cents *
    horizon_days / 30``, rounded half up to whole cents), and only bills
    count as committed outflow -- discretionary spending is not projected at
    all, by design (this is a bills-committed view, not a full budget
    forecast). ``today`` is injected (the router passes the machine-local
    date) so the function has no clock and is testable.

    ``avg_monthly_income_cents`` is ``None`` when there is no income history
    to estimate from. The bills side does not depend on it, so it is still
    computed, but the income projection is then unknown, not zero:
    ``expected_income_cents`` and ``projected_net_cents`` are ``None`` and
    ``income_data_sufficient`` is false -- inventing a $0 income would report
    a made-up shortfall.

    The window is INCLUSIVE at both ends (decision D15): ``today`` through
    ``today + horizon_days``, which for the default 30 is 31 calendar days of
    bills set against income scaled 30/30. That one-day asymmetry is
    accepted: a bill due exactly at the horizon end is owed within the
    period, and the income scale stays the plain "monthly average".

    Each entry of ``pending_bill_payments`` is one active bill's NEXT pending
    occurrence: ``due_date``, ``amount_cents``, plus the bill's
    ``anchor_due_date`` and ``frequency`` (needed to expand later
    occurrences). Every amount (and the income average) must already be in the
    base currency; the caller converts with ``base_amount_cents`` and drops
    what it cannot convert.

    Committed outflow, per bill, up to ``today + horizon_days`` (inclusive):

    * a pending occurrence already due before ``today`` is OVERDUE: it is still
      owed, so it counts once, and is also broken out as ``overdue_bills_*``;
    * a pending occurrence due inside the horizon counts once;
    * every LATER occurrence of the bill's schedule that falls inside the
      horizon counts too (a weekly bill contributes four or five payments in
      30 days, a monthly one usually one, an annual one usually none).

    ``committed_bills_cents`` includes the overdue amount; the ``overdue_*``
    fields are a breakdown, not an extra charge. Occurrences that were missed
    between an overdue row and ``today`` have no row and are not projected:
    the overdue row is what the user has to settle first.
    """
    horizon_end = today + timedelta(days=horizon_days)
    expected_income_cents = (
        None
        if avg_monthly_income_cents is None
        else _round_half_up_div(avg_monthly_income_cents * horizon_days, 30)
    )

    overdue_bills_cents = 0
    overdue_bills_count = 0
    upcoming_bills_cents = 0
    for payment in pending_bill_payments:
        due_date = _as_date(payment["due_date"])
        if due_date > horizon_end:
            continue

        amount_cents = payment["amount_cents"]
        if due_date < today:
            overdue_bills_cents += amount_cents
            overdue_bills_count += 1
        else:
            upcoming_bills_cents += amount_cents

        later_occurrences = occurrences_between(
            _as_date(payment["anchor_due_date"]),
            payment["frequency"],
            max(today, due_date + timedelta(days=1)),
            horizon_end,
        )
        upcoming_bills_cents += amount_cents * len(later_occurrences)

    committed_bills_cents = overdue_bills_cents + upcoming_bills_cents
    return {
        "horizon_days": horizon_days,
        "income_data_sufficient": expected_income_cents is not None,
        "expected_income_cents": expected_income_cents,
        "committed_bills_cents": committed_bills_cents,
        "overdue_bills_cents": overdue_bills_cents,
        "overdue_bills_count": overdue_bills_count,
        "projected_net_cents": (
            None if expected_income_cents is None else expected_income_cents - committed_bills_cents
        ),
    }


def compute_category_trend(current_month_cents: int, trailing_avg_cents: int) -> dict[str, Any]:
    """``is_anomaly`` flags a >30% spike over the trailing average -- a
    fixed threshold, not a statistical outlier test. Good enough for a
    personal dashboard's yellow-flag, not a monitoring system."""
    if trailing_avg_cents <= 0:
        return {"delta_pct": None, "is_anomaly": False}

    delta_pct = (current_month_cents - trailing_avg_cents) / trailing_avg_cents * 100
    return {"delta_pct": delta_pct, "is_anomaly": delta_pct > 30}
