from __future__ import annotations

import json

import pytest
import requests

from ops.telegram_notifier import (
    CHUNK_BUDGET_CHARS,
    MAX_RETRIES,
    MIN_SEND_INTERVAL_SECONDS,
    TelegramConfig,
    chunk_message,
    escape_html,
    redact,
    render_operational_message,
    send_telegram_message,
)


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

    def post(self, url: str, json: dict, timeout: int):
        self.requests.append({"url": url, "json": json, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


TOKEN = "123456789:AAFakeTokenForTestingPurposesOnly12"


def _config() -> TelegramConfig:
    return TelegramConfig(bot_token=TOKEN, chat_id="-100999")


# -- Threat matrix: untrusted text in HTML (task 2.1, RED before module existed) --


def test_untrusted_ticker_and_reason_values_are_escaped_before_reaching_session_post() -> None:
    payload = {
        "title": "IA Inversiones operational job failed",
        "status": "failure",
        "reports": [
            {
                "name": "market_data_job.json",
                "failed": 1,
                "error_summaries": [{"ticker": "<AAPL & Co>", "reason": "timeout <script>"}],
            }
        ],
    }

    rendered = render_operational_message(payload)

    assert "<AAPL & Co>" not in rendered
    assert "timeout <script>" not in rendered
    assert "&lt;AAPL &amp; Co&gt;" in rendered
    assert "timeout &lt;script&gt;" in rendered

    session = FakeSession([FakeResponse(status_code=200)])
    result = send_telegram_message(rendered, _config(), session=session, sleep=lambda _seconds: None)

    assert result["sent"] is True
    posted_text = session.requests[0]["json"]["text"]
    assert "<AAPL & Co>" not in posted_text
    assert "timeout <script>" not in posted_text


# -- Threat matrix: credential in the URL path (task 2.2, RED before module existed) --


def test_http_error_containing_token_in_url_never_leaks_token_in_result() -> None:
    error = requests.HTTPError(
        f"404 Client Error: Not Found for url: https://api.telegram.org/bot{TOKEN}/sendMessage"
    )
    session = FakeSession([error])

    result = send_telegram_message("hello", _config(), session=session, sleep=lambda _seconds: None)

    assert result["sent"] is False
    serialized = json.dumps(result)
    assert TOKEN not in serialized
    assert "***" in result["detail"]


def test_escape_html_order_ampersand_first() -> None:
    assert escape_html("&<>") == "&amp;&lt;&gt;"


def test_escape_html_does_not_over_escape() -> None:
    # Only &, <, > — not quotes or apostrophes (this is parse_mode=HTML, not
    # MarkdownV2's 18-character escape set).
    assert escape_html("100% \"quoted\" it's fine") == "100% \"quoted\" it's fine"


# -- Chunking ------------------------------------------------------------------


def test_chunk_message_groups_short_lines_and_reassembles_via_newline_join() -> None:
    lines = [f"line-{i}" for i in range(10)]
    text = "\n".join(lines)

    chunks = chunk_message(text, limit=CHUNK_BUDGET_CHARS)

    assert len(chunks) == 1
    assert "\n".join(chunks) == text


def test_chunk_message_splits_into_ordered_chunks_when_over_limit() -> None:
    lines = ["x" * 100 for _ in range(50)]
    text = "\n".join(lines)

    chunks = chunk_message(text, limit=300)

    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert "\n".join(chunks) == text


def test_chunk_message_hard_splits_a_single_oversized_line() -> None:
    oversized_line = "y" * 5000

    chunks = chunk_message(oversized_line, limit=CHUNK_BUDGET_CHARS)

    assert len(chunks) == 2
    assert all(len(chunk) <= CHUNK_BUDGET_CHARS for chunk in chunks)
    assert "".join(chunks) == oversized_line


# -- Pacing ----------------------------------------------------------------------


def test_send_telegram_message_paces_between_chunks_but_not_after_the_last_one() -> None:
    # Three lines of 3700 chars each exceed the 3800-char budget individually
    # combined, forcing three separate chunks at the real production budget.
    long_text = "\n".join("z" * 3700 for _ in range(3))
    sleeps: list[float] = []
    session = FakeSession([FakeResponse(status_code=200) for _ in range(3)])

    result = send_telegram_message(long_text, _config(), session=session, sleep=lambda seconds: sleeps.append(seconds))

    assert result["chunks"] == 3
    assert len(session.requests) == 3
    assert sleeps == [MIN_SEND_INTERVAL_SECONDS, MIN_SEND_INTERVAL_SECONDS]


def test_send_telegram_message_does_not_sleep_for_a_single_chunk() -> None:
    sleeps: list[float] = []
    session = FakeSession([FakeResponse(status_code=200)])

    result = send_telegram_message("short message", _config(), session=session, sleep=lambda s: sleeps.append(s))

    assert result["sent"] is True
    assert result["chunks"] == 1
    assert sleeps == []


# -- 429 / retry ----------------------------------------------------------------


def test_send_telegram_message_retries_after_429_then_succeeds() -> None:
    sleeps: list[float] = []
    session = FakeSession(
        [
            FakeResponse(status_code=429, json_payload={"parameters": {"retry_after": 2}}),
            FakeResponse(status_code=200),
        ]
    )

    result = send_telegram_message("hello", _config(), session=session, sleep=lambda s: sleeps.append(s))

    assert result == {"sent": True, "chunks": 1, "status_code": 200}
    assert len(session.requests) == 2
    assert sleeps == [2]


def test_send_telegram_message_exhausts_retries_on_persistent_429() -> None:
    sleeps: list[float] = []
    responses = [FakeResponse(status_code=429, json_payload={"parameters": {"retry_after": 1}}) for _ in range(10)]
    session = FakeSession(responses)

    result = send_telegram_message(
        "hello", _config(), session=session, sleep=lambda s: sleeps.append(s), max_retries=3
    )

    assert result == {"sent": False, "reason": "telegram_rate_limited"}
    assert len(session.requests) == MAX_RETRIES + 1


def test_from_env_returns_none_when_both_vars_unset(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    assert TelegramConfig.from_env() is None

    result = send_telegram_message("hello", TelegramConfig.from_env())
    assert result == {"sent": False, "reason": "missing_telegram_config"}


def test_from_env_reads_both_vars(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100999")

    config = TelegramConfig.from_env()

    assert config == TelegramConfig(bot_token=TOKEN, chat_id="-100999")


# -- Redaction (task 2.5): second and third threat-matrix cases -----------------


def test_400_response_echoing_url_never_leaks_token_in_detail() -> None:
    session = FakeSession(
        [
            FakeResponse(
                status_code=400,
                json_payload={"ok": False, "description": f"bad request, url=/bot{TOKEN}/sendMessage"},
                url=f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            )
        ]
    )

    result = send_telegram_message("hello", _config(), session=session, sleep=lambda _s: None)

    assert result["sent"] is False
    assert TOKEN not in json.dumps(result)
    assert "***" in result["detail"]


def test_persisted_error_reason_shaped_string_contains_no_token() -> None:
    """The exact string a caller would pass as `notifications.error_reason`
    must already be token-free -- `redact` is the only sanitization point."""
    session = FakeSession(
        [
            FakeResponse(
                status_code=400,
                json_payload={"ok": False, "description": f"invalid chat for /bot{TOKEN}/sendMessage"},
            )
        ]
    )

    result = send_telegram_message("hello", _config(), session=session, sleep=lambda _s: None)
    error_reason = result.get("detail")

    assert error_reason is not None
    assert TOKEN not in error_reason
    assert redact(error_reason, TOKEN) == error_reason  # already fully redacted
