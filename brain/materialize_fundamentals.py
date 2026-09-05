"""Materialize the `fundamental_v1` feature set: the `technical_v2` spine plus
the three point-in-time factors from `brain/fundamental_factors.py`, written
under `feature_set='fundamental_v1'`.

A NEW module, not an extension of `brain/materialize_dataset.py` (design.md
ADR-5): `materialize_asset_dataset` writes features *and* labels for every
asset on the daily path that feeds promoted `technical_v2` models. Branching
it on feature set would put a stock-only import on the crypto path and touch
a function whose current output must stay byte-identical (C2). This module
still *calls* `build_features` -- the spine math is reused, never duplicated,
so a `fundamental_v1` row's 25 technical columns are byte-identical to the
`technical_v2` row at the same timestamp.

C1 discipline (the point of this file): every `fundamental_v1` row's
timestamp is derived from a contributing SEC `filed_date` plus a lag of at
least one trading day -- NEVER from `period_end`. `build_fundamental_overlay`
is the one place that performs that translation; `materialize_asset_fundamentals`
is the thin I/O wrapper around it, mirroring `materialize_asset_dataset`'s
pure-function/I/O-caller split.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
import psycopg

from brain.features import build_features, feature_columns_for_set
from brain.fundamental_factors import FACTOR_KEYS, compute_factors_as_of
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository

OVERLAY_COLUMNS: tuple[str, ...] = (*FACTOR_KEYS, "max_filed_date")


def build_fundamental_overlay(
    spine: pd.DataFrame,
    facts: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    lag_trading_days: int = 1,
) -> pd.DataFrame:
    """Pure function: `technical_v2` spine + SEC facts + prices -> the spine
    joined with the three `fundamental_v1` factor columns plus `max_filed_date`
    (provenance only, never a feature column).

    Algorithm (design.md §7 / ADR-5b -- events + as-of join, not
    per-trading-day):

    1. `spine["timestamp"]` -- already sorted by `build_features` -- IS the
       trading calendar. No `exchange_calendars` dependency: the asset's own
       price index is by definition the days it traded.
    2. **Event dates** = every distinct `facts["filed_date"]`. For each `f`:
       `i = spine_ts.searchsorted(f, side="left")` (first trading day >= f),
       `effective = spine_ts[i + lag_trading_days]`. A filing past the end of
       the price history (`i + lag_trading_days` out of range) is not yet
       usable and is skipped -- never an error.
       `effective > f` STRICTLY, always: if `f` is itself a trading day, `i`
       lands exactly on it and `+1` moves past it; if `f` is a weekend or
       holiday, `i` already lands on the next trading day and `+1` moves past
       THAT. This is what makes C1's strict `max(filed_date) < timestamp`
       hold rather than only `<=`.
    3. `compute_factors_as_of(facts, prices, as_of_date=f)` -- the cutoff is
       the filing date itself; the price date for Altman's MVE is that same
       `f` (see `brain/fundamental_factors.py::_price_close_on`, exact-date,
       never interpolated).
    4. The per-event rows are indexed by `effective` (de-duplicated -- a
       later event's row wins if two events happen to land on the same
       effective trading day), then joined onto the FULL spine calendar via
       `pd.merge_asof(..., direction="backward")`: every spine day gets the
       values from the LAST event at or before it, verbatim -- including a
       genuinely-NaN factor value at that exact event (e.g. a filing whose
       own data cannot resolve one factor). This is deliberately NOT
       `reindex().ffill()`: plain `ffill()` cannot distinguish "no event yet"
       (a real NaN gap that should be filled from the prior event) from "an
       event happened but this one factor is NaN" (a real value that must
       stay NaN, not be silently overwritten by a STALE earlier value from a
       now-superseded period) -- `ffill()` would incorrectly paper over the
       latter with the former. `merge_asof` carries the exact matched row,
       NaN and all, so a step still looks step-shaped between events
       (correct output, not a bug: design.md's ADR-5b explicitly rejects
       recomputing per trading day as ~1500x more computation for the same
       answer on every day no filing landed) without ever resurrecting a
       superseded value to mask a fresh factor's own NaN.
    5. Left-joined back onto `spine` by `timestamp`. Days before the first
       usable filing carry NaN overlay values -- `upsert_features`'s existing
       `dropna(subset=feature_columns)` drops them, which is expected
       warm-up behavior, not a defect.

    A restatement (a later `filed_date` for an already-reported period) is
    just another event: its `compute_factors_as_of` call naturally picks up
    the greater `filed_date` value once its OWN cutoff is reached, and every
    row before that event's `effective` timestamp was already written by an
    earlier event and is never touched by this function again -- this is
    what makes a re-run of this function C1-safe under a restatement.
    """
    if "timestamp" not in spine.columns:
        raise ValueError("spine DataFrame missing required column: timestamp")

    spine_sorted = spine.sort_values("timestamp").reset_index(drop=True)
    spine_ts = spine_sorted["timestamp"]

    empty_overlay = pd.DataFrame(
        {
            "timestamp": spine_ts.to_numpy(),
            **{column: np.nan for column in FACTOR_KEYS},
            "max_filed_date": None,
        }
    )

    if facts is None or facts.empty or spine_ts.empty:
        return spine_sorted.merge(empty_overlay, on="timestamp", how="left", validate="one_to_one")

    event_dates = sorted(pd.to_datetime(pd.Series(facts["filed_date"]).dropna().unique(), utc=True))

    event_rows: list[dict] = []
    for event in event_dates:
        insertion_index = int(spine_ts.searchsorted(event, side="left"))
        effective_index = insertion_index + lag_trading_days
        if effective_index >= len(spine_ts):
            continue  # the filing is not yet usable within this price history
        effective_timestamp = spine_ts.iloc[effective_index]
        factors = compute_factors_as_of(facts, prices, as_of_date=event)
        event_rows.append({"timestamp": effective_timestamp, **factors})

    if not event_rows:
        return spine_sorted.merge(empty_overlay, on="timestamp", how="left", validate="one_to_one")

    events_frame = (
        pd.DataFrame(event_rows, columns=["timestamp", *OVERLAY_COLUMNS])
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )
    target_frame = pd.DataFrame({"timestamp": spine_ts.to_numpy()})
    # `direction="backward"` = the last event AT OR BEFORE this spine day,
    # carrying its row verbatim (NaN included) -- NOT a column-wise ffill,
    # which would let a fresh event's own NaN be silently replaced by an
    # earlier, now-superseded event's non-NaN value.
    overlay = pd.merge_asof(target_frame, events_frame, on="timestamp", direction="backward")

    return spine_sorted.merge(overlay, on="timestamp", how="left", validate="one_to_one")


@dataclass(frozen=True)
class FundamentalMaterializationConfig:
    ticker: str
    feature_set: str = "fundamental_v1"
    lag_trading_days: int = 1
    limit: int | None = None
    batch_size: int = 500


@dataclass(frozen=True)
class FundamentalMaterializationResult:
    ticker: str
    asset_id: str
    asset_class: str
    price_rows: int
    fact_rows: int
    event_dates: int
    first_factor_timestamp: str | None
    feature_rows_loaded: int
    skipped_assets: list[str]


def materialize_asset_fundamentals(
    repository: LocalPostgresRepository,
    config: FundamentalMaterializationConfig,
) -> FundamentalMaterializationResult:
    """I/O wrapper around `build_fundamental_overlay`. Stock-only (spec
    "Stock-Only Scope"): any `assets.asset_class` other than `"stock"`
    (crypto, or anything future) writes zero rows and is reported in
    `skipped_assets` -- never an error, never a partial write.
    """
    asset = repository.get_asset(config.ticker)
    asset_id = asset["id"]
    asset_class = (asset.get("asset_class") or "").strip().lower()
    normalized_ticker = config.ticker.upper()

    if asset_class != "stock":
        return FundamentalMaterializationResult(
            ticker=normalized_ticker,
            asset_id=asset_id,
            asset_class=asset_class,
            price_rows=0,
            fact_rows=0,
            event_dates=0,
            first_factor_timestamp=None,
            feature_rows_loaded=0,
            skipped_assets=[normalized_ticker],
        )

    prices = repository.get_prices(asset_id, limit=config.limit)
    spine = build_features(prices)
    facts = repository.get_fundamental_facts(asset_id)

    overlay = build_fundamental_overlay(
        spine, facts, prices, lag_trading_days=config.lag_trading_days
    )

    feature_columns = feature_columns_for_set(config.feature_set)
    feature_rows_loaded = repository.upsert_features(
        asset_id=asset_id,
        features=overlay,
        feature_columns=feature_columns,
        feature_set=config.feature_set,
        batch_size=config.batch_size,
    )

    factor_rows = overlay.dropna(subset=list(FACTOR_KEYS))
    first_factor_timestamp = (
        pd.Timestamp(factor_rows["timestamp"].min()).isoformat() if not factor_rows.empty else None
    )

    return FundamentalMaterializationResult(
        ticker=normalized_ticker,
        asset_id=asset_id,
        asset_class=asset_class,
        price_rows=len(prices),
        fact_rows=len(facts),
        event_dates=int(facts["filed_date"].nunique()) if not facts.empty else 0,
        first_factor_timestamp=first_factor_timestamp,
        feature_rows_loaded=feature_rows_loaded,
        skipped_assets=[],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize the fundamental_v1 overlay from local Postgres SEC facts + prices"
    )
    parser.add_argument("--ticker", required=True, help="Asset ticker stored locally, e.g. AAPL")
    parser.add_argument("--feature-set", default="fundamental_v1")
    parser.add_argument("--lag-trading-days", type=int, default=1)
    parser.add_argument("--limit", type=int, help="Optional max number of price rows")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        result = materialize_asset_fundamentals(
            repository,
            FundamentalMaterializationConfig(
                ticker=args.ticker,
                feature_set=args.feature_set,
                lag_trading_days=args.lag_trading_days,
                limit=args.limit,
                batch_size=args.batch_size,
            ),
        )

    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
