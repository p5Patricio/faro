from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Iterable

import psycopg

from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


REQUIRED_ML_RELATIONS = (
    "features_daily",
    "labels_daily",
    "model_runs",
    "predictions",
    "prediction_feedback",
    "backtests",
    "backtest_trades",
    "paper_trading_runs",
    "paper_trading_events",
    "risk_profiles",
    "notification_rules",
    "notifications",
    "asset_identifiers",
    "ingestion_runs",
    "fundamental_facts",
)


@dataclass(frozen=True)
class RelationStatus:
    name: str
    available: bool
    status_code: int | None = None
    error: str | None = None


def check_relations(
    repository: LocalPostgresRepository,
    relations: Iterable[str] = REQUIRED_ML_RELATIONS,
) -> list[RelationStatus]:
    statuses: list[RelationStatus] = []
    for relation in relations:
        try:
            available = repository.relation_exists(relation)
            statuses.append(RelationStatus(name=relation, available=available))
        except RuntimeError as exc:
            statuses.append(RelationStatus(name=relation, available=False, error=str(exc)))
    return statuses


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check required local Postgres ML schema relations")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    connection_string = LocalPostgresConfig.from_env().dsn

    with psycopg.connect(connection_string) as connection:
        repository = LocalPostgresRepository(connection=connection)
        statuses = check_relations(repository)

    missing = [status for status in statuses if not status.available]

    if args.json:
        print(json.dumps([asdict(status) for status in statuses], indent=2))
    else:
        for status in statuses:
            state = "OK" if status.available else "MISSING"
            suffix = f" ({status.status_code})" if status.status_code else ""
            print(f"{state}\t{status.name}{suffix}")

        if missing:
            print()
            print("Run py -3.14 -m db.migrate")

    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
