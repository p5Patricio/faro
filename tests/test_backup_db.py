from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import psycopg

from ops.backup_db import export_tables, pg_dump_command, prune, run_backup


def test_password_goes_to_the_environment_not_the_command_line(tmp_path: Path) -> None:
    argv, env = pg_dump_command("postgresql://faro:s3cret@localhost:5432/faro", tmp_path / "faro.dump")

    assert env == {"PGPASSWORD": "s3cret"}
    assert not any("s3cret" in part for part in argv)
    assert "--format=custom" in argv


def test_prune_keeps_the_newest_backups_and_ignores_other_folders(tmp_path: Path) -> None:
    for name in ("faro-20261001-062000", "faro-20261002-062000", "faro-20261003-062000", "mis-fotos"):
        (tmp_path / name).mkdir()

    removed = prune(tmp_path, keep=2)

    assert [path.name for path in removed] == ["faro-20261001-062000"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["faro-20261002-062000", "faro-20261003-062000", "mis-fotos"]


def test_export_writes_existing_tables_with_exact_numerics(db_connection: psycopg.Connection, tmp_path: Path) -> None:
    db_connection.execute(
        "INSERT INTO finance_accounts (name, account_type, currency) VALUES ('Respaldo', 'cash', 'USD')"
    )

    counts = export_tables(db_connection, tmp_path, tables=("finance_accounts", "no_such_table"))

    rows = json.loads((tmp_path / "finance_accounts.json").read_text(encoding="utf-8"))
    assert counts["finance_accounts"] == len(rows) and "no_such_table" not in counts
    assert any(row["name"] == "Respaldo" for row in rows)


def test_a_failed_dump_is_reported_without_exporting(tmp_path: Path) -> None:
    def failing_runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="pg_dump: error: connection refused")

    report = run_backup("postgresql://u:p@localhost/x", tmp_path, now=datetime(2026, 10, 3, 6, 20), runner=failing_runner)

    assert report["status"] == "failed" and report["reason"] == "pg_dump_failed"
    assert "json_rows" not in report
