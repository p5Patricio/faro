"""Adapts `LocalPostgresRepository` to the `IngestionRunRecorder` Protocol.

`SecEdgarClient` (and any future shared-ingestion client) writes exactly one
`IngestionRun` per fetch from a `finally` block -- see
`collector/providers/sec_edgar_client.py`. `RepositoryIngestionRecorder` is
the concrete `recorder=` implementation that persists that row via
`LocalPostgresRepository.insert_ingestion_run`, mapping every `IngestionRun`
field 1:1 (design.md: "`collector/ingestion_audit.py` (new) holds
`RepositoryIngestionRecorder(repository)` implementing `IngestionRunRecorder`
over `insert_ingestion_run`").

`IngestionRun.max_filed_date` (populated only by `fetch_submissions`, from its
`filings.recent.filingDate` list -- see `sec_edgar_client._max_filed_date`) is
threaded straight through to `insert_ingestion_run`'s own `max_filed_date`
column, enabling the point-in-time-features spec's "which filing dates were
available for this run" query. Full per-fact `filed`/`period_end` capture for
XBRL facts stays a sibling change's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from collector.providers.sec_edgar_client import IngestionRun


@dataclass
class RepositoryIngestionRecorder:
    """`IngestionRunRecorder` implementation backed by a repository.

    Accepts anything shaped like `LocalPostgresRepository` (duck-typed, so
    tests can inject a fake) exposing `insert_ingestion_run(...)`.
    """

    repository: Any

    def record(self, run: IngestionRun) -> None:
        self.repository.insert_ingestion_run(
            source=run.source,
            endpoint=run.endpoint,
            target_key=run.target_key,
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status,
            http_status=run.http_status,
            rows_written=run.rows_written,
            request_count=run.request_count,
            throttle_wait_seconds=run.throttle_wait_seconds,
            max_filed_date=run.max_filed_date,
            error=run.error,
            metadata=run.metadata,
        )
