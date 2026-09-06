from __future__ import annotations

from dataclasses import dataclass
import os


VALID_ENVIRONMENTS = {"development", "staging", "production", "test"}
TRUTHY_VALUES = {"1", "true", "yes", "on"}
FALSY_VALUES = {"0", "false", "no", "off"}

# Local dev servers only. Production MUST set API_CORS_ORIGINS explicitly.
# A bare "*" was the old default and, combined with credentialed CORS, let
# any site on the internet make authenticated requests against the API.
# 47319 is the frontend port used by ops/run_local_app.ps1 (deliberately
# outside the common dev range); 5173 is Vite's default, kept for anyone
# running `npm run dev` without that script.
DEFAULT_CORS_ORIGINS = (
    "http://localhost:47319",
    "http://127.0.0.1:47319",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
DEFAULT_RATE_LIMIT_PER_MINUTE = 240


@dataclass(frozen=True)
class AppConfig:
    environment: str = "development"
    allow_demo_fallback: bool = True
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE

    @classmethod
    def from_env(cls) -> "AppConfig":
        environment = normalize_environment(os.getenv("APP_ENV", "development"))
        return cls(
            environment=environment,
            allow_demo_fallback=parse_bool_env(
                "ALLOW_DEMO_FALLBACK",
                default=environment != "production",
            ),
            cors_origins=parse_csv_env("API_CORS_ORIGINS", default=DEFAULT_CORS_ORIGINS),
            rate_limit_per_minute=parse_int_env(
                "API_RATE_LIMIT_PER_MINUTE", default=DEFAULT_RATE_LIMIT_PER_MINUTE
            ),
        )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_allow_credentials(self) -> bool:
        """Credentialed CORS is only valid with an explicit origin allow-list.
        `Access-Control-Allow-Origin: *` and credentials cannot be combined."""
        return "*" not in self.cors_origins

    @property
    def rate_limiting_enabled(self) -> bool:
        return self.environment != "test" and self.rate_limit_per_minute > 0


def normalize_environment(value: str) -> str:
    environment = value.strip().lower()
    if environment not in VALID_ENVIRONMENTS:
        allowed = ", ".join(sorted(VALID_ENVIRONMENTS))
        raise RuntimeError(f"APP_ENV must be one of: {allowed}")
    return environment


def parse_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    value = raw_value.strip().lower()
    if value in TRUTHY_VALUES:
        return True
    if value in FALSY_VALUES:
        return False

    raise RuntimeError(f"{name} must be true or false")


def parse_csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    values = tuple(item.strip() for item in raw_value.split(",") if item.strip())
    return values or default


def parse_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        return int(raw_value.strip())
    except ValueError:
        raise RuntimeError(f"{name} must be an integer") from None
