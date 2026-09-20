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
from collector.universe import load_universe_document

router = APIRouter()

logger = logging.getLogger("faro.api")

DEFAULT_UNIVERSE_FILE = "config/universe.sp100.json"

# Fallback used only if config/universe.sp100.json itself can't be read (it
# is checked into the repo, so this should never trigger in practice) --
# mirrors api/main.py's demo_assets() in spirit: a tiny, clearly-synthetic
# set so the endpoint still renders something instead of an empty page.
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
# universe snapshot's membership changes.
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

    Real market capitalization (shares outstanding x price) is not stored
    anywhere in this schema: `assets` has no `market_cap`/`shares_outstanding`
    column (db/migrations/0001_core_market.sql), and `prices` is OHLCV-only.
    A genuine figure would require reusing brain/fundamental_factors.py's
    point-in-time SEC-XBRL concept-chain resolution (`shares_outstanding_mve`),
    which is built for one-asset-at-a-time backtest research (fiscal-period
    fallback, as-of cutoffs, restatement handling) -- not a cheap ~100-ticker
    batch read for a live UI endpoint. Reusing it here would be exactly the
    "new data-ingestion pipeline" this feature was told to avoid building.

    So: a deterministic, per-ticker pseudo share count (stable across
    requests, NOT sourced from any real filing) scaled into a plausible
    large-cap range (300M-15.3B shares), multiplied by the REAL latest close
    price. This gives the treemap varied tile sizes instead of one flat
    placeholder for every ticker, but the resulting number must never be
    read as a real market cap -- a future phase should replace this with
    ingested shares-outstanding data.
    """
    placeholder_shares = 300_000_000 + (_ticker_seed(f"{ticker}|shares") % 15_000_000_000)
    return round(price * placeholder_shares, 2)


def _synthetic_demo_price(ticker: str) -> float:
    return round(10.0 + (_ticker_seed(f"{ticker}|price") % 49_000) / 100, 2)


def _synthetic_demo_change_pct(ticker: str) -> float:
    # -6.00% .. +6.00% in 0.01% steps.
    return round(((_ticker_seed(f"{ticker}|chg") % 1201) - 600) / 100, 2)


def _tile(*, ticker: str, name: str, price: float, change_pct: float) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "sector": SECTOR_BY_TICKER.get(ticker, "Other"),
        "market_cap": _placeholder_market_cap(ticker, price),
        "change_pct": round(change_pct, 4),
        "price": round(price, 4),
    }


def _tracked_us_tickers() -> frozenset[str]:
    try:
        doc = load_universe_document(DEFAULT_UNIVERSE_FILE)
    except (OSError, ValueError):
        return frozenset()
    return frozenset(str(member["ticker"]).upper() for member in doc.members)


def _build_live_heatmap(repository: LocalPostgresRepository) -> list[dict]:
    tracked_tickers = _tracked_us_tickers()
    assets = [
        asset
        for asset in repository.get_assets()
        if (asset.get("asset_class") or "").lower() == "stock"
        and (not tracked_tickers or (asset.get("ticker") or "").upper() in tracked_tickers)
    ]
    if not assets:
        return []

    price_pairs = repository.get_latest_price_pairs([asset["id"] for asset in assets])

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
        tiles.append(_tile(ticker=ticker, name=asset.get("name") or ticker, price=price, change_pct=change_pct))
    return tiles


def _demo_heatmap() -> list[dict]:
    try:
        members = load_universe_document(DEFAULT_UNIVERSE_FILE).members
    except (OSError, ValueError):
        members = _FALLBACK_DEMO_MEMBERS

    tiles = []
    for member in members:
        ticker = str(member["ticker"]).upper()
        name = str(member.get("name") or ticker)
        price = _synthetic_demo_price(ticker)
        change_pct = _synthetic_demo_change_pct(ticker)
        tiles.append(_tile(ticker=ticker, name=name, price=price, change_pct=change_pct))
    return tiles


@router.get("/heatmap")
def get_heatmap(
    market: str = Query(default="us"),
    repository: LocalPostgresRepository | None = Depends(get_repository),
    config: AppConfig = Depends(get_app_config),
):
    """S&P-100-universe heatmap tiles: `{ticker, name, sector, market_cap,
    change_pct, price}` per tracked US stock. US market only for this pass
    -- Mexico/.MX and China are explicitly out of scope (later phases), so
    any other `market` value is rejected rather than silently ignored."""
    if market.strip().lower() != "us":
        raise HTTPException(
            status_code=422,
            detail="Solo 'us' esta soportado en esta fase (Mexico/.MX y China quedan fuera de alcance)",
        )

    if repository is None:
        _require_demo_fallback(config)
        return _demo_heatmap()

    try:
        return _build_live_heatmap(repository)
    except RuntimeError as error:
        _log_repo_error(error)
        _require_demo_fallback(config)
        return _demo_heatmap()
