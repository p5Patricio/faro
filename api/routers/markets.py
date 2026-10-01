"""Markets overview API (mounted at ``/api`` by ``api/main.py``, route
``/markets/overview``): indices, FX, commodities and yields tracked daily from
``config/universe.markets.json``.

Market-data endpoint, so it follows the same demo-fallback shape as
``api/routers/heatmap.py`` (``repository is None`` or a ``RuntimeError`` falls
back to synthetic data, gated by ``config.allow_demo_fallback``; 503 when
disabled). Like that module, it imports ``get_repository``/``get_app_config``
from ``api.main`` and defines its own small 503/log helpers rather than
importing the ones defined later in ``api.main`` (circular-import ordering).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from api.main import get_app_config, get_repository
from app_config import AppConfig
from collector.local_repository import LocalPostgresRepository
from collector.universe import MARKET_ASSET_CLASSES, load_universe_document

router = APIRouter()

logger = logging.getLogger("faro.api")

MARKETS_UNIVERSE_FILE = Path(__file__).resolve().parents[2] / "config" / "universe.markets.json"

# (key, label) in display order; each member of the universe file names its group key.
GROUPS: tuple[tuple[str, str], ...] = (
    ("indices_us", "EE.UU."),
    ("indices_mx", "México"),
    ("indices_ca", "Canadá"),
    ("indices_cn", "China y Hong Kong"),
    ("fx", "Divisas"),
    ("commodities", "Materias primas"),
    ("yields", "Rendimientos"),
)

STALE_AFTER_DAYS = 4

# Demo values stay inside a plausible magnitude for each unit; they are
# synthetic (hash-derived), never real quotes.
_DEMO_RANGE_BY_UNIT: dict[str, tuple[float, float]] = {
    "points": (1_000.0, 25_000.0),
    "price": (1.0, 2_000.0),
    "percent": (1.0, 5.5),
}


def _require_demo_fallback(config: AppConfig) -> None:
    if not config.allow_demo_fallback:
        raise HTTPException(
            status_code=503,
            detail="Fuente de datos no disponible y modo demo desactivado",
        )


def _log_repo_error(error: Exception) -> None:
    logger.warning(
        "endpoint=get_markets_overview serving demo data after repository error: %s: %s",
        type(error).__name__,
        error,
        exc_info=error,
    )


def _seed(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def _item(member: dict, *, last: float, change_pct: float, as_of: str, stale: bool) -> dict:
    return {
        "ticker": member["ticker"],
        "name": member.get("name") or member["ticker"],
        "last": round(last, 4),
        "change_pct": round(change_pct, 4),
        "as_of": as_of,
        "stale": stale,
        "currency": member.get("currency"),
        "unit": member.get("unit") or "price",
    }


def _assemble(members: tuple[dict, ...], items_by_ticker: dict[str, dict], *, is_demo: bool) -> dict:
    groups = []
    for key, label in GROUPS:
        items = [
            items_by_ticker[member["ticker"].upper()]
            for member in members
            if member.get("group") == key and member["ticker"].upper() in items_by_ticker
        ]
        if items:
            groups.append({"key": key, "label": label, "items": items})
    return {"as_of": datetime.now(tz=UTC).isoformat(), "is_demo": is_demo, "groups": groups}


def _bar_date(value) -> date:
    # The repository session is pinned to a non-UTC timezone; read the bar's date in UTC.
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.date()


def _build_live_overview(repository: LocalPostgresRepository) -> dict:
    members = load_universe_document(MARKETS_UNIVERSE_FILE).members
    assets_by_ticker = {
        (asset.get("ticker") or "").upper(): asset
        for asset in repository.get_assets()
        if (asset.get("asset_class") or "").lower() in MARKET_ASSET_CLASSES
    }
    price_pairs = repository.get_latest_price_pairs([asset["id"] for asset in assets_by_ticker.values()])
    today = datetime.now(tz=UTC).date()

    items_by_ticker: dict[str, dict] = {}
    for member in members:
        ticker = member["ticker"].upper()
        asset = assets_by_ticker.get(ticker)
        if asset is None:
            continue
        # Sort defensively (newest first), as the heatmap does.
        rows = price_pairs[price_pairs["asset_id"] == asset["id"]].sort_values("timestamp", ascending=False)
        if rows.empty:
            continue
        closes = [float(value) for value in rows["close"].tolist()]
        change_pct = 0.0
        if len(closes) > 1 and closes[1]:
            change_pct = ((closes[0] - closes[1]) / closes[1]) * 100
        bar_date = _bar_date(rows["timestamp"].iloc[0])
        items_by_ticker[ticker] = _item(
            member,
            last=closes[0],
            change_pct=change_pct,
            as_of=bar_date.isoformat(),
            stale=(today - bar_date).days > STALE_AFTER_DAYS,
        )
    return _assemble(members, items_by_ticker, is_demo=False)


def _demo_overview() -> dict:
    members = load_universe_document(MARKETS_UNIVERSE_FILE).members
    today = datetime.now(tz=UTC).date().isoformat()
    items_by_ticker: dict[str, dict] = {}
    for member in members:
        ticker = member["ticker"].upper()
        low, high = _DEMO_RANGE_BY_UNIT.get(member.get("unit") or "price", _DEMO_RANGE_BY_UNIT["price"])
        last = low + (_seed(f"{ticker}|last") % 10_000) / 10_000 * (high - low)
        change_pct = ((_seed(f"{ticker}|chg") % 601) - 300) / 100  # -3.00% .. +3.00%
        items_by_ticker[ticker] = _item(member, last=last, change_pct=change_pct, as_of=today, stale=False)
    return _assemble(members, items_by_ticker, is_demo=True)


@router.get("/markets/overview")
def get_markets_overview(
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    """Latest close and daily change for the tracked indices, FX pairs,
    commodities and yields, grouped for display. Instruments with no stored
    prices are skipped; groups left empty are omitted."""
    if repository is None:
        _require_demo_fallback(config)
        return _demo_overview()

    try:
        return _build_live_overview(repository)
    except RuntimeError as error:
        _log_repo_error(error)
        _require_demo_fallback(config)
        return _demo_overview()
