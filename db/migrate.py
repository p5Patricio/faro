"""Idempotent SQL-file migration runner for the local Postgres schema.

Usage::

    py -3.14 -m db.migrate [--dsn DSN] [--dry-run]

Applies every pending ``*.sql`` file under ``db/migrations/`` (scanned in
lexicographic order) inside its own transaction, tracks applied versions in
a ``schema_migrations`` table, and takes a Postgres advisory lock for the
duration of the run so two concurrent invocations never race.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Fixed advisory-lock key: any 64-bit hash of a stable string is fine since
# this only needs to be unique to this application, not cryptographically
# strong.
ADVISORY_LOCK_KEY = "ia_inversiones_migrations"


class MigrationError(RuntimeError):
    """Raised when the migration runner cannot proceed safely."""


def resolve_dsn(explicit_dsn: str | None = None) -> str:
    """Resolve the Postgres DSN from an explicit value, then the environment.

    Mirrors ``LocalPostgresConfig.from_env`` in
    ``collector/local_repository.py``: ``LOCAL_DATABASE_URL`` first, then a
    DSN composed from ``PGHOST``/``PGPORT``/``PGDATABASE``/``PGUSER``/
    ``PGPASSWORD``.
    """
    if explicit_dsn:
        return explicit_dsn

    load_dotenv()
    dsn = os.getenv("LOCAL_DATABASE_URL")
    if dsn:
        return dsn

    host = os.getenv("PGHOST")
    dbname = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    if host and dbname and user:
        port = os.getenv("PGPORT", "5432")
        password = os.getenv("PGPASSWORD")
        auth = f"{user}:{password}@" if password else f"{user}@"
        return f"postgresql://{auth}{host}:{port}/{dbname}"

    raise MigrationError(
        "LOCAL_DATABASE_URL or PGHOST/PGPORT/PGDATABASE/PGUSER must be set"
    )


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """Return every ``*.sql`` file under ``migrations_dir``, lexicographically sorted."""
    return sorted(migrations_dir.glob("*.sql"), key=lambda path: path.name)


def checksum_for(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_schema_migrations_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists schema_migrations (
              version text primary key,
              checksum text not null,
              applied_at timestamptz not null default now()
            )
            """
        )


def applied_versions(conn: psycopg.Connection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("select version, checksum from schema_migrations")
        return {row[0]: row[1] for row in cur.fetchall()}


def pending_migrations(migrations: list[Path], applied: dict[str, str]) -> list[Path]:
    return [migration for migration in migrations if migration.name not in applied]


def verify_no_checksum_drift(migrations: list[Path], applied: dict[str, str]) -> None:
    """Raise ``MigrationError`` if an already-applied file's contents changed.

    Migrations are immutable once applied; a checksum mismatch means someone
    edited a historical file instead of adding a new one.
    """
    for migration in migrations:
        recorded_checksum = applied.get(migration.name)
        if recorded_checksum is None:
            continue
        if checksum_for(migration) != recorded_checksum:
            raise MigrationError(f"migration_checksum_mismatch:{migration.name}")


def apply_migrations(dsn: str, dry_run: bool = False) -> list[str]:
    """Apply every pending migration and return the list of version names touched.

    In ``dry_run`` mode, nothing is applied; the pending list is returned as-is.
    """
    migrations = discover_migrations()

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("select pg_advisory_lock(hashtext(%s))", (ADVISORY_LOCK_KEY,))
        try:
            ensure_schema_migrations_table(conn)
            applied = applied_versions(conn)
            verify_no_checksum_drift(migrations, applied)
            pending = pending_migrations(migrations, applied)

            if dry_run:
                return [migration.name for migration in pending]

            for migration in pending:
                sql = migration.read_text(encoding="utf-8")
                checksum = checksum_for(migration)
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(sql)
                        cur.execute(
                            "insert into schema_migrations (version, checksum) values (%s, %s)",
                            (migration.name, checksum),
                        )

            return [migration.name for migration in pending]
        finally:
            with conn.cursor() as cur:
                cur.execute("select pg_advisory_unlock(hashtext(%s))", (ADVISORY_LOCK_KEY,))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply local Postgres migrations")
    parser.add_argument("--dsn", default=None, help="Postgres DSN (defaults to LOCAL_DATABASE_URL/PG* env vars)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List pending migrations without applying them",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        dsn = resolve_dsn(args.dsn)
        touched = apply_migrations(dsn, dry_run=args.dry_run)
    except MigrationError as error:
        print(str(error), file=sys.stderr)
        return 1

    if args.dry_run:
        if touched:
            print("Pending migrations:")
            for name in touched:
                print(f"  {name}")
            return 1
        print("No pending migrations.")
        return 0

    if touched:
        print("Applied migrations:")
        for name in touched:
            print(f"  {name}")
    else:
        print("No pending migrations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
