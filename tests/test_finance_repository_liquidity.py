"""DB-backed checks (real SQL, rolled-back per-test transaction) for the
liquidity flag on net-worth items in ``collector/local_repository.py``:
persistence, the no-silent-flip rule, and graceful degradation on a database
that has not applied migration 0013 (simulated by dropping the column inside
the test's transaction)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from collector.local_repository import _LIQUIDITY_PROBE_ATTR, LocalPostgresRepository

SNAPSHOT_DATE = "2026-09-01"


def _item(label: str, item_type: str, cents: int = 100_000, *, is_asset: bool = True, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "is_asset": is_asset,
        "label": label,
        "item_type": item_type,
        "amount_cents": cents,
        "currency": "MXN",
        "fx_rate_to_base": 1,
        "amount_base_cents": cents,
    }
    item.update(overrides)
    return item


def _save(repository: LocalPostgresRepository, items: list[dict[str, Any]]) -> dict[str, Any]:
    return repository.upsert_finance_net_worth_snapshot(snapshot_date=SNAPSHOT_DATE, notes=None, items=items)


def _flags(items: list[dict[str, Any]]) -> dict[str, bool | None]:
    return {item["label"]: item["is_liquid"] for item in items}


def _stored_flags(repository: LocalPostgresRepository) -> dict[str, bool | None]:
    return _flags(repository.get_finance_net_worth_snapshots(limit=1)[0]["items"])


# -- Persistence ----------------------------------------------------------------------


def test_an_explicit_flag_is_stored_and_read_back(repository: LocalPostgresRepository) -> None:
    saved = _save(
        repository,
        [
            _item("Ahorro", "other", is_liquid=True),
            _item("Terreno", "other", is_liquid=False),
            _item("Sin revisar", "other", is_liquid=None),
        ],
    )

    expected = {"Ahorro": True, "Terreno": False, "Sin revisar": None}
    assert _flags(saved["items"]) == expected
    assert _stored_flags(repository) == expected


def test_an_omitted_flag_defaults_by_item_type_for_a_new_item(repository: LocalPostgresRepository) -> None:
    _save(
        repository,
        [_item("Efectivo", "cash"), _item("Casa", "real_estate"), _item("Cuenta", "other")],
    )

    assert _stored_flags(repository) == {"Efectivo": True, "Casa": False, "Cuenta": None}


def test_a_liability_is_stored_unclassified_whatever_the_payload_says(repository: LocalPostgresRepository) -> None:
    _save(repository, [_item("Tarjeta", "credit_card", is_asset=False, is_liquid=None), _item("Efectivo", "cash")])

    assert _stored_flags(repository) == {"Tarjeta": None, "Efectivo": True}


def test_repeating_a_write_without_the_flag_does_not_flip_a_stored_choice(
    repository: LocalPostgresRepository,
) -> None:
    """The user marked a cash-typed item as NOT liquid and an `other` item as
    liquid; a client that resubmits the worksheet without the field must not
    replace those choices with the type defaults."""
    _save(repository, [_item("Efectivo", "cash", is_liquid=False), _item("Ahorro", "other", is_liquid=True)])

    _save(repository, [_item("Efectivo", "cash", 150_000), _item("Ahorro", "other", 250_000)])

    assert _stored_flags(repository) == {"Efectivo": False, "Ahorro": True}


def test_the_stored_choice_is_matched_by_kind_and_label_ignoring_case_and_spaces(
    repository: LocalPostgresRepository,
) -> None:
    _save(repository, [_item("Efectivo", "cash", is_liquid=False)])

    _save(repository, [_item("  efectivo ", "cash")])

    assert _stored_flags(repository) == {"  efectivo ": False}


def test_a_repeat_write_never_carries_a_choice_over_to_a_different_item(
    repository: LocalPostgresRepository,
) -> None:
    _save(repository, [_item("Efectivo", "cash", is_liquid=False)])

    _save(repository, [_item("Caja chica", "cash")])

    # A new label is a new item: it gets the default for its type.
    assert _stored_flags(repository) == {"Caja chica": True}


def test_an_explicit_flag_on_a_repeat_write_replaces_the_stored_one(repository: LocalPostgresRepository) -> None:
    _save(repository, [_item("Efectivo", "cash", is_liquid=False)])

    _save(repository, [_item("Efectivo", "cash", is_liquid=True)])

    assert _stored_flags(repository) == {"Efectivo": True}


def test_an_explicit_null_stays_unclassified_and_an_omitted_flag_later_takes_the_type_default(
    repository: LocalPostgresRepository,
) -> None:
    _save(repository, [_item("Efectivo", "cash", is_liquid=None)])
    assert _stored_flags(repository) == {"Efectivo": None}

    # Unclassified is not a choice to preserve: the omitted flag falls back to the type default.
    _save(repository, [_item("Efectivo", "cash")])

    assert _stored_flags(repository) == {"Efectivo": True}


# -- The probe ------------------------------------------------------------------------


def test_the_probe_reports_the_column_on_a_migrated_database(repository: LocalPostgresRepository) -> None:
    assert repository.net_worth_liquidity_flags_available() is True


def test_a_positive_probe_is_cached_across_repositories_sharing_the_connection(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert repository.net_worth_liquidity_flags_available() is True

    # The API builds a fresh repository per request over the same pool: the
    # answer lives on the pool/connection, so a new instance does not ask again.
    fresh = LocalPostgresRepository(connection=db_connection)
    queries: list[str] = []
    monkeypatch.setattr(fresh, "_cursor", lambda: queries.append("catalog lookup") or pytest.fail("probed again"))

    assert fresh.net_worth_liquidity_flags_available() is True
    assert queries == []


@pytest.fixture()
def pool(test_database_url: str) -> Iterator[ConnectionPool]:
    connection_pool = ConnectionPool(
        conninfo=test_database_url, min_size=1, max_size=2, configure=LocalPostgresRepository._configure, open=True
    )
    try:
        yield connection_pool
    finally:
        connection_pool.close()


def test_the_probe_answer_is_cached_on_the_pool_the_api_runs_on(pool: ConnectionPool) -> None:
    assert getattr(pool, _LIQUIDITY_PROBE_ATTR, None) is None

    assert LocalPostgresRepository(pool=pool).net_worth_liquidity_flags_available() is True

    assert getattr(pool, _LIQUIDITY_PROBE_ATTR, None) is True


# -- A database that has not applied migration 0013 ------------------------------------


@pytest.fixture()
def legacy_repository(repository: LocalPostgresRepository, db_connection: psycopg.Connection) -> LocalPostgresRepository:
    """The repository over a database without ``is_liquid`` (dropped inside
    this test's rolled-back transaction, so the real probe runs against it)."""
    db_connection.execute("ALTER TABLE finance_net_worth_items DROP COLUMN is_liquid")
    return repository


def test_the_probe_reports_a_missing_column(legacy_repository: LocalPostgresRepository) -> None:
    assert legacy_repository.net_worth_liquidity_flags_available() is False


def test_a_negative_probe_is_not_cached_so_applying_the_migration_takes_effect_without_a_restart(
    legacy_repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    assert legacy_repository.net_worth_liquidity_flags_available() is False

    db_connection.execute("ALTER TABLE finance_net_worth_items ADD COLUMN is_liquid boolean")

    assert legacy_repository.net_worth_liquidity_flags_available() is True


def test_writes_without_the_column_still_save_and_ignore_the_flag_with_a_warning(
    legacy_repository: LocalPostgresRepository, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="collector.local_repository"):
        saved = _save(legacy_repository, [_item("Efectivo", "cash", is_liquid=True), _item("Casa", "real_estate")])

    assert [record.message for record in caplog.records if "finance_net_worth_liquidity_ignored" in record.message]
    assert saved["total_assets_cents"] == 200_000
    assert _flags(saved["items"]) == {"Efectivo": None, "Casa": None}


def test_a_write_that_sends_no_flag_does_not_warn_on_a_database_without_the_column(
    legacy_repository: LocalPostgresRepository, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="collector.local_repository"):
        _save(legacy_repository, [_item("Efectivo", "cash")])

    assert not [record for record in caplog.records if "finance_net_worth_liquidity_ignored" in record.message]


def test_reads_without_the_column_report_every_item_as_unclassified(
    legacy_repository: LocalPostgresRepository,
) -> None:
    _save(legacy_repository, [_item("Efectivo", "cash"), _item("Tarjeta", "credit_card", is_asset=False)])

    snapshot = legacy_repository.get_finance_net_worth_snapshots(limit=1)[0]

    assert _flags(snapshot["items"]) == {"Efectivo": None, "Tarjeta": None}
    assert snapshot["net_worth_cents"] == 0
