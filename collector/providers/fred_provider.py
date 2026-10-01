"""FRED (St. Louis Fed) series through the keyless ``fredgraph.csv`` endpoint.

``parse_fred_csv`` is pure and ``fetch_fred_series`` takes an injectable
``fetch`` function, so tests feed fixtures and never open a socket. Network and
parse errors propagate to the caller (``collector/run_macro_job.py`` isolates
them per series). Not registered in ``collector.providers.registry``: it does
not satisfy the ``PriceProvider`` protocol.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Callable
from datetime import date, timedelta

import requests

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
REQUEST_TIMEOUT_SECONDS = 30

Observation = tuple[date, float]
FredFetch = Callable[[str, date | None], str]

# A year-over-year value needs the same month one year earlier; fetch a little
# more than 12 months before the requested start so the first month is covered.
_YOY_EXTRA_LOOKBACK_DAYS = 400


def fetch_fred_csv(series_id: str, start: date | None = None) -> str:
    params = {"id": series_id}
    if start is not None:
        params["cosd"] = start.isoformat()
    response = requests.get(FRED_CSV_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def parse_fred_csv(text: str) -> list[Observation]:
    """Parse ``observation_date,<ID>`` (older exports: ``DATE,<ID>``) into
    ascending ``(date, value)`` pairs. FRED marks a missing value with ``.``;
    those rows are skipped."""
    rows = list(csv.reader(io.StringIO(text.strip())))
    if not rows or len(rows[0]) < 2 or rows[0][0].strip() not in {"observation_date", "DATE"}:
        raise ValueError("Unexpected FRED CSV header")

    observations: list[Observation] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        raw_value = row[1].strip()
        if raw_value in {"", "."}:
            continue
        value = float(raw_value)
        if not math.isfinite(value):
            continue
        observations.append((date.fromisoformat(row[0].strip()), value))
    return sorted(observations)


def year_over_year(levels: list[Observation]) -> list[Observation]:
    """12-month % change of a monthly index: ``(level / level a year ago - 1) * 100``.
    Months without a reading twelve months earlier produce no value."""
    by_month = {(day.year, day.month): value for day, value in levels}
    result: list[Observation] = []
    for day, value in levels:
        previous = by_month.get((day.year - 1, day.month))
        if previous:
            result.append((day, round((value / previous - 1) * 100, 4)))
    return result


def fetch_fred_series(
    series_id: str,
    *,
    start: date | None = None,
    transform: str | None = None,
    fetch: FredFetch = fetch_fred_csv,
) -> list[Observation]:
    """Observations of one FRED series, ascending. With ``transform="yoy"`` the
    index levels are converted to their year-over-year % change."""
    fetch_start = start
    if transform == "yoy" and start is not None:
        fetch_start = start - timedelta(days=_YOY_EXTRA_LOOKBACK_DAYS)
    observations = parse_fred_csv(fetch(series_id, fetch_start))
    return year_over_year(observations) if transform == "yoy" else observations
