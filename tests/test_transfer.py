from __future__ import annotations

import copy
from pathlib import Path

import psycopg
import pytest

import ops.transfer as transfer
from ops.transfer import build_manifest, diff_manifests, pg_restore_command, restore

BASE = {
    "tables": {"a": {"rows": 2, "md5": "x"}, "b": {"rows": 0, "md5": None}},
    "migrations": ["0001.sql"],
    "extensions": ["plpgsql"],
}


def altered(**changes) -> dict:
    manifest = copy.deepcopy(BASE)
    manifest.update(changes)
    return manifest


def test_equal_manifests_have_no_differences() -> None:
    assert diff_manifests(BASE, copy.deepcopy(BASE)) == []


def test_missing_and_extra_tables_are_reported() -> None:
    actual = altered(tables={"a": BASE["tables"]["a"], "c": {"rows": 1, "md5": "z"}})

    assert diff_manifests(BASE, actual) == ["Falta la tabla b", "Sobra la tabla c"]


def test_a_row_count_mismatch_is_reported_once() -> None:
    actual = altered(tables={**BASE["tables"], "a": {"rows": 3, "md5": "other"}})

    assert diff_manifests(BASE, actual) == ["a: se esperaban 2 filas y hay 3"]


def test_same_count_with_different_content_is_an_md5_mismatch() -> None:
    actual = altered(tables={**BASE["tables"], "a": {"rows": 2, "md5": "other"}})

    (line,) = diff_manifests(BASE, actual)
    assert line.startswith("a:") and "md5" in line


@pytest.mark.parametrize("expected_md5, actual_md5", [("x", None), (None, "x")])
def test_md5_is_ignored_when_either_side_has_none(expected_md5: str | None, actual_md5: str | None) -> None:
    expected = altered(tables={"a": {"rows": 2, "md5": expected_md5}})
    actual = altered(tables={"a": {"rows": 2, "md5": actual_md5}})

    assert diff_manifests(expected, actual) == []


def test_different_migrations_are_reported() -> None:
    (line,) = diff_manifests(BASE, altered(migrations=["0002.sql"]))

    assert "migraciones" in line and "0001.sql" in line and "0002.sql" in line


def test_manifest_has_row_counts_and_md5_but_never_a_dsn(db_connection: psycopg.Connection) -> None:
    manifest = build_manifest(db_connection)

    count = db_connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
    assert manifest["tables"]["schema_migrations"]["rows"] == count
    assert len(manifest["tables"]["schema_migrations"]["md5"]) == 32
    assert manifest["migrations"] == sorted(manifest["migrations"]) and len(manifest["migrations"]) == count
    assert "://" not in str(manifest) and manifest["database"] == db_connection.info.dbname


def test_tables_over_the_row_limit_are_compared_by_count_only(
    db_connection: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transfer, "MD5_ROW_LIMIT", 0)

    entry = build_manifest(db_connection)["tables"]["schema_migrations"]

    assert entry["rows"] > 0 and entry["md5"] is None


def test_verifying_catches_a_changed_row_and_an_added_row(db_connection: psycopg.Connection) -> None:
    db_connection.execute("INSERT INTO finance_accounts (name, account_type, currency) VALUES ('Traslado', 'cash', 'USD')")
    before = build_manifest(db_connection)
    assert diff_manifests(before, build_manifest(db_connection)) == []

    db_connection.execute("UPDATE finance_accounts SET name = 'Traslado 2' WHERE name = 'Traslado'")
    (changed,) = diff_manifests(before, build_manifest(db_connection))
    assert changed.startswith("finance_accounts:") and "md5" in changed

    db_connection.execute("INSERT INTO finance_accounts (name, account_type, currency) VALUES ('Otra', 'cash', 'USD')")
    (added,) = diff_manifests(before, build_manifest(db_connection))
    assert added.startswith("finance_accounts: se esperaban")


def test_restore_refuses_a_database_that_already_has_tables(test_database_url: str, tmp_path: Path) -> None:
    def runner(*args, **kwargs):
        raise AssertionError("pg_restore must not run against a non-empty database")

    # Same server and database for the maintenance and the target connection.
    report = restore(
        tmp_path / "faro.dump", test_database_url, runner=runner,
        connect=lambda _dsn, **kwargs: psycopg.connect(test_database_url, **kwargs),
    )

    assert report["status"] == "refused" and "vacía" in report["message"]


def test_restore_password_goes_to_the_environment_not_the_command_line(tmp_path: Path) -> None:
    argv, env = pg_restore_command("postgresql://faro:s3cret@localhost:5432/faro", tmp_path / "faro.dump")

    assert env == {"PGPASSWORD": "s3cret"}
    assert not any("s3cret" in part for part in argv)
    assert "--no-owner" in argv and "--exit-on-error" in argv
