"""Thin inbound-only Telegram Bot API client: short-poll ``getUpdates``.

Transport concerns only, mirroring ``ops/telegram_notifier.py``'s outbound
contract exactly: never raises, every failure path returns a dict shaped
``{"ok": False, "reason": ..., "detail": <redacted>}``, and the bot token is
scrubbed from every surface via the shared ``redact()`` helper (imported,
never duplicated).

This module runs one short GET per invocation -- it is launched periodically
by Task Scheduler (see ``ops/finance_bot.py`` / ``ops/register_finance_bot.ps1``),
not as a long-lived long-poll loop. It therefore never sends Telegram's
``timeout`` long-polling body parameter: that would make a single
``getUpdates`` call block on the wire for up to that many seconds waiting for
new messages, which is the wrong shape for a job that runs every N minutes
and should return immediately with whatever is already pending.
"""

from __future__ import annotations

from typing import Any

import requests

from ops.telegram_notifier import TELEGRAM_API_BASE, TelegramConfig, redact

GET_UPDATES_TIMEOUT_SECONDS = 15


def _endpoint(token: str) -> str:
    """Mirrors ``telegram_notifier._endpoint``: built here, never stored in a
    returned dict, log line, or persisted row."""
    return f"{TELEGRAM_API_BASE}/bot{token}/getUpdates"


def _response_detail(response: Any) -> str:
    try:
        return str(response.json())
    except Exception:
        return str(getattr(response, "text", "") or getattr(response, "url", ""))


def fetch_updates(
    config: TelegramConfig,
    *,
    offset: int | None = None,
    session: Any = requests,
    timeout: int = GET_UPDATES_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """GET Telegram's ``getUpdates`` once and return whatever is pending.

    ``offset`` is only sent when not ``None`` (the caller's cursor
    optimization -- see ``ops/finance_bot.py``'s cursor handling; it is never
    the correctness mechanism on its own). ``timeout`` here is the HTTP
    client's request timeout, unrelated to -- and never forwarded as --
    Telegram's own long-polling ``timeout`` query parameter (see module
    docstring).

    Never raises: a ``requests.RequestException``, a non-2xx response, an
    unparseable body, or an ``{"ok": false, ...}`` Telegram API error all
    become ``{"ok": False, "reason": ..., "detail": <redacted>}``. On success,
    returns ``{"ok": True, "updates": [...]}``.
    """
    url = _endpoint(config.bot_token)
    params: dict[str, Any] = {}
    if offset is not None:
        params["offset"] = offset

    try:
        response = session.get(url, params=params, timeout=timeout)
    except requests.RequestException as error:
        return {
            "ok": False,
            "reason": "telegram_request_failed",
            "detail": redact(str(error), config.bot_token),
        }

    status_code = getattr(response, "status_code", None)
    if status_code is None or not (200 <= status_code < 300):
        return {
            "ok": False,
            "reason": "telegram_http_error",
            "detail": redact(_response_detail(response), config.bot_token),
        }

    try:
        payload = response.json()
    except Exception as error:
        return {
            "ok": False,
            "reason": "telegram_invalid_response",
            "detail": redact(str(error), config.bot_token),
        }

    if not isinstance(payload, dict) or not payload.get("ok", False):
        return {
            "ok": False,
            "reason": "telegram_api_error",
            "detail": redact(str(payload), config.bot_token),
        }

    return {"ok": True, "updates": payload.get("result") or []}
