"""Pure recurring-bill occurrence math: no I/O, no clock.

A bill is defined by an ``anchor_due_date`` plus a ``frequency``
(``finance_recurring_bills``, db/migrations/0008). Every occurrence date is
computed FROM THE ANCHOR -- occurrence ``n`` is the anchor plus ``n`` periods --
and never by chaining from the previous occurrence. Chaining drifts at month
ends: a bill anchored on Jan 31 would go Feb 28 -> Mar 28 -> Apr 28 forever,
while computing from the anchor gives Feb 28/29, Mar 31, Apr 30, May 31...

Rules:

* ``weekly`` / ``biweekly`` are the anchor plus ``n * 7`` / ``n * 14`` days.
* ``monthly`` / ``bimonthly`` / ``quarterly`` / ``semiannual`` / ``annual``
  advance ``n * 1/2/3/6/12`` calendar months and keep the anchor's day of
  month, clamped to the last day of a shorter month.
* The anchor is the first occurrence: nothing exists before it, so a day that
  precedes the anchor resolves to the anchor itself.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

_STEP_DAYS: dict[str, int] = {"weekly": 7, "biweekly": 14}
_STEP_MONTHS: dict[str, int] = {
    "monthly": 1,
    "bimonthly": 2,
    "quarterly": 3,
    "semiannual": 6,
    "annual": 12,
}

# Same seven values as the CHECK constraint on `finance_recurring_bills.frequency`.
RECURRENCE_FREQUENCIES: tuple[str, ...] = (*_STEP_DAYS, *_STEP_MONTHS)


def _require_known(frequency: str) -> None:
    if frequency not in _STEP_DAYS and frequency not in _STEP_MONTHS:
        raise ValueError(f"unknown recurrence frequency: {frequency!r}")


def nth_occurrence(anchor: date, frequency: str, index: int) -> date:
    """Occurrence number ``index`` (0 is the anchor), computed from the anchor."""
    _require_known(frequency)
    if index < 0:
        raise ValueError("occurrence index must not be negative")
    if frequency in _STEP_DAYS:
        return anchor + timedelta(days=_STEP_DAYS[frequency] * index)

    total_months = anchor.year * 12 + (anchor.month - 1) + _STEP_MONTHS[frequency] * index
    year, month_zero_based = divmod(total_months, 12)
    month = month_zero_based + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _first_index_on_or_after(anchor: date, frequency: str, day: date) -> int:
    """Smallest occurrence index whose date is on or after ``day``."""
    _require_known(frequency)
    if day <= anchor:
        return 0
    if frequency in _STEP_DAYS:
        step = _STEP_DAYS[frequency]
        # Ceiling division: the first whole number of periods that reaches `day`.
        return -((anchor - day).days // step)

    step = _STEP_MONTHS[frequency]
    months_apart = (day.year - anchor.year) * 12 + (day.month - anchor.month)
    # Every index below ceil(months_apart / step) lands in an earlier month than
    # `day`, so it cannot qualify. At that index the occurrence is in `day`'s own
    # month and may still fall before it (day-of-month clamping or a later day
    # in the month); one step further is then always a later month.
    index = -(-months_apart // step)
    while nth_occurrence(anchor, frequency, index) < day:
        index += 1
    return index


def occurrence_on_or_after(anchor: date, frequency: str, day: date) -> date:
    """The earliest occurrence dated ``day`` or later (``day`` itself counts)."""
    return nth_occurrence(anchor, frequency, _first_index_on_or_after(anchor, frequency, day))


def occurrence_after(anchor: date, frequency: str, day: date) -> date:
    """The earliest occurrence dated strictly after ``day``."""
    return occurrence_on_or_after(anchor, frequency, day + timedelta(days=1))


def occurrences_between(anchor: date, frequency: str, start: date, end: date) -> list[date]:
    """Every occurrence with ``start <= date <= end`` (both bounds inclusive),
    oldest first. Empty when ``end`` precedes ``start`` or the whole range
    precedes the anchor. Sized for forecast horizons (weeks to months), not for
    enumerating years of a weekly bill."""
    if end < start:
        return []
    occurrences: list[date] = []
    index = _first_index_on_or_after(anchor, frequency, start)
    while (occurrence := nth_occurrence(anchor, frequency, index)) <= end:
        occurrences.append(occurrence)
        index += 1
    return occurrences


def is_occurrence(anchor: date, frequency: str, day: date) -> bool:
    """Whether ``day`` is one of the bill's scheduled occurrence dates."""
    return occurrence_on_or_after(anchor, frequency, day) == day
