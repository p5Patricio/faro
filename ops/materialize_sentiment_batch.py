"""One-shot job: materialize `sentiment_v1` for every asset in the tracked
universe -- crypto and stocks alike, mirroring
`ops/materialize_technical_alpha_batch.py`'s "no stock-only restriction"
structure (unlike `ops/materialize_fundamentals_batch.py`). Companion to
`brain/materialize_sentiment.py` (single-ticker only); defaults to
`config/targets.core.json`, the full tracked universe.

Each ticker's `materialize_asset_sentiment` call does real work beyond a
features join: it also fetches fresh Finnhub headlines and runs any
unscored ones through FinBERT (lazily loaded once per process, not once per
ticker -- `brain.sentiment_factors`'s pipeline cache is module-level, so the
~400MB of weights load exactly once for the whole batch). That makes this
job meaningfully slower per ticker than the technical-alpha batch; still
in-process rather than subprocess-per-ticker, like that job, since there is
still no model training here. A single failing ticker (a Finnhub outage, a
missing asset) is caught and reported; it never aborts the batch -- same
contract as every other `materialize_*_batch.py` job.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

import psycopg

from brain.materialize_sentiment import (
    SentimentMaterializationConfig,
    materialize_asset_sentiment,
)
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from collector.news_repository import NewsRepository

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets-file", default="config/targets.core.json")
    parser.add_argument("--feature-set", default="sentiment_v1")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--out", help="Optional JSON summary path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = json.loads((REPO_ROOT / args.targets_file).read_text(encoding="utf-8"))

    results = []
    errors = []
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        news_repository = NewsRepository(connection=connection)
        for ticker in tickers:
            try:
                result = materialize_asset_sentiment(
                    repository,
                    news_repository,
                    SentimentMaterializationConfig(
                        ticker=ticker,
                        feature_set=args.feature_set,
                        lookback_days=args.lookback_days,
                    ),
                )
                results.append(
                    {
                        "ticker": result.ticker,
                        "asset_class": result.asset_class,
                        "headlines_ingested": result.headlines_ingested,
                        "headlines_scored": result.headlines_scored,
                        "feature_rows_loaded": result.feature_rows_loaded,
                        "ingestion_error": result.ingestion_error,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort the batch
                errors.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}"})

    summary = {
        "attempted": len(tickers),
        "succeeded": len(results),
        "failed": len(errors),
        "total_headlines_ingested": sum(r["headlines_ingested"] for r in results),
        "total_headlines_scored": sum(r["headlines_scored"] for r in results),
        "total_feature_rows_loaded": sum(r["feature_rows_loaded"] for r in results),
        "errors": errors,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
