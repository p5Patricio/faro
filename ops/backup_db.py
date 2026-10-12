"""Local backup and export of the Faro database (decision D12: nothing leaves
the machine).

Usage::

    py -3.14 -m ops.backup_db --dest D:\\Respaldos\\Faro [--keep 14] [--no-dump] [--no-json]

Writes, inside ``--dest``, one timestamped folder per run::

    faro-20261003-062000/
      faro.dump             # pg_dump custom format (restore with pg_restore)
      json/<table>.json     # personal tables, one JSON array each

and then deletes the oldest ``faro-*`` folders beyond ``--keep``. Only folders
this script named are ever touched.

The DSN is resolved like ``db.migrate`` (``LOCAL_DATABASE_URL`` from the
environment or ``.env``). The password reaches ``pg_dump`` through the
``PGPASSWORD`` environment variable, never the command line, and is never
printed.

Restore (into an EMPTY database)::

    createdb faro_restaurada
    pg_restore --no-owner -d faro_restaurada faro.dump
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from db.migrate import resolve_dsn

FOLDER_PREFIX = "faro-"

# The user's own records: what cannot be re-downloaded from a market data source.
EXPORT_TABLES: tuple[str, ...] = (
    "finance_accounts",
    "finance_categories",
    "finance_transactions",
    "finance_budgets",
    "finance_net_worth_snapshots",
    "finance_net_worth_items",
    "finance_recurring_bills",
    "finance_recurring_bill_payments",
    "finance_goals",
    "investment_accounts",
    "investment_transactions",
    "risk_profiles",
)

Runner = Callable[..., subprocess.CompletedProcess]


def pg_dump_command(dsn: str, output: Path, pg_dump: str = "pg_dump") -> tuple[list[str], dict[str, str]]:
    """The ``pg_dump`` argv and the extra environment, with the password moved
    out of the connection string into ``PGPASSWORD``."""
    params = conninfo_to_dict(dsn)
    password = params.pop("password", None)
    env = {"PGPASSWORD": password} if password else {}
    return [pg_dump, "--format=custom", "--no-owner", f"--file={output}", f"--dbname={make_conninfo(**params)}"], env


def export_tables(connection: psycopg.Connection, folder: Path, tables: Sequence[str] = EXPORT_TABLES) -> dict[str, int]:
    """One JSON array per existing table. ``row_to_json`` keeps ``numeric`` and
    dates exactly as Postgres prints them (no float round trip). A table whose
    migration is not applied is skipped."""
    folder.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for table in tables:
        exists = connection.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()[0]
        if not exists:
            continue
        query = sql.SQL("SELECT coalesce(json_agg(row_to_json(t)), '[]'::json)::text FROM {} t").format(
            sql.Identifier(table)
        )
        rows = connection.execute(query).fetchone()[0]
        (folder / f"{table}.json").write_text(rows, encoding="utf-8")
        counts[table] = len(json.loads(rows))
    return counts


def prune(dest: Path, keep: int) -> list[Path]:
    """Delete the oldest backup folders beyond ``keep`` (names sort by time)."""
    folders = sorted(path for path in dest.iterdir() if path.is_dir() and path.name.startswith(FOLDER_PREFIX))
    removed = folders[: max(len(folders) - keep, 0)]
    for path in removed:
        shutil.rmtree(path)
    return removed


def run_backup(
    dsn: str,
    dest: Path,
    *,
    keep: int = 14,
    dump: bool = True,
    export_json: bool = True,
    pg_dump: str = "pg_dump",
    now: datetime | None = None,
    runner: Runner = subprocess.run,
) -> dict:
    folder = dest / f"{FOLDER_PREFIX}{(now or datetime.now()):%Y%m%d-%H%M%S}"
    folder.mkdir(parents=True, exist_ok=False)
    report: dict = {"folder": str(folder)}
    if dump:
        argv, extra_env = pg_dump_command(dsn, folder / "faro.dump", pg_dump)
        completed = runner(argv, env={**os.environ, **extra_env}, capture_output=True, text=True)
        if completed.returncode != 0:
            report["status"] = "failed"
            report["reason"] = "pg_dump_failed"
            report["stderr"] = (completed.stderr or "").strip()[-500:]
            return report
        report["dump"] = "faro.dump"
    if export_json:
        with psycopg.connect(dsn) as connection:
            report["json_rows"] = export_tables(connection, folder / "json")
    report["pruned"] = [path.name for path in prune(dest, keep)]
    report["status"] = "ok"
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Respaldo local de la base de datos de Faro")
    parser.add_argument("--dest", required=True, type=Path, help="Carpeta local donde guardar los respaldos")
    parser.add_argument("--keep", type=int, default=14, help="Cuántos respaldos conservar (default 14)")
    parser.add_argument("--no-dump", action="store_true", help="Solo exportar JSON")
    parser.add_argument("--no-json", action="store_true", help="Solo pg_dump")
    parser.add_argument("--pg-dump", default="pg_dump", help="Ruta a pg_dump si no está en el PATH")
    args = parser.parse_args(argv)
    if args.keep < 1:
        parser.error("--keep must be at least 1")
    args.dest.mkdir(parents=True, exist_ok=True)
    try:
        report = run_backup(
            resolve_dsn(), args.dest, keep=args.keep, dump=not args.no_dump, export_json=not args.no_json,
            pg_dump=args.pg_dump,
        )
    except (OSError, RuntimeError, psycopg.Error) as error:
        # Only the error type: a connection error message can echo the DSN.
        report = {"status": "failed", "reason": type(error).__name__}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
