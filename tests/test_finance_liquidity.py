"""Pure checks for ``brain/finance/liquidity.py``: which assets are liquid by
default, and the liquidity totals of a snapshot."""

from __future__ import annotations

from typing import Any

import pytest

from brain.finance.liquidity import (
    ILLIQUID_ITEM_TYPES,
    LIQUID_ITEM_TYPES,
    default_is_liquid,
    is_liquidity_classified,
    summarize_net_worth_liquidity,
)


def _asset(label: str, cents: int, is_liquid: bool | None, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "is_asset": True,
        "label": label,
        "item_type": "other",
        "amount_cents": cents,
        "currency": "MXN",
        "amount_base_cents": cents,
        "is_liquid": is_liquid,
    }
    item.update(overrides)
    return item


def _liability(label: str, cents: int) -> dict[str, Any]:
    return {
        "is_asset": False,
        "label": label,
        "item_type": "credit_card",
        "amount_cents": cents,
        "currency": "MXN",
        "amount_base_cents": cents,
        "is_liquid": None,
    }


# -- default_is_liquid ----------------------------------------------------------------


@pytest.mark.parametrize("item_type", sorted(LIQUID_ITEM_TYPES))
def test_a_cash_like_asset_type_defaults_to_liquid(item_type: str) -> None:
    assert default_is_liquid(item_type, is_asset=True) is True


@pytest.mark.parametrize("item_type", sorted(ILLIQUID_ITEM_TYPES))
def test_a_clearly_illiquid_asset_type_defaults_to_not_liquid(item_type: str) -> None:
    assert default_is_liquid(item_type, is_asset=True) is False


@pytest.mark.parametrize("item_type", ["other", "equities", "fixed_income", "cetes", "", None])
def test_any_other_asset_type_stays_unclassified_instead_of_being_guessed(item_type: str | None) -> None:
    assert default_is_liquid(item_type, is_asset=True) is None


@pytest.mark.parametrize("item_type", ["  Cash ", "EFECTIVO", "Savings"])
def test_the_default_ignores_case_and_surrounding_spaces_because_item_type_is_free_text(item_type: str) -> None:
    assert default_is_liquid(item_type, is_asset=True) is True


@pytest.mark.parametrize("item_type", ["cash", "real_estate", "credit_card", "other"])
def test_a_liability_is_never_classified(item_type: str) -> None:
    assert default_is_liquid(item_type, is_asset=False) is None


def test_the_liquid_and_illiquid_lists_do_not_overlap() -> None:
    assert LIQUID_ITEM_TYPES.isdisjoint(ILLIQUID_ITEM_TYPES)


# -- summarize_net_worth_liquidity ----------------------------------------------------


def test_liquid_assets_count_only_the_assets_flagged_liquid() -> None:
    items = [
        _asset("Efectivo", 700_000, True),
        _asset("Casa", 20_000_000, False),
        _asset("Cuenta sin revisar", 50_000, None),
    ]

    summary = summarize_net_worth_liquidity(items, flags_available=True)

    assert summary == {
        "liquid_assets_cents": 700_000,
        "liquid_items_count": 1,
        "unclassified_items_count": 1,
        "liquidity_flags_available": True,
    }


def test_liabilities_are_not_subtracted_from_liquid_assets() -> None:
    items = [_asset("Efectivo", 700_000, True), _liability("Tarjeta", 500_000), _liability("Hipoteca", 9_000_000)]

    summary = summarize_net_worth_liquidity(items, flags_available=True)

    assert summary["liquid_assets_cents"] == 700_000
    # A liability is neither liquid nor unclassified: it is outside the classification.
    assert summary["liquid_items_count"] == 1
    assert summary["unclassified_items_count"] == 0


def test_liquid_assets_are_summed_in_base_currency_not_face_value() -> None:
    usd = _asset("Dolares", 10_000, True, currency="USD", amount_base_cents=175_000)
    items = [usd, _asset("Efectivo", 100_000, True)]

    assert summarize_net_worth_liquidity(items, flags_available=True)["liquid_assets_cents"] == 275_000


def test_a_liquid_foreign_asset_without_a_base_amount_contributes_nothing_but_is_still_counted() -> None:
    legacy = _asset("Dolares", 10_000, True, currency="USD", amount_base_cents=None)

    summary = summarize_net_worth_liquidity([legacy, _asset("Efectivo", 100_000, True)], flags_available=True)

    assert summary["liquid_assets_cents"] == 100_000
    assert summary["liquid_items_count"] == 2


def test_no_flags_in_the_database_means_unknown_liquid_assets_not_zero() -> None:
    # A database without the column returns items with no `is_liquid` key at all.
    items = [
        {"is_asset": True, "label": "Efectivo", "amount_cents": 700_000, "currency": "MXN", "amount_base_cents": 700_000},
        _liability("Tarjeta", 10_000),
    ]

    summary = summarize_net_worth_liquidity(items, flags_available=False)

    assert summary == {
        "liquid_assets_cents": None,
        "liquid_items_count": 0,
        "unclassified_items_count": 1,
        "liquidity_flags_available": False,
    }


def test_a_snapshot_without_assets_has_zero_liquid_assets_and_nothing_unclassified() -> None:
    summary = summarize_net_worth_liquidity([_liability("Tarjeta", 10_000)], flags_available=True)

    assert (summary["liquid_assets_cents"], summary["liquid_items_count"], summary["unclassified_items_count"]) == (0, 0, 0)


# -- is_liquidity_classified ----------------------------------------------------------


def _summary(*, available: bool, liquid: int, unclassified: int) -> dict[str, Any]:
    return {
        "liquid_assets_cents": 0,
        "liquid_items_count": liquid,
        "unclassified_items_count": unclassified,
        "liquidity_flags_available": available,
    }


@pytest.mark.parametrize(
    ("available", "liquid", "unclassified", "expected"),
    [
        (True, 1, 0, True),  # one liquid asset, everything classified
        (True, 1, 2, True),  # at least one liquid asset is enough to measure a cushion
        (True, 0, 0, True),  # every asset classified, none liquid: a real "zero"
        (True, 0, 1, False),  # nothing liquid and something still unclassified: unknown
        (False, 0, 3, False),  # the database cannot store flags
        (False, 2, 0, False),
    ],
)
def test_liquidity_is_classified_when_a_cushion_can_be_measured(
    available: bool, liquid: int, unclassified: int, expected: bool
) -> None:
    assert is_liquidity_classified(_summary(available=available, liquid=liquid, unclassified=unclassified)) is expected
