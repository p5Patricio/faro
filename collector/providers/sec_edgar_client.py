"""Rate-limited, audited SEC EDGAR client.

Transport concerns only, mirroring `ops/telegram_notifier.py`: injectable
`session`/`sleep`/`monotonic`, a hard `min_interval` pace between request
starts, bounded 429/5xx retry, and a strict two-tier failure contract.

Configuration errors (`SEC_USER_AGENT` missing or blank) **raise**
`SecEdgarConfigError` before any socket is opened -- an unidentified request
earns SEC a 403 and burns fair-access goodwill, so this is a programmer/
operator error, not a runtime outcome. Every other failure (network, 403,
429, 5xx, invalid JSON) **never raises**; it returns
`{"ok": False, "reason": ..., "detail": ...}`, matching
`send_telegram_message`'s contract exactly.

`SEC_USER_AGENT` carries the operator's name and email, so it is redacted
from every returned dict, error string, and recorded `IngestionRun` field --
not a secret in the `TELEGRAM_BOT_TOKEN` sense, but still PII nobody asked
to have echoed back.

Placed beside the price providers but deliberately **not** registered in
`collector.providers.registry.PROVIDERS`: it does not satisfy the
`PriceProvider` protocol (no `fetch_prices`), so `get_provider("sec_edgar")`
must keep failing.

`fetch_dera_dataset` (bulk SEC DERA quarterly datasets) is a named,
deliberately unbuilt seam owned by the `fundamental-analysis` sibling change
-- not implemented here.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import requests

SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE = "https://www.sec.gov"
MIN_REQUEST_INTERVAL_SECONDS = 0.11  # 10 req/s SEC ceiling, with headroom -> ~9.1 req/s
MAX_RETRIES = 3


class SecEdgarConfigError(RuntimeError):
    """Raised when `SEC_USER_AGENT` is missing/blank -- before any socket opens."""


@dataclass(frozen=True)
class SecEdgarConfig:
    user_agent: str  # "Sample Company Name AdminContact@sample.com" -- 403 without it

    @classmethod
    def from_env(cls) -> "SecEdgarConfig | None":
        user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
        if not user_agent:
            return None
        return cls(user_agent=user_agent)


@dataclass(frozen=True)
class IngestionRun:
    source: str
    endpoint: str
    target_key: str
    started_at: datetime
    finished_at: datetime
    status: str  # "success" | "failure"
    http_status: int | None
    rows_written: int
    request_count: int
    throttle_wait_seconds: float
    error: str | None
    metadata: dict[str, Any]
    # Point-in-time audit (spec: "Ingestion run records enable point-in-time
    # audit"): the newest `filingDate` found in a successful `fetch_submissions`
    # response's `filings.recent.filingDate` list -- filing INDEX metadata, not
    # an XBRL fact, so this stays outside `fetch_company_facts`'s documented
    # no-fact-parsing boundary. `None` for every other endpoint/outcome.
    max_filed_date: str | None = None


class IngestionRunRecorder(Protocol):
    def record(self, run: IngestionRun) -> None: ...


def pad_cik(value: str) -> str:
    """Zero-pad a raw CIK to SEC's 10-digit form: `"320193"` -> `"CIK0000320193"`."""
    digits = "".join(char for char in str(value) if char.isdigit())
    return f"CIK{digits.zfill(10)}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _redact(text: str, user_agent: str | None) -> str:
    """Strip the operator's `SEC_USER_AGENT` (name + email) out of any
    string before it is returned, logged, or recorded -- the SEC-client
    analogue of `ops/telegram_notifier.py`'s `redact()`."""
    if not text or not user_agent:
        return text
    return text.replace(user_agent, "***")


def _response_detail(response: Any, user_agent: str | None) -> str:
    try:
        detail = str(response.json())
    except Exception:
        detail = str(getattr(response, "text", "") or getattr(response, "url", ""))
    return _redact(detail, user_agent)


def _max_filed_date(payload: Any) -> str | None:
    """Extract the newest filing date from a `fetch_submissions` payload's
    `filings.recent.filingDate` list -- an ISO `"YYYY-MM-DD"` string list from
    SEC's filing INDEX, not XBRL fact data, so `max()` over these strings
    (lexicographic == chronological for zero-padded ISO dates) does not cross
    the client's "must not flatten or project XBRL facts" boundary (that rule
    is scoped to `fetch_company_facts`'s payload).

    An audit nicety, not a correctness gate: any missing/malformed shape --
    SEC's own payload shape can vary -- yields `None` rather than raising."""
    try:
        dates = payload["filings"]["recent"]["filingDate"]
    except (KeyError, TypeError):
        return None
    if not isinstance(dates, list):
        return None
    valid = [value for value in dates if isinstance(value, str) and value]
    if not valid:
        return None
    return max(valid)


def _retry_after_seconds(response: Any, default: float = 1.0) -> float:
    headers = getattr(response, "headers", None) or {}
    try:
        return float(headers.get("Retry-After", default))
    except (TypeError, ValueError):
        return default


@dataclass
class SecEdgarClient:
    config: SecEdgarConfig | None
    session: Any = requests
    sleep: Any = time.sleep
    monotonic: Any = time.monotonic
    recorder: IngestionRunRecorder | None = None
    min_interval: float = MIN_REQUEST_INTERVAL_SECONDS
    _last_request_started_at: float | None = field(default=None, init=False, repr=False, compare=False)

    def fetch_company_tickers(self) -> dict[str, Any]:
        """Bulk ticker->CIK map, one request for ~all tickers -- never a
        per-company loop (spec "bulk-preferring")."""
        url = f"{SEC_WWW_BASE}/files/company_tickers.json"
        return self._request(endpoint="company_tickers", target_key="", url=url)

    def fetch_company_facts(self, cik: str) -> dict[str, Any]:
        padded = pad_cik(cik)
        url = f"{SEC_DATA_BASE}/api/xbrl/companyfacts/{padded}.json"
        return self._request(endpoint="companyfacts", target_key=padded, url=url)

    def fetch_submissions(self, cik: str) -> dict[str, Any]:
        padded = pad_cik(cik)
        url = f"{SEC_DATA_BASE}/submissions/{padded}.json"
        return self._request(endpoint="submissions", target_key=padded, url=url)

    def _throttle(self) -> float:
        """Wait, if needed, so consecutive request STARTS are >= `min_interval`
        apart -- caps throughput at ~9.1 req/s without maintaining a sliding
        window."""
        now = self.monotonic()
        wait = 0.0
        if self._last_request_started_at is not None:
            wait = max(0.0, self.min_interval - (now - self._last_request_started_at))
            if wait > 0:
                self.sleep(wait)
                now += wait
        self._last_request_started_at = now
        return wait

    def _request(self, *, endpoint: str, target_key: str, url: str) -> dict[str, Any]:
        started_at = _utcnow()
        request_count = 0
        throttle_wait_seconds = 0.0
        status = "failure"
        http_status: int | None = None
        rows_written = 0
        error: str | None = None
        metadata: dict[str, Any] = {}
        max_filed_date: str | None = None
        user_agent: str | None = self.config.user_agent if self.config is not None else None

        try:
            if self.config is None:
                error = "missing_sec_user_agent"
                raise SecEdgarConfigError(
                    "SEC_USER_AGENT is not configured; refusing to send an "
                    "unidentified request to SEC EDGAR"
                )

            headers = {
                "User-Agent": self.config.user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
            attempt = 0

            while True:
                throttle_wait_seconds += self._throttle()
                request_count += 1
                try:
                    response = self.session.get(url, headers=headers, timeout=15)
                except requests.RequestException as exc:
                    detail = _redact(str(exc), user_agent)
                    error = f"sec_request_failed: {detail}"
                    return {"ok": False, "reason": "sec_request_failed", "detail": detail}

                http_status = getattr(response, "status_code", None)

                if http_status == 429:
                    metadata["failure_kind"] = "rate_limited"
                    if attempt >= MAX_RETRIES:
                        detail = _response_detail(response, user_agent)
                        error = f"sec_rate_limited: {detail}"
                        return {"ok": False, "reason": "sec_rate_limited", "detail": detail}
                    retry_after = _retry_after_seconds(response)
                    self.sleep(retry_after)
                    throttle_wait_seconds += retry_after
                    attempt += 1
                    continue

                if http_status is not None and 500 <= http_status < 600:
                    if attempt >= MAX_RETRIES:
                        detail = _response_detail(response, user_agent)
                        error = f"sec_server_error: {detail}"
                        return {"ok": False, "reason": "sec_server_error", "detail": detail}
                    self.sleep(2)
                    throttle_wait_seconds += 2
                    attempt += 1
                    continue

                if http_status is not None and http_status >= 400:
                    detail = _response_detail(response, user_agent)
                    error = f"sec_client_error: {detail}"
                    return {"ok": False, "reason": "sec_client_error", "detail": detail}

                try:
                    payload = response.json()
                except Exception as exc:
                    detail = _redact(str(exc), user_agent)
                    error = f"sec_invalid_json: {detail}"
                    return {"ok": False, "reason": "sec_invalid_json", "detail": detail}

                status = "success"
                rows_written = 1
                if endpoint == "submissions":
                    max_filed_date = _max_filed_date(payload)
                return {"ok": True, "payload": payload, "status_code": http_status}
        finally:
            finished_at = _utcnow()
            if self.recorder is not None:
                self.recorder.record(
                    IngestionRun(
                        source="sec_edgar",
                        endpoint=endpoint,
                        target_key=target_key,
                        started_at=started_at,
                        finished_at=finished_at,
                        status=status,
                        http_status=http_status,
                        rows_written=rows_written,
                        request_count=request_count,
                        throttle_wait_seconds=throttle_wait_seconds,
                        error=error,
                        metadata=metadata,
                        max_filed_date=max_filed_date,
                    )
                )
