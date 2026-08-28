from __future__ import annotations

import pytest
import requests

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
