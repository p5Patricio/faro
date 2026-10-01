"""Market heatmap API (mounted at ``/api`` by ``api/main.py``, route
``/heatmap``). This is a market-data endpoint, so -- unlike
``api/routers/finance.py``, which deliberately has NO demo fallback -- it
follows the exact demo-fallback shape every other market-data endpoint in
``api/main.py`` uses: ``repository is None`` or a ``RuntimeError`` falls
back to synthetic data, gated by ``config.allow_demo_fallback`` (503 when
disabled).

Import-order note: this module imports ``get_repository``/``get_app_config``
from ``api.main`` (safe -- both are defined near the top of that module,
before its deferred router-mount imports run). It deliberately does NOT
import ``api.main``'s ``require_demo_fallback``/``log_repo_error`` helpers:
those are defined further down in ``api/main.py``, AFTER the point where
that module imports and mounts this router, so importing them at this
module's top level would be a circular/ordering failure. This module
defines its own small equivalents instead (same behavior, same logger).
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from api.main import get_app_config, get_repository
from app_config import AppConfig
from collector.local_repository import LocalPostgresRepository
from collector.universe import HEATMAP_MARKETS, HeatmapMarket, load_universe_document

router = APIRouter()

logger = logging.getLogger("faro.api")

# Fallback used only if config/universe.sp100.json itself can't be read (it
# is checked into the repo, so this should never trigger in practice) --
# mirrors api/main.py's demo_assets() in spirit: a tiny, clearly-synthetic
# set so the endpoint still renders something instead of an empty page.
# The Mexican and Canadian universes have no such fallback: they render empty.
_FALLBACK_DEMO_MEMBERS: tuple[dict[str, str], ...] = (
    {"ticker": "AAPL", "name": "Apple Inc."},
    {"ticker": "MSFT", "name": "Microsoft Corp."},
    {"ticker": "GOOGL", "name": "Alphabet Inc. (Class A)"},
    {"ticker": "AMZN", "name": "Amazon"},
)

# Static, best-effort GICS-style sector classification for the S&P 100
# universe (config/universe.sp100.json). This is public reference data
# about what business each company is in -- NOT sourced from the database,
# because neither `assets` nor `prices` stores a sector column (see
# db/migrations/0001_core_market.sql). Keep in sync manually if the
# universe snapshot's membership changes. The Mexican and Canadian universes
# carry their own `sector` per member instead (config/universe.mx.json,
# config/universe.ca.json).
SECTOR_BY_TICKER: dict[str, str] = {
    "AAPL": "Information Technology", "ABBV": "Health Care", "ABT": "Health Care",
    "ACN": "Information Technology", "ADBE": "Information Technology", "AMAT": "Information Technology",
    "AMD": "Information Technology", "AMGN": "Health Care", "AMT": "Real Estate",
    "AMZN": "Consumer Discretionary", "AVGO": "Information Technology", "AXP": "Financials",
    "BA": "Industrials", "BAC": "Financials", "BKNG": "Consumer Discretionary",
    "BLK": "Financials", "BMY": "Health Care", "BNY": "Financials",
    "BRK-B": "Financials", "C": "Financials", "CAT": "Industrials",
    "CL": "Consumer Staples", "CMCSA": "Communication Services", "COF": "Financials",
    "COP": "Energy", "COST": "Consumer Staples", "CRM": "Information Technology",
    "CSCO": "Information Technology", "CVS": "Health Care", "CVX": "Energy",
    "DE": "Industrials", "DHR": "Health Care", "DIS": "Communication Services",
    "DUK": "Utilities", "EMR": "Industrials", "FDX": "Industrials",
    "GD": "Industrials", "GE": "Industrials", "GEV": "Industrials",
    "GILD": "Health Care", "GM": "Consumer Discretionary", "GOOG": "Communication Services",
    "GOOGL": "Communication Services", "GS": "Financials", "HD": "Consumer Discretionary",
    "HON": "Industrials", "IBM": "Information Technology", "INTC": "Information Technology",
    "INTU": "Information Technology", "ISRG": "Health Care", "JNJ": "Health Care",
    "JPM": "Financials", "KO": "Consumer Staples", "LIN": "Materials",
    "LLY": "Health Care", "LMT": "Industrials", "LOW": "Consumer Discretionary",
    "LRCX": "Information Technology", "MA": "Financials", "MCD": "Consumer Discretionary",
    "MDLZ": "Consumer Staples", "MDT": "Health Care", "META": "Communication Services",
    "MMM": "Industrials", "MO": "Consumer Staples", "MRK": "Health Care",
    "MS": "Financials", "MSFT": "Information Technology", "MU": "Information Technology",
    "NEE": "Utilities", "NFLX": "Communication Services", "NKE": "Consumer Discretionary",
    "NOW": "Information Technology", "NVDA": "Information Technology", "ORCL": "Information Technology",
    "PEP": "Consumer Staples", "PFE": "Health Care", "PG": "Consumer Staples",
    "PLTR": "Information Technology", "PM": "Consumer Staples", "QCOM": "Information Technology",
    "RTX": "Industrials", "SBUX": "Consumer Discretionary", "SCHW": "Financials",
    "SO": "Utilities", "SPG": "Real Estate", "T": "Communication Services",
    "TMO": "Health Care", "TMUS": "Communication Services", "TSLA": "Consumer Discretionary",
    "TXN": "Information Technology", "UBER": "Industrials", "UNH": "Health Care",
    "UNP": "Industrials", "UPS": "Industrials", "USB": "Financials",
    "V": "Financials", "VZ": "Communication Services", "WFC": "Financials",
    "WMT": "Consumer Staples", "XOM": "Energy",
}


def _require_demo_fallback(config: AppConfig) -> None:
    """Same 503 contract as api.main.require_demo_fallback (see module
    docstring for why this isn't a direct import)."""
    if not config.allow_demo_fallback:
        raise HTTPException(
            status_code=503,
            detail="Fuente de datos no disponible y modo demo desactivado",
        )


def _log_repo_error(error: Exception) -> None:
    logger.warning(
        "endpoint=get_heatmap serving demo data after repository error: %s: %s",
        type(error).__name__,
        error,
        exc_info=error,
    )


def _ticker_seed(key: str) -> int:
    """Stable (cross-process, cross-run) integer derived from `key`, used to
    deterministically vary the placeholder numbers below per ticker. NOT a
    source of real financial data -- see `_placeholder_market_cap`."""
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def _placeholder_market_cap(ticker: str, price: float) -> float:
    """PLACEHOLDER market-cap estimate -- NOT real data.

    Used only for a ticker with no stored real market cap (`asset_market_caps`,
    db/migrations/0015_asset_market_caps.sql, filled weekly by
    `collector.run_market_cap_job`): while that table is missing or empty, or
    before the job has covered the ticker. `_tile` flags every such tile with
    `market_cap_estimated: true`.

    A deterministic, per-ticker pseudo share count (stable across requests,
    NOT sourced from any real filing) scaled into a plausible large-cap range
    (300M-15.3B shares), multiplied by the REAL latest close price. This gives
    the treemap varied tile sizes instead of one flat placeholder for every
    ticker, but the resulting number must never be read as a real market cap.
    """
    placeholder_shares = 300_000_000 + (_ticker_seed(f"{ticker}|shares") % 15_000_000_000)
    return round(price * placeholder_shares, 2)


def _synthetic_demo_price(ticker: str) -> float:
    return round(10.0 + (_ticker_seed(f"{ticker}|price") % 49_000) / 100, 2)


def _synthetic_demo_change_pct(ticker: str) -> float:
    # -6.00% .. +6.00% in 0.01% steps.
    return round(((_ticker_seed(f"{ticker}|chg") % 1201) - 600) / 100, 2)


def _tile(
    *,
    ticker: str,
    name: str,
    sector: str,
    price: float,
    change_pct: float,
    currency: str,
    market_cap: float | None,
) -> dict:
    """`market_cap` is the latest stored real value; `None` means none is stored
    yet, and the tile then carries the placeholder estimate, flagged."""
    estimated = not market_cap
    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "market_cap": _placeholder_market_cap(ticker, price) if estimated else market_cap,
        "change_pct": round(change_pct, 4),
        "price": round(price, 4),
        "currency": currency,
        "market_cap_estimated": estimated,
    }


def _members(market: HeatmapMarket) -> tuple[dict, ...]:
    try:
        return load_universe_document(market.universe_file).members
    except (OSError, ValueError):
        return ()


def _sectors(market_key: str, members: tuple[dict, ...]) -> dict[str, str]:
    if market_key == "us":
        return SECTOR_BY_TICKER
    return {str(member["ticker"]).upper(): str(member.get("sector") or "Other") for member in members}


def _build_live_heatmap(repository: LocalPostgresRepository, market_key: str) -> list[dict]:
    market = HEATMAP_MARKETS[market_key]
    members = _members(market)
    tracked_tickers = frozenset(str(member["ticker"]).upper() for member in members)
    sectors = _sectors(market_key, members)
    assets = [
        asset
        for asset in repository.get_assets()
        if (asset.get("asset_class") or "").lower() == market.asset_class
        and (not tracked_tickers or (asset.get("ticker") or "").upper() in tracked_tickers)
    ]
    if not assets:
        return []

    asset_ids = [asset["id"] for asset in assets]
    price_pairs = repository.get_latest_price_pairs(asset_ids)
    market_caps = repository.get_latest_market_caps(asset_ids)

    tiles: list[dict] = []
    for asset in assets:
        # Sort defensively (newest first) rather than trusting caller order --
        # the real repository query already orders this way, but a stub or
        # future caller shouldn't be able to silently invert price/change_pct.
        rows = price_pairs[price_pairs["asset_id"] == asset["id"]].sort_values("timestamp", ascending=False)
        if rows.empty:
            continue
        closes = [float(value) for value in rows["close"].tolist()]
        price = closes[0]
        change_pct = 0.0
        if len(closes) > 1 and closes[1]:
            change_pct = ((price - closes[1]) / closes[1]) * 100

        ticker = (asset.get("ticker") or "").upper()
        tiles.append(
            _tile(
                ticker=ticker,
                name=asset.get("name") or ticker,
                sector=sectors.get(ticker, "Other"),
                price=price,
                change_pct=change_pct,
                currency=market.currency,
                market_cap=market_caps.get(asset["id"]),
            )
        )
    return tiles


def _demo_heatmap(market_key: str) -> list[dict]:
    market = HEATMAP_MARKETS[market_key]
    members = _members(market) or (_FALLBACK_DEMO_MEMBERS if market_key == "us" else ())
    sectors = _sectors(market_key, members)

    tiles = []
    for member in members:
        ticker = str(member["ticker"]).upper()
        name = str(member.get("name") or ticker)
        price = _synthetic_demo_price(ticker)
        change_pct = _synthetic_demo_change_pct(ticker)
        tiles.append(
            _tile(
                ticker=ticker,
                name=name,
                sector=sectors.get(ticker, "Other"),
                price=price,
                change_pct=change_pct,
                currency=market.currency,
                market_cap=None,
            )
        )
    return tiles


@router.get("/heatmap")
def get_heatmap(
    market: str = Query(default="us"),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    """Heatmap tiles for `market` (`us` S&P 100, `mx` IPC, `ca` S&P/TSX 60):
    `{ticker, name, sector, market_cap, change_pct, price, currency,
    market_cap_estimated}` per tracked stock. `market_cap` is the latest stored
    real value (`asset_market_caps`); `market_cap_estimated` is true only when
    none is stored and the placeholder estimate is used instead. Any other
    `market` value is rejected rather than silently ignored."""
    market_key = market.strip().lower()
    if market_key not in HEATMAP_MARKETS:
        raise HTTPException(
            status_code=422,
            detail=f"Mercado no soportado: '{market}'. Valores validos: {', '.join(HEATMAP_MARKETS)}",
        )

    if repository is None:
        _require_demo_fallback(config)
        return _demo_heatmap(market_key)

    try:
        return _build_live_heatmap(repository, market_key)
    except RuntimeError as error:
        _log_repo_error(error)
        _require_demo_fallback(config)
        return _demo_heatmap(market_key)
