"""One-shot job: materialize `technical_alpha_v1` for every asset in the
tracked universe -- crypto and stocks alike. Unlike
`ops/materialize_fundamentals_batch.py`, there is no stock-only restriction
here: both `technical_alpha_v1` column groups (the `technical_v2` spine and
the 19 alpha factors) are pure functions of OHLCV prices, which every
tracked asset class has. Companion to
`brain/materialize_technical_alpha.py` (single-ticker only); mirrors
`ops/materialize_fundamentals_batch.py`'s structure and defaults to
`config/targets.core.json` (the full 103-asset universe: 2 crypto + 101
stocks), not the stock-only `config/targets.stocks.json`.

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

from brain.materialize_technical_alpha import (
    TechnicalAlphaMaterializationConfig,
    materialize_asset_technical_alpha,
)
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets-file", default="config/targets.core.json")
    parser.add_argument("--feature-set", default="technical_alpha_v1")
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
                result = materialize_asset_technical_alpha(
                    repository, TechnicalAlphaMaterializationConfig(ticker=ticker, feature_set=args.feature_set)
                )
                results.append(
                    {
                        "ticker": result.ticker,
                        "asset_class": result.asset_class,
                        "feature_rows_loaded": result.feature_rows_loaded,
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
