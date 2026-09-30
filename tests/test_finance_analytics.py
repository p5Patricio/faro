from __future__ import annotations

from datetime import date

import pytest

from brain.finance.analytics import (
    annualize_recurring_bill_amount,
    compute_cash_flow_forecast,
    compute_category_trend,
    compute_emergency_fund_status,
    compute_fire_number,
    compute_investable_surplus,
    compute_monthly_summary,
    compute_subscription_total,
)

CATEGORIES = [
    {"id": "cat-vivienda", "slug": "vivienda", "name": "Vivienda", "kind": "expense", "budget_bucket": "necesidad"},
    {"id": "cat-entretenimiento", "slug": "entretenimiento", "name": "Entretenimiento", "kind": "expense", "budget_bucket": "deseo"},
    {"id": "cat-ahorro", "slug": "ahorro-inversion", "name": "Ahorro e Inversion", "kind": "expense", "budget_bucket": "ahorro_inversion"},
    {"id": "cat-sueldo", "slug": "sueldo", "name": "Sueldo", "kind": "income", "budget_bucket": None},
]


# -- compute_monthly_summary --------------------------------------------------


def test_compute_monthly_summary_buckets_expenses_and_computes_savings_rate() -> None:
    transactions = [
        {"kind": "income", "amount_cents": 100_000, "currency": "MXN", "category_id": "cat-sueldo"},
        {"kind": "expense", "amount_cents": 40_000, "currency": "MXN", "category_id": "cat-vivienda"},
        {"kind": "expense", "amount_cents": 10_000, "currency": "MXN", "category_id": "cat-entretenimiento"},
        {"kind": "expense", "amount_cents": 20_000, "currency": "MXN", "category_id": "cat-ahorro"},
        # A transfer must be ignored entirely (neither income nor expense).
        {"kind": "transfer", "amount_cents": 5_000, "currency": "MXN", "category_id": None},
    ]

    summary = compute_monthly_summary(transactions, CATEGORIES)

    assert summary["income_cents"] == 100_000
    assert summary["expense_cents"] == 70_000
    assert summary["net_cents"] == 30_000
    assert summary["buckets"]["necesidad"] == {"actual_cents": 40_000, "target_cents": 50_000}
    assert summary["buckets"]["deseo"] == {"actual_cents": 10_000, "target_cents": 30_000}
    assert summary["buckets"]["ahorro_inversion"] == {"actual_cents": 20_000, "target_cents": 20_000}
    assert summary["savings_rate_pct"] == 20.0
    assert summary["unconverted_transactions"] == 0


def test_compute_monthly_summary_converts_mixed_currencies_to_base_instead_of_adding_raw_cents() -> None:
    """Regression for the multi-currency bug: USD 50.00 booked at 17.5 plus
    MXN 1000.00 is MXN 1,875.00 (187,500 cents), NOT 1,050.00 of raw cents."""
    transactions = [
        {
            "kind": "expense",
            "amount_cents": 5_000,
            "currency": "USD",
            "fx_rate_to_base": 17.5,
            "amount_base_cents": 87_500,
            "category_id": "cat-vivienda",
        },
        {"kind": "expense", "amount_cents": 100_000, "currency": "MXN", "category_id": "cat-vivienda"},
    ]

    summary = compute_monthly_summary(transactions, CATEGORIES)

    assert summary["expense_cents"] == 187_500
    assert summary["buckets"]["necesidad"]["actual_cents"] == 187_500
    assert summary["unconverted_transactions"] == 0


def test_compute_monthly_summary_excludes_and_counts_rows_that_cannot_be_converted() -> None:
    transactions = [
        {"kind": "income", "amount_cents": 200_000, "currency": "MXN", "amount_base_cents": None, "category_id": "cat-sueldo"},
        # Base currency with a NULL base column (written before base amounts
        # existed) still counts as its own base amount.
        {"kind": "expense", "amount_cents": 30_000, "currency": "MXN", "amount_base_cents": None, "category_id": "cat-vivienda"},
        # Foreign currency with no base amount: excluded from every total, counted.
        {"kind": "expense", "amount_cents": 9_999, "currency": "USD", "amount_base_cents": None, "category_id": "cat-vivienda"},
        {"kind": "income", "amount_cents": 8_888, "currency": "CAD", "category_id": "cat-sueldo"},
        # A transfer never contributes, so an unconvertible one is not "lost" money.
        {"kind": "transfer", "amount_cents": 7_777, "currency": "USD", "category_id": None},
    ]

    summary = compute_monthly_summary(transactions, CATEGORIES)

    assert summary["income_cents"] == 200_000
    assert summary["expense_cents"] == 30_000
    assert summary["unconverted_transactions"] == 2


def test_compute_monthly_summary_zero_income_gives_zero_savings_rate_and_targets() -> None:
    summary = compute_monthly_summary([], CATEGORIES)

    assert summary["income_cents"] == 0
    assert summary["expense_cents"] == 0
    assert summary["savings_rate_pct"] == 0.0
    assert summary["buckets"]["necesidad"]["target_cents"] == 0


# -- compute_emergency_fund_status --------------------------------------------


def test_compute_emergency_fund_status_reports_months_covered_and_status() -> None:
    below = compute_emergency_fund_status(liquid_net_worth_cents=100_000, avg_monthly_fixed_expense_cents=100_000)
    assert below["months_covered"] == 1.0
    assert below["status"] == "below"

    within = compute_emergency_fund_status(liquid_net_worth_cents=400_000, avg_monthly_fixed_expense_cents=100_000)
    assert within["months_covered"] == 4.0
    assert within["status"] == "within"

    above = compute_emergency_fund_status(liquid_net_worth_cents=700_000, avg_monthly_fixed_expense_cents=100_000)
    assert above["months_covered"] == 7.0
    assert above["status"] == "above"


def test_compute_emergency_fund_status_guards_zero_expense_baseline() -> None:
    result = compute_emergency_fund_status(liquid_net_worth_cents=500_000, avg_monthly_fixed_expense_cents=0)

    assert result["months_covered"] is None
    assert result["status"] == "below"
    assert result["target_min_months"] == 3
    assert result["target_max_months"] == 6


def test_compute_emergency_fund_status_boundary_exactly_three_months_is_within() -> None:
    result = compute_emergency_fund_status(liquid_net_worth_cents=300_000, avg_monthly_fixed_expense_cents=100_000)

    assert result["months_covered"] == 3.0
    assert result["status"] == "within"


# -- compute_fire_number -------------------------------------------------


def test_compute_fire_number_targets_25x_annual_expense() -> None:
    result = compute_fire_number(net_worth_cents=1_250_000, avg_annual_expense_cents=1_200_000)

    assert result["target_cents"] == 30_000_000
    assert round(result["progress_pct"], 4) == round(1_250_000 / 30_000_000 * 100, 4)


def test_compute_fire_number_guards_zero_annual_expense() -> None:
    result = compute_fire_number(net_worth_cents=1_000_000, avg_annual_expense_cents=0)

    assert result == {"target_cents": 0, "progress_pct": None}


# -- compute_investable_surplus ------------------------------------------


def test_compute_investable_surplus_zero_when_building_emergency_fund() -> None:
    monthly_summary = {"buckets": {"ahorro_inversion": {"actual_cents": 50_000}}}
    emergency_fund_status = {"months_covered": 1.5, "target_min_months": 3}

    result = compute_investable_surplus(monthly_summary, emergency_fund_status)

    assert result == {"surplus_cents": 0, "reason": "building_emergency_fund"}


def test_compute_investable_surplus_none_months_covered_is_treated_as_building() -> None:
    monthly_summary = {"buckets": {"ahorro_inversion": {"actual_cents": 50_000}}}
    emergency_fund_status = {"months_covered": None, "target_min_months": 3}

    result = compute_investable_surplus(monthly_summary, emergency_fund_status)

    assert result == {"surplus_cents": 0, "reason": "building_emergency_fund"}


def test_compute_investable_surplus_boundary_exactly_target_months_counts_as_covered() -> None:
    monthly_summary = {"buckets": {"ahorro_inversion": {"actual_cents": 50_000}}}
    emergency_fund_status = {"months_covered": 3.0, "target_min_months": 3}

    result = compute_investable_surplus(monthly_summary, emergency_fund_status)

    assert result == {"surplus_cents": 50_000, "reason": "emergency_fund_covered"}


# -- annualize_recurring_bill_amount / compute_subscription_total ------------


def test_annualize_recurring_bill_amount_applies_occurrences_per_year() -> None:
    assert annualize_recurring_bill_amount(10_000, "monthly") == 120_000
    assert annualize_recurring_bill_amount(10_000, "annual") == 10_000
    assert annualize_recurring_bill_amount(10_000, "weekly") == 520_000


def test_compute_subscription_total_excludes_inactive_bills() -> None:
    bills = [
        {"name": "Netflix", "amount_cents": 20_000, "currency": "MXN", "frequency": "monthly", "is_active": True},
        {"name": "Gimnasio", "amount_cents": 60_000, "currency": "MXN", "frequency": "annual", "is_active": True},
        {"name": "Cancelado", "amount_cents": 99_999, "currency": "MXN", "frequency": "monthly", "is_active": False},
    ]

    result = compute_subscription_total(bills)

    assert result["annual_total_cents"] == 20_000 * 12 + 60_000
    assert result["monthly_average_cents"] == result["annual_total_cents"] // 12
    assert {b["name"] for b in result["bills"]} == {"Netflix", "Gimnasio"}


def test_compute_subscription_total_leaves_out_and_counts_non_base_bills() -> None:
    bills = [
        {"name": "Netflix", "amount_cents": 20_000, "currency": "MXN", "frequency": "monthly", "is_active": True},
        # A legacy USD bill has no base amount: adding its 999 cents at face
        # value would treat dollars as pesos.
        {"name": "iCloud", "amount_cents": 999, "currency": "USD", "frequency": "monthly", "is_active": True},
        {"name": "Cancelado", "amount_cents": 500, "currency": "USD", "frequency": "monthly", "is_active": False},
    ]

    result = compute_subscription_total(bills)

    assert result["annual_total_cents"] == 20_000 * 12
    assert [b["name"] for b in result["bills"]] == ["Netflix"]
    # Inactive bills are ignored before conversion, so only iCloud is unconverted.
    assert result["unconverted_bills"] == 1


def test_compute_subscription_total_empty_list_is_all_zero() -> None:
    result = compute_subscription_total([])

    assert result == {"annual_total_cents": 0, "monthly_average_cents": 0, "bills": [], "unconverted_bills": 0}


# -- compute_cash_flow_forecast -------------------------------------------


TODAY = date(2026, 9, 29)  # a Tuesday; a 30-day horizon therefore ends on 2026-10-29


def _pending(due: date | str, amount_cents: int, *, anchor: date, frequency: str) -> dict[str, object]:
    """One active bill's next pending occurrence, as the router builds it."""
    return {"due_date": due, "amount_cents": amount_cents, "anchor_due_date": anchor, "frequency": frequency}


def test_compute_cash_flow_forecast_counts_only_bills_due_within_horizon() -> None:
    pending = [
        _pending("2026-10-04", 30_000, anchor=date(2025, 10, 4), frequency="annual"),
        # Outside the 30-day horizon.
        _pending("2026-11-13", 99_999, anchor=date(2026, 11, 13), frequency="annual"),
    ]

    result = compute_cash_flow_forecast(pending, avg_monthly_income_cents=300_000, horizon_days=30, today=TODAY)

    assert result["horizon_days"] == 30
    assert result["expected_income_cents"] == 300_000
    assert result["committed_bills_cents"] == 30_000
    assert result["overdue_bills_cents"] == 0
    assert result["overdue_bills_count"] == 0
    assert result["projected_net_cents"] == 270_000


def test_compute_cash_flow_forecast_handles_no_pending_bills() -> None:
    result = compute_cash_flow_forecast([], avg_monthly_income_cents=0, horizon_days=30, today=TODAY)

    assert result["committed_bills_cents"] == 0
    assert result["overdue_bills_cents"] == 0
    assert result["overdue_bills_count"] == 0
    assert result["expected_income_cents"] == 0
    assert result["projected_net_cents"] == 0


def test_compute_cash_flow_forecast_takes_today_as_a_required_keyword() -> None:
    with pytest.raises(TypeError):
        compute_cash_flow_forecast([], 0, 30)  # type: ignore[call-arg]


def test_compute_cash_flow_forecast_result_depends_on_the_injected_today_only() -> None:
    pending = [_pending("2026-10-05", 10_000, anchor=date(2026, 9, 5), frequency="monthly")]

    inside = compute_cash_flow_forecast(pending, 0, 30, today=date(2026, 9, 29))
    overdue = compute_cash_flow_forecast(pending, 0, 30, today=date(2026, 10, 20))
    outside = compute_cash_flow_forecast(pending, 0, 30, today=date(2026, 9, 1))

    assert (inside["committed_bills_cents"], inside["overdue_bills_cents"]) == (10_000, 0)
    # Due 15 days ago is overdue, and the next monthly occurrence (Nov 5) is in the window.
    assert (overdue["committed_bills_cents"], overdue["overdue_bills_cents"]) == (20_000, 10_000)
    # Sep 1 + 30 days ends Oct 1: the Oct 5 occurrence is past the horizon.
    assert (outside["committed_bills_cents"], outside["overdue_bills_cents"]) == (0, 0)


def test_compute_cash_flow_forecast_expands_a_weekly_bill_into_every_occurrence_in_the_horizon() -> None:
    five = [_pending("2026-09-30", 10_000, anchor=date(2026, 9, 2), frequency="weekly")]
    four = [_pending("2026-10-02", 10_000, anchor=date(2026, 9, 4), frequency="weekly")]

    # Sep 30, Oct 7, 14, 21, 28 -- the horizon end (Oct 29) is inclusive.
    assert compute_cash_flow_forecast(five, 0, 30, today=TODAY)["committed_bills_cents"] == 5 * 10_000
    # Oct 2, 9, 16, 23 -- the next one, Oct 30, is one day past the horizon.
    assert compute_cash_flow_forecast(four, 0, 30, today=TODAY)["committed_bills_cents"] == 4 * 10_000


def test_compute_cash_flow_forecast_expands_a_biweekly_bill() -> None:
    pending = [_pending("2026-10-01", 20_000, anchor=date(2026, 9, 3), frequency="biweekly")]

    # Oct 1, 15, 29.
    assert compute_cash_flow_forecast(pending, 0, 30, today=TODAY)["committed_bills_cents"] == 3 * 20_000


def test_compute_cash_flow_forecast_counts_a_monthly_bill_once_and_an_annual_bill_usually_zero() -> None:
    monthly = [_pending("2026-10-05", 30_000, anchor=date(2026, 1, 5), frequency="monthly")]
    annual_far = [_pending("2027-03-01", 60_000, anchor=date(2026, 3, 1), frequency="annual")]
    annual_near = [_pending("2026-10-20", 60_000, anchor=date(2025, 10, 20), frequency="annual")]

    assert compute_cash_flow_forecast(monthly, 0, 30, today=TODAY)["committed_bills_cents"] == 30_000
    assert compute_cash_flow_forecast(annual_far, 0, 30, today=TODAY)["committed_bills_cents"] == 0
    assert compute_cash_flow_forecast(annual_near, 0, 30, today=TODAY)["committed_bills_cents"] == 60_000


def test_compute_cash_flow_forecast_counts_an_overdue_payment_once_and_breaks_it_out() -> None:
    pending = [_pending("2026-09-15", 30_000, anchor=date(2026, 1, 15), frequency="monthly")]

    result = compute_cash_flow_forecast(pending, 300_000, 30, today=TODAY)

    # The overdue Sep 15 payment is owed (counted once) and the Oct 15 one is coming.
    assert result["overdue_bills_cents"] == 30_000
    assert result["overdue_bills_count"] == 1
    assert result["committed_bills_cents"] == 60_000
    assert result["projected_net_cents"] == 240_000


def test_compute_cash_flow_forecast_does_not_project_occurrences_missed_before_an_overdue_row() -> None:
    # Weekly, Thursdays. The row is Sep 17; Sep 24 was also missed but has no
    # row of its own, so only the overdue row plus Oct 1, 8, 15, 22, 29 count.
    pending = [_pending("2026-09-17", 10_000, anchor=date(2026, 9, 3), frequency="weekly")]

    result = compute_cash_flow_forecast(pending, 0, 30, today=TODAY)

    assert result["overdue_bills_count"] == 1
    assert result["overdue_bills_cents"] == 10_000
    assert result["committed_bills_cents"] == 6 * 10_000


def test_compute_cash_flow_forecast_window_boundaries() -> None:
    def committed(due: str) -> int:
        return compute_cash_flow_forecast(
            [_pending(due, 1_000, anchor=date.fromisoformat(due), frequency="annual")], 0, 30, today=TODAY
        )["committed_bills_cents"]

    assert committed("2026-09-28") == 1_000  # yesterday: overdue, still owed
    assert committed("2026-09-29") == 1_000  # today: due, not overdue
    assert committed("2026-10-29") == 1_000  # the horizon end is inclusive
    assert committed("2026-10-30") == 0  # one day beyond

    today_due = compute_cash_flow_forecast(
        [_pending("2026-09-29", 1_000, anchor=date(2026, 9, 29), frequency="annual")], 0, 30, today=TODAY
    )
    assert today_due["overdue_bills_count"] == 0


def test_compute_cash_flow_forecast_sums_several_bills_and_accepts_date_objects() -> None:
    pending = [
        _pending(date(2026, 10, 1), 10_000, anchor=date(2026, 9, 3), frequency="weekly"),
        _pending("2026-10-05", 30_000, anchor=date(2026, 1, 5), frequency="monthly"),
    ]

    result = compute_cash_flow_forecast(pending, 500_000, 30, today=TODAY)

    assert result["committed_bills_cents"] == 5 * 10_000 + 30_000
    assert result["projected_net_cents"] == 500_000 - 80_000


@pytest.mark.parametrize(
    ("avg_income_cents", "horizon_days", "expected_cents"),
    [
        (100_001, 30, 100_001),
        (100_001, 15, 50_001),  # 50,000.5 rounds half up
        (1, 15, 1),  # 0.5
        (1, 14, 0),  # 0.466...
        (3, 10, 1),  # 1.0
        (7, 10, 2),  # 2.33...
        (0, 30, 0),
    ],
)
def test_compute_cash_flow_forecast_income_projection_is_whole_cents_rounded_half_up(
    avg_income_cents: int, horizon_days: int, expected_cents: int
) -> None:
    result = compute_cash_flow_forecast([], avg_income_cents, horizon_days, today=TODAY)

    assert result["expected_income_cents"] == expected_cents


def test_compute_cash_flow_forecast_returns_integer_cents_only() -> None:
    pending = [_pending("2026-09-15", 33_333, anchor=date(2026, 1, 15), frequency="monthly")]

    result = compute_cash_flow_forecast(pending, 100_001, 45, today=TODAY)

    for key in (
        "horizon_days",
        "expected_income_cents",
        "committed_bills_cents",
        "overdue_bills_cents",
        "overdue_bills_count",
        "projected_net_cents",
    ):
        assert type(result[key]) is int, key
    assert result["projected_net_cents"] == result["expected_income_cents"] - result["committed_bills_cents"]


# -- compute_category_trend -----------------------------------------------


def test_compute_category_trend_flags_anomaly_above_30_percent() -> None:
    result = compute_category_trend(current_month_cents=14_000, trailing_avg_cents=10_000)

    assert round(result["delta_pct"], 2) == 40.0
    assert result["is_anomaly"] is True


def test_compute_category_trend_guards_zero_trailing_average() -> None:
    result = compute_category_trend(current_month_cents=5_000, trailing_avg_cents=0)

    assert result == {"delta_pct": None, "is_anomaly": False}


def test_compute_category_trend_boundary_exactly_30_percent_is_not_anomaly() -> None:
    result = compute_category_trend(current_month_cents=13_000, trailing_avg_cents=10_000)

    assert result["delta_pct"] == 30.0
    assert result["is_anomaly"] is False
