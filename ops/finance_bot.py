"""Inbound Telegram ingestion for the personal-finance ledger.

Poll -> parse -> write ledger rows -> confirm. Standalone job, launched by
Task Scheduler (``ops/register_finance_bot.ps1``), operationally independent
from ``ops/run_local_scheduler.py`` (the ML pipeline's scheduler): different
cadence, different failure shape, own registration script.

Only the ingestion pipeline lives here -- no API router, no analytics, no UI
(future work).

-- Message grammar --------------------------------------------------------

    <amount> [currency] <category_word> [account_word] [free-text notes...]

Free text from a phone keyboard, so parsing is lenient about whitespace and
Spanish accents but explicit about rejection: an unrecognized category never
falls back to a fuzzy guess (task rationale: a wrong silent category guess in
someone's financial ledger is worse than an explicit rejection they can
immediately retry).

The amount may carry a leading ``$`` and thousands commas (``$1,200.50``); a
decimal comma with one or two digits (``120,50``) still works. An optional
currency code right after the amount (``120 mxn comida``) is checked against
the account's currency, never used to override it. Amounts above
``MAX_AMOUNT_UNITS`` are refused with a specific reply.

Income is never inferred from a near-miss: a word one letter away from an
expense word (``rentas`` vs ``renta``) is refused as ambiguous, and income
from rent has its own explicit keyword. Every confirmation names the kind
(gasto/ingreso), the currency and the category that was chosen, so a wrong
guess is visible immediately.

-- Currency ---------------------------------------------------------------

The currency of an entry is the currency of the account it lands in. The
free-text grammar cannot carry an FX rate, so a message that resolves to an
account in a non-base currency (``brain/finance/currency.py::BASE_CURRENCY``)
is rejected with an explanatory reply; those movements are captured in the
app, which asks for the rate. Accepted rows are written with rate 1 and the
base amount, so every ledger aggregate can read them.

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

-- Write failures --------------------------------------------------------

The "OK" confirmation is sent only AFTER the row was written. The batch is
written in one statement first; if that fails, each row is retried on its own
so one bad row cannot take the others down. Policy: the cursor still advances
past a row whose write failed (the batch is ``partial``). The failure is
logged and the user is told to resend it, so nothing is lost silently and a
message that can never be stored cannot block the queue (the same rule as an
unparseable message). Resending is safe: ``client_id`` upserts.
"""

from __future__ import annotations

import argparse
import json
import logging
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

from brain.finance.currency import BASE_CURRENCY, normalize_currency, resolve_fx_and_base
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from ops.telegram_inbox import fetch_updates
from ops.telegram_notifier import TelegramConfig, escape_html, send_telegram_message

logger = logging.getLogger(__name__)

# Fixed, never regenerated -- see module docstring's "client_id / idempotency"
# section. Any constant UUID literal works; this one has no other meaning.
FINANCE_TELEGRAM_NAMESPACE = uuid.UUID("6f1f9a9e-8f3a-4b8e-9c2d-2a6f7e6b1a10")

DEFAULT_FINANCE_ACCOUNT_NAME = "Efectivo"

REJECTION_MESSAGE = "No entendi ese mensaje. Formato: <monto> <categoria> [cuenta] [notas]"

# The message grammar has no way to state an FX rate, so the bot can only
# book into accounts whose currency is the ledger's base currency.
NON_BASE_ACCOUNT_MESSAGE = (
    "La cuenta {account} está en {currency}, una moneda distinta de la base del registro ({base}). "
    "Para registrar movimientos desde Telegram, la moneda de la cuenta debe ser {base}. "
    "Puedes capturar este movimiento en la app con su tipo de cambio."
)

AMOUNT_TOO_LARGE_MESSAGE = (
    "El monto es demasiado grande: el máximo por mensaje es $1,000,000,000.00. "
    "Revísalo y vuelve a enviarlo."
)

AMBIGUOUS_RENTAS_MESSAGE = (
    "«rentas» se parece demasiado a «renta» y cambiaría un gasto por un ingreso. "
    "Escribe «renta» para pagar la renta (gasto de vivienda) o «ingreso-renta» "
    "para registrar rentas que recibes."
)

CURRENCY_MISMATCH_MESSAGE = (
    "Indicaste {stated}, pero la cuenta {account} está en {currency}. "
    "Usa una cuenta en {stated} o quita la moneda del mensaje."
)

WRITE_FAILED_MESSAGE = (
    "No pude guardar {kind} de {amount} {currency} en {category}. "
    "Vuelve a enviar el mensaje en unos minutos."
)

# Largest amount one message may book (in the account's currency). Far below
# the `bigint` cents columns' limit (BIGINT_MAX cents), so a typo such as an
# extra run of digits is refused instead of crashing the write.
MAX_AMOUNT_UNITS = 1_000_000_000
MAX_AMOUNT_CENTS = MAX_AMOUNT_UNITS * 100

# Whole part, optional 1-2 digit decimal (`.` or `,`) -- `120`, `150.5`, `120,50`.
_PLAIN_AMOUNT_PATTERN = re.compile(r"^([0-9]+)(?:[.,]([0-9]{1,2}))?$")
# Comma-grouped thousands with an optional `.` decimal -- `1,200`, `1,200.50`.
_GROUPED_AMOUNT_PATTERN = re.compile(r"^([0-9]{1,3}(?:,[0-9]{3})+)(?:\.([0-9]{1,2}))?$")

# Currency codes recognised right after the amount. Deliberately a short
# closed list: a three-letter category word such as "luz" or "gas" must never
# be mistaken for a currency.
_CURRENCY_WORDS: dict[str, str] = {"mxn": "MXN", "usd": "USD", "eur": "EUR"}

_KIND_LABELS: dict[str, str] = {"expense": "gasto", "income": "ingreso"}

# Category aliases: common free-text words -> `finance_categories.slug`.
# Keys are lowercase and accent-free (matched against an accent-stripped,
# lowercased token -- see `_strip_accents`). Grouped by slug to mirror the
# spec's presentation. Income keywords are explicit and never a near-miss of
# an expense keyword: "renta" is the expense (vivienda), "ingreso-renta" the
# income, and the one-letter-apart "rentas" is refused as ambiguous (see
# `_AMBIGUOUS_CATEGORY_WORDS`).
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
    "rentas": ("ingreso-renta",),
    "dividendos": ("dividendos",),
    "ganancias-inversion": ("ganancia", "ganancias"),
    # "otros-ingresos" deliberately has no aliases: exact slug match only,
    # ambiguous otherwise with the expense category "otros".
}

# Words that would silently flip an expense into an income (or back) by one
# letter. Refused with a specific reply instead of guessed.
_AMBIGUOUS_CATEGORY_WORDS: dict[str, str] = {"rentas": AMBIGUOUS_RENTAS_MESSAGE}

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
    # No currency setting: a transaction's currency is its account's currency
    # (decision D1). A configured default currency is what used to book pesos
    # as USD.
    default_account_name: str

    @classmethod
    def from_env(cls) -> "FinanceBotConfig":
        return cls(
            default_account_name=(os.getenv("FINANCE_DEFAULT_ACCOUNT_NAME") or DEFAULT_FINANCE_ACCOUNT_NAME).strip(),
        )


class MessageRejected(ValueError):
    """A message refused for a SPECIFIC reason worth telling the user (as
    opposed to the generic "did not understand" ``None`` from the parser).
    ``reply`` is plain text, not yet HTML-escaped."""

    def __init__(self, reply: str) -> None:
        super().__init__(reply)
        self.reply = reply


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
    """Parse a token as a positive amount in integer cents (no floats).

    Accepts an optional leading ``$``, digits with an optional ``.`` or ``,``
    decimal separator (at most 2 decimal digits -- money only has cents
    precision) and comma-grouped thousands (``1,200.50``). Returns ``None``
    (parse failure) for anything else, including zero/negative values -- there
    is no unary minus in this grammar. Raises ``MessageRejected`` when the
    amount is valid but above ``MAX_AMOUNT_CENTS``.
    """
    body = token[1:] if token.startswith("$") else token
    match = _PLAIN_AMOUNT_PATTERN.match(body) or _GROUPED_AMOUNT_PATTERN.match(body)
    if match is None:
        return None
    whole = match.group(1).replace(",", "").lstrip("0") or "0"
    if len(whole) > 12:  # already far above the cap; skip the big-int work
        raise MessageRejected(AMOUNT_TOO_LARGE_MESSAGE)
    cents = int(whole) * 100 + int((match.group(2) or "").ljust(2, "0"))
    if cents <= 0:
        return None
    if cents > MAX_AMOUNT_CENTS:
        raise MessageRejected(AMOUNT_TOO_LARGE_MESSAGE)
    return cents


def format_cents(cents: int) -> str:
    """``150050`` -> ``$1,500.50`` (integer arithmetic, no float rounding)."""
    return f"${cents // 100:,}.{cents % 100:02d}"


def derive_client_id(update_id: int) -> uuid.UUID:
    """Deterministic idempotency key -- see module docstring."""
    return uuid.uuid5(FINANCE_TELEGRAM_NAMESPACE, str(update_id))


def _match_category(token: str, categories: list[dict[str, Any]]) -> dict[str, Any] | None:
    lowered = token.lower()
    normalized = _strip_accents(token).lower()
    ambiguous_reply = _AMBIGUOUS_CATEGORY_WORDS.get(normalized)
    if ambiguous_reply is not None:
        raise MessageRejected(ambiguous_reply)

    for category in categories:
        if category["slug"].lower() == lowered:
            return category

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
) -> ParsedMessage | None:
    """Parse one free-text ledger message. Returns ``None`` on any parse
    failure -- amount, category, and account resolution are all
    all-or-nothing; there is no partial/fuzzy result. Raises
    ``MessageRejected`` for the failures that have a specific reply (amount
    too large, ambiguous keyword, stated currency that is not the account's).

    The currency is the resolved account's currency, never a bot setting. It
    may be a non-base currency; ``process_updates`` rejects those (the
    grammar has no way to carry an FX rate)."""
    tokens = text.split()
    if len(tokens) < 2:
        return None

    amount_cents = parse_amount_cents(tokens[0])
    if amount_cents is None:
        return None

    rest = tokens[1:]
    stated_currency = _CURRENCY_WORDS.get(rest[0].lower())
    if stated_currency is not None:
        rest = rest[1:]
        if not rest:
            return None

    category = _match_category(rest[0], categories)
    if category is None:
        return None

    remaining = rest[1:]
    account, remaining = _match_account(remaining, accounts)
    if account is None:
        account = _resolve_default_account(default_account_name, accounts)
    if account is None:
        return None

    currency = normalize_currency(account["currency"])
    if stated_currency is not None and stated_currency != currency:
        raise MessageRejected(
            CURRENCY_MISMATCH_MESSAGE.format(stated=stated_currency, account=account["name"], currency=currency)
        )

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
    # Only base-currency messages reach this point (process_updates rejects
    # the rest), so the rate is 1 and the base amount is the amount itself.
    # Written explicitly because the bot inserts straight through the
    # repository, not through the API router that normally materializes them.
    fx_rate_to_base, amount_base_cents = resolve_fx_and_base(parsed.amount_cents, parsed.currency, None)
    return {
        "client_id": str(derive_client_id(update_id)),
        "account_id": parsed.account_id,
        "category_id": parsed.category_id,
        "kind": parsed.kind,
        "amount_cents": parsed.amount_cents,
        "currency": parsed.currency,
        "fx_rate_to_base": fx_rate_to_base,
        "amount_base_cents": amount_base_cents,
        "occurred_at": occurred_at.isoformat(),
        "merchant": None,
        "notes": parsed.notes,
        "source": "telegram",
        "raw_input": raw_text,
    }


def _reply_texts(parsed: ParsedMessage) -> tuple[str, str]:
    """``(confirmation, failure)`` HTML replies for one accepted message. Both
    name the kind, the currency and the category that was chosen, so a wrong
    guess is visible right away."""
    kind = _KIND_LABELS.get(parsed.kind, parsed.kind)
    amount = format_cents(parsed.amount_cents)
    currency = escape_html(parsed.currency)
    category = escape_html(parsed.category_name)
    confirmation = (
        f"OK: {kind} de {amount} {currency} en la categoría {category} "
        f"(cuenta {escape_html(parsed.account_name)})."
    )
    failure = WRITE_FAILED_MESSAGE.format(kind=kind, amount=amount, currency=currency, category=category)
    return confirmation, failure


def _write_rows(repository: Any, rows: list[dict[str, Any]]) -> list[bool]:
    """Persist ``rows`` and say which ones were stored. One batched write
    first (the normal path); if it fails, each row is retried on its own so a
    single bad row cannot take the others down. Failures are logged, never
    raised -- see the module docstring's "Write failures" policy."""
    if not rows:
        return []
    try:
        repository.upsert_finance_transactions(rows)
        return [True] * len(rows)
    except (psycopg.Error, RuntimeError):
        logger.exception("Batched ledger write failed; retrying %d row(s) one by one", len(rows))

    stored: list[bool] = []
    for row in rows:
        try:
            repository.upsert_finance_transactions([row])
            stored.append(True)
        except (psycopg.Error, RuntimeError):
            logger.exception("Ledger write failed for client_id %s", row.get("client_id"))
            stored.append(False)
    return stored


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
    and reply to the allowed chat -- with rejections only. Never touches the
    database itself: ``run_poll`` writes ``rows`` and only then sends each
    row's reply from ``replies`` (``(confirmation, failure)`` pairs aligned
    with ``rows``). ``applied_count`` here means "accepted for writing".
    """
    rows: list[dict[str, Any]] = []
    replies: list[tuple[str, str]] = []
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
        try:
            parsed = parse_message(
                text,
                categories=categories,
                accounts=accounts,
                default_account_name=config.default_account_name,
            )
        except MessageRejected as rejection:
            rejected_count += 1
            send_telegram_message(escape_html(rejection.reply), telegram_config, session=session, sleep=sleep)
            continue

        if parsed is None:
            rejected_count += 1
            send_telegram_message(
                escape_html(REJECTION_MESSAGE), telegram_config, session=session, sleep=sleep
            )
            continue

        if parsed.currency != BASE_CURRENCY:
            rejected_count += 1
            send_telegram_message(
                NON_BASE_ACCOUNT_MESSAGE.format(
                    account=escape_html(parsed.account_name),
                    currency=escape_html(parsed.currency),
                    base=BASE_CURRENCY,
                ),
                telegram_config,
                session=session,
                sleep=sleep,
            )
            continue

        occurred_at = datetime.fromtimestamp(message["date"], tz=timezone.utc)
        rows.append(_transaction_row(parsed, update_id=update_id, occurred_at=occurred_at, raw_text=text))
        applied_count += 1
        replies.append(_reply_texts(parsed))

    return {
        "rows": rows,
        "replies": replies,
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

    stored = _write_rows(repository, summary["rows"])
    # "OK" only after the write: a row that was not stored gets the failure
    # reply instead, and the cursor advances past it anyway (module docstring).
    for was_stored, (confirmation, failure) in zip(stored, summary["replies"], strict=True):
        send_telegram_message(
            confirmation if was_stored else failure, telegram_config, session=session, sleep=sleep
        )
    applied_count = sum(stored)
    write_failed_count = len(stored) - applied_count

    status = "ok" if summary["rejected_count"] == 0 and write_failed_count == 0 else "partial"
    cursor_update_id = summary["max_update_id"] if summary["max_update_id"] is not None else cursor

    repository.insert_finance_sync_batch(
        source="telegram",
        cursor_update_id=cursor_update_id,
        received_count=summary["received_count"],
        applied_count=applied_count,
        rejected_count=summary["rejected_count"],
        status=status,
        error_reason="ledger_write_failed" if write_failed_count else None,
        details={"write_failed_count": write_failed_count} if write_failed_count else {},
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )

    return {
        "status": status,
        "received_count": summary["received_count"],
        "applied_count": applied_count,
        "rejected_count": summary["rejected_count"],
        "write_failed_count": write_failed_count,
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
