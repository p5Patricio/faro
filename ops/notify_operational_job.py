from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import psycopg
import requests

from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from ops.notification_dispatch import dispatch_notifications
from ops.telegram_notifier import TelegramConfig, render_operational_message, send_telegram_message

# Marker distinguishing an unreadable report file inside `load_reports`'
# raw output from a normally-parsed report -- kept internal so both
# `build_notification_payload` and `ops.notification_dispatch` see a plain
# dict either way (the dispatcher's `.get("failed")` simply reads 0 from it).
_UNREADABLE_MARKER = "__unreadable__"


def load_reports(reports_dir: str | Path) -> dict[str, Any]:
    """Parse every ``*.json`` report file in ``reports_dir`` into
    ``{filename: raw_parsed_json}``. Shared verbatim by
    `build_notification_payload` (this module) and
    `ops.notification_dispatch.dispatch_notifications` (design.md section 2),
    so both consumers read the on-disk reports exactly once."""
    reports: dict[str, Any] = {}
    for report_path in sorted(Path(reports_dir).glob("*.json")):
        try:
            reports[report_path.name] = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            reports[report_path.name] = {_UNREADABLE_MARKER: f"unreadable_report:{error}"}
    return reports


def build_notification_payload(
    reports_dir: str | Path,
    *,
    status: str,
    job_mode: str | None = None,
    run_url: str | None = None,
    repository: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    raw_reports = load_reports(reports_dir)
    reports = [
        {"name": name, "error": raw[_UNREADABLE_MARKER]}
        if _UNREADABLE_MARKER in raw
        else summarize_report(name, raw)
        for name, raw in raw_reports.items()
    ]

    failures = sum(int(report.get("failed") or 0) for report in reports)
    skipped = sum(int(report.get("skipped_count") or 0) for report in reports)
    title_status = "failed" if status.lower() != "success" or failures else "completed"
    return {
        "title": f"IA Inversiones operational job {title_status}",
        "status": status,
        "job_mode": job_mode,
        "repository": repository,
        "ref": ref,
        "run_url": run_url,
        "failed": failures,
        "skipped": skipped,
        "reports": reports,
    }


def summarize_report(name: str, report: dict[str, Any]) -> dict[str, Any]:
    errors = report.get("errors") or []
    skipped_items = report.get("skipped") or []
    return {
        "name": name,
        "attempted": report.get("attempted"),
        "succeeded": report.get("succeeded"),
        "failed": report.get("failed", len(errors)),
        "skipped_count": len(skipped_items),
        "error_summaries": [summarize_issue(error) for error in errors[:5]],
        "skipped_summaries": [summarize_issue(item) for item in skipped_items[:5]],
    }


def summarize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": issue.get("ticker"),
        "reason": issue.get("reason") or issue.get("error") or issue.get("detail"),
    }


def send_notification(payload: dict[str, Any], webhook_url: str | None, *, session=requests) -> dict[str, Any]:
    """The original, unmodified generic-webhook transport. Can raise
    (`requests.RequestException`, `HTTPError` from `raise_for_status`) --
    unchanged behavior. `dispatch_notification` is the layer that now
    guards this so a webhook failure never suppresses the Telegram send."""
    if not webhook_url:
        return {"sent": False, "reason": "missing_webhook_url"}
    response = session.post(webhook_url, json=payload, timeout=15)
    response.raise_for_status()
    return {"sent": True, "status_code": response.status_code}


def send_telegram_notification(
    payload: dict[str, Any],
    config: TelegramConfig | None,
    *,
    session: Any = requests,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """Render `payload` (the same shape `build_notification_payload`
    produces) into Telegram HTML and delegate to the transport client."""
    message = render_operational_message(payload)
    return send_telegram_message(message, config, session=session, sleep=sleep)


def dispatch_notification(
    payload: dict[str, Any],
    *,
    webhook_url: str | None,
    telegram_config: TelegramConfig | None,
    session: Any = requests,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """Fan out `payload` to both transports independently. One failing
    transport never suppresses the other (design.md section 2).

    Credential boundary: `telegram_config` never enters `payload`, so the
    generic webhook (a third-party URL) cannot receive Telegram credentials.
    """
    try:
        webhook_result = send_notification(payload, webhook_url, session=session)
    except requests.RequestException as error:
        webhook_result = {"sent": False, "reason": "webhook_request_failed", "detail": str(error)}

    telegram_result = send_telegram_notification(payload, telegram_config, session=session, sleep=sleep)

    return {"webhook": webhook_result, "telegram": telegram_result}


def _dispatch_rule_notifications(
    reports_dir: str | Path,
    *,
    job_mode: str | None,
    telegram_config: TelegramConfig | None,
) -> dict[str, Any]:
    """Connect to the local database and run `ops.notification_dispatch`'s
    rule engine. The connection attempt is the documented failure boundary
    (design.md section 2): an unreachable/unconfigured database must not
    block the webhook/Telegram summary path above."""
    try:
        connection = psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True)
    except Exception as error:
        return {"dispatched": False, "reason": "database_unavailable", "detail": str(error)}

    try:
        repository = LocalPostgresRepository(connection=connection)
        reports = load_reports(reports_dir)
        return dispatch_notifications(
            repository,
            reports=reports,
            job_mode=job_mode,
            telegram_config=telegram_config,
        )
    except Exception as error:
        return {"dispatched": False, "reason": "database_unavailable", "detail": str(error)}
    finally:
        connection.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send an optional webhook summary for operational jobs")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--status", default=os.getenv("GITHUB_JOB_STATUS", "unknown"))
    parser.add_argument("--job-mode", default=os.getenv("JOB_MODE"))
    parser.add_argument("--webhook-url", default=os.getenv("OPERATIONAL_WEBHOOK_URL"))
    parser.add_argument("--run-url", default=os.getenv("GITHUB_RUN_URL"))
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY"))
    parser.add_argument("--ref", default=os.getenv("GITHUB_REF_NAME"))
    # No --telegram-bot-token flag: a flag would put the token in the Windows
    # process table, Task Scheduler's stored action, and every scheduler log
    # (design.md section 2). Config comes only from TelegramConfig.from_env().
    parser.add_argument("--no-telegram", action="store_true", help="Skip the Telegram transport this run")
    parser.add_argument(
        "--no-rule-notifications",
        action="store_true",
        help="Skip ops.notification_dispatch's rule engine this run",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_notification_payload(
        args.reports_dir,
        status=args.status,
        job_mode=args.job_mode,
        run_url=args.run_url,
        repository=args.repository,
        ref=args.ref,
    )

    telegram_config = None if args.no_telegram else TelegramConfig.from_env()
    notification = dispatch_notification(
        payload,
        webhook_url=args.webhook_url,
        telegram_config=telegram_config,
    )

    if args.no_rule_notifications:
        notification["rules"] = {"dispatched": False, "reason": "disabled_by_flag"}
    else:
        notification["rules"] = _dispatch_rule_notifications(
            args.reports_dir,
            job_mode=args.job_mode,
            telegram_config=telegram_config,
        )

    print(json.dumps({"notification": notification, "payload": payload}, indent=2))


if __name__ == "__main__":
    main()
