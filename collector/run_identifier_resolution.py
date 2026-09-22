"""One-shot job: resolve tracked-universe tickers to SEC CIKs.

Fetches `company_tickers.json` **once** via `SecEdgarClient` (never a
per-ticker loop -- spec "bulk-preferring"), upserts an `(asset_id, 'cik')`
`asset_identifiers` row for every matched ticker, and reports unresolved
tickers rather than dropping them silently (spec "Unresolved ticker is
logged, not skipped").

`run_identifier_resolution` itself takes an explicit `tickers: list[str]`
and stays decoupled from `collector.universe` -- it is exercised directly in
tests against a small fixture ticker list, matching the design's own PR
ordering (Phase 5 depends on Phase 1's repository methods and Phase 4's SEC
client, not on Phase 2's universe file landing first). The CLI entry point
below (`main`) is what actually reads the real universe document, and its
path is always a module constant or a `--universe-file`/`--tickers` CLI
argument -- never derived from an inbound request (non-matrix security
requirement, task 5.3).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

import psycopg
from dotenv import load_dotenv

from collector.ingestion_audit import RepositoryIngestionRecorder
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from collector.providers.sec_edgar_client import SecEdgarClient, SecEdgarConfig, SecEdgarConfigError
from collector.universe import load_universe_document

DEFAULT_UNIVERSE_PATH = "config/universe.sp100.json"  # module constant, never request-derived
INGESTION_SOURCE = "sec_edgar"
IDENTIFIER_SOURCE = "sec_company_tickers"
ID_TYPE_CIK = "cik"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cik_digits(raw_cik: Any) -> str:
    """Zero-pad a raw CIK to the 10-digit `asset_identifiers.id_value`
    convention (`320193` -> `"0000320193"`) -- distinct from `pad_cik`'s
    `"CIK0000320193"` URL form used by the SEC client's own endpoints."""
    digits = "".join(char for char in str(raw_cik) if char.isdigit())
    return digits.zfill(10)


def _build_ticker_to_cik(payload: Any) -> dict[str, str]:
    """`company_tickers.json` shape: a dict keyed by row index, each value
    `{"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}`."""
    lookup: dict[str, str] = {}
    entries = payload.values() if isinstance(payload, dict) else (payload or [])
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker", "")).strip().upper()
        cik = entry.get("cik_str")
        if ticker and cik is not None:
            lookup[ticker] = _cik_digits(cik)
    return lookup


def run_identifier_resolution(
    repository: Any,
    client: SecEdgarClient,
    tickers: list[str],
) -> dict[str, list[str]]:
    """Resolve every ticker in `tickers` to its SEC CIK, upsert matched rows,
    and report unresolved tickers -- both via the returned dict and via
    `ingestion_runs.metadata.unresolved_tickers`, never omitted."""
    started_at = _utcnow()
    normalized = sorted({ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()})

    fetch_result = client.fetch_company_tickers()

    resolved: list[str] = []
    unresolved: list[str] = []

    if not fetch_result.get("ok"):
        unresolved = list(normalized)
    else:
        ticker_to_cik = _build_ticker_to_cik(fetch_result.get("payload"))
        rows: list[dict[str, Any]] = []
        for ticker in normalized:
            cik = ticker_to_cik.get(ticker)
            if cik is None:
                unresolved.append(ticker)
                continue
            asset_id = repository.get_or_create_asset(ticker)
            rows.append(
                {
                    "asset_id": asset_id,
                    "id_type": ID_TYPE_CIK,
                    "id_value": cik,
                    "source": IDENTIFIER_SOURCE,
                    "metadata": {},
                }
            )
            resolved.append(ticker)
        if rows:
            repository.upsert_asset_identifiers(rows)

    finished_at = _utcnow()

    if unresolved:
        print(
            f"identifier resolution: {len(unresolved)} ticker(s) unresolved "
            f"(no company_tickers.json match): {', '.join(unresolved)}"
        )

    repository.insert_ingestion_run(
        source=INGESTION_SOURCE,
        endpoint="identifier_resolution",
        target_key="",
        started_at=started_at,
        finished_at=finished_at,
        status="success" if fetch_result.get("ok") else "failure",
        request_count=1,
        rows_written=len(resolved),
        error=None if fetch_result.get("ok") else fetch_result.get("reason"),
        metadata={"unresolved_tickers": unresolved},
    )

    return {"resolved": resolved, "unresolved": unresolved}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve tracked-universe tickers to SEC CIKs via company_tickers.json"
    )
    parser.add_argument(
        "--universe-file",
        default=DEFAULT_UNIVERSE_PATH,
        help="Universe snapshot document read when --tickers is not given",
    )
    parser.add_argument(
        "--tickers",
        help="Comma-separated tickers overriding the universe file, for example AAPL,MSFT",
    )
    return parser.parse_args()


def _parse_tickers(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [ticker.strip().upper() for ticker in value.split(",") if ticker.strip()]


def main() -> None:
    # Must run BEFORE SecEdgarConfig.from_env() -- see the identical fix in
    # collector/run_fundamental_ingestion.py for the full rationale.
    load_dotenv(override=True)
    args = parse_args()
    config = SecEdgarConfig.from_env()
    if config is None:
        raise SecEdgarConfigError(
            "SEC_USER_AGENT is not configured; refusing to run identifier resolution"
        )

    tickers = _parse_tickers(args.tickers)
    if tickers is None:
        doc = load_universe_document(args.universe_file)
        tickers = [member["ticker"] for member in doc.members]

    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        client = SecEdgarClient(config=config, recorder=RepositoryIngestionRecorder(repository))
        result = run_identifier_resolution(repository, client, tickers)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
