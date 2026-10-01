"""Which net-worth assets count as liquid, and the liquidity totals of a
snapshot. Pure module (no I/O) shared by the repository, the router and the
analytics so the classification rules live in exactly one place.

"Liquid" here means money the user could put to work within days without
losing value: cash and bank savings/checking. It is the basis of the
emergency-fund figure. Liabilities are NOT subtracted from liquid assets: a
credit-card balance is a claim on future income, not a reduction of the
cushion that exists today (see ``summarize_net_worth_liquidity``).

The three-valued flag on an item (``finance_net_worth_items.is_liquid``):
``True`` counts, ``False`` was classified as not liquid, ``None`` has not been
classified yet. Keeping "not classified" apart from "not liquid" is the point
of the column being nullable: it lets the emergency fund say "you have not
told me yet" instead of reporting a coverage that was never measured.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain.finance.currency import base_amount_cents

# Asset types that are clearly cash-like. The same list backs the SQL backfill
# in db/migrations/0013_finance_liquidity_and_single_pending_bill.sql (a test
# runs the migration against every type to keep the two in step) and is
# mirrored in ui/src/features/finance/lib/liquidity.ts. `item_type` is free
# text (0008 left it that way), so matching is case- and space-insensitive.
LIQUID_ITEM_TYPES: frozenset[str] = frozenset({"cash", "checking", "savings", "efectivo", "ahorro"})

# Asset types that are clearly NOT available as an emergency cushion. A NEW
# item of one of these types is defaulted to false. Existing rows are not
# backfilled with this list: the migration only ever sets true.
ILLIQUID_ITEM_TYPES: frozenset[str] = frozenset({"real_estate", "retirement"})


def normalize_item_type(item_type: str | None) -> str:
    return (item_type or "").strip().lower()


def default_is_liquid(item_type: str | None, *, is_asset: bool) -> bool | None:
    """The flag a NEW item gets when the client does not send one.

    ``True`` for a cash-like asset, ``False`` for a clearly illiquid one,
    ``None`` (not classified) for anything else -- including the generic
    ``other`` -- because guessing would put an unmeasured number on the
    emergency fund. A liability is never liquid or illiquid: ``None``.
    """
    if not is_asset:
        return None
    normalized = normalize_item_type(item_type)
    if normalized in LIQUID_ITEM_TYPES:
        return True
    if normalized in ILLIQUID_ITEM_TYPES:
        return False
    return None


def summarize_net_worth_liquidity(
    items: Iterable[Mapping[str, Any]], *, flags_available: bool
) -> dict[str, Any]:
    """Liquidity totals over one snapshot's items, in BASE currency.

    * ``liquid_assets_cents`` -- the sum of the base amounts of the ASSET items
      flagged liquid. Liabilities are not subtracted; ``None`` (unknown, not
      zero) when the database has no liquidity flags at all. An item with no
      usable base amount contributes nothing, exactly as in the snapshot
      totals.
    * ``liquid_items_count`` -- asset items flagged liquid.
    * ``unclassified_items_count`` -- asset items whose flag is ``None``.
      Items without an ``is_liquid`` key (a database without the column)
      count as unclassified.
    * ``liquidity_flags_available`` -- echoes ``flags_available``.
    """
    liquid_cents = 0
    liquid_count = 0
    unclassified_count = 0
    for item in items:
        if not item.get("is_asset"):
            continue
        flag = item.get("is_liquid")
        if flag is None:
            unclassified_count += 1
        elif flag:
            liquid_count += 1
            liquid_cents += base_amount_cents(item) or 0

    return {
        "liquid_assets_cents": liquid_cents if flags_available else None,
        "liquid_items_count": liquid_count if flags_available else 0,
        "unclassified_items_count": unclassified_count,
        "liquidity_flags_available": flags_available,
    }


def is_liquidity_classified(summary: Mapping[str, Any]) -> bool:
    """Whether the emergency fund can be measured from these flags.

    False when the database has no flags, or when no asset is flagged liquid
    AND at least one asset is still unclassified (the user has not said which
    assets are liquid). True when at least one asset is liquid, or when every
    asset has been classified -- including "none of them is liquid", which is
    a real answer: zero months covered, not an unmeasured coverage."""
    if not summary["liquidity_flags_available"]:
        return False
    return summary["liquid_items_count"] > 0 or summary["unclassified_items_count"] == 0
