"""Macro data pipeline: FRED/Banxico providers, the job and the repository.

No network: providers take an injected ``fetch`` and the job runs against a
fake repository. Only the round-trip test touches the test database.
"""

from __future__ import annotations

from datetime import date

import pytest
import requests

from collector.macro_catalog import catalog_rows
from collector.macro_repository import MacroRepository
from collector.providers.banxico_provider import BanxicoResult, fetch_banxico_series, parse_banxico_response
from collector.providers.fred_provider import fetch_fred_series, parse_fred_csv
from collector.run_macro_job import run_macro_job

# -- Providers -------------------------------------------------------------------------


def test_fred_csv_skips_missing_values_and_converts_index_levels_to_year_over_year() -> None:
    csv_text = (
        "observation_date,CPIAUCSL\n"
        "2024-01-01,100.0\n"
        "2024-02-01,200.0\n"
        "2024-03-01,.\n"
        "2025-01-01,102.5\n"
        "2025-02-01,206.0\n"
        "2025-03-01,210.0\n"  # no valid reading in 2024-03 -> no year-over-year value
    )

    assert parse_fred_csv(csv_text)[:3] == [(date(2024, 1, 1), 100.0), (date(2024, 2, 1), 200.0), (date(2025, 1, 1), 102.5)]
    assert parse_fred_csv("DATE,DFF\n2026-09-30,4.33\n") == [(date(2026, 9, 30), 4.33)]  # older header

    yoy = fetch_fred_series("CPIAUCSL", transform="yoy", fetch=lambda series_id, start: csv_text)

    assert yoy == [(date(2025, 1, 1), pytest.approx(2.5)), (date(2025, 2, 1), pytest.approx(3.0))]


def test_banxico_parse_skips_not_available_rows_and_builds_the_request() -> None:
    payload = {
        "bmx": {
            "series": [
                {
                    "idSerie": "SF43936",
                    "titulo": "Cetes 28 días",
                    "datos": [
                        {"fecha": "29/09/2026", "dato": "7.01"},
                        {"fecha": "22/09/2026", "dato": "N/E"},
                        {"fecha": "15/09/2026", "dato": "6.99"},
                    ],
                },
                {"idSerie": "SP30578", "titulo": "Inflación"},  # SIE omits `datos` when there is nothing
            ]
        }
    }

    assert parse_banxico_response(payload) == {
        "SF43936": [(date(2026, 9, 15), 6.99), (date(2026, 9, 29), 7.01)],
        "SP30578": [],
    }

    calls: list[tuple[str, str]] = []

    def fetch(url: str, token: str) -> dict:
        calls.append((url, token))
        return payload

    result = fetch_banxico_series(
        ["SF43936", "SP30578"], start=date(2026, 9, 1), end=date(2026, 9, 30), token="secret", fetch=fetch
    )

    assert result.status == "ok"
    assert calls == [
        (
            "https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF43936,SP30578/datos/2026-09-01/2026-09-30",
            "secret",
        )
    ]


def test_banxico_without_a_token_is_not_configured_and_never_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BANXICO_TOKEN", raising=False)

    def forbidden(url: str, token: str) -> dict:
        raise AssertionError("no request may be made without a token")

    for token in (None, "   "):
        result = fetch_banxico_series(["SF43936"], start=date(2026, 9, 1), end=date(2026, 9, 30), token=token, fetch=forbidden)
        assert result == BanxicoResult(status="not_configured")


# -- Job -------------------------------------------------------------------------------


class FakeMacroRepository:
    def __init__(self, *, tables_exist: bool = True) -> None:
        self._tables_exist = tables_exist
        self.series_rows: list[dict] = []
        self.observations: dict[str, list[tuple[date, float]]] = {}

    def tables_exist(self) -> bool:
        return self._tables_exist

    def upsert_series(self, rows: list[dict]) -> int:
        self.series_rows = rows
        return len(rows)

    def upsert_observations(self, series_id: str, observations) -> int:
        self.observations[series_id] = list(observations)
        return len(self.observations[series_id])


def test_job_isolates_failing_sources_and_reports_unconfigured_banxico() -> None:
    def fred_fetch(series_id: str, start: date | None) -> str:
        if series_id == "DFF":
            raise requests.ConnectionError("boom")
        return f"observation_date,{series_id}\n2026-09-29,4.1\n2026-09-30,4.2\n"

    def banxico_fetch(url: str, token: str) -> dict:
        raise AssertionError("Banxico must not be called without a token")

    repository = FakeMacroRepository()

    report = run_macro_job(
        repository, today=date(2026, 9, 30), fred_fetch=fred_fetch, banxico_fetch=banxico_fetch, banxico_token=""
    )

    series = report["series"]
    assert series["us_fed_funds"]["status"] == "error"  # raised before us_breakeven_10y ...
    assert series["us_breakeven_10y"] == {"status": "ok", "observations": 2}  # ... which still ran
    assert repository.observations["us_breakeven_10y"] == [(date(2026, 9, 29), 4.1), (date(2026, 9, 30), 4.2)]
    assert series["us_cpi_yoy"]["status"] == "no_data"  # two index levels cannot make a year-over-year value
    banxico_ids = {row["id"] for row in catalog_rows() if row["id"].startswith("mx_")}
    assert {series[series_id]["status"] for series_id in banxico_ids} == {"not_configured"}
    assert report["errors"] == 1
    assert "failed" not in report  # reports/*.json with `failed` would raise a job-failure notification
    assert len(repository.series_rows) == len(catalog_rows())


def test_job_skips_without_fetching_when_the_macro_tables_are_missing() -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("nothing may be fetched while the migration is unapplied")

    report = run_macro_job(FakeMacroRepository(tables_exist=False), fred_fetch=forbidden, banxico_fetch=forbidden)

    assert report["status"] == "skipped"
    assert "0014_macro_series.sql" in report["reason"]


# -- Repository (test database) ----------------------------------------------------------


def test_repository_upsert_overwrites_the_value_and_returns_the_latest_readings(db_connection) -> None:
    repository = MacroRepository(connection=db_connection)
    assert repository.tables_exist()
    repository.upsert_series(catalog_rows())

    repository.upsert_observations("mx_cetes_28d", [(date(2026, 9, 15), 6.99), (date(2026, 9, 22), 7.0)])
    repository.upsert_observations("mx_cetes_28d", [(date(2026, 9, 22), 7.05), (date(2026, 9, 29), 7.1)])

    assert repository.get_recent_observations(["mx_cetes_28d", "us_fed_funds"], 36) == {
        "mx_cetes_28d": [(date(2026, 9, 15), 6.99), (date(2026, 9, 22), 7.05), (date(2026, 9, 29), 7.1)]
    }
    assert repository.get_recent_observations(["mx_cetes_28d"], 2) == {
        "mx_cetes_28d": [(date(2026, 9, 22), 7.05), (date(2026, 9, 29), 7.1)]
    }
