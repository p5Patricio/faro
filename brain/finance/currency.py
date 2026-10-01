"""Base currency and integer-safe conversion for the personal-finance ledger.

Single source of truth: the API router, the Telegram bot, the SQL aggregates
in ``collector/local_repository.py`` and the analytics all take the base
currency from here. Pure module -- no I/O, no third-party imports -- so the
repository can import it without pulling in the ML stack.

Money never touches binary floats on the way to the ledger: the FX rate
arrives as a float from the API, is converted through ``Decimal(str(x))`` (so
``17.5`` stays exactly ``17.5``) and the product with integer cents is rounded
half-up back to integer cents.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

BASE_CURRENCY = "MXN"

# Every money column is `bigint` cents. Payload amounts are bounded to it, and
# so is a converted base amount: a big amount times a big rate can leave it.
BIGINT_MAX = 9_223_372_036_854_775_807

# `finance_transactions.fx_rate_to_base` and the net-worth item column are
# both `numeric(18,8)`: 8 decimals, at most 10 integer digits.
_FX_SCALE = Decimal("0.00000001")
_FX_MAX_EXCLUSIVE = Decimal(10) ** 10


def normalize_currency(code: str | None) -> str:
    """Upper-cased, trimmed ISO code. ``char(3)`` columns can come back
    space-padded and clients may send lower case."""
    return (code or "").strip().upper()


def _parse_fx_rate(fx_rate_to_base: float | int | str | Decimal | None) -> Decimal:
    if fx_rate_to_base is None:
        raise ValueError("fx_rate_to_base is required for a non-base currency")
    try:
        rate = fx_rate_to_base if isinstance(fx_rate_to_base, Decimal) else Decimal(str(fx_rate_to_base))
    except InvalidOperation:
        raise ValueError(f"fx_rate_to_base is not a number: {fx_rate_to_base!r}") from None
    if not rate.is_finite() or rate <= 0:
        raise ValueError("fx_rate_to_base must be a finite number greater than zero")
    # Bound before quantizing: quantize() raises InvalidOperation, not
    # ValueError, when the result would not fit the default context.
    if rate >= _FX_MAX_EXCLUSIVE:
        raise ValueError("fx_rate_to_base is too large to store")
    # Quantize to the column's scale so the rate that is stored is exactly the
    # rate the base amount was computed from.
    rate = rate.quantize(_FX_SCALE, rounding=ROUND_HALF_UP)
    if rate <= 0:
        raise ValueError("fx_rate_to_base is too small to store")
    if rate >= _FX_MAX_EXCLUSIVE:
        raise ValueError("fx_rate_to_base is too large to store")
    return rate


def to_base_cents(
    amount_cents: int,
    currency: str,
    fx_rate_to_base: float | int | str | Decimal | None,
) -> int:
    """``amount_cents`` of ``currency`` expressed in base-currency cents,
    rounded half-up. A base-currency amount passes through untouched (any
    ``fx_rate_to_base`` is ignored); a foreign one needs a positive rate,
    otherwise ``ValueError``."""
    if normalize_currency(currency) == BASE_CURRENCY:
        base_cents = amount_cents
    else:
        rate = _parse_fx_rate(fx_rate_to_base)
        with localcontext() as context:
            # A bigint of cents times a 10-digit rate stays well inside 60
            # digits; larger inputs make quantize() raise InvalidOperation,
            # reported as the same ValueError as any other unstorable result.
            context.prec = 60
            try:
                base_cents = int((Decimal(amount_cents) * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            except InvalidOperation:
                raise ValueError("base amount is too large to store") from None
    if abs(base_cents) > BIGINT_MAX:
        raise ValueError("base amount does not fit the bigint column")
    return base_cents


def resolve_fx_and_base(
    amount_cents: int,
    currency: str,
    fx_rate_to_base: float | int | str | Decimal | None,
) -> tuple[Decimal, int]:
    """The ``(fx_rate_to_base, amount_base_cents)`` pair to persist. The base
    currency always gets rate ``1`` -- whatever the caller sent -- and a
    foreign currency gets its (scale-normalized) rate."""
    if normalize_currency(currency) == BASE_CURRENCY:
        return Decimal(1), amount_cents
    rate = _parse_fx_rate(fx_rate_to_base)
    return rate, to_base_cents(amount_cents, currency, rate)


def base_amount_cents(row: Mapping[str, Any]) -> int | None:
    """One row's amount in base cents, or ``None`` when it cannot be
    converted.

    ``amount_base_cents`` wins when present. Otherwise a base-currency row is
    its own base amount (rows written before base amounts were materialized
    have a NULL column). A foreign-currency row without a base amount has no
    trustworthy value, so callers exclude it from totals and count it."""
    materialized = row.get("amount_base_cents")
    if materialized is not None:
        return int(materialized)
    if normalize_currency(row.get("currency")) == BASE_CURRENCY:
        return int(row["amount_cents"])
    return None
