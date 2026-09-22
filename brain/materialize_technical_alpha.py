"""Materialize the `technical_alpha_v1` feature set: the `technical_v2`
spine plus the 19 Alpha158-inspired factors from
`brain/technical_factors_v2.py`, written under
`feature_set='technical_alpha_v1'`.

A NEW module, not an extension of `brain/materialize_dataset.py`, mirroring
`brain/materialize_fundamentals.py`'s own ADR-5 reasoning (see that module's
docstring for the full argument -- ADR-5's separation-of-concerns rationale
applies unchanged here: `materialize_asset_dataset` writes features *and*
labels for every asset on the daily path that feeds promoted `technical_v2`
models, and that function's current output must stay byte-identical).

Simpler than `fundamental_v1`, though: `technical_alpha_v1`'s two column
groups -- the `technical_v2` spine and the 19 alpha factors -- are BOTH pure
functions of the exact same chronological per-ticker OHLCV DataFrame. There
is no second, irregularly-timed data source (like SEC filings) that needs an
as-of join, so `build_technical_alpha_overlay` below does a plain
column-wise merge, never a timestamp-keyed `merge_asof`.

Row alignment, proven by construction rather than merely assumed:
`build_technical_alpha_overlay` calls `compute_technical_alpha_factors` on
`build_features`'s OWN return value, not on the raw `prices` argument a
second time. `build_features` internally normalizes `prices` via
`prepare_price_frame` (sorted ascending by timestamp, deduplicated by
timestamp keeping the last row, numeric-coerced, `RangeIndex`-reset) before
computing a single derived column -- the open/high/low/close/volume values
`compute_technical_alpha_factors` reads are therefore the exact SAME
already-normalized values, at the exact SAME row positions, that
`build_features` itself used for its own spine columns. Two independent
calls to `prepare_price_frame(prices)` would also be row-identical (it is a
deterministic pure function of `prices`), but computing the alpha factors
directly off the spine avoids relying on that equivalence at all: there is
only one normalization, so a `pd.concat(..., axis=1)` of the spine and the
alpha factors is a safe, order-preserving positional merge, not a hopeful
one.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

import pandas as pd
import psycopg

from brain.features import build_features, feature_columns_for_set
from brain.technical_factors_v2 import FACTOR_KEYS, compute_technical_alpha_factors
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository

OVERLAY_COLUMNS: tuple[str, ...] = FACTOR_KEYS


def build_technical_alpha_overlay(prices: pd.DataFrame) -> pd.DataFrame:
    """Pure function: chronological per-ticker OHLCV `prices` -> the
    `technical_v2` spine joined with the 19 `technical_alpha_v1` factor
    columns (see module docstring for why this is a safe positional
    `pd.concat`, not a timestamp-keyed join).

    Returns a DataFrame with `timestamp`, every `technical_v2` column, and
    every `FACTOR_KEYS` column, aligned row-for-row. Warm-up rows (not
    enough history for the longest rolling window in either group) carry
    NaN in the affected columns, exactly like `build_features` and
    `compute_technical_alpha_factors` already do on their own -- never an
    exception. `upsert_features`'s existing `dropna(subset=feature_columns)`
    drops any row still NaN in an overlay column, which is expected warm-up
    behavior, not a defect.
    """
    spine = build_features(prices)
    alpha_factors = compute_technical_alpha_factors(spine)
    return pd.concat([spine, alpha_factors], axis=1)


@dataclass(frozen=True)
class TechnicalAlphaMaterializationConfig:
    ticker: str
    feature_set: str = "technical_alpha_v1"
    limit: int | None = None
    batch_size: int = 500


@dataclass(frozen=True)
class TechnicalAlphaMaterializationResult:
    ticker: str
    asset_id: str
    asset_class: str
    price_rows: int
    feature_rows_loaded: int


def materialize_asset_technical_alpha(
    repository: LocalPostgresRepository,
    config: TechnicalAlphaMaterializationConfig,
) -> TechnicalAlphaMaterializationResult:
    """I/O wrapper around `build_technical_alpha_overlay`. Unlike
    `fundamental_v1`, `technical_alpha_v1` has no stock-only restriction --
    both its column groups are pure functions of OHLCV prices, which every
    tracked asset class (stock or crypto) has -- so there is no
    `skipped_assets`/asset_class branch here."""
    asset = repository.get_asset(config.ticker)
    asset_id = asset["id"]
    asset_class = (asset.get("asset_class") or "").strip().lower()
    normalized_ticker = config.ticker.upper()

    prices = repository.get_prices(asset_id, limit=config.limit)
    overlay = build_technical_alpha_overlay(prices)

    feature_columns = feature_columns_for_set(config.feature_set)
    feature_rows_loaded = repository.upsert_features(
        asset_id=asset_id,
        features=overlay,
        feature_columns=feature_columns,
        feature_set=config.feature_set,
        batch_size=config.batch_size,
    )

    return TechnicalAlphaMaterializationResult(
        ticker=normalized_ticker,
        asset_id=asset_id,
        asset_class=asset_class,
        price_rows=len(prices),
        feature_rows_loaded=feature_rows_loaded,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize the technical_alpha_v1 overlay from local Postgres OHLCV prices"
    )
    parser.add_argument("--ticker", required=True, help="Asset ticker stored locally, e.g. AAPL")
    parser.add_argument("--feature-set", default="technical_alpha_v1")
    parser.add_argument("--limit", type=int, help="Optional max number of price rows")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        result = materialize_asset_technical_alpha(
            repository,
            TechnicalAlphaMaterializationConfig(
                ticker=args.ticker,
                feature_set=args.feature_set,
                limit=args.limit,
                batch_size=args.batch_size,
            ),
        )

    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
