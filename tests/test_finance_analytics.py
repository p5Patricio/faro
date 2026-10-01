from __future__ import annotations

from datetime import date

import pytest

from brain.finance.analytics import (
    MIN_TRANSACTIONS_PER_TRAILING_MONTH,
    annualize_recurring_bill_amount,
    compute_cash_flow_forecast,
    compute_category_breakdown,
    compute_category_trend,
    compute_emergency_fund_status,
    compute_fire_number,
    compute_investable_surplus,
    compute_monthly_summary,
    compute_subscription_total,
    compute_trailing_baseline,
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
    # `expense_cents` is the raw total (savings included); spending is without the savings bucket.
    assert summary["expense_cents"] == 70_000
    assert summary["spending_cents"] == 50_000
    assert summary["saved_cents"] == 20_000
    # Saving is not spending, so it does not reduce `net_cents` (it used to: 30_000).
    assert summary["net_cents"] == 50_000
    assert summary["buckets"]["necesidad"] == {"actual_cents": 40_000, "target_cents": 50_000}
    assert summary["buckets"]["deseo"] == {"actual_cents": 10_000, "target_cents": 30_000}
    assert summary["buckets"]["ahorro_inversion"] == {"actual_cents": 20_000, "target_cents": 20_000}
    assert summary["buckets"]["sin_categoria"] == {"actual_cents": 0}
    assert summary["savings_rate_pct"] == 20.0
    assert summary["converted_transactions"] == 4
    assert summary["unconverted_transactions"] == 0


def test_compute_monthly_summary_saving_does_not_reduce_net() -> None:
    """A month of pure saving must not read as a loss: the money was moved,
    not spent, so nothing is missing from `net_cents`."""
    transactions = [
        {"kind": "income", "amount_cents": 100_000, "currency": "MXN", "category_id": "cat-sueldo"},
        {"kind": "expense", "amount_cents": 100_000, "currency": "MXN", "category_id": "cat-ahorro"},
    ]

    summary = compute_monthly_summary(transactions, CATEGORIES)

    assert summary["spending_cents"] == 0
    assert summary["saved_cents"] == 100_000
    assert summary["net_cents"] == 100_000
    assert summary["savings_rate_pct"] == 100.0


def test_compute_monthly_summary_puts_unbucketed_spend_in_sin_categoria_and_buckets_sum_to_expense() -> None:
    transactions = [
        {"kind": "income", "amount_cents": 200_000, "currency": "MXN", "category_id": "cat-sueldo"},
        {"kind": "expense", "amount_cents": 40_000, "currency": "MXN", "category_id": "cat-vivienda"},
        {"kind": "expense", "amount_cents": 20_000, "currency": "MXN", "category_id": "cat-ahorro"},
        # No category at all.
        {"kind": "expense", "amount_cents": 7_000, "currency": "MXN", "category_id": None},
        # A category id that is not among the active categories.
        {"kind": "expense", "amount_cents": 3_000, "currency": "MXN", "category_id": "cat-retired"},
        # A known category with no bucket (an income category booked on an expense).
        {"kind": "expense", "amount_cents": 500, "currency": "MXN", "category_id": "cat-sueldo"},
    ]

    summary = compute_monthly_summary(transactions, CATEGORIES)

    # Unclassified spend has an actual amount and NO target: the rule says nothing about it.
    assert summary["buckets"]["sin_categoria"] == {"actual_cents": 10_500}
    assert sum(bucket["actual_cents"] for bucket in summary["buckets"].values()) == summary["expense_cents"] == 70_500
    # It is spending (only the savings bucket is not), so it lowers what was left unspent.
    assert summary["spending_cents"] == 50_500
    assert summary["net_cents"] == 200_000 - 50_500


def test_compute_monthly_summary_counts_only_converted_income_and_expense_rows() -> None:
    transactions = [
        {"kind": "income", "amount_cents": 1_000, "currency": "MXN", "category_id": "cat-sueldo"},
        {"kind": "expense", "amount_cents": 1_000, "currency": "MXN", "category_id": "cat-vivienda"},
        {"kind": "expense", "amount_cents": 1_000, "currency": "USD", "amount_base_cents": None, "category_id": "cat-vivienda"},
        {"kind": "transfer", "amount_cents": 1_000, "currency": "MXN", "category_id": None},
    ]

    summary = compute_monthly_summary(transactions, CATEGORIES)

    assert summary["converted_transactions"] == 2
    assert summary["unconverted_transactions"] == 1


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
    assert summary["spending_cents"] == 0
    assert summary["saved_cents"] == 0
    assert summary["net_cents"] == 0
    assert summary["savings_rate_pct"] == 0.0
    assert summary["buckets"]["necesidad"]["target_cents"] == 0
    assert summary["buckets"]["sin_categoria"] == {"actual_cents": 0}
    assert summary["converted_transactions"] == 0


# -- compute_category_breakdown -------------------------------------------------

BREAKDOWN_CATEGORIES = [
    {**CATEGORIES[0], "emoji": "H"},
    {**CATEGORIES[1], "emoji": "E"},
    {**CATEGORIES[2], "emoji": "A"},
    {**CATEGORIES[3], "emoji": "S"},
]


def _expense(cents: int, category_id: str | None, **extra: object) -> dict[str, object]:
    return {"kind": "expense", "amount_cents": cents, "currency": "MXN", "category_id": category_id, **extra}


def test_category_breakdown_rows_sum_to_the_summary_expense_and_include_the_uncategorized_row() -> None:
    transactions = [
        _expense(40_000, "cat-vivienda"),
        _expense(15_000, "cat-vivienda"),
        _expense(10_000, "cat-entretenimiento"),
        _expense(20_000, "cat-ahorro"),
        _expense(7_000, None),
        _expense(3_000, "cat-retired"),
        # Not expenses, and not convertible: neither may show up in the breakdown.
        {"kind": "income", "amount_cents": 99_999, "currency": "MXN", "category_id": "cat-sueldo"},
        _expense(9_999, "cat-vivienda", currency="USD", amount_base_cents=None),
    ]

    breakdown = compute_category_breakdown(transactions, BREAKDOWN_CATEGORIES, {})
    summary = compute_monthly_summary(transactions, BREAKDOWN_CATEGORIES)

    assert sum(row["actual_cents"] for row in breakdown) == summary["expense_cents"] == 95_000
    assert [(row["category_name"], row["actual_cents"]) for row in breakdown] == [
        ("Vivienda", 55_000),
        ("Ahorro e Inversion", 20_000),
        ("Entretenimiento", 10_000),
        ("Sin categoría", 10_000),
    ]
    uncategorized = breakdown[-1]
    assert uncategorized["category_id"] is None
    assert uncategorized["bucket"] == "sin_categoria"
    assert uncategorized["budget_cents"] is None
    vivienda = breakdown[0]
    assert (vivienda["slug"], vivienda["emoji"], vivienda["bucket"]) == ("vivienda", "H", "necesidad")


def test_category_breakdown_attaches_budgets_and_keeps_a_budgeted_category_with_no_spend() -> None:
    transactions = [_expense(40_000, "cat-vivienda")]

    breakdown = compute_category_breakdown(
        transactions,
        BREAKDOWN_CATEGORIES,
        {"cat-vivienda": 50_000, "cat-entretenimiento": 30_000, "cat-retired": 1},
    )

    by_name = {row["category_name"]: row for row in breakdown}
    assert by_name["Vivienda"]["budget_cents"] == 50_000
    assert by_name["Vivienda"]["actual_cents"] == 40_000
    # A budget with nothing spent against it is still listed; a budget on a category that is not active is not.
    assert by_name["Entretenimiento"]["budget_cents"] == 30_000
    assert by_name["Entretenimiento"]["actual_cents"] == 0
    assert set(by_name) == {"Vivienda", "Entretenimiento"}


def test_category_breakdown_omits_the_uncategorized_row_when_nothing_is_uncategorized() -> None:
    breakdown = compute_category_breakdown([_expense(1_000, "cat-vivienda")], BREAKDOWN_CATEGORIES, {})

    assert [row["category_name"] for row in breakdown] == ["Vivienda"]
    assert compute_category_breakdown([], BREAKDOWN_CATEGORIES, {}) == []


def test_category_breakdown_labels_a_known_category_without_a_bucket_as_sin_categoria() -> None:
    breakdown = compute_category_breakdown([_expense(500, "cat-sueldo")], BREAKDOWN_CATEGORIES, {})

    assert [(row["category_name"], row["bucket"]) for row in breakdown] == [("Sueldo", "sin_categoria")]


# -- compute_trailing_baseline (coverage rule, decision D2) ---------------------


def _month_summary(
    *, transactions: int, spending: int = 0, necesidad: int = 0, income: int = 0, unconverted: int = 0
) -> dict[str, object]:
    """A month as `compute_monthly_summary` returns it, with only the fields the baseline reads."""
    return {
        "converted_transactions": transactions,
        "unconverted_transactions": unconverted,
        "spending_cents": spending,
        "income_cents": income,
        "buckets": {"necesidad": {"actual_cents": necesidad}},
    }


def test_the_coverage_rule_needs_at_least_five_converted_transactions() -> None:
    assert MIN_TRANSACTIONS_PER_TRAILING_MONTH == 5

    four = compute_trailing_baseline([_month_summary(transactions=4, spending=100_000)])
    five = compute_trailing_baseline([_month_summary(transactions=5, spending=100_000)])

    assert four["months_used"] == 0
    assert four["avg_spending_cents"] == 0
    assert five["months_used"] == 1
    assert five["avg_spending_cents"] == 100_000


def test_a_month_with_only_unconverted_or_no_rows_is_skipped_but_its_unconverted_rows_are_counted() -> None:
    months = [
        _month_summary(transactions=0, unconverted=6),  # nothing but unconverted rows
        _month_summary(transactions=0),  # empty
        _month_summary(transactions=8, spending=90_000, necesidad=60_000, income=200_000, unconverted=2),
    ]

    baseline = compute_trailing_baseline(months)

    assert baseline["months_used"] == 1
    assert baseline["months_considered"] == 3
    # The skipped months are not averaged in as zeros...
    assert baseline["avg_spending_cents"] == 90_000
    assert baseline["avg_necesidad_cents"] == 60_000
    assert baseline["avg_income_cents"] == 200_000
    # ...and the unconverted rows of every considered month are reported, not dropped.
    assert baseline["unconverted_transactions"] == 8


def test_baseline_averages_only_the_months_that_count() -> None:
    months = [
        _month_summary(transactions=5, spending=100_000, necesidad=40_000, income=300_000),
        _month_summary(transactions=3, spending=999_999, necesidad=999_999, income=999_999),
        _month_summary(transactions=6, spending=200_000, necesidad=60_000, income=100_000),
    ]

    baseline = compute_trailing_baseline(months)

    assert baseline["months_used"] == 2
    assert baseline["avg_spending_cents"] == 150_000
    assert baseline["avg_necesidad_cents"] == 50_000
    assert baseline["avg_income_cents"] == 200_000


def test_baseline_with_no_months_is_all_zero() -> None:
    assert compute_trailing_baseline([]) == {
        "months_used": 0,
        "months_considered": 0,
        "unconverted_transactions": 0,
        "avg_spending_cents": 0,
        "avg_necesidad_cents": 0,
        "avg_income_cents": 0,
    }


def test_baseline_averages_are_whole_cents_rounded_half_up() -> None:
    months = [
        _month_summary(transactions=5, spending=100_000),
        _month_summary(transactions=5, spending=100_001),
    ]

    assert compute_trailing_baseline(months)["avg_spending_cents"] == 100_001  # 100,000.5 rounds up


def test_the_fire_baseline_excludes_savings_and_the_emergency_baseline_is_essential_expenses() -> None:
    """End to end over the pure functions: two covered months in which the
    user also saved. FIRE is 25x (12 x average SPENDING) with savings left
    out; the emergency fund is measured against the necesidad average only."""
    months = [
        compute_monthly_summary(
            [
                {"kind": "income", "amount_cents": 300_000, "currency": "MXN", "category_id": "cat-sueldo"},
                _expense(100_000, "cat-vivienda"),
                _expense(50_000, "cat-entretenimiento"),
                _expense(80_000, "cat-ahorro"),  # saved, not spent
                _expense(10_000, None),
            ],
            CATEGORIES,
        )
        for _ in range(2)
    ]
    baseline = compute_trailing_baseline(months)

    assert baseline["months_used"] == 2
    # Spending = 100k + 50k + 10k uncategorized = 160k; the 80k saved is not in it.
    assert baseline["avg_spending_cents"] == 160_000
    assert baseline["avg_necesidad_cents"] == 100_000

    fire = compute_fire_number(net_worth_cents=48_000_000, avg_annual_expense_cents=baseline["avg_spending_cents"] * 12)
    assert fire["target_cents"] == 160_000 * 12 * 25 == 48_000_000
    assert fire["progress_pct"] == 100.0

    emergency = compute_emergency_fund_status(
        liquid_assets_cents=350_000, avg_monthly_fixed_expense_cents=baseline["avg_necesidad_cents"]
    )
    assert emergency["months_covered"] == 3.5
    assert emergency["status"] == "within"


# -- compute_emergency_fund_status --------------------------------------------


def test_compute_emergency_fund_status_reports_months_covered_and_status() -> None:
    below = compute_emergency_fund_status(liquid_assets_cents=100_000, avg_monthly_fixed_expense_cents=100_000)
    assert below["months_covered"] == 1.0
    assert below["status"] == "below"

    within = compute_emergency_fund_status(liquid_assets_cents=400_000, avg_monthly_fixed_expense_cents=100_000)
    assert within["months_covered"] == 4.0
    assert within["status"] == "within"

    above = compute_emergency_fund_status(liquid_assets_cents=700_000, avg_monthly_fixed_expense_cents=100_000)
    assert above["months_covered"] == 7.0
    assert above["status"] == "above"


def test_compute_emergency_fund_status_guards_zero_expense_baseline() -> None:
    result = compute_emergency_fund_status(liquid_assets_cents=500_000, avg_monthly_fixed_expense_cents=0)

    assert result["months_covered"] is None
    assert result["status"] == "below"
    assert result["target_min_months"] == 3
    assert result["target_max_months"] == 6


def test_compute_emergency_fund_status_boundary_exactly_three_months_is_within() -> None:
    result = compute_emergency_fund_status(liquid_assets_cents=300_000, avg_monthly_fixed_expense_cents=100_000)

    assert result["months_covered"] == 3.0
    assert result["status"] == "within"


def test_compute_emergency_fund_status_is_unclassified_not_below_when_no_asset_is_known_to_be_liquid() -> None:
    """Nothing was measured, so no coverage is claimed: no months and a status
    of its own, not the misleading "below" a $0 cushion would get."""
    result = compute_emergency_fund_status(
        liquid_assets_cents=0, avg_monthly_fixed_expense_cents=100_000, liquidity_classified=False
    )

    assert result == {
        "months_covered": None,
        "target_min_months": 3,
        "target_max_months": 6,
        "status": "unclassified",
    }


def test_compute_emergency_fund_status_unclassified_takes_precedence_over_a_missing_expense_baseline() -> None:
    result = compute_emergency_fund_status(
        liquid_assets_cents=0, avg_monthly_fixed_expense_cents=0, liquidity_classified=False
    )

    assert result["status"] == "unclassified"


def test_compute_emergency_fund_status_classified_zero_liquid_assets_is_zero_months_below() -> None:
    """The user said none of the assets is liquid: that is a measurement."""
    result = compute_emergency_fund_status(liquid_assets_cents=0, avg_monthly_fixed_expense_cents=100_000)

    assert result["months_covered"] == 0.0
    assert result["status"] == "below"


# -- compute_fire_number -------------------------------------------------


def test_compute_fire_number_targets_25x_annual_expense() -> None:
    result = compute_fire_number(net_worth_cents=1_250_000, avg_annual_expense_cents=1_200_000)

    assert result["target_cents"] == 30_000_000
    assert round(result["progress_pct"], 4) == round(1_250_000 / 30_000_000 * 100, 4)


def test_compute_fire_number_guards_zero_annual_expense() -> None:
    result = compute_fire_number(net_worth_cents=1_000_000, avg_annual_expense_cents=0)

    assert result == {"target_cents": 0, "progress_pct": None}


# -- compute_investable_surplus ------------------------------------------


def _income_and_spending(income_cents: int, spending_cents: int, saved_cents: int = 0) -> dict[str, int]:
    return {"income_cents": income_cents, "spending_cents": spending_cents, "saved_cents": saved_cents}


def test_compute_investable_surplus_zero_when_building_emergency_fund() -> None:
    emergency_fund_status = {"months_covered": 1.5, "target_min_months": 3}

    result = compute_investable_surplus(_income_and_spending(300_000, 250_000), emergency_fund_status)

    # The gate zeroes the investable figure, but what was left unspent is still reported truthfully.
    assert result == {
        "surplus_cents": 0,
        "reason": "building_emergency_fund",
        "available_cents": 50_000,
        "shortfall_cents": 0,
        "income_cents": 300_000,
        "spending_cents": 250_000,
        "saved_cents": 0,
    }


def test_compute_investable_surplus_none_months_covered_is_treated_as_building() -> None:
    emergency_fund_status = {"months_covered": None, "target_min_months": 3}

    result = compute_investable_surplus(_income_and_spending(300_000, 250_000), emergency_fund_status)

    assert result["surplus_cents"] == 0
    assert result["reason"] == "building_emergency_fund"
    assert result["available_cents"] == 50_000


def test_compute_investable_surplus_boundary_exactly_target_months_counts_as_covered() -> None:
    emergency_fund_status = {"months_covered": 3.0, "target_min_months": 3}

    result = compute_investable_surplus(_income_and_spending(300_000, 250_000), emergency_fund_status)

    # Decision D3: the surplus is income minus non-savings spending, not the savings bucket.
    assert result["surplus_cents"] == 50_000
    assert result["reason"] == "emergency_fund_covered"


def test_compute_investable_surplus_is_gated_with_its_own_reason_while_liquidity_is_unclassified() -> None:
    unclassified = compute_emergency_fund_status(
        liquid_assets_cents=0, avg_monthly_fixed_expense_cents=100_000, liquidity_classified=False
    )

    result = compute_investable_surplus(_income_and_spending(300_000, 250_000), unclassified)

    # Gated like "building", but the reason names what is actually missing; the unspent money is still reported.
    assert result["surplus_cents"] == 0
    assert result["reason"] == "liquidity_unclassified"
    assert result["available_cents"] == 50_000


def test_compute_investable_surplus_opens_the_gate_once_a_classified_fund_is_covered() -> None:
    covered = compute_emergency_fund_status(liquid_assets_cents=400_000, avg_monthly_fixed_expense_cents=100_000)

    result = compute_investable_surplus(_income_and_spending(300_000, 250_000), covered)

    assert (result["surplus_cents"], result["reason"]) == (50_000, "emergency_fund_covered")


def test_compute_investable_surplus_reports_a_shortfall_when_spending_exceeds_income() -> None:
    covered = {"months_covered": 4.0, "target_min_months": 3}
    building = {"months_covered": 1.0, "target_min_months": 3}

    over_covered = compute_investable_surplus(_income_and_spending(100_000, 130_000), covered)
    over_building = compute_investable_surplus(_income_and_spending(100_000, 130_000), building)

    for result in (over_covered, over_building):
        assert result["available_cents"] == -30_000
        assert result["shortfall_cents"] == 30_000
        assert result["surplus_cents"] == 0
    # `reason` describes only the emergency-fund gate; the shortfall is the fact to lead with.
    assert over_covered["reason"] == "emergency_fund_covered"
    assert over_building["reason"] == "building_emergency_fund"


def test_compute_investable_surplus_breaking_even_has_neither_surplus_nor_shortfall() -> None:
    result = compute_investable_surplus(_income_and_spending(100_000, 100_000), {"months_covered": 5.0})

    assert (result["available_cents"], result["shortfall_cents"], result["surplus_cents"]) == (0, 0, 0)


def test_compute_investable_surplus_does_not_treat_saving_as_spending() -> None:
    """Income 300k; spent 100k; saved 150k (the savings bucket is not in
    spending). What was left unspent is 200k, not 50k."""
    month = compute_monthly_summary(
        [
            {"kind": "income", "amount_cents": 300_000, "currency": "MXN", "category_id": "cat-sueldo"},
            _expense(100_000, "cat-vivienda"),
            _expense(150_000, "cat-ahorro"),
        ],
        CATEGORIES,
    )

    result = compute_investable_surplus(month, {"months_covered": 6.0, "target_min_months": 3})

    assert result["available_cents"] == 200_000
    assert result["surplus_cents"] == 200_000


def test_compute_investable_surplus_reports_no_activity_as_zero_income_and_spending() -> None:
    month = compute_monthly_summary([], CATEGORIES)

    result = compute_investable_surplus(month, {"months_covered": None, "target_min_months": 3})

    # The caller tells "nothing logged" (all zero) apart from "everything spent" through these.
    assert (result["income_cents"], result["spending_cents"], result["available_cents"]) == (0, 0, 0)
    assert result["saved_cents"] == 0


def test_compute_investable_surplus_tells_a_savings_only_month_from_an_empty_one() -> None:
    """Saving is neither income nor spending, so a month with only savings has
    income 0 and spending 0 like an empty one; `saved_cents` is what tells them apart."""
    month = compute_monthly_summary([_expense(80_000, "cat-ahorro")], CATEGORIES)

    result = compute_investable_surplus(month, {"months_covered": None, "target_min_months": 3})

    assert (result["income_cents"], result["spending_cents"]) == (0, 0)
    assert result["saved_cents"] == 80_000


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


def test_compute_cash_flow_forecast_without_income_history_still_counts_the_bills() -> None:
    pending = [
        _pending("2026-09-15", 30_000, anchor=date(2026, 1, 15), frequency="monthly"),
        _pending("2026-10-05", 10_000, anchor=date(2026, 1, 5), frequency="monthly"),
    ]

    result = compute_cash_flow_forecast(pending, None, 30, today=TODAY)

    # Unknown income is not zero income: no invented shortfall, but the bills are facts.
    assert result["income_data_sufficient"] is False
    assert result["expected_income_cents"] is None
    assert result["projected_net_cents"] is None
    assert result["overdue_bills_cents"] == 30_000
    assert result["overdue_bills_count"] == 1
    assert result["committed_bills_cents"] == 30_000 + 30_000 + 10_000


def test_compute_cash_flow_forecast_with_income_history_marks_the_income_projection_sufficient() -> None:
    result = compute_cash_flow_forecast([], 0, 30, today=TODAY)

    # A known income of zero is still known: sufficient, and the projection is a number.
    assert result["income_data_sufficient"] is True
    assert result["expected_income_cents"] == 0
    assert result["projected_net_cents"] == 0


def test_compute_cash_flow_forecast_window_is_31_calendar_days_against_income_scaled_30_over_30() -> None:
    """Decision D15, pinned so the documented asymmetry cannot drift: the
    window is inclusive at both ends, so a 30-day horizon spans 31 calendar
    days of bills, while the expected income is exactly the monthly average."""
    pending = [
        _pending("2026-09-29", 1_000, anchor=date(2026, 9, 29), frequency="annual"),  # first day of the window
        _pending("2026-10-29", 2_000, anchor=date(2026, 10, 29), frequency="annual"),  # last day of the window
        _pending("2026-10-30", 4_000, anchor=date(2026, 10, 30), frequency="annual"),  # one day past it
    ]

    result = compute_cash_flow_forecast(pending, 300_000, 30, today=TODAY)

    assert result["committed_bills_cents"] == 1_000 + 2_000
    assert result["expected_income_cents"] == 300_000
    assert (date(2026, 10, 29) - TODAY).days + 1 == 31


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
