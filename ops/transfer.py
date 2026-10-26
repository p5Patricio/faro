"""Verified transfer of the Faro database to another machine.

Usage::

    py -3.14 -m ops.transfer manifest --out manifest.json
    py -3.14 -m ops.transfer verify --manifest manifest.json
    py -3.14 -m ops.transfer restore --dump faro.dump [--manifest manifest.json]
        [--database NAME] [--pg-restore PATH]

``manifest`` fingerprints the database named by ``LOCAL_DATABASE_URL`` (same
resolution as ``db.migrate``): every ``public`` table with its row count and,
up to ``MD5_ROW_LIMIT`` rows, an md5 of its content, plus the applied
migrations and the extensions. ``verify`` recomputes that fingerprint and
reports every difference. ``restore`` loads a ``pg_dump`` custom-format file
into an EMPTY database (created when missing) and, with ``--manifest``,
verifies the result. The DSN and the password are never printed: the password
reaches ``pg_restore`` through ``PGPASSWORD``, never the command line.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from db.migrate import resolve_dsn

MD5_ROW_LIMIT = 200_000  # bigger tables are compared by row count only

# Settings that change how a value prints as text; pinned so the same data
# hashes the same on any machine.
RENDERING = (("TimeZone", "UTC"), ("DateStyle", "ISO, YMD"), ("IntervalStyle", "postgres"),
             ("extra_float_digits", "1"), ("bytea_output", "hex"))

Runner = Callable[..., subprocess.CompletedProcess]
Connect = Callable[..., psycopg.Connection]


def build_manifest(connection: psycopg.Connection) -> dict:
    """Fingerprint of the connected database (no DSN, only its name)."""
    for name, value in RENDERING:
        connection.execute("SELECT set_config(%s, %s, false)", (name, value))
    names = [row[0] for row in connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1"
    )]
    tables: dict[str, dict] = {}
    for name in names:
        source = sql.SQL(" FROM {} transfer_row").format(sql.Identifier(name))
        rows = connection.execute(sql.SQL("SELECT count(*)") + source).fetchone()[0]
        digest = None
        if rows <= MD5_ROW_LIMIT:  # hash each row first so wide rows never pile up in one string
            digest = connection.execute(
                sql.SQL("SELECT md5(coalesce(string_agg(md5(transfer_row::text), '' "
                        "ORDER BY md5(transfer_row::text) COLLATE \"C\"), ''))") + source
            ).fetchone()[0]
        tables[name] = {"rows": rows, "md5": digest}
    migrations: list[str] = []
    if connection.execute("SELECT to_regclass('schema_migrations') IS NOT NULL").fetchone()[0]:
        migrations = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY 1")]
    return {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "server_version": connection.execute("SHOW server_version").fetchone()[0],
        "database": connection.execute("SELECT current_database()").fetchone()[0],
        "migrations": migrations,
        "extensions": [row[0] for row in connection.execute("SELECT extname FROM pg_extension ORDER BY 1")],
        "tables": tables,
    }


def diff_manifests(expected: dict, actual: dict) -> list[str]:
    """Human-readable differences (empty list = the databases match)."""
    want, have = expected["tables"], actual["tables"]
    lines = [f"Falta la tabla {name}" for name in sorted(want.keys() - have.keys())]
    lines += [f"Sobra la tabla {name}" for name in sorted(have.keys() - want.keys())]
    for name in sorted(want.keys() & have.keys()):
        if want[name]["rows"] != have[name]["rows"]:
            lines.append(f"{name}: se esperaban {want[name]['rows']} filas y hay {have[name]['rows']}")
        elif want[name].get("md5") and have[name].get("md5") and want[name]["md5"] != have[name]["md5"]:
            lines.append(f"{name}: el contenido no coincide (md5 distinto)")
    for key, label in (("migrations", "migraciones"), ("extensions", "extensiones")):
        missing = sorted(set(expected.get(key, [])) - set(actual.get(key, [])))
        extra = sorted(set(actual.get(key, [])) - set(expected.get(key, [])))
        if missing or extra:
            lines.append(f"Las {label} no coinciden: faltan {missing or 'ninguna'}, sobran {extra or 'ninguna'}")
    return lines


def verify(dsn: str, manifest_path: Path) -> int:
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    with psycopg.connect(dsn) as connection:
        actual = build_manifest(connection)
    lines = diff_manifests(expected, actual)
    print("\n".join(lines) if lines else f"OK: {len(actual['tables'])} tablas coinciden")
    return 1 if lines else 0


def pg_restore_command(dsn: str, dump: Path, pg_restore: str = "pg_restore") -> tuple[list[str], dict[str, str]]:
    """The ``pg_restore`` argv and extra environment (password in ``PGPASSWORD``)."""
    params = conninfo_to_dict(dsn)
    password = params.pop("password", None)
    argv = [pg_restore, "--no-owner", "--exit-on-error", f"--dbname={make_conninfo(**params)}", str(dump)]
    return argv, {"PGPASSWORD": password} if password else {}


def _public_tables(connection: psycopg.Connection) -> int:
    return connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()[0]


def restore(
    dump: Path, dsn: str, *, pg_restore: str = "pg_restore",
    connect: Connect = psycopg.connect, runner: Runner = subprocess.run,
) -> dict:
    """Create the target database when missing, refuse a non-empty one, then load the dump."""
    params = conninfo_to_dict(dsn)
    report: dict = {"database": params["dbname"]}
    with connect(make_conninfo(**{**params, "dbname": "postgres"}), autocommit=True) as admin:
        if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (params["dbname"],)).fetchone():
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(params["dbname"])))
    with connect(dsn) as target:
        if _public_tables(target):
            return {**report, "status": "refused",
                    "message": "La base ya tiene tablas en public; restaura en una base vacía (usa --database)."}
    argv, extra_env = pg_restore_command(dsn, dump, pg_restore)
    try:
        completed = runner(argv, env={**os.environ, **extra_env}, capture_output=True, text=True)
    except FileNotFoundError:
        return {**report, "status": "failed", "reason": "pg_restore_not_found",
                "message": "No encuentro pg_restore; indica su ruta con --pg-restore."}
    if completed.returncode != 0:
        return {**report, "status": "failed", "reason": "pg_restore_failed",
                "stderr": (completed.stderr or "").strip()[-500:]}
    with connect(dsn) as target:
        return {**report, "status": "ok", "tables": _public_tables(target)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Traslado verificado de la base de datos de Faro")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("manifest", help="Escribe la huella de la base actual").add_argument(
        "--out", type=Path, required=True, help="Archivo JSON de salida")
    commands.add_parser("verify", help="Compara la base actual con una huella").add_argument(
        "--manifest", type=Path, required=True, help="Huella generada con 'manifest'")
    restorer = commands.add_parser("restore", help="Restaura un dump en una base vacía")
    restorer.add_argument("--dump", type=Path, required=True, help="Archivo faro.dump (pg_dump formato custom)")
    restorer.add_argument("--manifest", type=Path, help="Verifica el resultado contra esta huella")
    restorer.add_argument("--pg-restore", default="pg_restore", help="Ruta a pg_restore si no está en el PATH")
    restorer.add_argument("--database", help="Base destino (default: la de LOCAL_DATABASE_URL)")
    args = parser.parse_args(argv)
    if args.command == "restore":
        for path in (args.dump, args.manifest):
            if path is not None and not path.is_file():
                parser.error(f"No existe el archivo {path}")
    try:
        dsn = resolve_dsn()
        if args.command == "manifest":
            with psycopg.connect(dsn) as connection:
                manifest = build_manifest(connection)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps({"status": "ok", "manifest": str(args.out), "tables": len(manifest["tables"])}))
            return 0
        if args.command == "verify":
            return verify(dsn, args.manifest)
        target = make_conninfo(**{**conninfo_to_dict(dsn), **({"dbname": args.database} if args.database else {})})
        report = restore(args.dump, target, pg_restore=args.pg_restore)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if report["status"] != "ok":
            return 2 if report["status"] == "refused" else 1
        return verify(target, args.manifest) if args.manifest else 0
    except (OSError, RuntimeError, ValueError, LookupError, psycopg.Error) as error:
        # Only the error type: a connection error message can echo the DSN.
        print(f"Error: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
