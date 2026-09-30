"""Pure tests for ``brain/finance/recurrence.py``: every occurrence is computed
from the anchor, never chained from the previous one."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from brain.finance.recurrence import (
    RECURRENCE_FREQUENCIES,
    is_occurrence,
    nth_occurrence,
    occurrence_after,
    occurrence_on_or_after,
    occurrences_between,
)

# -- nth_occurrence: every frequency ---------------------------------------------


@pytest.mark.parametrize(
    ("frequency", "index", "expected"),
    [
        ("weekly", 0, date(2026, 1, 15)),
        ("weekly", 1, date(2026, 1, 22)),
        ("weekly", 5, date(2026, 2, 19)),
        ("biweekly", 1, date(2026, 1, 29)),
        ("biweekly", 3, date(2026, 2, 26)),
        ("monthly", 1, date(2026, 2, 15)),
        ("monthly", 12, date(2027, 1, 15)),
        ("bimonthly", 1, date(2026, 3, 15)),
        ("bimonthly", 6, date(2027, 1, 15)),
        ("quarterly", 1, date(2026, 4, 15)),
        ("quarterly", 4, date(2027, 1, 15)),
        ("semiannual", 1, date(2026, 7, 15)),
        ("semiannual", 2, date(2027, 1, 15)),
        ("annual", 1, date(2027, 1, 15)),
        ("annual", 3, date(2029, 1, 15)),
    ],
)
def test_nth_occurrence_advances_one_period_per_index_from_the_anchor(
    frequency: str, index: int, expected: date
) -> None:
    assert nth_occurrence(date(2026, 1, 15), frequency, index) == expected


def test_the_recurrence_frequencies_match_the_schema_check_constraint() -> None:
    assert set(RECURRENCE_FREQUENCIES) == {
        "weekly",
        "biweekly",
        "monthly",
        "bimonthly",
        "quarterly",
        "semiannual",
        "annual",
    }


def test_nth_occurrence_rejects_an_unknown_frequency_and_a_negative_index() -> None:
    with pytest.raises(ValueError, match="unknown recurrence frequency"):
        nth_occurrence(date(2026, 1, 15), "fortnightly", 1)
    with pytest.raises(ValueError, match="negative"):
        nth_occurrence(date(2026, 1, 15), "monthly", -1)


# -- Month-end clamping and no drift ------------------------------------------------


def test_a_monthly_bill_anchored_on_the_31st_clamps_short_months_and_recovers() -> None:
    anchor = date(2026, 1, 31)

    assert [nth_occurrence(anchor, "monthly", n) for n in range(6)] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
        date(2026, 6, 30),
    ]


def test_february_clamps_to_the_29th_in_a_leap_year() -> None:
    anchor = date(2028, 1, 31)

    assert nth_occurrence(anchor, "monthly", 1) == date(2028, 2, 29)
    assert nth_occurrence(anchor, "monthly", 2) == date(2028, 3, 31)


def test_the_anchor_day_never_drifts_after_many_periods() -> None:
    anchor = date(2026, 1, 31)

    # A chained implementation would be stuck on the 28th after the first February.
    assert nth_occurrence(anchor, "monthly", 13) == date(2027, 2, 28)
    assert nth_occurrence(anchor, "monthly", 14) == date(2027, 3, 31)
    assert nth_occurrence(anchor, "monthly", 25) == date(2028, 2, 29)
    assert nth_occurrence(anchor, "monthly", 1200) == date(2126, 1, 31)


def test_longer_month_frequencies_also_keep_the_anchor_day() -> None:
    anchor = date(2026, 8, 31)

    assert nth_occurrence(anchor, "bimonthly", 1) == date(2026, 10, 31)
    assert nth_occurrence(anchor, "bimonthly", 3) == date(2027, 2, 28)
    assert nth_occurrence(anchor, "quarterly", 1) == date(2026, 11, 30)
    assert nth_occurrence(anchor, "quarterly", 2) == date(2027, 2, 28)
    assert nth_occurrence(anchor, "quarterly", 3) == date(2027, 5, 31)
    assert nth_occurrence(anchor, "semiannual", 1) == date(2027, 2, 28)
    assert nth_occurrence(anchor, "semiannual", 2) == date(2027, 8, 31)


def test_a_leap_day_anchor_lands_on_the_28th_until_the_next_leap_year() -> None:
    anchor = date(2028, 2, 29)

    assert [nth_occurrence(anchor, "annual", n) for n in range(5)] == [
        date(2028, 2, 29),
        date(2029, 2, 28),
        date(2030, 2, 28),
        date(2031, 2, 28),
        date(2032, 2, 29),
    ]
    assert nth_occurrence(anchor, "monthly", 12) == date(2029, 2, 28)
    assert nth_occurrence(anchor, "monthly", 1) == date(2028, 3, 29)


def test_weekly_and_biweekly_are_exact_day_offsets_across_month_and_year_ends() -> None:
    anchor = date(2026, 12, 28)

    assert nth_occurrence(anchor, "weekly", 1) == date(2027, 1, 4)
    assert nth_occurrence(anchor, "biweekly", 1) == date(2027, 1, 11)
    assert nth_occurrence(anchor, "weekly", 52) == anchor + timedelta(days=364)


# -- on_or_after vs strictly after ---------------------------------------------------


def test_on_or_after_keeps_the_day_itself_while_after_moves_past_it() -> None:
    anchor = date(2026, 1, 15)

    assert occurrence_on_or_after(anchor, "monthly", date(2026, 2, 15)) == date(2026, 2, 15)
    assert occurrence_after(anchor, "monthly", date(2026, 2, 15)) == date(2026, 3, 15)


def test_the_day_before_and_the_day_after_an_occurrence_resolve_around_it() -> None:
    anchor = date(2026, 1, 15)

    assert occurrence_on_or_after(anchor, "monthly", date(2026, 2, 14)) == date(2026, 2, 15)
    assert occurrence_after(anchor, "monthly", date(2026, 2, 14)) == date(2026, 2, 15)
    assert occurrence_on_or_after(anchor, "monthly", date(2026, 2, 16)) == date(2026, 3, 15)
    assert occurrence_after(anchor, "monthly", date(2026, 2, 16)) == date(2026, 3, 15)


def test_nothing_exists_before_the_anchor_so_earlier_days_resolve_to_it() -> None:
    anchor = date(2026, 6, 10)

    assert occurrence_on_or_after(anchor, "weekly", date(2025, 1, 1)) == anchor
    assert occurrence_on_or_after(anchor, "monthly", anchor) == anchor
    assert occurrence_after(anchor, "monthly", anchor - timedelta(days=1)) == anchor
    assert occurrence_after(anchor, "monthly", anchor) == date(2026, 7, 10)


def test_on_or_after_and_after_across_a_clamped_month_end() -> None:
    anchor = date(2026, 1, 31)

    assert occurrence_on_or_after(anchor, "monthly", date(2026, 2, 1)) == date(2026, 2, 28)
    assert occurrence_on_or_after(anchor, "monthly", date(2026, 2, 28)) == date(2026, 2, 28)
    assert occurrence_after(anchor, "monthly", date(2026, 2, 28)) == date(2026, 3, 31)
    assert occurrence_on_or_after(anchor, "monthly", date(2026, 3, 1)) == date(2026, 3, 31)
    assert occurrence_on_or_after(anchor, "monthly", date(2028, 2, 20)) == date(2028, 2, 29)


def test_on_or_after_for_weekly_and_biweekly_from_a_midweek_day() -> None:
    anchor = date(2026, 9, 7)  # a Monday
    tuesday = date(2026, 9, 29)

    assert occurrence_on_or_after(anchor, "weekly", tuesday) == date(2026, 10, 5)
    assert occurrence_on_or_after(anchor, "weekly", date(2026, 9, 28)) == date(2026, 9, 28)
    assert occurrence_on_or_after(anchor, "biweekly", tuesday) == date(2026, 10, 5)
    assert occurrence_on_or_after(anchor, "biweekly", date(2026, 10, 6)) == date(2026, 10, 19)


@pytest.mark.parametrize("frequency", RECURRENCE_FREQUENCIES)
@pytest.mark.parametrize("anchor", [date(2026, 1, 31), date(2028, 2, 29), date(2026, 3, 15)])
def test_on_or_after_and_after_match_a_brute_force_scan_of_two_years(frequency: str, anchor: date) -> None:
    schedule = [nth_occurrence(anchor, frequency, n) for n in range(0, 200)]

    day = anchor - timedelta(days=10)
    for _ in range(0, 800):
        expected_on_or_after = next(o for o in schedule if o >= day)
        expected_after = next(o for o in schedule if o > day)
        assert occurrence_on_or_after(anchor, frequency, day) == expected_on_or_after, day
        assert occurrence_after(anchor, frequency, day) == expected_after, day
        assert is_occurrence(anchor, frequency, day) == (day in schedule), day
        day += timedelta(days=1)


# -- occurrences_between --------------------------------------------------------------


def test_occurrences_between_includes_both_bounds() -> None:
    anchor = date(2026, 9, 30)

    weekly = occurrences_between(anchor, "weekly", date(2026, 9, 30), date(2026, 10, 28))

    assert weekly == [
        date(2026, 9, 30),
        date(2026, 10, 7),
        date(2026, 10, 14),
        date(2026, 10, 21),
        date(2026, 10, 28),
    ]


def test_occurrences_between_excludes_dates_just_outside_the_bounds() -> None:
    anchor = date(2026, 9, 30)

    assert occurrences_between(anchor, "weekly", date(2026, 10, 1), date(2026, 10, 27)) == [
        date(2026, 10, 7),
        date(2026, 10, 14),
        date(2026, 10, 21),
    ]


def test_occurrences_between_a_single_day_range_on_an_occurrence() -> None:
    anchor = date(2026, 1, 15)

    assert occurrences_between(anchor, "monthly", date(2026, 3, 15), date(2026, 3, 15)) == [date(2026, 3, 15)]
    assert occurrences_between(anchor, "monthly", date(2026, 3, 16), date(2026, 3, 16)) == []


def test_occurrences_between_is_empty_for_a_reversed_range_or_before_the_anchor() -> None:
    anchor = date(2026, 6, 10)

    assert occurrences_between(anchor, "weekly", date(2026, 7, 1), date(2026, 6, 1)) == []
    assert occurrences_between(anchor, "weekly", date(2026, 1, 1), date(2026, 6, 9)) == []


def test_occurrences_between_counts_per_frequency_over_thirty_days() -> None:
    start, end = date(2026, 9, 29), date(2026, 10, 29)

    assert len(occurrences_between(date(2026, 9, 30), "weekly", start, end)) == 5
    assert len(occurrences_between(date(2026, 10, 2), "weekly", start, end)) == 4
    assert len(occurrences_between(date(2026, 10, 1), "biweekly", start, end)) == 3
    assert len(occurrences_between(date(2026, 10, 5), "monthly", start, end)) == 1
    assert len(occurrences_between(date(2026, 10, 15), "annual", start, end)) == 1
    assert occurrences_between(date(2025, 12, 15), "annual", start, end) == []


def test_occurrences_between_follows_the_anchor_through_short_months() -> None:
    anchor = date(2026, 1, 31)

    assert occurrences_between(anchor, "monthly", date(2026, 2, 1), date(2026, 4, 30)) == [
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


# -- is_occurrence ---------------------------------------------------------------------


def test_is_occurrence_is_true_only_on_schedule_dates() -> None:
    anchor = date(2026, 1, 31)

    assert is_occurrence(anchor, "monthly", date(2026, 2, 28)) is True
    assert is_occurrence(anchor, "monthly", date(2026, 2, 27)) is False
    assert is_occurrence(anchor, "monthly", date(2025, 12, 31)) is False  # before the anchor
    assert is_occurrence(anchor, "weekly", date(2026, 2, 7)) is True
