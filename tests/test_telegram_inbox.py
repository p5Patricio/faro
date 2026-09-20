from __future__ import annotations

import json

import pytest
import requests

from ops.telegram_inbox import GET_UPDATES_TIMEOUT_SECONDS, fetch_updates
from ops.telegram_notifier import TelegramConfig

TOKEN = "123456789:AAFakeTokenForTestingPurposesOnly12"


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_payload: dict | None = None,
        text: str = "",
        url: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_payload = json_payload if json_payload is not None else {}
        self.text = text
        self.url = url

    def json(self) -> dict:
        return self._json_payload


class FakeSession:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def get(self, url: str, params: dict | None = None, timeout: int | None = None):
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _config() -> TelegramConfig:
    return TelegramConfig(bot_token=TOKEN, chat_id="-100999")


# -- Happy path -----------------------------------------------------------


def test_fetch_updates_success_returns_updates_list() -> None:
    payload = {"ok": True, "result": [{"update_id": 1}, {"update_id": 2}]}
    session = FakeSession([FakeResponse(status_code=200, json_payload=payload)])

    result = fetch_updates(_config(), offset=None, session=session)

    assert result == {"ok": True, "updates": payload["result"]}


def test_fetch_updates_empty_result_is_still_ok() -> None:
    session = FakeSession([FakeResponse(status_code=200, json_payload={"ok": True, "result": []})])

    result = fetch_updates(_config(), offset=None, session=session)

    assert result == {"ok": True, "updates": []}


# -- offset handling --------------------------------------------------------


def test_fetch_updates_omits_offset_param_when_none() -> None:
    session = FakeSession([FakeResponse(status_code=200, json_payload={"ok": True, "result": []})])

    fetch_updates(_config(), offset=None, session=session)

    assert session.requests[0]["params"] == {}


def test_fetch_updates_passes_offset_when_given() -> None:
    session = FakeSession([FakeResponse(status_code=200, json_payload={"ok": True, "result": []})])

    fetch_updates(_config(), offset=42, session=session)

    assert session.requests[0]["params"] == {"offset": 42}


def test_fetch_updates_never_sends_long_poll_timeout_body_param() -> None:
    """This job short-polls periodically via Task Scheduler -- it must never
    ask Telegram to hold the connection open waiting for new messages."""
    session = FakeSession([FakeResponse(status_code=200, json_payload={"ok": True, "result": []})])

    fetch_updates(_config(), offset=None, session=session)

    assert "timeout" not in session.requests[0]["params"]
    assert session.requests[0]["timeout"] == GET_UPDATES_TIMEOUT_SECONDS


# -- Failure paths never raise, and always redact the token ------------------


def test_fetch_updates_request_exception_is_caught_and_token_redacted() -> None:
    error = requests.ConnectionError(f"failed for https://api.telegram.org/bot{TOKEN}/getUpdates")
    session = FakeSession([error])

    result = fetch_updates(_config(), offset=None, session=session)

    assert result["ok"] is False
    assert result["reason"] == "telegram_request_failed"
    assert TOKEN not in json.dumps(result)
    assert "***" in result["detail"]


def test_fetch_updates_non_2xx_status_is_reported_with_redacted_detail() -> None:
    session = FakeSession(
        [
            FakeResponse(
                status_code=401,
                json_payload={"ok": False, "description": f"unauthorized /bot{TOKEN}/getUpdates"},
            )
        ]
    )

    result = fetch_updates(_config(), offset=None, session=session)

    assert result["ok"] is False
    assert result["reason"] == "telegram_http_error"
    assert TOKEN not in result["detail"]
    assert "***" in result["detail"]


def test_fetch_updates_telegram_level_error_envelope_is_a_failure() -> None:
    session = FakeSession([FakeResponse(status_code=200, json_payload={"ok": False, "description": "boom"})])

    result = fetch_updates(_config(), offset=None, session=session)

    assert result == {"ok": False, "reason": "telegram_api_error", "detail": "{'ok': False, 'description': 'boom'}"}


def test_fetch_updates_unparseable_body_is_a_failure() -> None:
    class BadJsonResponse(FakeResponse):
        def json(self):
            raise ValueError("not json")

    session = FakeSession([BadJsonResponse(status_code=200)])

    result = fetch_updates(_config(), offset=None, session=session)

    assert result["ok"] is False
    assert result["reason"] == "telegram_invalid_response"


def test_fetch_updates_never_raises_even_on_unexpected_exception_types() -> None:
    session = FakeSession([RuntimeError("unexpected")])

    with pytest.raises(RuntimeError):
        # Only requests.RequestException is caught, matching
        # send_telegram_message's contract exactly -- a non-requests
        # exception is a genuine bug and should not be silently swallowed.
        fetch_updates(_config(), offset=None, session=session)
