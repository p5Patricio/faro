from __future__ import annotations

import pytest

from app_config import DEFAULT_CORS_ORIGINS, AppConfig


def test_development_defaults_keep_demo_fallback_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ALLOW_DEMO_FALLBACK", raising=False)
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("API_RATE_LIMIT_PER_MINUTE", raising=False)

    config = AppConfig.from_env()

    assert config.environment == "development"
    assert config.allow_demo_fallback is True
    # Default is the local dev origins, never a bare "*".
    assert config.cors_origins == DEFAULT_CORS_ORIGINS
    assert config.cors_allow_credentials is True


def test_wildcard_cors_disables_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_CORS_ORIGINS", "*")

    config = AppConfig.from_env()

    assert config.cors_origins == ("*",)
    assert config.cors_allow_credentials is False


def test_rate_limit_per_minute_parsed_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_PER_MINUTE", "30")
    assert AppConfig.from_env().rate_limit_per_minute == 30

    monkeypatch.setenv("API_RATE_LIMIT_PER_MINUTE", "not-a-number")
    with pytest.raises(RuntimeError, match="API_RATE_LIMIT_PER_MINUTE"):
        AppConfig.from_env()


def test_rate_limiting_disabled_in_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    assert AppConfig.from_env().rate_limiting_enabled is False

    monkeypatch.setenv("APP_ENV", "development")
    assert AppConfig.from_env().rate_limiting_enabled is True


def test_production_defaults_disable_demo_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ALLOW_DEMO_FALLBACK", raising=False)

    config = AppConfig.from_env()

    assert config.is_production is True
    assert config.allow_demo_fallback is False


def test_explicit_demo_fallback_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_DEMO_FALLBACK", "true")

    config = AppConfig.from_env()

    assert config.allow_demo_fallback is True


def test_cors_origins_are_parsed_from_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_CORS_ORIGINS", "http://localhost:5173, https://app.example.com")

    config = AppConfig.from_env()

    assert config.cors_origins == ("http://localhost:5173", "https://app.example.com")


def test_invalid_environment_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "sandbox")

    with pytest.raises(RuntimeError, match="APP_ENV"):
        AppConfig.from_env()
