"""DB-backed checks (real SQL, rolled-back per-test transaction) for the
recurring-bill lifecycle in ``collector/local_repository.py``: a saved active
bill always has exactly one pending occurrence, and settling an occurrence
creates the next one from the bill's anchor."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import psycopg

from collector.local_repository import LocalPostgresRepository

MakeAccount = Callable[[str, str], str]

TODAY = date(2026, 9, 29)


def _bill(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": "Netflix",
        "amount_cents": 19_900,
        "currency": "MXN",
        "frequency": "monthly",
        "anchor_due_date": date(2026, 1, 5),
        "reminder_days_before": 3,
        "is_active": True,
    }
    row.update(overrides)
    return row


def _payments(db_connection: psycopg.Connection, bill_id: str) -> list[tuple[date, str]]:
    """(due_date, status) of every occurrence row of the bill, oldest first."""
    rows = db_connection.execute(
        "SELECT due_date, status FROM finance_recurring_bill_payments WHERE bill_id = %s ORDER BY due_date",
        (bill_id,),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def _pending_dates(db_connection: psycopg.Connection, bill_id: str) -> list[date]:
    return [due for due, status in _payments(db_connection, bill_id) if status == "pending"]


# -- Saving a bill ------------------------------------------------------------------


def test_saving_an_active_bill_creates_its_pending_occurrence_on_or_after_today(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)

    # Anchor Jan 5, monthly: the earliest occurrence on or after Sep 29 is Oct 5.
    assert saved["next_due_date"] == date(2026, 10, 5)
    assert saved["next_status"] == "pending"
    assert _payments(db_connection, saved["id"]) == [(date(2026, 10, 5), "pending")]


def test_an_old_anchor_never_fabricates_overdue_rows(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(anchor_due_date=date(2020, 1, 5)), today=TODAY)

    assert _payments(db_connection, saved["id"]) == [(date(2026, 10, 5), "pending")]


def test_a_future_anchor_is_its_own_first_pending_occurrence(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(anchor_due_date=date(2026, 11, 20)), today=TODAY)

    assert _payments(db_connection, saved["id"]) == [(date(2026, 11, 20), "pending")]


def test_a_bill_due_today_has_today_as_its_pending_occurrence(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(anchor_due_date=date(2026, 8, 29)), today=TODAY)

    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 9, 29)]


def test_saving_the_same_bill_again_generates_nothing_new(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    row_id = db_connection.execute(
        "SELECT id FROM finance_recurring_bill_payments WHERE bill_id = %s", (saved["id"],)
    ).fetchone()[0]

    for _ in range(3):
        repository.upsert_finance_recurring_bill({**_bill(), "id": saved["id"]}, today=TODAY)

    assert _payments(db_connection, saved["id"]) == [(date(2026, 10, 5), "pending")]
    assert (
        db_connection.execute(
            "SELECT id FROM finance_recurring_bill_payments WHERE bill_id = %s", (saved["id"],)
        ).fetchone()[0]
        == row_id
    )


def test_bills_do_not_share_pending_rows(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    first = repository.upsert_finance_recurring_bill(_bill(name="Netflix"), today=TODAY)
    second = repository.upsert_finance_recurring_bill(_bill(name="Luz"), today=TODAY)

    assert _pending_dates(db_connection, first["id"]) == [date(2026, 10, 5)]
    assert _pending_dates(db_connection, second["id"]) == [date(2026, 10, 5)]


def test_an_inactive_bill_gets_no_pending_row_until_it_is_saved_active(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(is_active=False), today=TODAY)
    assert saved["next_due_date"] is None
    assert _payments(db_connection, saved["id"]) == []

    reactivated = repository.upsert_finance_recurring_bill({**_bill(), "id": saved["id"]}, today=TODAY)

    assert reactivated["next_due_date"] == date(2026, 10, 5)
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 10, 5)]


# -- Editing a bill ------------------------------------------------------------------


def test_editing_the_schedule_replaces_a_stale_pending_row_and_keeps_history(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 9, 5), "status": "paid", "paid_at": "2026-09-05T10:00:00+00:00"}
    )
    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 8, 5), "status": "skipped"}
    )

    edited = repository.upsert_finance_recurring_bill(
        {**_bill(anchor_due_date=date(2026, 1, 12)), "id": saved["id"]}, today=TODAY
    )

    assert edited["next_due_date"] == date(2026, 10, 12)
    assert _payments(db_connection, saved["id"]) == [
        (date(2026, 8, 5), "skipped"),
        (date(2026, 9, 5), "paid"),
        (date(2026, 10, 12), "pending"),
    ]


def test_editing_the_frequency_regenerates_the_pending_row_from_the_anchor(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(anchor_due_date=date(2026, 1, 15)), today=TODAY)
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 10, 15)]

    # Quarterly from Jan 15: Apr 15, Jul 15, Oct 15 -- Oct 15 is still a schedule date.
    repository.upsert_finance_recurring_bill(
        {**_bill(anchor_due_date=date(2026, 1, 15), frequency="quarterly"), "id": saved["id"]}, today=TODAY
    )
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 10, 15)]

    # Bimonthly from Jan 15 skips Oct (Jan, Mar, May, Jul, Sep, Nov): Oct 15 is stale.
    edited = repository.upsert_finance_recurring_bill(
        {**_bill(anchor_due_date=date(2026, 1, 15), frequency="bimonthly"), "id": saved["id"]}, today=TODAY
    )
    assert edited["next_due_date"] == date(2026, 11, 15)
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 11, 15)]


def test_editing_an_annual_bill_to_monthly_brings_the_pending_row_forward(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(
        _bill(frequency="annual", anchor_due_date=date(2026, 1, 15)), today=TODAY
    )
    assert _pending_dates(db_connection, saved["id"]) == [date(2027, 1, 15)]

    # Jan 15 2027 is still a schedule date of the monthly bill, but it would
    # hide the Oct 15 payment that is now due sooner.
    edited = repository.upsert_finance_recurring_bill(
        {**_bill(frequency="monthly", anchor_due_date=date(2026, 1, 15)), "id": saved["id"]}, today=TODAY
    )

    assert edited["next_due_date"] == date(2026, 10, 15)
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 10, 15)]


def test_editing_a_bill_keeps_the_next_pending_row_once_an_earlier_occurrence_was_paid_early(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "paid"}
    )
    before = db_connection.execute(
        "SELECT id FROM finance_recurring_bill_payments WHERE bill_id = %s AND status = 'pending'", (saved["id"],)
    ).fetchone()[0]

    # Oct 5 is on or after today but already settled, so Nov 5 skips nothing open.
    repository.upsert_finance_recurring_bill({**_bill(amount_cents=25_000), "id": saved["id"]}, today=TODAY)

    after = db_connection.execute(
        "SELECT id FROM finance_recurring_bill_payments WHERE bill_id = %s AND status = 'pending'", (saved["id"],)
    ).fetchone()[0]
    assert after == before
    assert _payments(db_connection, saved["id"]) == [(date(2026, 10, 5), "paid"), (date(2026, 11, 5), "pending")]


def test_editing_only_the_amount_keeps_the_same_pending_row(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    before = db_connection.execute(
        "SELECT id FROM finance_recurring_bill_payments WHERE bill_id = %s", (saved["id"],)
    ).fetchone()[0]

    repository.upsert_finance_recurring_bill({**_bill(amount_cents=25_000), "id": saved["id"]}, today=TODAY)

    after = db_connection.execute(
        "SELECT id FROM finance_recurring_bill_payments WHERE bill_id = %s", (saved["id"],)
    ).fetchone()[0]
    assert after == before


def test_editing_a_bill_keeps_a_genuinely_overdue_pending_row(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(anchor_due_date=date(2026, 1, 15)), today=date(2026, 8, 20))
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 9, 15)]

    # A month later Sep 15 is overdue; editing the amount must not erase it.
    edited = repository.upsert_finance_recurring_bill(
        {**_bill(anchor_due_date=date(2026, 1, 15), amount_cents=30_000), "id": saved["id"]}, today=TODAY
    )

    assert edited["next_due_date"] == date(2026, 9, 15)
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 9, 15)]


def test_a_pending_row_linked_to_a_transaction_is_never_deleted_by_an_edit(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection, make_finance_account: MakeAccount
) -> None:
    account_id = make_finance_account("Cuenta MXN de prueba", "MXN")
    transaction_id = str(
        db_connection.execute(
            "INSERT INTO finance_transactions (client_id, account_id, kind, amount_cents, currency, occurred_at) "
            "VALUES (%s, %s, 'expense', 1000, 'MXN', '2026-09-10T12:00:00+00:00') RETURNING id",
            (str(uuid.uuid4()), account_id),
        ).fetchone()[0]
    )
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 9), "status": "pending", "transaction_id": transaction_id}
    )

    edited = repository.upsert_finance_recurring_bill(
        {**_bill(anchor_due_date=date(2026, 1, 12)), "id": saved["id"]}, today=TODAY
    )

    # The unlinked Oct 5 row is stale and gone; the linked Oct 9 row stays and
    # counts as the bill's pending occurrence, so nothing else is generated.
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 10, 9)]
    assert edited["next_due_date"] == date(2026, 10, 9)


# -- Settling an occurrence ------------------------------------------------------------


def test_marking_paid_creates_the_next_pending_occurrence_strictly_after_it(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)

    payment = repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "paid", "paid_at": "2026-10-04T09:00:00+00:00"}
    )

    assert payment is not None
    assert payment["status"] == "paid"
    assert _payments(db_connection, saved["id"]) == [(date(2026, 10, 5), "paid"), (date(2026, 11, 5), "pending")]


def test_marking_skipped_creates_the_next_pending_occurrence_too(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)

    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "skipped"}
    )

    assert _payments(db_connection, saved["id"]) == [(date(2026, 10, 5), "skipped"), (date(2026, 11, 5), "pending")]


def test_settling_the_same_occurrence_twice_is_idempotent_and_keeps_the_original_paid_at(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    first = repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "paid", "paid_at": "2026-10-04T09:00:00+00:00"}
    )

    second = repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "paid", "paid_at": "2026-10-07T18:30:00+00:00"}
    )

    assert first is not None and second is not None
    assert second["paid_at"] == first["paid_at"]
    assert _payments(db_connection, saved["id"]) == [(date(2026, 10, 5), "paid"), (date(2026, 11, 5), "pending")]


def test_correcting_paid_to_skipped_clears_paid_at_and_adds_no_second_pending_row(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "paid", "paid_at": "2026-10-04T09:00:00+00:00"}
    )

    corrected = repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "skipped", "paid_at": None}
    )

    assert corrected is not None
    assert corrected["status"] == "skipped"
    assert corrected["paid_at"] is None
    assert _payments(db_connection, saved["id"]) == [(date(2026, 10, 5), "skipped"), (date(2026, 11, 5), "pending")]


def test_settling_an_old_occurrence_yields_a_next_row_that_may_already_be_overdue(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(anchor_due_date=date(2026, 7, 15)), today=date(2026, 7, 1))
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 7, 15)]

    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 7, 15), "status": "paid"}
    )

    # Aug 15 is long past by Sep 29, but it was never paid: it stays pending.
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 8, 15)]


def test_a_month_end_bill_does_not_drift_across_successive_settlements(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(
        _bill(anchor_due_date=date(2026, 1, 31)), today=date(2026, 2, 20)
    )
    assert _pending_dates(db_connection, saved["id"]) == [date(2026, 2, 28)]

    expected_next = [date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30)]
    current = date(2026, 2, 28)
    for expected in expected_next:
        repository.upsert_finance_recurring_bill_payment(
            {"bill_id": saved["id"], "due_date": current, "status": "paid"}
        )
        assert _pending_dates(db_connection, saved["id"]) == [expected]
        current = expected


def test_settling_skips_dates_that_already_have_history(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    # Nov 5 was settled first (out of order), so it is history, not a pending slot.
    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 11, 5), "status": "paid"}
    )

    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "paid"}
    )

    assert _payments(db_connection, saved["id"]) == [
        (date(2026, 10, 5), "paid"),
        (date(2026, 11, 5), "paid"),
        (date(2026, 12, 5), "pending"),
    ]


def test_settling_never_leaves_two_pending_rows_for_one_bill(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)

    for due in (date(2026, 10, 5), date(2026, 11, 5), date(2026, 12, 5)):
        repository.upsert_finance_recurring_bill_payment(
            {"bill_id": saved["id"], "due_date": due, "status": "paid"}
        )
        assert len(_pending_dates(db_connection, saved["id"])) == 1

    assert _pending_dates(db_connection, saved["id"]) == [date(2027, 1, 5)]


def test_settling_an_occurrence_of_an_inactive_bill_creates_no_pending_row(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    repository.upsert_finance_recurring_bill({**_bill(is_active=False), "id": saved["id"]}, today=TODAY)

    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "paid"}
    )

    assert _payments(db_connection, saved["id"]) == [(date(2026, 10, 5), "paid")]


def test_settling_an_occurrence_of_an_unknown_bill_returns_none(repository: LocalPostgresRepository) -> None:
    result = repository.upsert_finance_recurring_bill_payment(
        {"bill_id": str(uuid.uuid4()), "due_date": date(2026, 10, 5), "status": "paid"}
    )

    assert result is None


def test_settling_creates_no_ledger_transaction(
    repository: LocalPostgresRepository, db_connection: psycopg.Connection
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)

    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "paid"}
    )

    assert db_connection.execute("SELECT count(*) FROM finance_transactions").fetchone()[0] == 0


def test_get_finance_recurring_bills_reports_the_earliest_pending_occurrence(
    repository: LocalPostgresRepository,
) -> None:
    saved = repository.upsert_finance_recurring_bill(_bill(), today=TODAY)
    repository.upsert_finance_recurring_bill_payment(
        {"bill_id": saved["id"], "due_date": date(2026, 10, 5), "status": "paid"}
    )

    bill = next(b for b in repository.get_finance_recurring_bills() if b["id"] == saved["id"])

    assert bill["next_due_date"] == date(2026, 11, 5)
    assert bill["next_status"] == "pending"
