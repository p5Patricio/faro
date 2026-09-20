from __future__ import annotations

from typing import Any

import pytest

from ops import finance_bot
from ops.finance_bot import (
    FinanceBotConfig,
    derive_client_id,
    parse_amount_cents,
    parse_message,
)
from ops.telegram_notifier import TelegramConfig

TOKEN = "123456789:AAFakeTokenForTestingPurposesOnly12"

# Mirrors db/migrations/0008_personal_finance.sql's seed rows closely enough
# to exercise the real slugs/names/kinds the parser matches against.
CATEGORIES: list[dict[str, Any]] = [
    {"id": "cat-vivienda", "slug": "vivienda", "name": "Vivienda", "kind": "expense", "budget_bucket": "necesidad"},
    {"id": "cat-alimentacion", "slug": "alimentacion", "name": "Alimentacion", "kind": "expense", "budget_bucket": "necesidad"},
    {"id": "cat-transporte", "slug": "transporte", "name": "Transporte", "kind": "expense", "budget_bucket": "necesidad"},
    {"id": "cat-servicios", "slug": "servicios", "name": "Servicios", "kind": "expense", "budget_bucket": "necesidad"},
    {"id": "cat-salud", "slug": "salud", "name": "Salud", "kind": "expense", "budget_bucket": "necesidad"},
    {"id": "cat-educacion-hijos", "slug": "educacion-hijos", "name": "Educacion / Hijos", "kind": "expense", "budget_bucket": "necesidad"},
    {"id": "cat-entretenimiento", "slug": "entretenimiento", "name": "Entretenimiento", "kind": "expense", "budget_bucket": "deseo"},
    {"id": "cat-ropa", "slug": "ropa", "name": "Ropa", "kind": "expense", "budget_bucket": "deseo"},
    {"id": "cat-ahorro-inversion", "slug": "ahorro-inversion", "name": "Ahorro e Inversion", "kind": "expense", "budget_bucket": "ahorro_inversion"},
    {"id": "cat-sueldo", "slug": "sueldo", "name": "Sueldo", "kind": "income", "budget_bucket": None},
    {"id": "cat-honorarios", "slug": "honorarios", "name": "Honorarios / Freelance", "kind": "income", "budget_bucket": None},
    {"id": "cat-rentas", "slug": "rentas", "name": "Rentas", "kind": "income", "budget_bucket": None},
    {"id": "cat-dividendos", "slug": "dividendos", "name": "Dividendos", "kind": "income", "budget_bucket": None},
    {"id": "cat-ganancias-inversion", "slug": "ganancias-inversion", "name": "Ganancias de inversion", "kind": "income", "budget_bucket": None},
    {"id": "cat-otros-ingresos", "slug": "otros-ingresos", "name": "Otros ingresos", "kind": "income", "budget_bucket": None},
]

ACCOUNTS: list[dict[str, Any]] = [
    {"id": "acc-efectivo", "name": "Efectivo", "account_type": "cash", "currency": "USD"},
    {"id": "acc-debito", "name": "Tarjeta debito", "account_type": "debit", "currency": "USD"},
    {"id": "acc-credito", "name": "Tarjeta credito", "account_type": "credit", "currency": "USD"},
    {"id": "acc-ahorro", "name": "Ahorro", "account_type": "savings", "currency": "USD"},
]


def _parse(text: str, *, default_account_name: str = "Efectivo", currency: str = "USD"):
    return parse_message(
        text,
        categories=CATEGORIES,
        accounts=ACCOUNTS,
        default_account_name=default_account_name,
        currency=currency,
    )


# -- parse_amount_cents -------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected_cents",
    [
        ("150", 15000),
        ("150.5", 15050),
        ("150.50", 15050),
        ("120,50", 12050),
        ("0.99", 99),
        ("1", 100),
    ],
)
def test_parse_amount_cents_valid(token: str, expected_cents: int) -> None:
    assert parse_amount_cents(token) == expected_cents


@pytest.mark.parametrize(
    "token",
    ["abc", "-150", "0", "-1.5", "15.999", "", "15.5.5", "15,5,5", "$150"],
)
def test_parse_amount_cents_rejects_invalid_or_non_positive(token: str) -> None:
    assert parse_amount_cents(token) is None


# -- parse_message: happy paths -----------------------------------------------


def test_parse_message_valid_expense_defaults_to_efectivo() -> None:
    parsed = _parse("150 comida")

    assert parsed is not None
    assert parsed.amount_cents == 15000
    assert parsed.category_slug == "alimentacion"
    assert parsed.kind == "expense"
    assert parsed.account_name == "Efectivo"
    assert parsed.notes == ""


def test_parse_message_income_kind_is_derived_from_category_not_guessed() -> None:
    parsed = _parse("5000 sueldo")

    assert parsed is not None
    assert parsed.category_slug == "sueldo"
    assert parsed.kind == "income"


def test_parse_message_comma_decimal_amount_is_normalized() -> None:
    parsed = _parse("120,50 comida")

    assert parsed is not None
    assert parsed.amount_cents == 12050


def test_parse_message_account_word_overrides_default_account() -> None:
    parsed = _parse("150 comida debito")

    assert parsed is not None
    assert parsed.account_name == "Tarjeta debito"
    assert parsed.notes == ""


def test_parse_message_default_account_fallback_when_no_account_word_present() -> None:
    parsed = _parse("150 comida cena con amigos")

    assert parsed is not None
    assert parsed.account_name == "Efectivo"
    assert parsed.notes == "cena con amigos"


def test_parse_message_respects_configured_default_account_name() -> None:
    parsed = _parse("150 comida", default_account_name="Ahorro")

    assert parsed is not None
    assert parsed.account_name == "Ahorro"


def test_parse_message_notes_excludes_amount_category_and_matched_account_token() -> None:
    parsed = _parse("150 comida efectivo cena con amigos")

    assert parsed is not None
    assert parsed.account_name == "Efectivo"
    assert parsed.notes == "cena con amigos"


def test_parse_message_alias_word_in_notes_position_is_not_reparsed_as_category() -> None:
    """'uber' is a category alias (-> transporte), but only token[1] is ever
    checked as a category; here it lands in notes and must stay there."""
    parsed = _parse("200 transporte uber viaje al aeropuerto")

    assert parsed is not None
    assert parsed.category_slug == "transporte"
    assert parsed.account_name == "Efectivo"
    assert parsed.notes == "uber viaje al aeropuerto"


# -- "renta" vs "rentas" disambiguation ---------------------------------------


def test_parse_message_renta_alias_is_vivienda_expense() -> None:
    parsed = _parse("8000 renta")

    assert parsed is not None
    assert parsed.category_slug == "vivienda"
    assert parsed.kind == "expense"


def test_parse_message_rentas_exact_slug_is_income_not_vivienda() -> None:
    parsed = _parse("3000 rentas")

    assert parsed is not None
    assert parsed.category_slug == "rentas"
    assert parsed.kind == "income"


# -- Rejections ----------------------------------------------------------------


def test_parse_message_unknown_category_is_rejected_not_fuzzy_matched() -> None:
    assert _parse("150 marciano") is None


@pytest.mark.parametrize("text", ["abc comida", "-150 comida", "0 comida", "comida", "150"])
def test_parse_message_missing_or_invalid_amount_is_rejected(text: str) -> None:
    assert _parse(text) is None


def test_parse_message_otros_ingresos_has_no_alias_only_exact_slug_matches() -> None:
    assert _parse("100 otros") is None
    parsed = _parse("100 otros-ingresos")
    assert parsed is not None
    assert parsed.category_slug == "otros-ingresos"


def test_parse_message_unresolvable_default_account_is_rejected() -> None:
    # "Bank of Nowhere" is not in the seeded accounts list and no account
    # word was given either -- there is nothing valid to fall back to.
    assert _parse("150 comida", default_account_name="Bank of Nowhere") is None


# -- client_id determinism (the core replay-safety contract) -----------------


def test_derive_client_id_is_deterministic_across_calls() -> None:
    assert derive_client_id(123456789) == derive_client_id(123456789)


def test_derive_client_id_differs_for_different_update_ids() -> None:
    assert derive_client_id(1) != derive_client_id(2)


def test_derive_client_id_is_stable_not_random_uuid4() -> None:
    ids = {str(derive_client_id(42)) for _ in range(5)}
    assert len(ids) == 1


# -- Orchestration: process_updates / run_poll --------------------------------


class FakeSendResponse:
    status_code = 200

    def json(self) -> dict:
        return {}


class FakeSendSession:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def post(self, url: str, json: dict, timeout: int):
        self.requests.append({"url": url, "json": json, "timeout": timeout})
        return FakeSendResponse()


class FakeRepository:
    def __init__(self, *, cursor: int | None = None) -> None:
        self._cursor = cursor
        self.upsert_calls: list[list[dict]] = []
        self.batch_calls: list[dict] = []

    def get_finance_sync_cursor(self, source: str) -> int | None:
        assert source == "telegram"
        return self._cursor

    def get_finance_categories(self) -> list[dict[str, Any]]:
        return CATEGORIES

    def get_finance_accounts(self) -> list[dict[str, Any]]:
        return ACCOUNTS

    def upsert_finance_transactions(self, rows: list[dict[str, Any]]) -> int:
        self.upsert_calls.append(rows)
        return len(rows)

    def insert_finance_sync_batch(self, **fields: Any) -> None:
        self.batch_calls.append(fields)


def _telegram_config() -> TelegramConfig:
    return TelegramConfig(bot_token=TOKEN, chat_id="-100999")


def _bot_config() -> FinanceBotConfig:
    return FinanceBotConfig(default_account_name="Efectivo", default_currency="USD")


def _fake_fetch(result: dict[str, Any]):
    def _fetch(config, *, offset=None, session=None):
        return result

    return _fetch


def test_process_updates_skips_wrong_chat_silently_but_counts_it_toward_cursor() -> None:
    updates = [
        {
            "update_id": 10,
            "message": {"date": 1700000000, "chat": {"id": 555}, "text": "150 comida"},
        }
    ]
    session = FakeSendSession()

    summary = finance_bot.process_updates(
        updates,
        categories=CATEGORIES,
        accounts=ACCOUNTS,
        config=_bot_config(),
        telegram_config=_telegram_config(),
        session=session,
        sleep=lambda *_a: None,
    )

    assert summary["max_update_id"] == 10
    assert summary["applied_count"] == 0
    assert summary["rejected_count"] == 0
    assert summary["rows"] == []
    assert session.requests == []  # no reply sent for a foreign chat


def test_process_updates_skips_textless_and_edited_updates_silently() -> None:
    updates = [
        {"update_id": 11, "edited_message": {"date": 1700000000, "chat": {"id": -100999}, "text": "150 comida"}},
        {"update_id": 12, "message": {"date": 1700000000, "chat": {"id": -100999}}},  # no text
        {"update_id": 13, "channel_post": {"date": 1700000000, "chat": {"id": -100999}, "text": "150 comida"}},
    ]
    session = FakeSendSession()

    summary = finance_bot.process_updates(
        updates,
        categories=CATEGORIES,
        accounts=ACCOUNTS,
        config=_bot_config(),
        telegram_config=_telegram_config(),
        session=session,
        sleep=lambda *_a: None,
    )

    assert summary["max_update_id"] == 13
    assert summary["applied_count"] == 0
    assert summary["rejected_count"] == 0
    assert session.requests == []


def test_run_poll_mixed_batch_advances_cursor_to_max_and_reports_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [
        {"update_id": 100, "message": {"date": 1700000000, "chat": {"id": -100999}, "text": "150 comida"}},
        {"update_id": 101, "message": {"date": 1700000100, "chat": {"id": -100999}, "text": "not a valid message"}},
        {"update_id": 102, "message": {"date": 1700000200, "chat": {"id": 555}, "text": "999 comida"}},
    ]
    monkeypatch.setattr(finance_bot, "fetch_updates", _fake_fetch({"ok": True, "updates": updates}))
    repository = FakeRepository(cursor=None)
    session = FakeSendSession()

    result = finance_bot.run_poll(
        repository=repository,
        telegram_config=_telegram_config(),
        config=_bot_config(),
        session=session,
        sleep=lambda *_a: None,
    )

    assert result["status"] == "partial"
    assert result["cursor_update_id"] == 102
    assert result["received_count"] == 3
    assert result["applied_count"] == 1
    assert result["rejected_count"] == 1

    assert len(repository.upsert_calls) == 1
    assert len(repository.upsert_calls[0]) == 1
    inserted_row = repository.upsert_calls[0][0]
    assert inserted_row["client_id"] == str(derive_client_id(100))
    assert inserted_row["kind"] == "expense"

    assert len(repository.batch_calls) == 1
    batch = repository.batch_calls[0]
    assert batch["status"] == "partial"
    assert batch["cursor_update_id"] == 102
    assert batch["received_count"] == 3
    assert batch["applied_count"] == 1
    assert batch["rejected_count"] == 1

    # One confirmation (update 100) + one rejection reply (update 101); the
    # wrong-chat update (102) gets no reply at all.
    assert len(session.requests) == 2


def test_run_poll_all_valid_batch_reports_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [
        {"update_id": 200, "message": {"date": 1700000000, "chat": {"id": -100999}, "text": "150 comida"}},
    ]
    monkeypatch.setattr(finance_bot, "fetch_updates", _fake_fetch({"ok": True, "updates": updates}))
    repository = FakeRepository(cursor=None)

    result = finance_bot.run_poll(
        repository=repository,
        telegram_config=_telegram_config(),
        config=_bot_config(),
        session=FakeSendSession(),
        sleep=lambda *_a: None,
    )

    assert result["status"] == "ok"
    assert result["rejected_count"] == 0
    assert result["cursor_update_id"] == 200


def test_run_poll_fetch_failure_reports_failed_without_advancing_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        finance_bot,
        "fetch_updates",
        _fake_fetch({"ok": False, "reason": "telegram_request_failed", "detail": "boom (redacted)"}),
    )
    repository = FakeRepository(cursor=50)

    result = finance_bot.run_poll(
        repository=repository,
        telegram_config=_telegram_config(),
        config=_bot_config(),
        session=FakeSendSession(),
        sleep=lambda *_a: None,
    )

    assert result["status"] == "failed"
    assert repository.upsert_calls == []
    assert len(repository.batch_calls) == 1
    batch = repository.batch_calls[0]
    assert batch["status"] == "failed"
    assert batch["cursor_update_id"] is None
    assert batch["error_reason"] == "boom (redacted)"


def test_run_poll_zero_updates_is_ok_and_leaves_cursor_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(finance_bot, "fetch_updates", _fake_fetch({"ok": True, "updates": []}))
    repository = FakeRepository(cursor=77)

    result = finance_bot.run_poll(
        repository=repository,
        telegram_config=_telegram_config(),
        config=_bot_config(),
        session=FakeSendSession(),
        sleep=lambda *_a: None,
    )

    assert result["status"] == "ok"
    assert result["cursor_update_id"] == 77
    assert repository.upsert_calls == []


def test_run_poll_uses_offset_derived_from_cursor_plus_one(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_offsets: list[int | None] = []

    def _fetch(config, *, offset=None, session=None):
        seen_offsets.append(offset)
        return {"ok": True, "updates": []}

    monkeypatch.setattr(finance_bot, "fetch_updates", _fetch)
    repository = FakeRepository(cursor=500)

    finance_bot.run_poll(
        repository=repository,
        telegram_config=_telegram_config(),
        config=_bot_config(),
        session=FakeSendSession(),
        sleep=lambda *_a: None,
    )

    assert seen_offsets == [501]
