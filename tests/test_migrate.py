from __future__ import annotations

from pathlib import Path

import pytest

from db.migrate import (
    MigrationError,
    checksum_for,
    discover_migrations,
    pending_migrations,
    resolve_dsn,
    verify_no_checksum_drift,
)


def _write_migration(directory: Path, name: str, sql: str) -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


def test_discover_migrations_orders_lexicographically(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0002_second.sql", "select 2;")
    _write_migration(tmp_path, "0001_first.sql", "select 1;")
    _write_migration(tmp_path, "0010_tenth.sql", "select 10;")

    migrations = discover_migrations(tmp_path)

    assert [migration.name for migration in migrations] == [
        "0001_first.sql",
        "0002_second.sql",
        "0010_tenth.sql",
    ]


def test_pending_migrations_excludes_applied_versions(tmp_path: Path) -> None:
    first = _write_migration(tmp_path, "0001_first.sql", "select 1;")
    second = _write_migration(tmp_path, "0002_second.sql", "select 2;")
    migrations = discover_migrations(tmp_path)
    applied = {first.name: checksum_for(first)}

    pending = pending_migrations(migrations, applied)

    assert [migration.name for migration in pending] == [second.name]


def test_pending_migrations_is_empty_when_all_applied(tmp_path: Path) -> None:
    first = _write_migration(tmp_path, "0001_first.sql", "select 1;")
    migrations = discover_migrations(tmp_path)
    applied = {first.name: checksum_for(first)}

    assert pending_migrations(migrations, applied) == []


def test_verify_no_checksum_drift_passes_when_unchanged(tmp_path: Path) -> None:
    first = _write_migration(tmp_path, "0001_first.sql", "select 1;")
    migrations = discover_migrations(tmp_path)
    applied = {first.name: checksum_for(first)}

    verify_no_checksum_drift(migrations, applied)  # does not raise


def test_verify_no_checksum_drift_ignores_unapplied_files(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_first.sql", "select 1;")
    migrations = discover_migrations(tmp_path)

    verify_no_checksum_drift(migrations, applied={})  # does not raise


def test_verify_no_checksum_drift_raises_on_mismatch(tmp_path: Path) -> None:
    first = _write_migration(tmp_path, "0001_first.sql", "select 1;")
    migrations = discover_migrations(tmp_path)
    applied = {first.name: checksum_for(first)}

    # Simulate editing an already-applied, immutable migration file.
    first.write_text("select 999;", encoding="utf-8")

    with pytest.raises(MigrationError, match="migration_checksum_mismatch:0001_first.sql"):
        verify_no_checksum_drift(migrations, applied)


def test_0006_applies_after_0007_without_reapplying() -> None:
    """0006 is authored after 0007 but sorts before it (non-contiguous pattern).

    Exercises the real ``db/migrations`` directory: a database that already has
    every migration EXCEPT the new 0006 recorded must discover exactly 0006 as
    pending, must not re-apply 0007, and must reject any later edit of the
    already-applied 0006 through the checksum-drift guard that
    ``apply_migrations`` runs before touching the database.
    """
    migrations = discover_migrations()
    names = [migration.name for migration in migrations]

    assert "0006_fundamental_facts.sql" in names
    assert "0007_notifications.sql" in names
    assert names.index("0006_fundamental_facts.sql") < names.index("0007_notifications.sql")

    applied = {
        migration.name: checksum_for(migration)
        for migration in migrations
        if migration.name != "0006_fundamental_facts.sql"
    }

    pending = pending_migrations(migrations, applied)
    assert [migration.name for migration in pending] == ["0006_fundamental_facts.sql"]
    assert "0007_notifications.sql" not in [migration.name for migration in pending]
    verify_no_checksum_drift(migrations, applied)  # unapplied 0006 is ignored

    # Simulate editing the immutable, already-applied 0006 migration file.
    drifted = {migration.name: checksum_for(migration) for migration in migrations}
    drifted["0006_fundamental_facts.sql"] = "0" * 64
    with pytest.raises(
        MigrationError, match="migration_checksum_mismatch:0006_fundamental_facts.sql"
    ):
        verify_no_checksum_drift(migrations, drifted)


def test_resolve_dsn_prefers_explicit_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCAL_DATABASE_URL", raising=False)

    assert resolve_dsn("postgresql://explicit") == "postgresql://explicit"


def test_resolve_dsn_uses_local_database_url_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_DATABASE_URL", "postgresql://from-env")

    assert resolve_dsn() == "postgresql://from-env"


def test_resolve_dsn_composes_from_pg_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    # resolve_dsn() calls load_dotenv(), which searches upward from the
    # current directory for a real .env file. A developer's actual .env
    # (which legitimately sets LOCAL_DATABASE_URL) would otherwise refill
    # the var this test just deleted, defeating the fallback-path test.
    # Stub load_dotenv() out so this test is isolated from ambient state.
    monkeypatch.setattr("db.migrate.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("LOCAL_DATABASE_URL", raising=False)
    monkeypatch.setenv("PGHOST", "localhost")
    monkeypatch.setenv("PGDATABASE", "ia_inversiones")
    monkeypatch.setenv("PGUSER", "postgres")
    monkeypatch.setenv("PGPASSWORD", "test-only-fixture-password")
    monkeypatch.setenv("PGPORT", "5433")

    assert resolve_dsn() == (
        "postgresql://postgres:test-only-fixture-password@localhost:5433/ia_inversiones"
    )


def test_resolve_dsn_raises_without_any_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # See test_resolve_dsn_composes_from_pg_parts: isolate from a real .env.
    monkeypatch.setattr("db.migrate.load_dotenv", lambda *args, **kwargs: False)
    for key in ("LOCAL_DATABASE_URL", "PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGPORT"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(MigrationError):
        resolve_dsn()
