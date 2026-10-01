"""Banxico SIE (Sistema de Información Económica) REST API.

Needs ``BANXICO_TOKEN`` (sent as the ``Bmx-Token`` header). A missing token is
an expected state, not an error: ``fetch_banxico_series`` returns a typed
``not_configured`` result before any socket opens, so the job never sees an
exception for it. ``parse_banxico_response`` is pure and ``fetch`` is
injectable, so tests feed fixtures and never touch the network. Real network
and HTTP errors propagate to the caller (``collector/run_macro_job.py``
isolates them). The token is read lazily, never at import time, and never
placed in a URL or in an error message.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import requests

BANXICO_BASE = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"
REQUEST_TIMEOUT_SECONDS = 30

Observation = tuple[date, float]
BanxicoFetch = Callable[[str, str], dict[str, Any]]


@dataclass(frozen=True)
class BanxicoResult:
    status: str  # 'ok' | 'not_configured'
    observations: dict[str, list[Observation]] = field(default_factory=dict)  # by Banxico series id


def fetch_banxico_json(url: str, token: str) -> dict[str, Any]:
    response = requests.get(url, headers={"Bmx-Token": token}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def parse_banxico_response(payload: dict[str, Any]) -> dict[str, list[Observation]]:
    """``{"bmx": {"series": [{"idSerie", "datos": [{"fecha": "dd/mm/yyyy", "dato"}]}]}}``
    -> ascending observations per series id. ``"N/E"`` (no data) rows are
    skipped; a series that comes back without ``datos`` maps to ``[]``."""
    parsed: dict[str, list[Observation]] = {}
    for series in payload["bmx"]["series"]:
        observations: list[Observation] = []
        for row in series.get("datos") or []:
            try:
                value = float(str(row["dato"]).replace(",", "").strip())
            except ValueError:  # 'N/E'
                continue
            if not math.isfinite(value):
                continue
            observations.append((datetime.strptime(row["fecha"], "%d/%m/%Y").date(), value))
        parsed[series["idSerie"]] = sorted(observations)
    return parsed


def fetch_banxico_series(
    series_ids: Sequence[str],
    *,
    start: date,
    end: date,
    token: str | None = None,
    fetch: BanxicoFetch = fetch_banxico_json,
) -> BanxicoResult:
    """One request for every id in ``series_ids`` between ``start`` and ``end``.
    ``token=None`` reads ``BANXICO_TOKEN``; a blank or missing token returns
    ``not_configured`` without calling ``fetch``."""
    resolved = (token if token is not None else os.getenv("BANXICO_TOKEN") or "").strip()
    if not resolved:
        return BanxicoResult(status="not_configured")
    url = f"{BANXICO_BASE}/{','.join(series_ids)}/datos/{start.isoformat()}/{end.isoformat()}"
    return BanxicoResult(status="ok", observations=parse_banxico_response(fetch(url, resolved)))
