from __future__ import annotations

import os
from collections.abc import Iterator

# Run the suite as the "test" environment. Among other things this disables
# the API rate limiter (app_config.AppConfig.rate_limiting_enabled) so the
# many TestClient requests, all from one client host, never trip it.
os.environ.setdefault("APP_ENV", "test")

import psycopg
import pytest
from dotenv import load_dotenv

from collector.local_repository import LocalPostgresRepository
from db.migrate import apply_migrations

DEFAULT_TEST_DSN = "postgresql://postgres@localhost:5432/ia_inversiones_test"


def _resolve_test_dsn() -> str:
    load_dotenv()
    return os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DSN)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Resolve TEST_DATABASE_URL and apply migrations once per test session.

    Skips every test that depends on this fixture (transitively, every DB
    test in the suite) when the database is unreachable, so `pytest` stays
    runnable in environments without a local Postgres instance (e.g. CI
    until a Postgres service container is added in a later phase).
    """
    dsn = _resolve_test_dsn()
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(f"TEST_DATABASE_URL unreachable: {exc}")

    apply_migrations(dsn)
    return dsn


@pytest.fixture()
def db_connection(test_database_url: str) -> Iterator[psycopg.Connection]:
    """A live connection wrapping the test in a transaction that is always
    rolled back, so no test leaves state behind for the next one (D12)."""
    connection = psycopg.connect(test_database_url)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture()
def repository(db_connection: psycopg.Connection) -> LocalPostgresRepository:
    return LocalPostgresRepository(connection=db_connection)
