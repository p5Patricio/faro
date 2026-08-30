from __future__ import annotations

from typing import Any

import pytest
import requests

from collector.ingestion_audit import RepositoryIngestionRecorder
from collector.local_repository import LocalPostgresRepository
from collector.providers.sec_edgar_client import (
    MAX_RETRIES,
    MIN_REQUEST_INTERVAL_SECONDS,
    SEC_DATA_BASE,
    SEC_WWW_BASE,
    IngestionRun,
    SecEdgarClient,
    SecEdgarConfig,
    SecEdgarConfigError,
    pad_cik,
)
from collector.run_identifier_resolution import run_identifier_resolution

DEFAULT_USER_AGENT = "Faro Ops Team ops@faro.example"


class FakeResponse:
    """Extends `tests/test_collector_providers.py`'s `FakeResponse` pattern
    with `status_code`/`headers`, since the SEC client branches on status
    codes and honors `Retry-After`."""

    def __init__(
        self,
        status_code: int = 200,
        payload: object = None,
        text: str = "",
        headers: dict[str, str] | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self._json_error = json_error

    def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeSession:
    """Extends `tests/test_collector_providers.py:23`'s `FakeSession` with
    `headers` capture, so tests can assert `User-Agent` was sent."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def get(self, url: str, headers: dict | None = None, timeout: int | None = None) -> FakeResponse:
        self.requests.append({"url": url, "headers": headers, "timeout": timeout})
        return self.responses.pop(0)


class RaisingSession:
    """Simulates a transport-level failure (DNS/connection error) before any
    HTTP response is received."""

    def __init__(self, message: str) -> None:
        self.message = message
        self.requests: list[dict] = []

    def get(self, url: str, headers: dict | None = None, timeout: int | None = None) -> FakeResponse:
        self.requests.append({"url": url, "headers": headers, "timeout": timeout})
        raise requests.ConnectionError(self.message)


class FakeRecorder:
    def __init__(self) -> None:
        self.runs: list[IngestionRun] = []

    def record(self, run: IngestionRun) -> None:
        self.runs.append(run)


def _client(session, *, recorder=None, sleeps=None, monotonic=None, config=...) -> SecEdgarClient:
    resolved_config = SecEdgarConfig(user_agent=DEFAULT_USER_AGENT) if config is ... else config
    return SecEdgarClient(
        config=resolved_config,
        session=session,
        sleep=(sleeps.append if sleeps is not None else lambda _seconds: None),
        monotonic=monotonic or (lambda: 0.0),
        recorder=recorder,
    )


# -- pad_cik --


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("320193", "CIK0000320193"),
        ("0000320193", "CIK0000320193"),
        ("CIK0000320193", "CIK0000320193"),
        (320193, "CIK0000320193"),
    ],
)
def test_pad_cik(raw: object, expected: str) -> None:
    assert pad_cik(raw) == expected


# -- SecEdgarConfig.from_env --


def test_from_env_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert SecEdgarConfig.from_env() is None


def test_from_env_returns_none_when_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "   ")
    assert SecEdgarConfig.from_env() is None


def test_from_env_reads_configured_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", DEFAULT_USER_AGENT)
    assert SecEdgarConfig.from_env() == SecEdgarConfig(user_agent=DEFAULT_USER_AGENT)


# -- Missing User-Agent fails loudly (spec scenario) --


def test_missing_user_agent_raises_before_any_request() -> None:
    session = FakeSession([])
    recorder = FakeRecorder()
    client = _client(session, recorder=recorder, config=None)

    with pytest.raises(SecEdgarConfigError):
        client.fetch_company_tickers()

    assert session.requests == []
    assert len(recorder.runs) == 1
    run = recorder.runs[0]
    assert run.status == "failure"
    assert run.error == "missing_sec_user_agent"
    assert run.request_count == 0


def test_missing_user_agent_raises_for_every_fetch_method() -> None:
    session = FakeSession([])
    client = _client(session, config=None)

    with pytest.raises(SecEdgarConfigError):
        client.fetch_company_facts("320193")
    with pytest.raises(SecEdgarConfigError):
        client.fetch_submissions("320193")

    assert session.requests == []


# -- URL construction / User-Agent header --


def test_fetch_company_tickers_uses_bulk_endpoint() -> None:
    session = FakeSession([FakeResponse(200, payload={"0": {"cik_str": 320193, "ticker": "AAPL"}})])
    client = _client(session)

    client.fetch_company_tickers()

    assert session.requests[0]["url"] == f"{SEC_WWW_BASE}/files/company_tickers.json"


def test_fetch_company_facts_pads_cik_into_url() -> None:
    session = FakeSession([FakeResponse(200, payload={"cik": 320193})])
    client = _client(session)

    client.fetch_company_facts("320193")

    assert session.requests[0]["url"] == f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK0000320193.json"


def test_fetch_submissions_pads_cik_into_url() -> None:
    session = FakeSession([FakeResponse(200, payload={"cik": 320193})])
    client = _client(session)

    client.fetch_submissions("320193")

    assert session.requests[0]["url"] == f"{SEC_DATA_BASE}/submissions/CIK0000320193.json"


def test_every_request_sends_configured_user_agent() -> None:
    session = FakeSession([FakeResponse(200, payload={})])
    client = _client(session)

    client.fetch_company_tickers()

    assert session.requests[0]["headers"]["User-Agent"] == DEFAULT_USER_AGENT


# -- Success / payload fidelity --


def test_success_returns_ok_true_with_status_code() -> None:
    session = FakeSession([FakeResponse(200, payload={"a": 1})])
    client = _client(session)

    result = client.fetch_company_tickers()

    assert result == {"ok": True, "payload": {"a": 1}, "status_code": 200}


def test_success_returns_provider_payload_unmodified() -> None:
    """Payload fidelity: the client must not flatten or project XBRL facts --
    a sibling change's `filed`-date extraction depends on nothing being lost
    here."""
    payload = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": "2023-12-31", "val": 100, "filed": "2024-02-01", "form": "10-K"},
                        ]
                    }
                }
            }
        },
    }
    session = FakeSession([FakeResponse(200, payload=payload)])
    client = _client(session)

    result = client.fetch_company_facts("320193")

    assert result["payload"] == payload
    assert (
        result["payload"]["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["filed"] == "2024-02-01"
    )


# -- Transport failures never raise --


def test_client_error_returns_typed_failure_without_raising() -> None:
    session = FakeSession([FakeResponse(403, text="Forbidden")])
    client = _client(session)

    result = client.fetch_company_tickers()

    assert result["ok"] is False
    assert result["reason"] == "sec_client_error"


def test_network_error_returns_typed_failure_without_raising() -> None:
    session = RaisingSession("connection refused")
    client = _client(session)

    result = client.fetch_company_tickers()

    assert result == {"ok": False, "reason": "sec_request_failed", "detail": "connection refused"}


def test_bad_json_returns_typed_failure_without_raising() -> None:
    session = FakeSession([FakeResponse(200, json_error=ValueError("not json"))])
    client = _client(session)

    result = client.fetch_company_tickers()

    assert result["ok"] is False
    assert result["reason"] == "sec_invalid_json"


# -- 429 backoff (spec: "429 triggers backoff, not silent failure") --


def test_429_honors_retry_after_then_succeeds() -> None:
    session = FakeSession(
        [
            FakeResponse(429, headers={"Retry-After": "2"}),
            FakeResponse(200, payload={"ok": True}),
        ]
    )
    sleeps: list[float] = []
    recorder = FakeRecorder()
    client = _client(session, recorder=recorder, sleeps=sleeps)

    result = client.fetch_company_tickers()

    assert result == {"ok": True, "payload": {"ok": True}, "status_code": 200}
    assert 2.0 in sleeps
    assert len(session.requests) == 2
    assert len(recorder.runs) == 1
    run = recorder.runs[0]
    assert run.status == "success"
    assert run.metadata == {"failure_kind": "rate_limited"}
    assert run.request_count == 2


def test_429_exhausts_retries_and_returns_rate_limited() -> None:
    session = FakeSession(
        [FakeResponse(429, headers={"Retry-After": "1"}) for _ in range(MAX_RETRIES + 1)]
    )
    recorder = FakeRecorder()
    client = _client(session, recorder=recorder)

    result = client.fetch_company_tickers()

    assert result["ok"] is False
    assert result["reason"] == "sec_rate_limited"
    assert len(session.requests) == MAX_RETRIES + 1
    run = recorder.runs[0]
    assert run.status == "failure"
    assert run.error is not None and run.error.startswith("sec_rate_limited")
    assert run.metadata == {"failure_kind": "rate_limited"}


# -- 5xx backoff --


def test_5xx_retries_then_succeeds() -> None:
    session = FakeSession([FakeResponse(503, text="unavailable"), FakeResponse(200, payload={"ok": True})])
    sleeps: list[float] = []
    client = _client(session, sleeps=sleeps)

    result = client.fetch_company_tickers()

    assert result == {"ok": True, "payload": {"ok": True}, "status_code": 200}
    assert 2 in sleeps


def test_5xx_exhausts_retries_and_returns_server_error() -> None:
    session = FakeSession([FakeResponse(503, text="unavailable") for _ in range(MAX_RETRIES + 1)])
    client = _client(session)

    result = client.fetch_company_tickers()

    assert result["ok"] is False
    assert result["reason"] == "sec_server_error"
    assert len(session.requests) == MAX_RETRIES + 1


# -- Throttle: min_interval between request starts, zero real wall-clock time --


def test_throttle_waits_the_remaining_gap_to_min_interval() -> None:
    session = FakeSession([FakeResponse(200, payload={"a": 1}), FakeResponse(200, payload={"b": 2})])
    monotonic_values = iter([0.0, 0.05])  # second request starts 0.05s after the first
    sleeps: list[float] = []
    client = _client(session, sleeps=sleeps, monotonic=lambda: next(monotonic_values))

    client.fetch_company_tickers()
    client.fetch_company_facts("320193")

    assert sleeps == [pytest.approx(MIN_REQUEST_INTERVAL_SECONDS - 0.05)]


def test_throttle_skips_wait_when_elapsed_exceeds_min_interval() -> None:
    session = FakeSession([FakeResponse(200, payload={"a": 1}), FakeResponse(200, payload={"b": 2})])
    monotonic_values = iter([0.0, 5.0])  # plenty of real time already elapsed
    sleeps: list[float] = []
    client = _client(session, sleeps=sleeps, monotonic=lambda: next(monotonic_values))

    client.fetch_company_tickers()
    client.fetch_company_facts("320193")

    assert sleeps == []


# -- ingestion_runs on every exit path --


def test_recorder_gets_one_run_per_method_call_on_success() -> None:
    session = FakeSession([FakeResponse(200, payload={"a": 1})])
    recorder = FakeRecorder()
    client = _client(session, recorder=recorder)

    client.fetch_company_tickers()

    assert len(recorder.runs) == 1
    run = recorder.runs[0]
    assert run.source == "sec_edgar"
    assert run.endpoint == "company_tickers"
    assert run.target_key == ""
    assert run.status == "success"
    assert run.http_status == 200
    assert run.rows_written == 1
    assert run.error is None


def test_recorder_gets_one_run_with_target_key_for_facts() -> None:
    session = FakeSession([FakeResponse(200, payload={"cik": 320193})])
    recorder = FakeRecorder()
    client = _client(session, recorder=recorder)

    client.fetch_company_facts("320193")

    run = recorder.runs[0]
    assert run.endpoint == "companyfacts"
    assert run.target_key == "CIK0000320193"


@pytest.mark.parametrize(
    "response,expected_reason",
    [
        (FakeResponse(403, text="Forbidden"), "sec_client_error"),
        (FakeResponse(200, json_error=ValueError("bad json")), "sec_invalid_json"),
    ],
)
def test_recorder_gets_exactly_one_failure_run_per_reason(response: FakeResponse, expected_reason: str) -> None:
    session = FakeSession([response])
    recorder = FakeRecorder()
    client = _client(session, recorder=recorder)

    result = client.fetch_company_tickers()

    assert result["reason"] == expected_reason
    assert len(recorder.runs) == 1
    assert recorder.runs[0].status == "failure"
    assert recorder.runs[0].error is not None and recorder.runs[0].error.startswith(expected_reason)


def test_recorder_gets_one_run_for_a_network_failure() -> None:
    session = RaisingSession("boom")
    recorder = FakeRecorder()
    client = _client(session, recorder=recorder)

    client.fetch_company_tickers()

    assert len(recorder.runs) == 1
    run = recorder.runs[0]
    assert run.status == "failure"
    assert run.error == "sec_request_failed: boom"
    assert run.http_status is None


def test_no_recorder_attached_does_not_raise() -> None:
    session = FakeSession([FakeResponse(200, payload={"a": 1})])
    client = SecEdgarClient(
        config=SecEdgarConfig(user_agent=DEFAULT_USER_AGENT),
        session=session,
        sleep=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )

    result = client.fetch_company_tickers()

    assert result["ok"] is True


# -- Redaction: SEC_USER_AGENT (operator email) must never leak --


def test_user_agent_never_leaks_into_client_error_detail() -> None:
    leaking_text = f"Blocked request from User-Agent: {DEFAULT_USER_AGENT}"
    session = FakeSession([FakeResponse(403, text=leaking_text, json_error=ValueError("no json body"))])
    client = _client(session)

    result = client.fetch_company_tickers()

    assert DEFAULT_USER_AGENT not in result["detail"]
    assert "***" in result["detail"]


def test_user_agent_never_leaks_into_server_error_detail() -> None:
    leaking_text = f"Blocked request from User-Agent: {DEFAULT_USER_AGENT}"
    session = FakeSession(
        [
            FakeResponse(503, text=leaking_text, json_error=ValueError("no json body"))
            for _ in range(MAX_RETRIES + 1)
        ]
    )
    client = _client(session)

    result = client.fetch_company_tickers()

    assert DEFAULT_USER_AGENT not in result["detail"]
    assert "***" in result["detail"]


def test_user_agent_never_leaks_into_network_error_detail() -> None:
    session = RaisingSession(f"failed for {DEFAULT_USER_AGENT}")
    client = _client(session)

    result = client.fetch_company_tickers()

    assert DEFAULT_USER_AGENT not in result["detail"]
    assert "***" in result["detail"]


def test_user_agent_never_leaks_into_recorded_ingestion_run() -> None:
    leaking_text = f"echo: {DEFAULT_USER_AGENT}"
    session = FakeSession([FakeResponse(403, text=leaking_text, json_error=ValueError("no json body"))])
    recorder = FakeRecorder()
    client = _client(session, recorder=recorder)

    client.fetch_company_tickers()

    run = recorder.runs[0]
    assert DEFAULT_USER_AGENT not in str(run.error)
    assert DEFAULT_USER_AGENT not in str(run.metadata)


def test_user_agent_never_leaks_across_every_failure_case_and_config_error() -> None:
    """Closes task 4.10 across every case in 4.6-4.9: no returned dict,
    error string, or recorded `IngestionRun` field carries the raw
    `SEC_USER_AGENT` value in any of the covered failure paths."""
    leaking_text = f"echo: {DEFAULT_USER_AGENT}"

    def leaking_response(status: int) -> FakeResponse:
        return FakeResponse(status, text=leaking_text, json_error=ValueError("no json body"))

    cases: list[SecEdgarClient] = [
        _client(FakeSession([leaking_response(403)])),
        _client(FakeSession([leaking_response(503) for _ in range(MAX_RETRIES + 1)])),
        _client(RaisingSession(f"boom for {DEFAULT_USER_AGENT}")),
        _client(FakeSession([FakeResponse(200, json_error=ValueError(f"bad json near {DEFAULT_USER_AGENT}"))])),
    ]

    for client in cases:
        result = client.fetch_company_tickers()
        assert DEFAULT_USER_AGENT not in str(result)

    missing_agent_client = _client(FakeSession([]), config=None)
    with pytest.raises(SecEdgarConfigError) as exc_info:
        missing_agent_client.fetch_company_tickers()
    assert DEFAULT_USER_AGENT not in str(exc_info.value)


# ===========================================================================
# Identifier resolution (Phase 5: `RepositoryIngestionRecorder` +
# `collector.run_identifier_resolution.run_identifier_resolution`)
# ===========================================================================


class FakeIdentifierRepository:
    """Offline stand-in for `LocalPostgresRepository`'s identifier-resolution
    surface -- covers exactly the methods `run_identifier_resolution` and
    `RepositoryIngestionRecorder` call, so tests 5.4-5.6 stay fast and never
    touch a real database (task 5.7 is the dedicated real-DB round-trip)."""

    def __init__(self) -> None:
        self._asset_ids: dict[str, str] = {}
        self.identifier_rows: list[dict[str, Any]] = []
        self.ingestion_runs: list[dict[str, Any]] = []

    def get_or_create_asset(
        self, ticker: str, name: str | None = None, asset_class: str | None = None
    ) -> str:
        normalized = ticker.upper()
        return self._asset_ids.setdefault(normalized, f"asset-{normalized}")

    def upsert_asset_identifiers(self, rows: list[dict[str, Any]], batch_size: int = 500) -> int:
        self.identifier_rows.extend(rows)
        return len(rows)

    def resolve_asset_by_identifier(self, id_type: str, id_value: str) -> dict[str, Any] | None:
        for row in self.identifier_rows:
            if row["id_type"] == id_type and row["id_value"] == id_value:
                ticker = next(
                    ticker
                    for ticker, asset_id in self._asset_ids.items()
                    if asset_id == row["asset_id"]
                )
                return {"id": row["asset_id"], "ticker": ticker}
        return None

    def insert_ingestion_run(self, **kwargs: Any) -> dict[str, Any]:
        run = {"id": f"run-{len(self.ingestion_runs) + 1}", **kwargs}
        self.ingestion_runs.append(run)
        return run


def _company_tickers_payload(entries: dict[str, int]) -> dict[str, Any]:
    """Builds the real `company_tickers.json` shape: a dict keyed by row
    index, each value carrying `cik_str`/`ticker`/`title`."""
    return {
        str(index): {"cik_str": cik, "ticker": ticker, "title": ticker}
        for index, (ticker, cik) in enumerate(entries.items())
    }


# -- 5.4: RepositoryIngestionRecorder — one insert_ingestion_run call per record() call --


def test_repository_ingestion_recorder_calls_insert_once_per_record() -> None:
    repository = FakeIdentifierRepository()
    recorder = RepositoryIngestionRecorder(repository)
    run = IngestionRun(
        source="sec_edgar",
        endpoint="company_tickers",
        target_key="",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
        status="success",
        http_status=200,
        rows_written=105,
        request_count=1,
        throttle_wait_seconds=0.11,
        error=None,
        metadata={},
    )

    recorder.record(run)
    recorder.record(run)

    assert len(repository.ingestion_runs) == 2
    call = repository.ingestion_runs[0]
    # 1:1 field mapping from IngestionRun to insert_ingestion_run kwargs.
    assert call["source"] == run.source
    assert call["endpoint"] == run.endpoint
    assert call["target_key"] == run.target_key
    assert call["started_at"] == run.started_at
    assert call["finished_at"] == run.finished_at
    assert call["status"] == run.status
    assert call["http_status"] == run.http_status
    assert call["rows_written"] == run.rows_written
    assert call["request_count"] == run.request_count
    assert call["throttle_wait_seconds"] == run.throttle_wait_seconds
    assert call["error"] == run.error
    assert call["metadata"] == run.metadata


# -- 5.5: unresolved ticker surfacing (spec "Unresolved ticker is logged, not skipped") --


def test_unresolved_ticker_appears_in_result_and_ingestion_run_metadata() -> None:
    payload = _company_tickers_payload({"AAPL": 320193, "MSFT": 789019})
    session = FakeSession([FakeResponse(200, payload=payload)])
    client = _client(session)
    repository = FakeIdentifierRepository()

    result = run_identifier_resolution(repository, client, ["AAPL", "MSFT", "NOPE"])

    assert result["resolved"] == ["AAPL", "MSFT"]
    assert result["unresolved"] == ["NOPE"]

    identifier_runs = [run for run in repository.ingestion_runs if run["endpoint"] == "identifier_resolution"]
    assert len(identifier_runs) == 1
    assert identifier_runs[0]["metadata"]["unresolved_tickers"] == ["NOPE"]
    assert identifier_runs[0]["status"] == "success"


def test_unresolved_ticker_is_printed_not_silently_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    payload = _company_tickers_payload({"AAPL": 320193})
    session = FakeSession([FakeResponse(200, payload=payload)])
    client = _client(session)
    repository = FakeIdentifierRepository()

    run_identifier_resolution(repository, client, ["AAPL", "GHOST"])

    captured = capsys.readouterr()
    assert "GHOST" in captured.out


def test_fetch_failure_marks_every_ticker_unresolved_and_never_raises() -> None:
    session = FakeSession([FakeResponse(503, text="unavailable") for _ in range(MAX_RETRIES + 1)])
    client = _client(session)
    repository = FakeIdentifierRepository()

    result = run_identifier_resolution(repository, client, ["AAPL", "MSFT"])

    assert result["resolved"] == []
    assert sorted(result["unresolved"]) == ["AAPL", "MSFT"]
    identifier_runs = [run for run in repository.ingestion_runs if run["endpoint"] == "identifier_resolution"]
    assert identifier_runs[0]["status"] == "failure"
    assert sorted(identifier_runs[0]["metadata"]["unresolved_tickers"]) == ["AAPL", "MSFT"]
    assert repository.identifier_rows == []


# -- 5.6: resolved-ticker CIK lookup + payload-fidelity proof --


def test_resolved_ticker_asset_identifiers_row_returns_cik() -> None:
    payload = _company_tickers_payload({"AAPL": 320193})
    session = FakeSession([FakeResponse(200, payload=payload)])
    client = _client(session)
    repository = FakeIdentifierRepository()

    run_identifier_resolution(repository, client, ["AAPL"])

    resolved = repository.resolve_asset_by_identifier("cik", "0000320193")
    assert resolved is not None
    assert resolved["ticker"] == "AAPL"


def test_fetch_company_tickers_called_exactly_once_regardless_of_ticker_count() -> None:
    """spec "bulk-preferring": one company_tickers.json fetch resolves the
    whole batch, never a per-ticker request loop."""
    payload = _company_tickers_payload({"AAPL": 320193, "MSFT": 789019, "GOOG": 1652044})
    session = FakeSession([FakeResponse(200, payload=payload)])
    client = _client(session)
    repository = FakeIdentifierRepository()

    run_identifier_resolution(repository, client, ["AAPL", "MSFT", "GOOG"])

    assert len(session.requests) == 1
    assert session.requests[0]["url"] == f"{SEC_WWW_BASE}/files/company_tickers.json"


def test_resolved_cik_fetch_retains_filed_date_independent_of_period_end() -> None:
    """Transport-fidelity proof for the point-in-time-features spec
    ("Ingested fact retains both dates"): once a ticker resolves to a CIK
    here, a subsequent `fetch_company_facts` for that CIK returns `filed`
    unmodified and independently queryable from `period_end`/`end` -- full
    XBRL parsing is a sibling change's scope, this proves the transport
    layer never drops or merges the two dates."""
    tickers_payload = _company_tickers_payload({"AAPL": 320193})
    facts_payload = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": "2023-12-31", "val": 100, "filed": "2024-02-01", "form": "10-K"},
                        ]
                    }
                }
            }
        },
    }
    session = FakeSession(
        [
            FakeResponse(200, payload=tickers_payload),
            FakeResponse(200, payload=facts_payload),
        ]
    )
    client = _client(session)
    repository = FakeIdentifierRepository()

    result = run_identifier_resolution(repository, client, ["AAPL"])
    assert result["resolved"] == ["AAPL"]

    identifier = repository.resolve_asset_by_identifier("cik", "0000320193")
    facts_result = client.fetch_company_facts("320193")

    fact = facts_result["payload"]["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]
    assert fact["filed"] == "2024-02-01"
    assert fact["end"] == "2023-12-31"
    assert fact["filed"] != fact["end"]
    assert identifier is not None


# -- 5.7: real repository round-trip (TEST_DATABASE_URL) --


def test_run_identifier_resolution_persists_rows_against_real_repository(
    repository: LocalPostgresRepository,
) -> None:
    payload = _company_tickers_payload({"AAPL": 320193})
    session = FakeSession([FakeResponse(200, payload=payload)])
    client = _client(session)

    result = run_identifier_resolution(repository, client, ["AAPL", "ZZZZ-NOPE"])

    assert result["resolved"] == ["AAPL"]
    assert result["unresolved"] == ["ZZZZ-NOPE"]

    identifier = repository.resolve_asset_by_identifier("cik", "0000320193")
    assert identifier is not None
    assert identifier["ticker"] == "AAPL"

    runs = repository.get_recent_ingestion_runs(source="sec_edgar")
    matching = [run for run in runs if run["endpoint"] == "identifier_resolution"]
    assert len(matching) == 1
    assert matching[0]["metadata"]["unresolved_tickers"] == ["ZZZZ-NOPE"]
    assert matching[0]["status"] == "success"
