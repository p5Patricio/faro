from __future__ import annotations

from decimal import Decimal

import pytest

from brain.finance.currency import (
    BASE_CURRENCY,
    BIGINT_MAX,
    base_amount_cents,
    normalize_currency,
    resolve_fx_and_base,
    to_base_cents,
)


def test_base_currency_is_mxn() -> None:
    assert BASE_CURRENCY == "MXN"


def test_normalize_currency_trims_and_uppercases() -> None:
    assert normalize_currency(" usd ") == "USD"
    assert normalize_currency("MXN") == "MXN"
    assert normalize_currency(None) == ""


# -- to_base_cents ------------------------------------------------------------


def test_to_base_cents_base_currency_passes_through_and_ignores_any_rate() -> None:
    assert to_base_cents(123_45, "MXN", None) == 123_45
    assert to_base_cents(123_45, "mxn", 99.0) == 123_45


def test_to_base_cents_converts_foreign_currency_exactly() -> None:
    # USD 50.00 at 17.5 -> MXN 875.00
    assert to_base_cents(5_000, "USD", 17.5) == 87_500


def test_to_base_cents_rounds_half_up_not_bankers() -> None:
    # Exactly half a base cent: half-up rounds up, Python's round() would go to even.
    assert to_base_cents(1, "USD", 0.5) == 1  # 0.5 -> 1 (round() gives 0)
    assert to_base_cents(5, "USD", 0.5) == 3  # 2.5 -> 3 (round() gives 2)
    assert to_base_cents(10, "USD", 1.15) == 12  # 11.5 -> 12


def test_to_base_cents_converts_the_printed_rate_not_its_binary_float_expansion() -> None:
    # The trap: in binary floats 100 * 0.29 is 28.999999999999996, so a
    # float-based int() would give 28 cents. The rate goes through
    # Decimal(str(x)), so the 0.29 the user typed is what gets multiplied.
    assert int(100 * 0.29) == 28
    assert to_base_cents(100, "USD", 0.29) == 29


@pytest.mark.parametrize("rate", [None, 0, -1.0, float("nan"), float("inf"), 10**10, "abc"])
def test_to_base_cents_rejects_missing_or_invalid_rate_for_foreign_currency(rate: object) -> None:
    with pytest.raises(ValueError):
        to_base_cents(100, "USD", rate)  # type: ignore[arg-type]


def test_to_base_cents_rejects_rate_that_quantizes_to_zero() -> None:
    with pytest.raises(ValueError):
        to_base_cents(100, "USD", 1e-12)


def test_to_base_cents_accepts_the_largest_bigint_and_rejects_a_product_beyond_it() -> None:
    assert to_base_cents(BIGINT_MAX, "USD", 1) == BIGINT_MAX
    with pytest.raises(ValueError):
        to_base_cents(BIGINT_MAX, "USD", 2)
    with pytest.raises(ValueError):
        to_base_cents(BIGINT_MAX + 1, "MXN", None)


def test_to_base_cents_reports_decimal_overflow_as_value_error_not_invalid_operation() -> None:
    # 10**70 cents times a 10-digit rate needs 80 digits; the 60-digit context
    # makes quantize() raise decimal.InvalidOperation (an ArithmeticError).
    with pytest.raises(ValueError):
        to_base_cents(10**70, "USD", 9_999_999_999)


# -- resolve_fx_and_base --------------------------------------------------------


def test_resolve_fx_and_base_forces_rate_one_for_base_currency() -> None:
    assert resolve_fx_and_base(500, "MXN", 42.0) == (Decimal(1), 500)


def test_resolve_fx_and_base_returns_scale_normalized_rate_and_matching_base_amount() -> None:
    rate, base = resolve_fx_and_base(1_000, "USD", 17.123456789)

    assert rate == Decimal("17.12345679")  # 8 decimals, half-up: what numeric(18,8) stores
    assert base == to_base_cents(1_000, "USD", rate) == 17_123


def test_resolve_fx_and_base_requires_a_rate_for_foreign_currency() -> None:
    with pytest.raises(ValueError):
        resolve_fx_and_base(500, "USD", None)


# -- base_amount_cents ----------------------------------------------------------


def test_base_amount_cents_prefers_the_materialized_base_amount() -> None:
    row = {"amount_cents": 5_000, "currency": "USD", "amount_base_cents": 87_500}

    assert base_amount_cents(row) == 87_500


def test_base_amount_cents_uses_raw_amount_for_base_currency_row_with_null_base_column() -> None:
    assert base_amount_cents({"amount_cents": 100_000, "currency": "MXN", "amount_base_cents": None}) == 100_000
    assert base_amount_cents({"amount_cents": 100_000, "currency": "MXN"}) == 100_000
    assert base_amount_cents({"amount_cents": 100_000, "currency": "mxn "}) == 100_000


def test_base_amount_cents_is_none_for_foreign_currency_without_base_amount() -> None:
    assert base_amount_cents({"amount_cents": 5_000, "currency": "USD", "amount_base_cents": None}) is None
    assert base_amount_cents({"amount_cents": 5_000, "currency": "USD"}) is None


def test_base_amount_cents_is_none_when_currency_is_missing() -> None:
    assert base_amount_cents({"amount_cents": 5_000}) is None


def test_base_amount_cents_keeps_a_materialized_zero() -> None:
    # 0 is a valid converted amount; only None means "not converted".
    assert base_amount_cents({"amount_cents": 0, "currency": "USD", "amount_base_cents": 0}) == 0
