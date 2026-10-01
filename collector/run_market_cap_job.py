"""Store the latest real market capitalization of every heatmap stock (the
S&P 100, the IPC and the S&P/TSX 60 universes) in ``asset_market_caps``.

Usage::

    py -3.14 -m collector.run_market_cap_job [--out reports/market_cap_job.json]

Each ticker is read from yfinance (``fast_info.market_cap``, falling back to
``info["marketCap"]``) and appended as a new row in the market's currency (USD,
MXN, CAD). Only assets the price job already created are processed. Every ticker
is isolated: a failing one is recorded under its market's ``problems`` and the
rest still run. If the table is missing (``db/migrations/0015_asset_market_caps.sql``
not applied) or the database is unreachable, the job logs, reports
``"status": "skipped"`` and exits 0, so the scheduled weekly cycle never depends
on it.

The report counts problems under ``errors``, never ``failed``:
``ops/notification_dispatch.py`` reads every ``reports/*.json`` and would turn a
``failed`` count into a job-failure notification, and market caps are non-fatal.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import yfinance as yf

from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from collector.universe import HEATMAP_MARKETS, load_universe_document

logger = logging.getLogger("faro.market_cap")

SOURCE = "yfinance"
MIGRATION_HINT = "apply db/migrations/0015_asset_market_caps.sql (py -3.14 -m db.migrate)"

TickerFactory = Callable[[str], Any]


def _skipped(reason: str) -> dict[str, Any]:
    logger.warning("market cap job skipped: %s", reason)
    return {"status": "skipped", "reason": reason, "stored": 0, "errors": 0, "markets": {}}


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def fetch_market_cap(ticker: str, ticker_factory: TickerFactory = yf.Ticker) -> float | None:
    """``fast_info.market_cap`` first, ``info["marketCap"]`` as the fallback;
    ``None`` when neither yields a positive number."""
    stock = ticker_factory(ticker)
    try:
        market_cap = _positive_number(stock.fast_info.market_cap)
    except Exception:  # fast_info raises for some symbols; the info fallback decides
        market_cap = None
    if market_cap is None:
        market_cap = _positive_number((stock.info or {}).get("marketCap"))
    return market_cap


def run_market_cap_job(repository: LocalPostgresRepository, *, ticker_factory: TickerFactory = yf.Ticker) -> dict[str, Any]:
    try:
        if not repository.relation_exists("asset_market_caps"):
            return _skipped(f"asset_market_caps table is missing; {MIGRATION_HINT}")
        asset_ids = {str(asset["ticker"]).upper(): asset["id"] for asset in repository.get_assets()}
    except RuntimeError as error:
        return _skipped(f"database error: {error}")

    report: dict[str, Any] = {"status": "ok", "stored": 0, "errors": 0, "markets": {}}
    for key, market in HEATMAP_MARKETS.items():
        summary: dict[str, Any] = {"stored": 0, "problems": {}}
        report["markets"][key] = summary
        try:
            members = load_universe_document(market.universe_file).members
        except (OSError, ValueError) as error:
            summary["problems"]["universe"] = f"{type(error).__name__}: {error}"
            continue

        for member in members:
            ticker = str(member["ticker"]).upper()
            try:
                if ticker not in asset_ids:
                    summary["problems"][ticker] = "asset not collected yet"
                    continue
                market_cap = fetch_market_cap(ticker, ticker_factory)
                if market_cap is None:
                    summary["problems"][ticker] = "no market cap returned"
                    continue
                repository.insert_asset_market_cap(asset_ids[ticker], market_cap, market.currency, SOURCE)
                summary["stored"] += 1
            except Exception as error:  # isolation boundary: one ticker must not stop the others
                logger.warning("market cap for %s failed: %s: %s", ticker, type(error).__name__, error)
                summary["problems"][ticker] = f"{type(error).__name__}: {error}"

        report["stored"] += summary["stored"]
        report["errors"] += len(summary["problems"])
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Store real market caps for the heatmap universes")
    parser.add_argument("--out", help="Optional JSON report path (the report is always printed too)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    try:
        with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
            report = run_market_cap_job(LocalPostgresRepository(connection=connection))
    except (psycopg.Error, RuntimeError) as error:  # unreachable database or no DSN configured
        report = _skipped(f"database unavailable: {type(error).__name__}")

    text = json.dumps(report, indent=2, default=str)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
