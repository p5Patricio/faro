"""Pure investment-ledger math: positions, average cost and realized gains in
MXN, plus the yearly income records an accountant reconciles against each
broker's annual statement.

Informational only. Nothing here computes a tax: there is no INPC update of
the cost (LISR art. 129 / CFF art. 17-A) and no rate is applied. See
``docs/sat/modelo-de-datos.md``.

Money rules: amounts are integer cents in the operation's currency; every
conversion to MXN goes through ``brain.finance.currency.to_base_cents``
(``Decimal`` product, half-up to whole cents). Quantities and rates are
``Decimal``; a ``float`` never touches a money figure.

Average cost is tracked per ``(account_id, symbol)``, the way each broker
computes it on its own statement, so every figure can be reconciled against
that broker's document. Operations are applied in ``(trade_date, seq)`` order,
where ``seq`` is their position in the input list (the repository orders by
``trade_date, created_at``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from brain.finance.currency import to_base_cents

INCOME_KINDS = ("dividend", "fibra_distribution", "capital_return", "interest")


class LedgerError(ValueError):
    """An operation the ledger cannot apply (e.g. selling more than is held)."""


@dataclass
class _Position:
    account_id: str
    symbol: str
    instrument_type: str
    quantity: Decimal = Decimal(0)
    cost_mxn_cents: int = 0


@dataclass
class LedgerResult:
    positions: list[dict[str, Any]] = field(default_factory=list)
    sales: list[dict[str, Any]] = field(default_factory=list)
    income: list[dict[str, Any]] = field(default_factory=list)
    fees: list[dict[str, Any]] = field(default_factory=list)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _mxn(cents: int, operation: Mapping[str, Any]) -> int:
    return to_base_cents(cents, operation["currency"], _decimal(operation["fx_rate_to_mxn"]))


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _trace(operation: Mapping[str, Any]) -> dict[str, Any]:
    """The fields every output row carries so it can be traced to its source."""
    return {
        "client_id": str(operation["client_id"]),
        "trade_date": operation["trade_date"],
        "account_id": str(operation["account_id"]),
        "symbol": operation["symbol"],
        "instrument_type": operation.get("instrument_type") or "otro",
        "currency": operation["currency"],
        "fx_rate_to_mxn": str(_decimal(operation["fx_rate_to_mxn"])),
        "fx_rate_date": operation.get("fx_rate_date"),
    }


def compute_ledger(operations: Iterable[Mapping[str, Any]]) -> LedgerResult:
    """Replay ``operations`` (soft-deleted rows already excluded).

    * ``buy``: quantity up; cost up by ``amount + fee`` in MXN.
    * ``sell``: the cost of the units sold is ``cost * q / quantity`` (average
      cost); proceeds are ``amount - fee`` in MXN; gain = proceeds - cost sold.
      Selling more than is held raises ``LedgerError``.
    * ``split``: quantity times the factor; cost unchanged.
    * ``capital_return`` (FIBRA reembolso de capital): lowers the cost, never
      below zero; any excess is reported as ``excess_over_cost_mxn_cents``.
    * ``dividend`` / ``fibra_distribution`` / ``interest``: income records
      (gross and withholding in MXN); the cost is untouched.
    * ``fee``: a standalone fee record (``fee_cents``).
    """
    ordered = sorted(enumerate(operations), key=lambda pair: (pair[1]["trade_date"], pair[0]))
    positions: dict[tuple[str, str], _Position] = {}
    result = LedgerResult()

    for _, operation in ordered:
        kind = operation["kind"]
        key = (str(operation["account_id"]), str(operation["symbol"]).upper())
        position = positions.get(key)
        if position is None:
            position = positions[key] = _Position(key[0], key[1], operation.get("instrument_type") or "otro")
        elif operation.get("instrument_type"):
            position.instrument_type = operation["instrument_type"]

        amount = int(operation.get("amount_cents") or 0)
        fee = int(operation.get("fee_cents") or 0)
        withheld = int(operation.get("tax_withheld_cents") or 0)
        quantity = _decimal(operation.get("quantity"))

        if kind == "buy":
            position.quantity += quantity
            position.cost_mxn_cents += _mxn(amount + fee, operation)
        elif kind == "sell":
            if quantity > position.quantity:
                raise LedgerError(
                    f"{key[1]}: se venden {quantity} títulos el {operation['trade_date']} "
                    f"pero solo se tienen {position.quantity}."
                )
            cost_sold = _round_cents(Decimal(position.cost_mxn_cents) * quantity / position.quantity)
            proceeds = _mxn(amount - fee, operation)
            position.quantity -= quantity
            position.cost_mxn_cents -= cost_sold
            result.sales.append(
                {
                    **_trace(operation),
                    "quantity": format(quantity.normalize(), "f"),
                    "proceeds_mxn_cents": proceeds,
                    "cost_mxn_cents": cost_sold,
                    "gain_mxn_cents": proceeds - cost_sold,
                    "tax_withheld_mxn_cents": _mxn(withheld, operation),
                }
            )
        elif kind == "split":
            position.quantity *= quantity
        elif kind in INCOME_KINDS:
            gross = _mxn(amount, operation)
            record = {
                **_trace(operation),
                "kind": kind,
                "gross_mxn_cents": gross,
                "tax_withheld_mxn_cents": _mxn(withheld, operation),
            }
            if kind == "capital_return":
                applied = min(gross, position.cost_mxn_cents)
                position.cost_mxn_cents -= applied
                record["excess_over_cost_mxn_cents"] = gross - applied
            result.income.append(record)
        elif kind == "fee":
            result.fees.append({**_trace(operation), "fee_mxn_cents": _mxn(fee, operation)})
        else:
            raise LedgerError(f"Tipo de operación desconocido: {kind}")

    for position in positions.values():
        if position.quantity == 0 and position.cost_mxn_cents == 0:
            continue
        average = (
            (Decimal(position.cost_mxn_cents) / position.quantity).quantize(Decimal("0.0001"))
            if position.quantity
            else None
        )
        result.positions.append(
            {
                "account_id": position.account_id,
                "symbol": position.symbol,
                "instrument_type": position.instrument_type,
                "quantity": format(position.quantity.normalize(), "f"),
                "cost_basis_mxn_cents": position.cost_mxn_cents,
                "average_cost_mxn_cents": str(average) if average is not None else None,
            }
        )
    result.positions.sort(key=lambda row: (row["account_id"], row["symbol"]))
    return result


def yearly_worksheet(result: LedgerResult, year: int) -> dict[str, Any]:
    """The year's sales, income and fees plus per-account totals by concept,
    for reconciling line by line against each broker's annual statement."""

    def in_year(row: Mapping[str, Any]) -> bool:
        return row["trade_date"].year == year

    sales = [row for row in result.sales if in_year(row)]
    income = [row for row in result.income if in_year(row)]
    fees = [row for row in result.fees if in_year(row)]

    totals: dict[tuple[str, str], dict[str, int]] = {}

    def add(account_id: str, concept: str, gross: int, withheld: int) -> None:
        bucket = totals.setdefault((account_id, concept), {"amount_mxn_cents": 0, "tax_withheld_mxn_cents": 0})
        bucket["amount_mxn_cents"] += gross
        bucket["tax_withheld_mxn_cents"] += withheld

    for row in sales:
        add(row["account_id"], "sale_gain", row["gain_mxn_cents"], row["tax_withheld_mxn_cents"])
    for row in income:
        add(row["account_id"], row["kind"], row["gross_mxn_cents"], row["tax_withheld_mxn_cents"])
    for row in fees:
        add(row["account_id"], "fee", row["fee_mxn_cents"], 0)

    summary = [
        {"account_id": account_id, "concept": concept, **amounts}
        for (account_id, concept), amounts in sorted(totals.items())
    ]
    return {"year": year, "sales": sales, "income": income, "fees": fees, "summary": summary}
