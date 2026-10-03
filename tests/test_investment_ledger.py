from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from brain.investments.ledger import LedgerError, compute_ledger, yearly_worksheet


def op(kind: str, day: date, **fields) -> dict:
    base = {
        "client_id": f"{kind}-{day}-{fields.get('amount_cents', 0)}",
        "account_id": "acc",
        "trade_date": day,
        "kind": kind,
        "symbol": "AAPL",
        "instrument_type": "accion_sic",
        "currency": "USD",
        "fx_rate_to_mxn": Decimal("17"),
    }
    return {**base, **fields}


def test_average_cost_includes_fees_and_converts_each_operation_at_its_own_rate() -> None:
    result = compute_ledger(
        [
            op("buy", date(2026, 1, 5), quantity=Decimal(10), amount_cents=100_000, fee_cents=1_000),
            op("buy", date(2026, 2, 5), quantity=Decimal(10), amount_cents=120_000, fx_rate_to_mxn=Decimal("18")),
            op("sell", date(2026, 3, 5), quantity=Decimal(5), amount_cents=70_000, fee_cents=500,
               fx_rate_to_mxn=Decimal("19.5")),
        ]
    )

    # Cost: 101,000 x 17 + 120,000 x 18 = 3,877,000; a quarter is sold.
    sale = result.sales[0]
    assert sale["cost_mxn_cents"] == 969_250
    assert sale["proceeds_mxn_cents"] == 1_355_250  # 69,500 x 19.5
    assert sale["gain_mxn_cents"] == 386_000
    assert result.positions[0]["quantity"] == "15"
    assert result.positions[0]["cost_basis_mxn_cents"] == 2_907_750
    assert result.positions[0]["average_cost_mxn_cents"] == "193850.0000"


def test_selling_more_than_is_held_is_refused() -> None:
    with pytest.raises(LedgerError):
        compute_ledger(
            [
                op("buy", date(2026, 1, 5), quantity=Decimal(1), amount_cents=100),
                op("sell", date(2026, 1, 6), quantity=Decimal(2), amount_cents=200),
            ]
        )


def test_split_multiplies_quantity_and_keeps_the_cost() -> None:
    result = compute_ledger(
        [
            op("buy", date(2026, 1, 5), quantity=Decimal(2), amount_cents=1_000, currency="MXN",
               fx_rate_to_mxn=Decimal(1)),
            op("split", date(2026, 6, 1), quantity=Decimal(10), currency="MXN", fx_rate_to_mxn=Decimal(1)),
        ]
    )

    assert result.positions[0]["quantity"] == "20"
    assert result.positions[0]["cost_basis_mxn_cents"] == 1_000


def test_capital_return_lowers_the_cost_and_reports_any_excess() -> None:
    mxn = {"currency": "MXN", "fx_rate_to_mxn": Decimal(1), "symbol": "FUNO11", "instrument_type": "fibra"}
    result = compute_ledger(
        [
            op("buy", date(2026, 1, 5), quantity=Decimal(100), amount_cents=5_000, **mxn),
            op("capital_return", date(2026, 2, 9), amount_cents=3_000, **mxn),
            op("capital_return", date(2026, 5, 9), amount_cents=3_000, **mxn),
            op("fibra_distribution", date(2026, 5, 9), amount_cents=1_000, tax_withheld_cents=300, **mxn),
        ]
    )

    assert result.positions[0]["cost_basis_mxn_cents"] == 0
    assert [row.get("excess_over_cost_mxn_cents") for row in result.income] == [0, 1_000, None]
    assert result.income[2]["tax_withheld_mxn_cents"] == 300


def test_worksheet_keeps_only_the_year_and_totals_by_account_and_concept() -> None:
    result = compute_ledger(
        [
            op("dividend", date(2025, 12, 30), amount_cents=1_000),
            op("dividend", date(2026, 3, 1), amount_cents=1_000, tax_withheld_cents=100),
            op("dividend", date(2026, 6, 1), amount_cents=2_000, tax_withheld_cents=200),
        ]
    )

    worksheet = yearly_worksheet(result, 2026)

    assert len(worksheet["income"]) == 2
    assert worksheet["summary"] == [
        {"account_id": "acc", "concept": "dividend", "amount_mxn_cents": 51_000, "tax_withheld_mxn_cents": 5_100}
    ]
