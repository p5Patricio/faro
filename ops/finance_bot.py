"""Inbound Telegram ingestion for the personal-finance ledger.

Poll -> parse -> write ledger rows -> confirm. Standalone job, launched by
Task Scheduler (``ops/register_finance_bot.ps1``), operationally independent
from ``ops/run_local_scheduler.py`` (the ML pipeline's scheduler): different
cadence, different failure shape, own registration script.

Only the ingestion pipeline lives here -- no API router, no analytics, no UI
(future work).

-- Message grammar --------------------------------------------------------

    <amount> <category_word> [account_word] [free-text notes...]

Free text from a phone keyboard, so parsing is lenient about whitespace and
Spanish accents but explicit about rejection: an unrecognized category never
falls back to a fuzzy guess (task rationale: a wrong silent category guess in
someone's financial ledger is worse than an explicit rejection they can
immediately retry).

-- client_id / idempotency ------------------------------------------------

There is no real client-side app generating a UUID here (the phone just sends
free text to Telegram). ``client_id`` is instead derived *deterministically*
from the Telegram ``update_id`` via ``uuid.uuid5(FINANCE_TELEGRAM_NAMESPACE,
str(update_id))``, so replaying the same update (e.g. after an offset
regression) upserts instead of duplicating -- see
``finance_transactions.client_id``'s unique index in
``db/migrations/0008_personal_finance.sql``. ``FINANCE_TELEGRAM_NAMESPACE`` is
a fixed module-level constant: never swap it for ``uuid.uuid4()``, which would
silently defeat the entire replay-safety design.

-- Cursor / idempotency ----------------------------------------------------

The cursor (``finance_sync_batches.cursor_update_id``) is an optimization to
avoid re-downloading already-seen updates -- it is NOT the correctness
mechanism; the deterministic ``client_id`` above is what makes re-processing
safe regardless of cursor state.

A batch is ``failed`` only when the Telegram *fetch* itself fails
(network/API error): the cursor must not advance so the same offset is
retried next run. Once the fetch succeeds, the batch is ``ok`` (nothing
rejected) or ``partial`` (at least one message failed to parse) and the
cursor advances to ``max(update_id)`` across *every* fetched update --
regardless of type, chat origin, or parse outcome -- because Telegram's
``getUpdates`` offset is a single global per-bot cursor: a single
unparseable or wrong-chat message must never block it forever.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
import requests
from dotenv import load_dotenv

from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from ops.telegram_inbox import fetch_updates
from ops.telegram_notifier import TelegramConfig, escape_html, send_telegram_message

# Fixed, never regenerated -- see module docstring's "client_id / idempotency"
# section. Any constant UUID literal works; this one has no other meaning.
FINANCE_TELEGRAM_NAMESPACE = uuid.UUID("6f1f9a9e-8f3a-4b8e-9c2d-2a6f7e6b1a10")

DEFAULT_FINANCE_ACCOUNT_NAME = "Efectivo"
DEFAULT_FINANCE_CURRENCY = "USD"

REJECTION_MESSAGE = "No entendi ese mensaje. Formato: <monto> <categoria> [cuenta] [notas]"

_AMOUNT_PATTERN = re.compile(r"^\d+([.,]\d{1,2})?$")

# Category aliases: common free-text words -> `finance_categories.slug`.
# Keys are lowercase and accent-free (matched against an accent-stripped,
# lowercased token -- see `_strip_accents`). Grouped by slug to mirror the
# spec's presentation and make the "renta" (expense, vivienda) vs "rentas"
# (income, exact-slug-only) disambiguation visually obvious: "renta" is
# deliberately NOT aliased to "rentas", and vice versa.
_CATEGORY_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "alimentacion": ("comida", "alimentos", "super", "mercado", "almuerzo", "cena", "desayuno", "restaurante"),
    "transporte": ("uber", "taxi", "gasolina", "gas", "camion", "metro", "transporte", "pasaje"),
    "vivienda": ("renta", "hipoteca", "casa", "alquiler"),
    "servicios": ("luz", "agua", "internet", "telefono", "celular", "cable"),
    "salud": ("doctor", "medico", "farmacia", "medicina", "dentista"),
    "educacion-hijos": ("escuela", "colegiatura", "utiles", "colegio"),
    "entretenimiento": ("netflix", "spotify", "cine", "salida", "streaming"),
    "ropa": ("ropa", "zapatos", "calzado"),
    "ahorro-inversion": ("ahorro", "inversion", "invertir"),
    "sueldo": ("sueldo", "nomina", "salario"),
    "honorarios": ("honorarios", "freelance"),
    "rentas": ("rentas",),
    "dividendos": ("dividendos",),
    "ganancias-inversion": ("ganancia", "ganancias"),
    # "otros-ingresos" deliberately has no aliases: exact slug match only,
    # ambiguous otherwise with the expense category "otros".
}

CATEGORY_ALIASES: dict[str, str] = {
    alias: slug for slug, aliases in _CATEGORY_ALIAS_GROUPS.items() for alias in aliases
}

# Account aliases: common free-text words -> `finance_accounts.name`.
ACCOUNT_ALIASES: dict[str, str] = {
    "efectivo": "Efectivo",
    "cash": "Efectivo",
    "debito": "Tarjeta debito",
    "debit": "Tarjeta debito",
    "credito": "Tarjeta credito",
    "credit": "Tarjeta credito",
    "tarjeta": "Tarjeta credito",
    "ahorro": "Ahorro",
    "savings": "Ahorro",
}


@dataclass(frozen=True)
class FinanceBotConfig:
    default_account_name: str
    default_currency: str

    @classmethod
    def from_env(cls) -> "FinanceBotConfig":
        return cls(
            default_account_name=(os.getenv("FINANCE_DEFAULT_ACCOUNT_NAME") or DEFAULT_FINANCE_ACCOUNT_NAME).strip(),
            default_currency=(os.getenv("FINANCE_DEFAULT_CURRENCY") or DEFAULT_FINANCE_CURRENCY).strip().upper(),
        )


@dataclass(frozen=True)
class ParsedMessage:
    """One successfully parsed ledger entry -- pure data, no I/O."""

    amount_cents: int
    category_id: str
    category_slug: str
    category_name: str
    kind: str
    account_id: str
    account_name: str
    currency: str
    notes: str


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def parse_amount_cents(token: str) -> int | None:
    """Parse the first whitespace-separated token as a positive amount.

    Accepts digits with an optional single ``.`` or ``,`` decimal separator
    (at most 2 decimal digits -- money only has cents precision). Returns
    ``None`` (parse failure) for anything else, including zero/negative
    values -- there is no unary minus in this grammar.
    """
    if not _AMOUNT_PATTERN.match(token):
        return None
    normalized = token.replace(",", ".")
    value = float(normalized)
    if value <= 0:
        return None
    return round(value * 100)


def derive_client_id(update_id: int) -> uuid.UUID:
    """Deterministic idempotency key -- see module docstring."""
    return uuid.uuid5(FINANCE_TELEGRAM_NAMESPACE, str(update_id))


def _match_category(token: str, categories: list[dict[str, Any]]) -> dict[str, Any] | None:
    lowered = token.lower()
    for category in categories:
        if category["slug"].lower() == lowered:
            return category

    normalized = _strip_accents(token).lower()
    slug = CATEGORY_ALIASES.get(normalized)
    if slug is None:
        return None
    for category in categories:
        if category["slug"].lower() == slug:
            return category
    return None


def _match_account(
    tokens: list[str], accounts: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return the first token that resolves to a known account (and the
    remaining tokens with it removed), or ``(None, tokens)`` unchanged."""
    for index, token in enumerate(tokens):
        normalized = _strip_accents(token).lower()
        canonical_name = ACCOUNT_ALIASES.get(normalized)
        if canonical_name is None:
            continue
        for account in accounts:
            if account["name"].lower() == canonical_name.lower():
                remaining = tokens[:index] + tokens[index + 1 :]
                return account, remaining
    return None, tokens


def _resolve_default_account(
    default_account_name: str, accounts: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for account in accounts:
        if account["name"].lower() == default_account_name.lower():
            return account
    return None


def parse_message(
    text: str,
    *,
    categories: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    default_account_name: str,
    currency: str,
) -> ParsedMessage | None:
    """Parse one free-text ledger message. Returns ``None`` on any parse
    failure -- amount, category, and account resolution are all
    all-or-nothing; there is no partial/fuzzy result."""
    tokens = text.split()
    if len(tokens) < 2:
        return None

    amount_cents = parse_amount_cents(tokens[0])
    if amount_cents is None:
        return None

    category = _match_category(tokens[1], categories)
    if category is None:
        return None

    remaining = tokens[2:]
    account, remaining = _match_account(remaining, accounts)
    if account is None:
        account = _resolve_default_account(default_account_name, accounts)
    if account is None:
        return None

    notes = " ".join(remaining)

    return ParsedMessage(
        amount_cents=amount_cents,
        category_id=category["id"],
        category_slug=category["slug"],
        category_name=category["name"],
        kind=category["kind"],
        account_id=account["id"],
        account_name=account["name"],
        currency=currency,
        notes=notes,
    )


def _transaction_row(parsed: ParsedMessage, *, update_id: int, occurred_at: datetime, raw_text: str) -> dict[str, Any]:
    return {
        "client_id": str(derive_client_id(update_id)),
        "account_id": parsed.account_id,
        "category_id": parsed.category_id,
        "kind": parsed.kind,
        "amount_cents": parsed.amount_cents,
        "currency": parsed.currency,
        "occurred_at": occurred_at.isoformat(),
        "merchant": None,
        "notes": parsed.notes,
        "source": "telegram",
        "raw_input": raw_text,
    }


def process_updates(
    updates: list[dict[str, Any]],
    *,
    categories: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    config: FinanceBotConfig,
    telegram_config: TelegramConfig,
    session: Any = requests,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """Process one poll's worth of updates: parse, collect rows to persist,
    and reply to the allowed chat. Never touches the database itself --
    ``run_poll`` does the single batched write from ``rows``.
    """
    rows: list[dict[str, Any]] = []
    applied_count = 0
    rejected_count = 0
    max_update_id: int | None = None

    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None:
            max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)

        message = update.get("message")
        if not message or not message.get("text"):
            # edited_message / channel_post / callback_query / textless
            # messages: silently skipped, but already counted toward the
            # cursor above.
            continue

        chat = message.get("chat") or {}
        if str(chat.get("id")) != telegram_config.chat_id:
            # Chat-id allowlist is the only auth -- silently skip anything
            # from another chat, no reply, no error.
            continue

        text = message["text"]
        parsed = parse_message(
            text,
            categories=categories,
            accounts=accounts,
            default_account_name=config.default_account_name,
            currency=config.default_currency,
        )

        if parsed is None:
            rejected_count += 1
            send_telegram_message(
                escape_html(REJECTION_MESSAGE), telegram_config, session=session, sleep=sleep
            )
            continue

        occurred_at = datetime.fromtimestamp(message["date"], tz=timezone.utc)
        rows.append(_transaction_row(parsed, update_id=update_id, occurred_at=occurred_at, raw_text=text))
        applied_count += 1

        confirmation = (
            f"OK: ${parsed.amount_cents / 100:.2f} - "
            f"{escape_html(parsed.category_name)} ({escape_html(parsed.account_name)})"
        )
        send_telegram_message(confirmation, telegram_config, session=session, sleep=sleep)

    return {
        "rows": rows,
        "received_count": len(updates),
        "applied_count": applied_count,
        "rejected_count": rejected_count,
        "max_update_id": max_update_id,
    }


def run_poll(
    *,
    repository: Any,
    telegram_config: TelegramConfig,
    config: FinanceBotConfig,
    session: Any = requests,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """One full poll cycle: read cursor, fetch, parse, batch-write, record
    exactly one ``finance_sync_batches`` row. See module docstring for the
    failed/ok/partial status rules and the cursor-advancement contract.
    """
    started_at = datetime.now(timezone.utc)
    cursor = repository.get_finance_sync_cursor("telegram")
    offset = cursor + 1 if cursor is not None else None

    fetch_result = fetch_updates(telegram_config, offset=offset, session=session)

    if not fetch_result.get("ok"):
        repository.insert_finance_sync_batch(
            source="telegram",
            cursor_update_id=None,
            received_count=0,
            applied_count=0,
            rejected_count=0,
            status="failed",
            error_reason=fetch_result.get("detail") or fetch_result.get("reason"),
            details={"reason": fetch_result.get("reason")},
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        return {"status": "failed", "reason": fetch_result.get("reason")}

    updates = fetch_result.get("updates") or []
    categories = repository.get_finance_categories()
    accounts = repository.get_finance_accounts()

    summary = process_updates(
        updates,
        categories=categories,
        accounts=accounts,
        config=config,
        telegram_config=telegram_config,
        session=session,
        sleep=sleep,
    )

    if summary["rows"]:
        repository.upsert_finance_transactions(summary["rows"])

    status = "ok" if summary["rejected_count"] == 0 else "partial"
    cursor_update_id = summary["max_update_id"] if summary["max_update_id"] is not None else cursor

    repository.insert_finance_sync_batch(
        source="telegram",
        cursor_update_id=cursor_update_id,
        received_count=summary["received_count"],
        applied_count=summary["applied_count"],
        rejected_count=summary["rejected_count"],
        status=status,
        error_reason=None,
        details={},
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )

    return {
        "status": status,
        "received_count": summary["received_count"],
        "applied_count": summary["applied_count"],
        "rejected_count": summary["rejected_count"],
        "cursor_update_id": cursor_update_id,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Poll Telegram for personal-finance ledger messages and write ledger rows"
    )
    return parser.parse_args()


def main() -> None:
    # `.env` before any config resolution -- this module is launched as a
    # fresh subprocess by Task Scheduler, nothing has populated `os.environ`
    # yet (same rationale as `ops/notify_operational_job.py:main`).
    load_dotenv(override=True)
    parse_args()

    telegram_config = TelegramConfig.from_env()
    if telegram_config is None:
        print(json.dumps({"status": "failed", "reason": "missing_telegram_config"}, indent=2))
        return

    config = FinanceBotConfig.from_env()

    try:
        connection = psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True)
    except Exception as error:
        print(json.dumps({"status": "failed", "reason": "database_unavailable", "detail": str(error)}, indent=2))
        return

    try:
        repository = LocalPostgresRepository(connection=connection)
        summary = run_poll(repository=repository, telegram_config=telegram_config, config=config)
    finally:
        connection.close()

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
