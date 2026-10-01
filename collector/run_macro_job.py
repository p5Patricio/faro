"""Fetch the Mexico/US macro series (``collector/macro_catalog.py``) and upsert
them into ``macro_observations``.

Usage::

    py -3.14 -m collector.run_macro_job [--lookback-days 1100] [--out reports/macro_job.json]

Every source is isolated: a failing FRED series, a failing Banxico request or a
failing write is recorded in the report and the rest still run. Banxico series
report ``not_configured`` while ``BANXICO_TOKEN`` is unset. If the macro tables
are missing (``db/migrations/0014_macro_series.sql`` not applied) or the
database is unreachable, the job logs, reports ``"status": "skipped"`` and
exits 0, so the scheduled daily cycle never depends on it.

The report counts problems under ``errors``, never ``failed``:
``ops/notification_dispatch.py`` reads every ``reports/*.json`` and would turn a
``failed`` count into a job-failure notification, and macro data is non-fatal.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from collector.local_repository import LocalPostgresConfig
from collector.macro_catalog import MACRO_SERIES, catalog_rows
from collector.macro_repository import MacroRepository
from collector.providers.banxico_provider import BanxicoFetch, fetch_banxico_json, fetch_banxico_series
from collector.providers.fred_provider import FredFetch, fetch_fred_csv, fetch_fred_series

logger = logging.getLogger("faro.macro")

# ~3 years: enough to fill the 36 monthly points the overview shows.
DEFAULT_LOOKBACK_DAYS = 1100

MIGRATION_HINT = "apply db/migrations/0014_macro_series.sql (py -3.14 -m db.migrate)"


def _skipped(reason: str) -> dict[str, Any]:
    logger.warning("macro job skipped: %s", reason)
    return {"status": "skipped", "reason": reason, "series": {}, "errors": 0}


def _record_error(report: dict[str, Any], series_id: str, error: Exception) -> None:
    logger.warning("macro series %s failed: %s: %s", series_id, type(error).__name__, error)
    report["series"][series_id] = {"status": "error", "detail": f"{type(error).__name__}: {error}"}
    report["errors"] += 1


def _store(
    repository: MacroRepository, report: dict[str, Any], series_id: str, observations: list[tuple[date, float]]
) -> None:
    count = repository.upsert_observations(series_id, observations)
    report["series"][series_id] = {"status": "ok" if count else "no_data", "observations": count}


def run_macro_job(
    repository: MacroRepository,
    *,
    today: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    fred_fetch: FredFetch = fetch_fred_csv,
    banxico_fetch: BanxicoFetch = fetch_banxico_json,
    banxico_token: str | None = None,
) -> dict[str, Any]:
    today = today or datetime.now(tz=UTC).date()
    start = today - timedelta(days=lookback_days)

    try:
        if not repository.tables_exist():
            return _skipped(f"macro tables are missing; {MIGRATION_HINT}")
        repository.upsert_series(catalog_rows())
    except RuntimeError as error:
        return _skipped(f"database error: {error}")

    report: dict[str, Any] = {"status": "ok", "series": {}, "errors": 0}

    for series in (s for s in MACRO_SERIES if s.provider == "fred"):
        try:
            observations = fetch_fred_series(
                series.provider_id, start=start, transform=series.transform, fetch=fred_fetch
            )
            _store(repository, report, series.id, observations)
        except Exception as error:  # isolation boundary: one series must not stop the others
            _record_error(report, series.id, error)

    banxico_series = [s for s in MACRO_SERIES if s.provider == "banxico"]
    try:
        result = fetch_banxico_series(
            [s.provider_id for s in banxico_series],
            start=start,
            end=today,
            token=banxico_token,
            fetch=banxico_fetch,
        )
    except Exception as error:  # isolation boundary
        for series in banxico_series:
            _record_error(report, series.id, error)
        return report

    for series in banxico_series:
        if result.status == "not_configured":
            report["series"][series.id] = {"status": "not_configured"}
            continue
        try:
            _store(repository, report, series.id, result.observations.get(series.provider_id, []))
        except Exception as error:  # isolation boundary
            _record_error(report, series.id, error)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Mexico/US macro series into macro_observations")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--out", help="Optional JSON report path (the report is always printed too)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    try:
        with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
            report = run_macro_job(MacroRepository(connection=connection), lookback_days=args.lookback_days)
    except (psycopg.Error, RuntimeError) as error:  # unreachable database or no DSN configured
        report = _skipped(f"database unavailable: {type(error).__name__}")

    text = json.dumps(report, indent=2, default=str)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
