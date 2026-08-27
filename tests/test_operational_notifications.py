from __future__ import annotations

import json

import requests

from ops.notify_operational_job import (
    _parse_failed_steps,
    build_notification_payload,
    dispatch_notification,
    load_reports,
    send_notification,
    send_telegram_notification,
)
from ops.telegram_notifier import TelegramConfig


def test_build_notification_payload_summarizes_reports(tmp_path) -> None:
    (tmp_path / "retraining_job.json").write_text(
        json.dumps(
            {
                "attempted": 2,
                "succeeded": 1,
                "failed": 0,
                "skipped": [
                    {
                        "ticker": "BTC-USD",
                        "reason": "candidate_not_better_than_incumbent",
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )

    payload = build_notification_payload(
        tmp_path,
        status="success",
        job_mode="full_retrain",
        run_url="https://github.com/example/actions/runs/1",
        repository="owner/repo",
        ref="main",
    )

    assert payload["title"] == "IA Inversiones operational job completed"
    assert payload["job_mode"] == "full_retrain"
    assert payload["repository"] == "owner/repo"
    assert payload["skipped"] == 1
    assert payload["failed"] == 0
    assert payload["reports"][0]["skipped_summaries"][0]["ticker"] == "BTC-USD"


def test_build_notification_payload_marks_failed_when_report_has_errors(tmp_path) -> None:
    (tmp_path / "market_data_job.json").write_text(
        json.dumps({"attempted": 1, "succeeded": 0, "failed": 1, "errors": [{"ticker": "AAPL", "error": "timeout"}]}),
        encoding="utf-8",
    )

    payload = build_notification_payload(tmp_path, status="success")

    assert payload["title"] == "IA Inversiones operational job failed"
    assert payload["failed"] == 1
    assert payload["reports"][0]["error_summaries"][0]["reason"] == "timeout"


def test_send_notification_skips_when_webhook_is_missing() -> None:
    result = send_notification({"status": "success"}, None)

    assert result == {"sent": False, "reason": "missing_webhook_url"}


# -- Threat matrix: third-party payload egress (task 6b.1, RED before dispatch_notification existed) --


TOKEN = "123456789:AAFakeTokenForTestingPurposesOnly12"
CHAT_ID = "-100999"


class FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def json(self) -> dict:
        return {}

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, webhook_raises: Exception | None = None) -> None:
        self.requests: list[dict] = []
        self._webhook_raises = webhook_raises

    def post(self, url: str, json: dict, timeout: int):
        self.requests.append({"url": url, "json": json, "timeout": timeout})
        if url == "https://example.com/webhook" and self._webhook_raises is not None:
            raise self._webhook_raises
        return FakeResponse(status_code=200)


def _telegram_config() -> TelegramConfig:
    return TelegramConfig(bot_token=TOKEN, chat_id=CHAT_ID)


def test_dispatch_notification_never_puts_telegram_credentials_in_the_webhook_payload() -> None:
    payload = {"title": "Operational job failed", "status": "failure", "failed": 1, "reports": []}
    session = FakeSession()

    dispatch_notification(
        payload,
        webhook_url="https://example.com/webhook",
        telegram_config=_telegram_config(),
        session=session,
        sleep=lambda *_args: None,
    )

    webhook_calls = [call for call in session.requests if call["url"] == "https://example.com/webhook"]
    assert len(webhook_calls) == 1
    body = json.dumps(webhook_calls[0]["json"])
    assert TOKEN not in body
    assert CHAT_ID not in body
    assert webhook_calls[0]["json"] == payload


def test_dispatch_notification_webhook_failure_does_not_suppress_telegram() -> None:
    payload = {"title": "Operational job failed", "status": "failure", "failed": 1, "reports": []}
    session = FakeSession(webhook_raises=requests.ConnectionError("webhook down"))

    result = dispatch_notification(
        payload,
        webhook_url="https://example.com/webhook",
        telegram_config=_telegram_config(),
        session=session,
        sleep=lambda *_args: None,
    )

    telegram_calls = [call for call in session.requests if "api.telegram.org" in call["url"]]
    assert len(telegram_calls) == 1
    assert result["webhook"]["sent"] is False
    assert result["telegram"]["sent"] is True


def test_dispatch_notification_both_transports_unconfigured_are_two_no_ops() -> None:
    payload = {"title": "Operational job ok", "status": "success", "failed": 0, "reports": []}
    session = FakeSession()

    result = dispatch_notification(
        payload,
        webhook_url=None,
        telegram_config=None,
        session=session,
        sleep=lambda *_args: None,
    )

    assert result == {
        "webhook": {"sent": False, "reason": "missing_webhook_url"},
        "telegram": {"sent": False, "reason": "missing_telegram_config"},
    }
    assert session.requests == []


def test_send_telegram_notification_renders_payload_and_delegates_to_transport() -> None:
    payload = {"title": "Operational job failed", "status": "failure", "failed": 2, "reports": []}
    session = FakeSession()

    result = send_telegram_notification(payload, _telegram_config(), session=session, sleep=lambda *_args: None)

    assert result["sent"] is True
    assert len(session.requests) == 1
    assert "Failed: 2" in session.requests[0]["json"]["text"]


def test_load_reports_returns_raw_parsed_json_keyed_by_filename(tmp_path) -> None:
    (tmp_path / "market_data_job.json").write_text(json.dumps({"attempted": 1, "failed": 1}), encoding="utf-8")

    reports = load_reports(tmp_path)

    assert reports == {"market_data_job.json": {"attempted": 1, "failed": 1}}


def test_load_reports_marks_unreadable_files_without_raising(tmp_path) -> None:
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    reports = load_reports(tmp_path)

    assert "broken.json" in reports
    assert "unreadable_report" in str(reports["broken.json"])


# -- Task 7: --failed-steps CLI parsing (ops.run_local_scheduler gap-filling) --


def test_parse_failed_steps_none_or_empty_stays_none() -> None:
    assert _parse_failed_steps(None) is None
    assert _parse_failed_steps("") is None
    assert _parse_failed_steps("   ,  ,") is None


def test_parse_failed_steps_splits_comma_joined_names_and_strips_whitespace() -> None:
    assert _parse_failed_steps("schema_check") == ["schema_check"]
    assert _parse_failed_steps("schema_check, market_data") == ["schema_check", "market_data"]
