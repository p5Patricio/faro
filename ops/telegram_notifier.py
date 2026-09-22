"""Thin outbound-only Telegram Bot API client.

Transport concerns only: HTML escaping, 4096-char chunking, ~1 msg/sec
pacing, and bounded 429/5xx retry. Never raises -- every failure path
returns a dict, matching `ops/notify_operational_job.py`'s
`send_notification` contract exactly (`{"sent": False, "reason": ...}`).

The bot token lives in the request path (``/bot{TOKEN}/sendMessage``), so
every error surface is redacted before it is returned, logged, or persisted.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"
CHUNK_BUDGET_CHARS = 3800  # < 4096; see module docstring / design rationale
MIN_SEND_INTERVAL_SECONDS = 1.05
MAX_RETRIES = 3

_HTML_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))
# Structural fallback for a token that arrives by another route (nested
# exception, a second token) -- `redact()`'s primary defense is the exact
# `str.replace` below, this regex is belt-and-braces.
_TOKEN_PATTERN = re.compile(r"bot\d+:[\w-]+")


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str

    @classmethod
    def from_env(cls) -> "TelegramConfig | None":
        bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        if not bot_token or not chat_id:
            return None
        return cls(bot_token=bot_token, chat_id=chat_id)


def escape_html(text: str) -> str:
    """Escape only `&`, `<`, `>` (in that order) -- `parse_mode=HTML`'s full
    escape set, not MarkdownV2's 18-character set. Over-escaping quotes or
    apostrophes here would corrupt readable message text for no reason."""
    result = text
    for raw, escaped in _HTML_ESCAPES:
        result = result.replace(raw, escaped)
    return result


def redact(text: str, token: str | None = None) -> str:
    """The only sanitization point for the bot token. `insert_notification`
    trusts its `error_reason` to have already passed through this."""
    result = text
    if token:
        result = result.replace(token, "***")
    return _TOKEN_PATTERN.sub("bot***", result)


def chunk_message(text: str, limit: int = CHUNK_BUDGET_CHARS) -> list[str]:
    """Split on `\\n`, accumulating lines up to `limit`. A single
    over-budget line is hard-split into tagless fragments -- HTML validity
    per chunk rests on a renderer invariant (every tag opens and closes
    inside one line), not on a chunk-time parser.
    """
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        if len(line) > limit:
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit])
            continue

        added_len = len(line) + (1 if current else 0)
        if current and current_len + added_len > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += added_len

    if current:
        chunks.append("\n".join(current))

    return chunks or [""]


def render_operational_message(payload: dict[str, Any]) -> str:
    """Render an operational-job payload into line-scoped HTML: every
    `<b>`/`<code>` opens and closes inside one line, so a line-boundary
    chunk split can never orphan a tag."""
    title = escape_html(str(payload.get("title") or "Operational notification"))
    lines = [f"<b>{title}</b>"]

    status = payload.get("status")
    if status:
        lines.append(f"Status: {escape_html(str(status))}")
    job_mode = payload.get("job_mode")
    if job_mode:
        lines.append(f"Job mode: {escape_html(str(job_mode))}")
    if payload.get("failed") is not None:
        lines.append(f"Failed: {escape_html(str(payload['failed']))}")
    if payload.get("skipped") is not None:
        lines.append(f"Skipped: {escape_html(str(payload['skipped']))}")

    for report in payload.get("reports") or []:
        name = escape_html(str(report.get("name", "")))
        failed = escape_html(str(report.get("failed", 0)))
        lines.append(f"<code>{name}</code>: failed={failed}")
        for issue in report.get("error_summaries") or []:
            ticker = escape_html(str(issue.get("ticker") or ""))
            reason = escape_html(str(issue.get("reason") or ""))
            lines.append(f"- {ticker}: {reason}")
        for issue in report.get("skipped_summaries") or []:
            ticker = escape_html(str(issue.get("ticker") or ""))
            reason = escape_html(str(issue.get("reason") or ""))
            lines.append(f"- skipped {ticker}: {reason}")

    return "\n".join(lines)


def _endpoint(token: str) -> str:
    """The URL is built here and never stored in a returned dict, log line,
    or `notifications` row -- the first of `redact()`'s layered defenses."""
    return f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"


def _response_detail(response: Any) -> str:
    try:
        return str(response.json())
    except Exception:
        return str(getattr(response, "text", "") or getattr(response, "url", ""))


def send_telegram_message(
    text: str,
    config: TelegramConfig | None,
    *,
    session: Any = requests,
    sleep: Any = time.sleep,
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Send `text` to Telegram, chunked and paced. Never raises -- every
    `requests.RequestException` and every non-2xx status is caught and
    returned as `{"sent": False, "reason": ..., "detail": ...}`, with the
    bot token redacted from every surface."""
    if config is None:
        return {"sent": False, "reason": "missing_telegram_config"}

    url = _endpoint(config.bot_token)
    chunks = chunk_message(text)
    last_status_code: int | None = None

    for index, chunk in enumerate(chunks):
        attempt = 0
        while True:
            try:
                response = session.post(
                    url,
                    json={"chat_id": config.chat_id, "text": chunk, "parse_mode": "HTML"},
                    timeout=15,
                )
            except requests.RequestException as error:
                return {
                    "sent": False,
                    "reason": "telegram_request_failed",
                    "detail": redact(str(error), config.bot_token),
                }

            status_code = getattr(response, "status_code", None)

            if status_code == 429:
                if attempt >= max_retries:
                    return {"sent": False, "reason": "telegram_rate_limited"}
                try:
                    retry_after = int(response.json()["parameters"]["retry_after"])
                except Exception:
                    retry_after = 1
                sleep(retry_after)
                attempt += 1
                continue

            if status_code is not None and 500 <= status_code < 600:
                if attempt >= max_retries:
                    return {
                        "sent": False,
                        "reason": "telegram_server_error",
                        "detail": redact(_response_detail(response), config.bot_token),
                    }
                sleep(2)
                attempt += 1
                continue

            if status_code is not None and status_code >= 400:
                return {
                    "sent": False,
                    "reason": "telegram_client_error",
                    "detail": redact(_response_detail(response), config.bot_token),
                }

            last_status_code = status_code
            break

        if index < len(chunks) - 1:
            sleep(MIN_SEND_INTERVAL_SECONDS)

    return {"sent": True, "chunks": len(chunks), "status_code": last_status_code}
