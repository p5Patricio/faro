"""One-shot job: ingest SEC XBRL `companyfacts` for every asset with a
resolved CIK.

Mirrors `collector/run_identifier_resolution.py` (module constants, explicit
argument list decoupled from a universe file, `main()` reads env + opens
psycopg). Per CIK, calls `SecEdgarClient.fetch_company_facts` -- the job
itself writes **no** per-fetch `ingestion_runs` row: the client's own
`finally` block already emits exactly one `IngestionRun` per fetch through
`RepositoryIngestionRecorder` (see `collector/ingestion_audit.py`).
Duplicating it here would double-count `ingestion_runs` and create two
disagreeing sources of audit truth.

A failed fetch is recorded by `reason` code only, never `detail` --
`detail` can echo the request URL or headers and `ingestion_runs.error`/
`metadata` must never carry `SEC_USER_AGENT` (the operator's email). One bad
CIK never aborts the run; an unmapped CIK is reported as unresolved, never
silently dropped.

After the loop, exactly one job-summary `ingestion_runs` row closes the run
(`endpoint="fundamental_ingestion"`), and the `--out` JSON report carries a
per-logical-concept coverage summary (each `CONCEPT_CHAINS` key -> count of
processed CIKs that resolved at least one of its tags) -- this is the Phase 3
gate (tasks.md Open Question 6): the chains are pruned/extended on evidence
before factor math is frozen.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from collector.fundamentals import CONCEPT_CHAINS, parse_company_facts
from collector.ingestion_audit import RepositoryIngestionRecorder
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from collector.providers.sec_edgar_client import SecEdgarClient, SecEdgarConfig, SecEdgarConfigError

DEFAULT_OUT_PATH = "artifacts/fund_coverage.json"  # module constant, never request-derived
INGESTION_SOURCE = "sec_edgar"
ID_TYPE_CIK = "cik"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _pad10(value: Any) -> str:
    """Zero-pad a raw CIK to the 10-digit `asset_identifiers.id_value`
    convention (`"320193"` -> `"0000000320193"[-10:]`... i.e. `"0000320193"`)
    -- the same normalization `run_identifier_resolution._cik_digits` uses,
    kept local so this module has no cross-job coupling."""
    digits = "".join(char for char in str(value) if char.isdigit())
    return digits.zfill(10)


def _resolve_targets(
    identifiers: list[dict[str, Any]], ciks: list[str] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """`ciks` FILTERS the resolved identifier list; it never bypasses it, so
    an unmapped CIK cannot be ingested. Returns `(targets, unresolved_ciks)`
    where `unresolved_ciks` are the requested CIKs (10-digit padded) with no
    matching `asset_identifiers` row."""
    if ciks is None:
        return list(identifiers), []

    wanted: list[str] = []
    seen: set[str] = set()
    for raw in ciks:
        padded = _pad10(raw)
        if padded and padded not in seen:
            seen.add(padded)
            wanted.append(padded)

    by_cik = {row["id_value"]: row for row in identifiers}
    targets: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for cik in wanted:
        row = by_cik.get(cik)
        if row is None:
            unresolved.append(cik)
        else:
            targets.append(row)
    return targets, unresolved


def run_fundamental_ingestion(
    repository: Any,
    client: SecEdgarClient,
    *,
    ciks: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Ingest `companyfacts` for every resolved CIK (optionally filtered by
    `ciks` and capped by `limit`); return the `--out` report payload."""
    started_at = _utcnow()

    identifiers = repository.get_asset_identifiers(id_type=ID_TYPE_CIK)
    targets, unresolved_ciks = _resolve_targets(identifiers, ciks)
    if limit is not None:
        targets = targets[:limit]

    rows_written_total = 0
    failed_ciks: list[dict[str, str]] = []
    assets_with_no_facts: list[str] = []
    assets_processed = 0
    max_filed_date_seen: str | None = None
    concept_coverage: dict[str, int] = {concept: 0 for concept in CONCEPT_CHAINS}

    for row in targets:
        asset_id = row["asset_id"]
        cik = row["id_value"]
        assets_processed += 1

        result = client.fetch_company_facts(cik)
        if not result.get("ok"):
            failed_ciks.append({"cik": cik, "reason": result.get("reason")})
            continue

        fact_rows = parse_company_facts(result["payload"], asset_id=asset_id)
        if not fact_rows:
            assets_with_no_facts.append(cik)
            continue

        repository.upsert_fundamental_facts(fact_rows)
        rows_written_total += len(fact_rows)

        concepts_seen = {(fact["taxonomy"], fact["concept"]) for fact in fact_rows}
        for logical_concept, (_unit, chain) in CONCEPT_CHAINS.items():
            if concepts_seen & set(chain):
                concept_coverage[logical_concept] += 1

        newest_filed = max(fact["filed_date"] for fact in fact_rows)
        if max_filed_date_seen is None or newest_filed > max_filed_date_seen:
            max_filed_date_seen = newest_filed

    finished_at = _utcnow()
    status = "success" if not failed_ciks else "failure"
    request_count = len(targets)

    metadata = {
        "failed_ciks": failed_ciks,
        "assets_processed": assets_processed,
        "assets_with_no_facts": assets_with_no_facts,
        "unresolved_ciks": unresolved_ciks,
    }

    repository.insert_ingestion_run(
        source=INGESTION_SOURCE,
        endpoint="fundamental_ingestion",
        target_key="",
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        request_count=request_count,
        rows_written=rows_written_total,
        max_filed_date=max_filed_date_seen,
        error=None,
        metadata=metadata,
    )

    return {
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "assets_processed": assets_processed,
        "assets_with_no_facts": assets_with_no_facts,
        "failed_ciks": failed_ciks,
        "unresolved_ciks": unresolved_ciks,
        "request_count": request_count,
        "rows_written": rows_written_total,
        "max_filed_date": max_filed_date_seen,
        "per_concept_coverage": concept_coverage,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest SEC XBRL companyfacts for every asset with a resolved CIK"
    )
    parser.add_argument(
        "--ciks",
        help="Comma-separated raw CIKs restricting the run, for example 320193,789019",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap the number of assets processed this run"
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT_PATH,
        help="Path to write the JSON coverage report (default: artifacts/fund_coverage.json)",
    )
    return parser.parse_args()


def _parse_ciks(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    args = parse_args()
    config = SecEdgarConfig.from_env()
    if config is None:
        raise SecEdgarConfigError(
            "SEC_USER_AGENT is not configured; refusing to run fundamental ingestion"
        )

    ciks = _parse_ciks(args.ciks)

    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        client = SecEdgarClient(config=config, recorder=RepositoryIngestionRecorder(repository))
        report = run_fundamental_ingestion(repository, client, ciks=ciks, limit=args.limit)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
