"""Phase 2 (Ingestion): `collector.fundamentals.parse_company_facts` +
`collector.run_fundamental_ingestion.run_fundamental_ingestion`.

Requirement "XBRL Fact Ingestion" is the acceptance contract. Every fetch is
audited (one `ingestion_runs` row per fetch, emitted by the SEC client's own
`RepositoryIngestionRecorder`), one job-summary row closes the run, an
unresolved CIK is surfaced in that summary rather than silently skipped, and
the `--out` report carries a per-logical-concept coverage map that gates
Phase 3. No test opens a socket -- every fetch goes through a fake `session`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from collector.fundamentals import ALLOWED_TAGS, CONCEPT_CHAINS, parse_company_facts
from collector.ingestion_audit import RepositoryIngestionRecorder
from collector.providers.sec_edgar_client import SecEdgarClient, SecEdgarConfig, pad_cik
from collector.run_fundamental_ingestion import run_fundamental_ingestion

FIXTURE = Path(__file__).parent / "fixtures" / "companyfacts_fake.json"
TEST_USER_AGENT = "Faro Test Suite tests@faro.example"


def _payload() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _expected_row_count(payload: dict[str, Any]) -> int:
    total = 0
    for taxonomy, concepts in payload["facts"].items():
        for concept, body in concepts.items():
            if (taxonomy, concept) not in ALLOWED_TAGS:
                continue
            for entries in body["units"].values():
                total += len(entries)
    return total


# ---------------------------------------------------------------------------
# parse_company_facts
# ---------------------------------------------------------------------------


def test_parse_company_facts_maps_filed_and_period_end_one_to_one() -> None:
    payload = _payload()

    rows = parse_company_facts(payload, asset_id="asset-1")

    assert len(rows) == _expected_row_count(payload)
    # Every row keeps `period_end` (SEC `end`) and `filed_date` (SEC `filed`)
    # as distinct, independently carried values.
    assert all(row["period_end"] != row["filed_date"] for row in rows)

    original = next(
        r for r in rows if r["concept"] == "Assets" and r["filed_date"] == "2023-02-15"
    )
    assert original == {
        "asset_id": "asset-1",
        "taxonomy": "us-gaap",
        "concept": "Assets",
        "unit": "USD",
        "period_end": "2022-12-31",
        "fiscal_year": 2022,
        "fiscal_period": "FY",
        "filed_date": "2023-02-15",
        "accession": "0000320193-23-000001",
        "value": 1200.0,
    }

    # The restatement is a second row for the same period_end at a later filing.
    assets_2022 = {
        (r["filed_date"], r["value"])
        for r in rows
        if r["concept"] == "Assets" and r["period_end"] == "2022-12-31"
    }
    assert assets_2022 == {("2023-02-15", 1200.0), ("2023-11-01", 1150.0)}

    # Tag-fallback case: both raw SEC tags are stored verbatim, never collapsed
    # to a logical "revenue" name (Phase 3 interprets the chain at read time).
    concepts = {r["concept"] for r in rows}
    assert "SalesRevenueNet" in concepts
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in concepts


def test_parse_company_facts_absent_fp_becomes_empty_string() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {"end": "2022-12-31", "val": 10, "filed": "2023-02-15", "fy": 2022},
                        ]
                    }
                }
            }
        }
    }

    rows = parse_company_facts(payload, asset_id="asset-1")

    assert len(rows) == 1
    # NOT None -- fiscal_period is a NOT NULL key column.
    assert rows[0]["fiscal_period"] == ""


def test_parse_company_facts_ignores_non_allowlisted_concepts() -> None:
    payload = _payload()

    rows = parse_company_facts(payload, asset_id="asset-1")

    assert ("us-gaap", "MarketableSecuritiesCurrent") not in ALLOWED_TAGS
    assert all(row["concept"] != "MarketableSecuritiesCurrent" for row in rows)


def test_parse_company_facts_skips_entries_missing_end_filed_or_val() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {"val": 1, "filed": "2023-02-15"},                 # no end
                            {"end": "2022-12-31", "val": 2},                    # no filed
                            {"end": "2022-12-31", "filed": "2023-02-15"},       # no val
                            {"end": "2022-12-31", "val": "n/a", "filed": "2023-02-15"},  # non-numeric
                            {"end": "2022-12-31", "val": True, "filed": "2023-02-15"},   # bool is not numeric
                            {"end": "2022-12-31", "val": 9, "filed": "2023-02-15", "fp": "FY"},  # kept
                        ]
                    }
                }
            }
        }
    }

    rows = parse_company_facts(payload, asset_id="asset-1")

    assert len(rows) == 1
    assert rows[0]["value"] == 9.0


def test_parse_company_facts_in_batch_dedupe_keeps_last() -> None:
    # companyfacts repeats an identical fact across the 10-Q and the 10-K; the
    # parser keeps the LAST occurrence in SEC's own list order.
    payload = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {"end": "2022-12-31", "val": 100, "filed": "2023-02-15", "fp": "FY"},
                            {"end": "2022-12-31", "val": 999, "filed": "2023-02-15", "fp": "FY"},
                        ]
                    }
                }
            }
        }
    }

    rows = parse_company_facts(payload, asset_id="asset-1")

    assert len(rows) == 1
    assert rows[0]["value"] == 999.0


def test_allowed_tags_is_derived_from_concept_chains() -> None:
    derived = frozenset(
        pair for _unit, chain in CONCEPT_CHAINS.values() for pair in chain
    )
    assert ALLOWED_TAGS == derived
    # Open Question 3: the two shares chains are distinct logical concepts.
    assert "shares_outstanding_mve" in CONCEPT_CHAINS
    assert "shares_outstanding_wavg" in CONCEPT_CHAINS
    assert CONCEPT_CHAINS["shares_outstanding_mve"] != CONCEPT_CHAINS["shares_outstanding_wavg"]


# ---------------------------------------------------------------------------
# run_fundamental_ingestion
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers: dict[str, str] = {}

    def json(self) -> object:
        return self._payload


class FakeFactsSession:
    """Maps a padded CIK URL to a canned SEC response (or an exception to
    raise). Robust to fetch ordering, unlike a positional response list."""

    def __init__(self, by_padded_cik: dict[str, Any]) -> None:
        self._by = dict(by_padded_cik)
        self.requests: list[dict[str, Any]] = []

    def get(self, url: str, headers: dict | None = None, timeout: int | None = None) -> FakeResponse:
        self.requests.append({"url": url, "headers": headers})
        padded = url.rsplit("/", 1)[-1][: -len(".json")]
        resp = self._by[padded]
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeFundamentalRepository:
    """Offline stand-in covering exactly the surface the job and the SEC
    client's recorder touch."""

    def __init__(self, identifiers: list[tuple[str, str]]) -> None:
        self._identifiers = [
            {"asset_id": asset_id, "id_type": "cik", "id_value": id_value}
            for asset_id, id_value in identifiers
        ]
        self.fundamental_facts: list[dict[str, Any]] = []
        self.ingestion_runs: list[dict[str, Any]] = []

    def get_asset_identifiers(self, id_type: str | None = None) -> list[dict[str, Any]]:
        if id_type is None:
            return list(self._identifiers)
        return [row for row in self._identifiers if row["id_type"] == id_type]

    def upsert_fundamental_facts(self, rows: list[dict[str, Any]], batch_size: int = 500) -> int:
        self.fundamental_facts.extend(rows)
        return len(rows)

    def insert_ingestion_run(self, **kwargs: Any) -> dict[str, Any]:
        run = {"id": f"run-{len(self.ingestion_runs) + 1}", **kwargs}
        self.ingestion_runs.append(run)
        return run

    # test helpers ---------------------------------------------------------
    def fetch_runs(self) -> list[dict[str, Any]]:
        return [r for r in self.ingestion_runs if r["endpoint"] == "companyfacts"]

    def summary_run(self) -> dict[str, Any]:
        summaries = [r for r in self.ingestion_runs if r["endpoint"] == "fundamental_ingestion"]
        assert len(summaries) == 1
        return summaries[0]


def _client(session: Any, repository: Any) -> SecEdgarClient:
    return SecEdgarClient(
        config=SecEdgarConfig(user_agent=TEST_USER_AGENT),
        session=session,
        sleep=lambda _seconds: None,
        monotonic=lambda: 0.0,
        recorder=RepositoryIngestionRecorder(repository),
    )


def _facts_payload(concepts: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "cik": 1,
        "facts": {
            "us-gaap": {
                concept: {"units": {"USD": entries}} for concept, entries in concepts.items()
            }
        },
    }


def _entry(val: float, *, end: str = "2022-12-31", filed: str) -> dict[str, Any]:
    return {"end": end, "val": val, "filed": filed, "fy": 2022, "fp": "FY", "accn": "acc-1"}


def test_run_fundamental_ingestion_audits_every_fetch() -> None:
    repository = FakeFundamentalRepository(
        [("asset-A", "0000000001"), ("asset-B", "0000000002")]
    )
    session = FakeFactsSession(
        {
            pad_cik("0000000001"): FakeResponse(
                200, payload=_facts_payload({"Assets": [_entry(100, filed="2023-02-15")]})
            ),
            pad_cik("0000000002"): FakeResponse(403, text="Forbidden"),
        }
    )
    client = _client(session, repository)

    report = run_fundamental_ingestion(
        repository, client, ciks=["1", "2", "3"], limit=None
    )

    # A's facts landed; B failed but did not abort the run; C was never fetched.
    assert [r["concept"] for r in repository.fundamental_facts] == ["Assets"]
    assert repository.fundamental_facts[0]["asset_id"] == "asset-A"

    # Exactly one per-fetch ingestion_runs row per fetch (client recorder), and
    # C (no asset_identifiers row) is not fetched.
    fetch_runs = repository.fetch_runs()
    assert len(fetch_runs) == 2
    assert {r["status"] for r in fetch_runs} == {"success", "failure"}

    # The failed fetch is audited by reason only; no SEC_USER_AGENT anywhere.
    summary = repository.summary_run()
    assert summary["error"] is None
    assert summary["metadata"]["failed_ciks"] == [
        {"cik": "0000000002", "reason": "sec_client_error"}
    ]
    assert summary["metadata"]["unresolved_ciks"] == ["0000000003"]
    assert TEST_USER_AGENT not in json.dumps(summary["metadata"])
    assert report["failed_ciks"] == [{"cik": "0000000002", "reason": "sec_client_error"}]
    assert report["unresolved_ciks"] == ["0000000003"]


def test_run_fundamental_ingestion_job_summary_row() -> None:
    repository = FakeFundamentalRepository([("asset-A", "0000000001")])
    session = FakeFactsSession(
        {
            pad_cik("0000000001"): FakeResponse(
                200,
                payload=_facts_payload(
                    {
                        "Assets": [
                            _entry(100, filed="2023-02-15"),
                            _entry(90, filed="2023-11-01"),
                        ],
                        "Liabilities": [_entry(40, filed="2023-02-15")],
                    }
                ),
            )
        }
    )
    client = _client(session, repository)

    report = run_fundamental_ingestion(repository, client)

    summary = repository.summary_run()
    assert summary["source"] == "sec_edgar"
    assert summary["endpoint"] == "fundamental_ingestion"
    assert summary["target_key"] == ""
    assert summary["status"] == "success"
    assert summary["request_count"] == 1
    assert summary["rows_written"] == len(repository.fundamental_facts) == 3
    assert summary["max_filed_date"] == "2023-11-01"
    assert set(summary["metadata"]) == {
        "failed_ciks",
        "assets_processed",
        "assets_with_no_facts",
        "unresolved_ciks",
    }
    assert summary["metadata"]["assets_processed"] == 1
    assert summary["metadata"]["assets_with_no_facts"] == []
    assert report["max_filed_date"] == "2023-11-01"
    # The report is the --out payload: it must be JSON-serializable.
    json.dumps(report, indent=2)


def test_run_fundamental_ingestion_report_has_per_concept_coverage() -> None:
    repository = FakeFundamentalRepository(
        [("asset-A", "0000000001"), ("asset-B", "0000000002")]
    )
    session = FakeFactsSession(
        {
            pad_cik("0000000001"): FakeResponse(
                200,
                payload=_facts_payload(
                    {
                        "Assets": [_entry(100, filed="2023-02-15")],
                        "Revenues": [_entry(500, filed="2023-02-15")],
                    }
                ),
            ),
            pad_cik("0000000002"): FakeResponse(
                200, payload=_facts_payload({"Assets": [_entry(200, filed="2023-02-15")]})
            ),
        }
    )
    client = _client(session, repository)

    report = run_fundamental_ingestion(repository, client)

    coverage = report["per_concept_coverage"]
    # Every logical concept is a key, even at zero coverage (Phase 3 gate).
    assert set(coverage) == set(CONCEPT_CHAINS)
    assert coverage["assets"] == 2
    assert coverage["revenue"] == 1
    assert coverage["equity"] == 0


def test_run_fundamental_ingestion_records_cik_with_no_facts() -> None:
    repository = FakeFundamentalRepository([("asset-A", "0000000001")])
    session = FakeFactsSession(
        {pad_cik("0000000001"): FakeResponse(200, payload={"cik": 1, "facts": {}})}
    )
    client = _client(session, repository)

    report = run_fundamental_ingestion(repository, client)

    assert repository.fundamental_facts == []
    assert report["assets_with_no_facts"] == ["0000000001"]
    assert repository.summary_run()["metadata"]["assets_with_no_facts"] == ["0000000001"]
    assert report["assets_processed"] == 1
    assert repository.fetch_runs()[0]["status"] == "success"


def test_run_fundamental_ingestion_limit_caps_processed_assets() -> None:
    repository = FakeFundamentalRepository(
        [("asset-A", "0000000001"), ("asset-B", "0000000002")]
    )
    session = FakeFactsSession(
        {
            pad_cik("0000000001"): FakeResponse(
                200, payload=_facts_payload({"Assets": [_entry(1, filed="2023-02-15")]})
            ),
            pad_cik("0000000002"): FakeResponse(
                200, payload=_facts_payload({"Assets": [_entry(2, filed="2023-02-15")]})
            ),
        }
    )
    client = _client(session, repository)

    report = run_fundamental_ingestion(repository, client, limit=1)

    assert len(repository.fetch_runs()) == 1
    assert report["request_count"] == 1
