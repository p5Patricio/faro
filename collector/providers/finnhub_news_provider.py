"""Rate-limited Finnhub company-news client, mirroring
`collector/providers/sec_edgar_client.py`'s two-tier failure contract:
injectable `session`/`sleep`/`monotonic`, a hard `min_interval` pace between
request starts (free tier: 60 calls/min), bounded 429/5xx retry.

Configuration errors (`FINNHUB_API_KEY` missing or blank) **raise**
`FinnhubConfigError` before any socket is opened -- an unauthenticated
request would just earn a 401 from Finnhub, so this is a programmer/operator
error, not a runtime outcome. Every other failure (network, 4xx/5xx, invalid
JSON, unexpected payload shape) **never raises**; `fetch_company_news`
returns `{"ok": False, "reason": ..., "detail": ...}`, matching
`SecEdgarClient._request`'s contract exactly -- one bad day for Finnhub (rate
limited, down, malformed response) must never crash the collector pipeline.

`FINNHUB_API_KEY` is redacted from every returned error string, the same way
`sec_edgar_client.py` redacts `SEC_USER_AGENT` -- not logged, echoed, or
raised verbatim.

Placed beside the price providers but deliberately **not** registered in
`collector.providers.registry.PROVIDERS`: it does not satisfy the
`PriceProvider` protocol (no `fetch_prices`, this fetches news, not OHLCV),
so `get_provider("finnhub_news")` must keep failing -- same reasoning
`sec_edgar_client.py`'s own docstring gives for staying unregistered.

No live network call is required for this module to import or for its tests
to pass: `FinnhubNewsProvider` accepts an injected `session`, and every test
supplies a fake one. `FINNHUB_API_KEY` is read lazily, only inside
`FinnhubConfig.from_env()` / `__post_init__`, never at import time.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import requests

FINNHUB_BASE = "https://finnhub.io/api/v1"
MIN_REQUEST_INTERVAL_SECONDS = 1.05  # free tier: 60 req/min ceiling, with headroom
MAX_RETRIES = 3


class FinnhubConfigError(RuntimeError):
    """Raised when `FINNHUB_API_KEY` is missing/blank -- before any socket opens."""


@dataclass(frozen=True)
class FinnhubConfig:
    api_key: str

    @classmethod
    def from_env(cls) -> "FinnhubConfig | None":
        api_key = (os.getenv("FINNHUB_API_KEY") or "").strip()
        if not api_key:
            return None
        return cls(api_key=api_key)


@dataclass(frozen=True)
class NewsHeadline:
    """One parsed Finnhub `/company-news` item -- the shape
    `collector/news_repository.py::upsert_news_headlines` and
    `brain/sentiment_factors.py` both consume."""

    ticker: str
    source: str
    headline: str
    published_at: datetime  # tz-aware UTC -- THE point-in-time anchor
    summary: str = ""
    url: str = ""
    external_id: str | None = None


def _to_iso_date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _redact(text: str, api_key: str | None) -> str:
    if not text or not api_key:
        return text
    return text.replace(api_key, "***")


def _response_detail(response: Any) -> str:
    try:
        return str(response.json())
    except Exception:
        return str(getattr(response, "text", "") or getattr(response, "url", ""))


def _retry_after_seconds(response: Any, default: float = 1.0) -> float:
    headers = getattr(response, "headers", None) or {}
    try:
        return float(headers.get("Retry-After", default))
    except (TypeError, ValueError):
        return default


def _parse_headlines(payload: list[Any], ticker: str) -> list[NewsHeadline]:
    """Best-effort parse of Finnhub's `/company-news` array shape:
    ``[{"category", "datetime" (unix seconds), "headline", "id", "image",
    "related", "source", "summary", "url"}, ...]``. A malformed item (missing
    `headline`/`datetime`, or an unparseable timestamp) is skipped, never
    raised -- matches this module's non-raising runtime-failure contract."""
    headlines: list[NewsHeadline] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        headline_text = item.get("headline")
        unix_ts = item.get("datetime")
        if not headline_text or unix_ts is None:
            continue
        try:
            published_at = datetime.fromtimestamp(float(unix_ts), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            continue
        headlines.append(
            NewsHeadline(
                ticker=ticker.upper(),
                source="finnhub",
                headline=str(headline_text),
                published_at=published_at,
                summary=str(item.get("summary") or ""),
                url=str(item.get("url") or ""),
                external_id=str(item["id"]) if item.get("id") is not None else None,
            )
        )
    return headlines


@dataclass
class FinnhubNewsProvider:
    """Fetches company news headlines for one ticker/date-range from
    Finnhub's free `/company-news` endpoint. Sentiment scoring itself is
    deliberately NOT done here -- see `brain/sentiment_factors.py`; this
    provider is transport-only, mirroring `SecEdgarClient`'s own
    "transport concerns only" scoping.
    """

    config: FinnhubConfig | None = None
    session: Any = requests
    sleep: Any = time.sleep
    monotonic: Any = time.monotonic
    min_interval: float = MIN_REQUEST_INTERVAL_SECONDS
    _last_request_started_at: float | None = field(default=None, init=False, repr=False, compare=False)

    name = "finnhub_news"

    def __post_init__(self) -> None:
        # Resolved lazily from the environment only when the caller did not
        # inject an explicit config -- keeps `FinnhubNewsProvider()` (the
        # production default) convenient while every test passes its own
        # `FinnhubConfig` and never touches `FINNHUB_API_KEY`.
        if self.config is None:
            self.config = FinnhubConfig.from_env()

    def _throttle(self) -> None:
        now = self.monotonic()
        if self._last_request_started_at is not None:
            wait = max(0.0, self.min_interval - (now - self._last_request_started_at))
            if wait > 0:
                self.sleep(wait)
                now += wait
        self._last_request_started_at = now

    def fetch_company_news(
        self,
        ticker: str,
        start: str | date | datetime,
        end: str | date | datetime,
    ) -> dict[str, Any]:
        """Company news headlines for `ticker` between `start` and `end`
        (inclusive, calendar dates -- Finnhub's own granularity).

        Returns ``{"ok": True, "headlines": [NewsHeadline, ...]}`` on
        success, ``{"ok": False, "reason": ..., "detail": ...}`` on any
        transport/HTTP/parse failure -- including an empty-but-valid result
        (``headlines: []``), which is `ok: True` with zero rows, never an
        error: "no news today" is a legitimate outcome, not a failure.

        Raises `FinnhubConfigError` if `FINNHUB_API_KEY` is not configured.
        Checked here, at call time, not at import time or construction time
        -- importing this module, or constructing a provider with an
        explicit injected `config`, never touches the environment.
        """
        if self.config is None:
            raise FinnhubConfigError(
                "FINNHUB_API_KEY is not configured; refusing to send an "
                "unauthenticated request to Finnhub"
            )

        api_key = self.config.api_key
        params = {
            "symbol": ticker.upper(),
            "from": _to_iso_date(start),
            "to": _to_iso_date(end),
            "token": api_key,
        }

        attempt = 0
        while True:
            self._throttle()
            try:
                response = self.session.get(f"{FINNHUB_BASE}/company-news", params=params, timeout=15)
            except requests.RequestException as exc:
                detail = _redact(str(exc), api_key)
                return {"ok": False, "reason": "finnhub_request_failed", "detail": detail}

            status_code = getattr(response, "status_code", None)

            if status_code == 429:
                if attempt >= MAX_RETRIES:
                    detail = _redact(_response_detail(response), api_key)
                    return {"ok": False, "reason": "finnhub_rate_limited", "detail": detail}
                self.sleep(_retry_after_seconds(response))
                attempt += 1
                continue

            if status_code is not None and 500 <= status_code < 600:
                if attempt >= MAX_RETRIES:
                    detail = _redact(_response_detail(response), api_key)
                    return {"ok": False, "reason": "finnhub_server_error", "detail": detail}
                self.sleep(2)
                attempt += 1
                continue

            if status_code is not None and status_code >= 400:
                detail = _redact(_response_detail(response), api_key)
                return {"ok": False, "reason": "finnhub_client_error", "detail": detail}

            try:
                payload = response.json()
            except Exception as exc:
                detail = _redact(str(exc), api_key)
                return {"ok": False, "reason": "finnhub_invalid_json", "detail": detail}

            if not isinstance(payload, list):
                detail = _redact(str(payload)[:500], api_key)
                return {"ok": False, "reason": "finnhub_unexpected_payload", "detail": detail}

            return {"ok": True, "headlines": _parse_headlines(payload, ticker)}
