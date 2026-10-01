from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers.macro import get_macro_repository

INFLATION_IDS = ["mx_inflation_yoy", "mx_core_inflation_yoy", "us_cpi_yoy", "us_core_cpi_yoy"]
RATE_IDS = [
    "mx_policy_rate",
    "mx_tiie28",
    "mx_cetes_28d",
    "mx_cetes_91d",
    "mx_cetes_182d",
    "mx_cetes_364d",
    "us_fed_funds",
    "us_breakeven_10y",
]
ITEM_KEYS = {"series_id", "label", "country", "unit", "frequency", "source", "status", "latest", "previous", "history"}


class FakeMacroRepository:
    def __init__(self, observations: dict[str, list[tuple[date, float]]]) -> None:
        self._observations = observations
        self.limits: list[int] = []

    def get_recent_observations(self, series_ids, limit: int) -> dict[str, list[tuple[date, float]]]:
        self.limits.append(limit)
        return {series_id: self._observations[series_id] for series_id in series_ids if series_id in self._observations}


class RaisingMacroRepository:
    def get_recent_observations(self, series_ids, limit: int):
        raise RuntimeError('relation "macro_observations" does not exist')


@pytest.fixture()
def use() -> Iterator:
    def _use(repository) -> TestClient:
        app.dependency_overrides[get_macro_repository] = lambda: repository
        return TestClient(app)

    yield _use
    app.dependency_overrides.clear()


def _days_ago(days: int) -> date:
    return datetime.now(tz=UTC).date() - timedelta(days=days)


def test_overview_reports_status_per_series_and_the_real_rate(use, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BANXICO_TOKEN", raising=False)
    repository = FakeMacroRepository(
        {
            "mx_inflation_yoy": [(_days_ago(50), 3.5), (_days_ago(20), 4.0)],
            "mx_cetes_364d": [(_days_ago(10), 7.5), (_days_ago(3), 8.0)],
            "us_fed_funds": [(_days_ago(30), 4.33)],  # daily series 30 days old -> stale
        }
    )
    client = use(repository)

    response = client.get("/api/macro/overview")

    assert response.status_code == 200
    body = response.json()
    assert datetime.fromisoformat(body["as_of"]).tzinfo is not None
    assert repository.limits == [36]
    inflation, rates = body["sections"]
    assert (inflation["key"], inflation["label"]) == ("inflation", "Inflación")
    assert (rates["key"], rates["label"]) == ("rates", "Tasas")
    assert [item["series_id"] for item in inflation["items"]] == INFLATION_IDS
    assert [item["series_id"] for item in rates["items"]] == RATE_IDS
    assert all(set(item) == ITEM_KEYS for item in inflation["items"] + rates["items"])

    by_id = {item["series_id"]: item for item in inflation["items"] + rates["items"]}
    cpi = by_id["mx_inflation_yoy"]
    assert cpi["status"] == "ok"
    assert cpi["latest"] == {"date": _days_ago(20).isoformat(), "value": 4.0}
    assert cpi["previous"] == {"date": _days_ago(50).isoformat(), "value": 3.5}
    assert [point["value"] for point in cpi["history"]] == [3.5, 4.0]  # ascending
    assert (cpi["country"], cpi["unit"], cpi["frequency"]) == ("MX", "percent", "monthly")
    assert by_id["us_fed_funds"]["status"] == "stale"
    assert by_id["us_fed_funds"]["previous"] is None
    no_data = by_id["us_cpi_yoy"]
    assert (no_data["status"], no_data["latest"], no_data["previous"], no_data["history"]) == ("no_data", None, None, [])
    assert by_id["mx_core_inflation_yoy"]["status"] == "not_configured"  # Banxico series, no token
    assert body["real_rate"] == {"cetes_364d": 8.0, "inflation": 4.0, "real_rate": 3.85}  # (1.08 / 1.04 - 1) * 100

    monkeypatch.setenv("BANXICO_TOKEN", "configured")
    by_id = {item["series_id"]: item for section in client.get("/api/macro/overview").json()["sections"] for item in section["items"]}
    assert by_id["mx_core_inflation_yoy"]["status"] == "no_data"


def test_overview_real_rate_is_null_when_an_input_is_missing(use) -> None:
    client = use(FakeMacroRepository({"mx_cetes_364d": [(_days_ago(3), 8.0)]}))

    assert client.get("/api/macro/overview").json()["real_rate"] is None


def test_overview_answers_503_without_demo_data_when_the_database_is_unavailable(use) -> None:
    # No repository at all (database unreachable) and a repository whose tables are missing.
    for repository in (None, RaisingMacroRepository()):
        response = use(repository).get("/api/macro/overview")

        assert response.status_code == 503
        assert isinstance(response.json()["detail"], str)
