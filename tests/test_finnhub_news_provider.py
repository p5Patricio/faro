"""`collector/providers/finnhub_news_provider.py`: the HTTP layer is always
mocked here (`FakeSession`/`FakeResponse`, mirroring
`tests/test_sec_edgar_client.py`'s own fakes) -- no real `FINNHUB_API_KEY`
and no real network call is ever required for this file to pass."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests

from collector.providers.finnhub_news_provider import (
    FINNHUB_BASE,
    MAX_RETRIES,
    FinnhubConfig,
    FinnhubConfigError,
    FinnhubNewsProvider,
    NewsHeadline,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None, json_error=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        return self.responses.pop(0)


class RaisingSession:
    def __init__(self, message: str):
        self.message = message
        self.requests: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        raise requests.ConnectionError(self.message)


def _provider(session, *, config=..., sleeps=None) -> FinnhubNewsProvider:
    resolved_config = FinnhubConfig(api_key="test-key") if config is ... else config
    return FinnhubNewsProvider(
        config=resolved_config,
        session=session,
        sleep=(sleeps.append if sleeps is not None else lambda _seconds: None),
        monotonic=lambda: 0.0,
    )


SAMPLE_PAYLOAD = [
    {
        "category": "company",
        "datetime": 1768521600,  # 2026-01-16T00:00:00Z
        "headline": "Acme Corp beats Q4 earnings expectations",
        "id": 111,
        "related": "ACME",
        "source": "Reuters",
        "summary": "Acme Corp reported...",
        "url": "https://example.com/acme-earnings",
    },
    {
        "category": "company",
        "datetime": 1768608000,  # 2026-01-17T00:00:00Z
        "headline": "Acme Corp announces new product line",
        "id": 112,
        "related": "ACME",
        "source": "Bloomberg",
        "summary": "Acme Corp unveiled...",
        "url": "https://example.com/acme-product",
    },
]


# -- config -------------------------------------------------------------


def test_from_env_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert FinnhubConfig.from_env() is None


def test_from_env_returns_none_when_blank(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "   ")
    assert FinnhubConfig.from_env() is None


def test_from_env_returns_config_when_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "abc123")
    assert FinnhubConfig.from_env() == FinnhubConfig(api_key="abc123")


def test_provider_without_config_and_without_env_key_raises_on_fetch(monkeypatch: pytest.MonkeyPatch):
    """No key injected AND none in the environment -- fails clearly and
    predictably (`FinnhubConfigError`, raised only at fetch time, never at
    construction or import time), never a live network call."""
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    provider = FinnhubNewsProvider(session=FakeSession([]))
    with pytest.raises(FinnhubConfigError):
        provider.fetch_company_news("ACME", "2026-01-01", "2026-01-31")


# -- fetch_company_news: success ------------------------------------------


def test_fetch_company_news_parses_headlines():
    session = FakeSession([FakeResponse(status_code=200, payload=SAMPLE_PAYLOAD)])
    provider = _provider(session)

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result["ok"] is True
    headlines = result["headlines"]
    assert len(headlines) == 2
    first = headlines[0]
    assert isinstance(first, NewsHeadline)
    assert first.ticker == "ACME"
    assert first.source == "finnhub"
    assert first.headline == "Acme Corp beats Q4 earnings expectations"
    assert first.published_at == datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    assert first.summary == "Acme Corp reported..."
    assert first.url == "https://example.com/acme-earnings"
    assert first.external_id == "111"


def test_fetch_company_news_sends_token_and_date_range():
    session = FakeSession([FakeResponse(status_code=200, payload=[])])
    provider = _provider(session, config=FinnhubConfig(api_key="secret-token"))

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result == {"ok": True, "headlines": []}
    sent = session.requests[0]
    assert sent["url"] == f"{FINNHUB_BASE}/company-news"
    assert sent["params"]["symbol"] == "ACME"
    assert sent["params"]["from"] == "2026-01-01"
    assert sent["params"]["to"] == "2026-01-31"
    assert sent["params"]["token"] == "secret-token"


def test_fetch_company_news_accepts_date_and_datetime_inputs():
    from datetime import date

    session = FakeSession([FakeResponse(status_code=200, payload=[])])
    provider = _provider(session)

    provider.fetch_company_news("acme", date(2026, 1, 1), datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc))

    sent = session.requests[0]
    assert sent["params"]["from"] == "2026-01-01"
    assert sent["params"]["to"] == "2026-01-31"


def test_fetch_company_news_skips_malformed_items():
    payload = [
        {"headline": "Missing datetime"},
        {"datetime": 1768521600},  # missing headline
        "not-a-dict",
        SAMPLE_PAYLOAD[0],
    ]
    session = FakeSession([FakeResponse(status_code=200, payload=payload)])
    provider = _provider(session)

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result["ok"] is True
    assert len(result["headlines"]) == 1
    assert result["headlines"][0].headline == SAMPLE_PAYLOAD[0]["headline"]


# -- fetch_company_news: failure modes, all non-raising --------------------


def test_fetch_company_news_transport_error_returns_ok_false():
    provider = _provider(RaisingSession("connection refused"))

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result["ok"] is False
    assert result["reason"] == "finnhub_request_failed"


def test_fetch_company_news_client_error_returns_ok_false():
    session = FakeSession([FakeResponse(status_code=401, text="unauthorized")])
    provider = _provider(session)

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result["ok"] is False
    assert result["reason"] == "finnhub_client_error"


def test_fetch_company_news_invalid_json_returns_ok_false():
    session = FakeSession([FakeResponse(status_code=200, json_error=ValueError("bad json"))])
    provider = _provider(session)

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result["ok"] is False
    assert result["reason"] == "finnhub_invalid_json"


def test_fetch_company_news_unexpected_payload_shape_returns_ok_false():
    session = FakeSession([FakeResponse(status_code=200, payload={"not": "a list"})])
    provider = _provider(session)

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result["ok"] is False
    assert result["reason"] == "finnhub_unexpected_payload"


def test_fetch_company_news_rate_limited_retries_then_gives_up():
    responses = [FakeResponse(status_code=429, headers={"Retry-After": "0"}) for _ in range(MAX_RETRIES + 1)]
    session = FakeSession(responses)
    sleeps: list[float] = []
    provider = _provider(session, sleeps=sleeps)

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result["ok"] is False
    assert result["reason"] == "finnhub_rate_limited"
    assert len(session.requests) == MAX_RETRIES + 1


def test_fetch_company_news_rate_limited_then_recovers():
    session = FakeSession(
        [FakeResponse(status_code=429, headers={"Retry-After": "0"}), FakeResponse(status_code=200, payload=[])]
    )
    provider = _provider(session, sleeps=[])

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result == {"ok": True, "headlines": []}


def test_fetch_company_news_server_error_retries_then_gives_up():
    responses = [FakeResponse(status_code=503) for _ in range(MAX_RETRIES + 1)]
    session = FakeSession(responses)
    provider = _provider(session, sleeps=[])

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert result["ok"] is False
    assert result["reason"] == "finnhub_server_error"


def test_api_key_is_redacted_from_error_details():
    session = FakeSession(
        [
            FakeResponse(
                status_code=401,
                text="token=super-secret-key is invalid",
                json_error=ValueError("no json body"),
            )
        ]
    )
    provider = _provider(session, config=FinnhubConfig(api_key="super-secret-key"))

    result = provider.fetch_company_news("acme", "2026-01-01", "2026-01-31")

    assert "super-secret-key" not in result["detail"]


# -- not registered in the price-provider registry -------------------------


def test_not_registered_as_a_price_provider():
    from collector.providers.registry import PROVIDERS

    assert "finnhub_news" not in PROVIDERS
