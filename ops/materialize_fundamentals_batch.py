"""One-shot job: materialize `fundamental_v1` for every stock in the tracked
universe. Companion to `brain/materialize_fundamentals.py` (single-ticker
only) -- run after `collector.run_fundamental_ingestion` refreshes SEC facts,
so newly-filed data actually reaches `features_daily` before the weekly
retraining step reads it.

In-process, not subprocess-per-ticker (unlike ops/retrain_batched.py): this
does no model training, just a features join per ticker, so it is fast
enough (seconds per ticker) that isolation/resumability overhead is not
worth it. A single failing ticker is caught and reported; it never aborts
the batch.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

import psycopg

from brain.materialize_fundamentals import (
    FundamentalMaterializationConfig,
    materialize_asset_fundamentals,
)
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets-file", default="config/targets.stocks.json")
    parser.add_argument("--feature-set", default="fundamental_v1")
    parser.add_argument("--out", help="Optional JSON summary path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = json.loads((REPO_ROOT / args.targets_file).read_text(encoding="utf-8"))

    results = []
    errors = []
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        for ticker in tickers:
            try:
                result = materialize_asset_fundamentals(
                    repository, FundamentalMaterializationConfig(ticker=ticker, feature_set=args.feature_set)
                )
                results.append(
                    {
                        "ticker": result.ticker,
                        "feature_rows_loaded": result.feature_rows_loaded,
                        "skipped_assets": result.skipped_assets,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort the batch
                errors.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}"})

    summary = {
        "attempted": len(tickers),
        "succeeded": len(results),
        "failed": len(errors),
        "total_feature_rows_loaded": sum(r["feature_rows_loaded"] for r in results),
        "errors": errors,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
