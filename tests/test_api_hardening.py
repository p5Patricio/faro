from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app
from api.rate_limit import FixedWindowRateLimiter, client_key_for
from app_config import AppConfig


# --- FixedWindowRateLimiter -------------------------------------------------


def test_rate_limiter_allows_up_to_the_limit_then_blocks() -> None:
    limiter = FixedWindowRateLimiter(requests_per_window=3, window_seconds=60)

    assert [limiter.check("a", now=0).allowed for _ in range(3)] == [True, True, True]

    blocked = limiter.check("a", now=10)
    assert blocked.allowed is False
    assert blocked.retry_after == 50  # 60s window, 10s elapsed


def test_rate_limiter_window_resets() -> None:
    limiter = FixedWindowRateLimiter(requests_per_window=1, window_seconds=60)

    assert limiter.check("a", now=0).allowed is True
    assert limiter.check("a", now=30).allowed is False
    assert limiter.check("a", now=61).allowed is True  # new window


def test_rate_limiter_keys_are_independent() -> None:
    limiter = FixedWindowRateLimiter(requests_per_window=1, window_seconds=60)

    assert limiter.check("a", now=0).allowed is True
    assert limiter.check("b", now=0).allowed is True
    assert limiter.check("a", now=0).allowed is False


def test_client_key_prefers_first_forwarded_for_hop() -> None:
    assert client_key_for(forwarded_for="1.1.1.1, 2.2.2.2", client_host="10.0.0.1") == "1.1.1.1"
    assert client_key_for(forwarded_for=None, client_host="10.0.0.1") == "10.0.0.1"
    assert client_key_for(forwarded_for="  ", client_host=None) == "unknown"


# --- CORS -----------------------------------------------------------------


def test_cors_echoes_an_allowed_origin_and_never_wildcards_with_credentials() -> None:
    client = TestClient(app)

    response = client.options(
        "/api/assets",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_rejects_an_unlisted_origin() -> None:
    client = TestClient(app)

    response = client.options(
        "/api/assets",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


# --- rate-limit middleware wiring ----------------------------------------


def test_api_returns_429_once_the_window_is_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main, "APP_CONFIG", AppConfig(environment="development", rate_limit_per_minute=2))
    monkeypatch.setattr(api_main, "_RATE_LIMITER", FixedWindowRateLimiter(requests_per_window=2))
    app.dependency_overrides[api_main.get_repository] = lambda: None
    client = TestClient(app)

    try:
        assert client.get("/api/assets").status_code == 200
        assert client.get("/api/assets").status_code == 200
        blocked = client.get("/api/assets")
    finally:
        app.dependency_overrides.clear()

    assert blocked.status_code == 429
    assert blocked.headers["retry-after"].isdigit()
    # health is exempt even when the window is exhausted
    assert client.get("/api/health?include_schema=false").status_code == 200
