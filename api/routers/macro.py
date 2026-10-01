"""Macro overview API (mounted at ``/api`` by ``api/main.py``, route
``/macro/overview``): Mexico/US inflation and interest rates stored by
``collector/run_macro_job.py`` in ``macro_observations``.

Like the personal-finance router and unlike ``api/routers/markets.py``, there is
NO demo data: official macro figures are never fabricated. An unreachable
database, and a database that has not applied
``db/migrations/0014_macro_series.sql`` yet, both answer 503 in clear text. A
series without rows reports ``no_data`` (``not_configured`` when it comes from
Banxico and ``BANXICO_TOKEN`` is unset). Like the other routers it imports
``get_repository`` from ``api.main`` (circular-import ordering: always enter
through ``api.main``).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.main import get_repository
from collector.local_repository import LocalPostgresRepository
from collector.macro_catalog import SECTIONS, SERIES_BY_ID, MacroSeries
from collector.macro_repository import MacroRepository

router = APIRouter()

logger = logging.getLogger("faro.api")

HISTORY_LIMIT = 36

# A latest observation older than this many days is flagged "stale".
STALE_AFTER_DAYS: dict[str, int] = {"monthly": 75, "weekly": 21, "daily": 7}


def get_macro_repository(
    repository: LocalPostgresRepository | None = Depends(get_repository),
) -> MacroRepository | None:
    if repository is None:
        return None
    return MacroRepository(pool=repository.pool, connection=repository.connection)


def _point(observation: tuple[date, float]) -> dict[str, Any]:
    return {"date": observation[0].isoformat(), "value": observation[1]}


def _item(
    series: MacroSeries, history: list[tuple[date, float]], *, today: date, banxico_configured: bool
) -> dict[str, Any]:
    latest = previous = None
    if history:
        latest = _point(history[-1])
        previous = _point(history[-2]) if len(history) > 1 else None
        stale = (today - history[-1][0]).days > STALE_AFTER_DAYS[series.frequency]
        status = "stale" if stale else "ok"
    elif series.provider == "banxico" and not banxico_configured:
        status = "not_configured"
    else:
        status = "no_data"
    return {
        "series_id": series.id,
        "label": series.label,
        "country": series.country,
        "unit": series.unit,
        "frequency": series.frequency,
        "source": series.source,
        "status": status,
        "latest": latest,
        "previous": previous,
        "history": [_point(observation) for observation in history],
    }


def _real_rate(items_by_id: dict[str, dict[str, Any]]) -> dict[str, float] | None:
    """Ex-post real yield: the 364-day Cetes rate deflated by the latest annual
    inflation, ``((1 + cetes/100) / (1 + inflation/100) - 1) * 100``."""
    cetes = items_by_id["mx_cetes_364d"]["latest"]
    inflation = items_by_id["mx_inflation_yoy"]["latest"]
    if cetes is None or inflation is None:
        return None
    real = ((1 + cetes["value"] / 100) / (1 + inflation["value"] / 100) - 1) * 100
    return {
        "cetes_364d": round(cetes["value"], 2),
        "inflation": round(inflation["value"], 2),
        "real_rate": round(real, 2),
    }


@router.get("/macro/overview")
def get_macro_overview(repository: MacroRepository | None = Depends(get_macro_repository)):
    """Latest reading, previous reading and the last 36 observations of each
    tracked inflation and rate series, plus the Mexican real rate."""
    if repository is None:
        raise HTTPException(status_code=503, detail="Base de datos no disponible para datos macroeconómicos")

    series_ids = [series_id for _, _, ids in SECTIONS for series_id in ids]
    try:
        observations = repository.get_recent_observations(series_ids, HISTORY_LIMIT)
    except RuntimeError as error:
        logger.warning("endpoint=get_macro_overview database error: %s: %s", type(error).__name__, error)
        raise HTTPException(status_code=503, detail="No se pudieron obtener los datos macroeconómicos") from None

    today = datetime.now(tz=UTC).date()
    banxico_configured = bool((os.getenv("BANXICO_TOKEN") or "").strip())
    items_by_id = {
        series_id: _item(
            SERIES_BY_ID[series_id], observations.get(series_id, []), today=today, banxico_configured=banxico_configured
        )
        for series_id in series_ids
    }
    return {
        "as_of": datetime.now(tz=UTC).isoformat(),
        "sections": [
            {"key": key, "label": label, "items": [items_by_id[series_id] for series_id in ids]}
            for key, label, ids in SECTIONS
        ],
        "real_rate": _real_rate(items_by_id),
    }
