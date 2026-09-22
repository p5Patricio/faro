from __future__ import annotations

from datetime import date, timedelta

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
        {"kind": "income", "amount_cents": 100_000, "category_id": "cat-sueldo"},
        {"kind": "expense", "amount_cents": 40_000, "category_id": "cat-vivienda"},
        {"kind": "expense", "amount_cents": 10_000, "category_id": "cat-entretenimiento"},
        {"kind": "expense", "amount_cents": 20_000, "category_id": "cat-ahorro"},
        # A transfer must be ignored entirely (neither income nor expense).
        {"kind": "transfer", "amount_cents": 5_000, "category_id": None},
    ]

    summary = compute_monthly_summary(transactions, CATEGORIES)

    assert summary["income_cents"] == 100_000
    assert summary["expense_cents"] == 70_000
    assert summary["net_cents"] == 30_000
    assert summary["buckets"]["necesidad"] == {"actual_cents": 40_000, "target_cents": 50_000}
    assert summary["buckets"]["deseo"] == {"actual_cents": 10_000, "target_cents": 30_000}
    assert summary["buckets"]["ahorro_inversion"] == {"actual_cents": 20_000, "target_cents": 20_000}
    assert summary["savings_rate_pct"] == 20.0


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
        {"name": "Netflix", "amount_cents": 20_000, "frequency": "monthly", "is_active": True},
        {"name": "Gimnasio", "amount_cents": 60_000, "frequency": "annual", "is_active": True},
        {"name": "Cancelado", "amount_cents": 99_999, "frequency": "monthly", "is_active": False},
    ]

    result = compute_subscription_total(bills)

    assert result["annual_total_cents"] == 20_000 * 12 + 60_000
    assert result["monthly_average_cents"] == result["annual_total_cents"] // 12
    assert {b["name"] for b in result["bills"]} == {"Netflix", "Gimnasio"}


def test_compute_subscription_total_empty_list_is_all_zero() -> None:
    result = compute_subscription_total([])

    assert result == {"annual_total_cents": 0, "monthly_average_cents": 0, "bills": []}


# -- compute_cash_flow_forecast -------------------------------------------


def test_compute_cash_flow_forecast_counts_only_bills_due_within_horizon() -> None:
    today = date.today()
    pending = [
        {"due_date": (today + timedelta(days=5)).isoformat(), "amount_cents": 30_000},
        {"due_date": (today + timedelta(days=45)).isoformat(), "amount_cents": 99_999},  # outside 30-day horizon
    ]

    result = compute_cash_flow_forecast(pending, avg_monthly_income_cents=300_000, horizon_days=30)

    assert result["horizon_days"] == 30
    assert result["expected_income_cents"] == 300_000
    assert result["committed_bills_cents"] == 30_000
    assert result["projected_net_cents"] == 270_000


def test_compute_cash_flow_forecast_handles_no_pending_bills() -> None:
    result = compute_cash_flow_forecast([], avg_monthly_income_cents=0, horizon_days=30)

    assert result["committed_bills_cents"] == 0
    assert result["expected_income_cents"] == 0
    assert result["projected_net_cents"] == 0


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
