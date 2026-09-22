"""Materialize the `sentiment_v1` feature set: the `technical_alpha_v1`
spine plus the two point-in-time factors from `brain/sentiment_factors.py`,
written under `feature_set='sentiment_v1'`.

A NEW module, not an extension of `brain/materialize_dataset.py` or either
sibling materializer (design precedent: `brain/materialize_fundamentals.py`'s
ADR-5, `brain/materialize_technical_alpha.py`'s own docstring) -- same
separation-of-concerns rationale: this must never touch the byte-identical
output contract of `materialize_asset_dataset`/`build_features`.

Composed onto the bare `technical_v2` spine, the same base
`fundamental_v1` uses -- not `technical_alpha_v1` -- so this module only
ever calls `build_features` (never
`brain.materialize_technical_alpha.build_technical_alpha_overlay`), keeping
the two sibling materializers independent of one another, exactly like
`fundamental_v1` and `technical_alpha_v1` already are independent of each
other. Unlike `fundamental_v1`, there is no stock-only restriction here: a
news-driven signal is at least as plausible for crypto as it is for stocks,
so `sentiment_v1` is registered for every asset class -- see
`brain/features.py`'s `FEATURE_COLUMNS_BY_SET["sentiment_v1"]` registration
for the exact composition.

C1 discipline (the point of `brain/sentiment_factors.py`, reused here
unchanged): every `sentiment_v1` row's factor values are computed from
headlines filtered by `published_at <= cutoff`, cutoff being that row's own
trading-day `timestamp` -- never `ingested_at`. Unlike
`build_fundamental_overlay` (event dates carried forward via
`merge_asof(direction="backward")`), `build_sentiment_overlay` below
recomputes the exponentially-decayed window at EVERY spine row, because the
factor value keeps drifting day over day even with zero new headlines (see
`brain/sentiment_factors.py::compute_sentiment_factors_as_of`'s docstring).

I/O layering (`materialize_asset_sentiment`) additionally owns two steps
`fundamental_v1`/`technical_alpha_v1` never needed, because sentiment is the
first `brain/` feature set built on top of a NEW external provider
(`collector/providers/finnhub_news_provider.py`) rather than data another
job already ingested:

1. **Ingest** -- pull recent company news from Finnhub and upsert raw
   headlines via `collector/news_repository.py::NewsRepository`. Skipped,
   never raised, when `FINNHUB_API_KEY` is not configured (see
   `_ingest_new_headlines`) -- materialization must keep working on
   whatever headlines are already stored, exactly like a stock with zero
   SEC facts yields an all-NaN `fundamental_v1` overlay rather than an
   error.
2. **Score** -- run any not-yet-scored headline through
   `brain.sentiment_factors.score_headlines` (lazily loading FinBERT unless
   a `scorer` was injected) and persist the scores. Both steps are
   idempotent: re-running with the same headlines already stored/scored is
   a no-op.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import psycopg

from brain.features import build_features, feature_columns_for_set
from brain.sentiment_factors import (
    FACTOR_KEYS,
    compute_sentiment_factors_as_of,
    label_for_score,
    score_headlines,
)
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository
from collector.news_repository import NewsRepository
from collector.providers.finnhub_news_provider import FinnhubConfigError, FinnhubNewsProvider

OVERLAY_COLUMNS: tuple[str, ...] = (*FACTOR_KEYS, "max_published_at")

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_FEATURE_SET = "sentiment_v1"


def _to_date(value: Any) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def build_sentiment_overlay(spine: pd.DataFrame, headlines: pd.DataFrame) -> pd.DataFrame:
    """Pure function: a chronological feature `spine` (must carry
    `timestamp`) + a `headlines` frame (`published_at`, `sentiment_score`
    columns; see `collector/news_repository.py::NewsRepository.get_news_headlines`)
    -> the spine joined with the two `sentiment_v1` factor columns
    (`FACTOR_KEYS`) plus `max_published_at` (provenance only, never a
    feature column -- mirrors `max_filed_date` in
    `brain/materialize_fundamentals.py`).

    Calls `compute_sentiment_factors_as_of` once per DISTINCT spine
    calendar date, never once per `headlines` row -- `spine["timestamp"]`
    is already sorted/deduplicated upstream (`build_features`), so this
    keeps the cost to O(trading_days x headlines_in_window), not
    O(trading_days x all_headlines_ever). Every value is NaN/0 on missing
    input (see `compute_sentiment_factors_as_of`'s own dead-end
    documentation) -- this function never raises for that reason.
    """
    if "timestamp" not in spine.columns:
        raise ValueError("spine DataFrame missing required column: timestamp")

    spine_sorted = spine.sort_values("timestamp").reset_index(drop=True)
    spine_dates = spine_sorted["timestamp"].apply(_to_date)

    factor_rows = [compute_sentiment_factors_as_of(headlines, cutoff) for cutoff in spine_dates]
    factors_frame = pd.DataFrame(factor_rows, index=spine_sorted.index, columns=list(OVERLAY_COLUMNS))

    return pd.concat([spine_sorted, factors_frame], axis=1)


def _ingest_new_headlines(
    news_repository: NewsRepository,
    asset_id: str,
    ticker: str,
    *,
    provider: FinnhubNewsProvider | None,
    lookback_days: int,
) -> tuple[int, str | None]:
    """Fetch recent Finnhub company news and upsert it. Returns
    `(rows_upserted, error_reason)` -- `error_reason` is `None` on success
    OR when `provider` is `None`/unconfigured (a deliberate skip, not a
    failure); it is set to Finnhub's own `reason` string when the provider
    IS configured but the fetch itself failed (rate limited, network error,
    etc). Never raises: a missing `FINNHUB_API_KEY` or a failed fetch both
    leave `news_headlines` exactly as it was, so materialization can still
    proceed on whatever is already stored."""
    active_provider = provider if provider is not None else FinnhubNewsProvider()

    end = datetime.now(tz=UTC).date()
    start = end - timedelta(days=lookback_days)
    try:
        result = active_provider.fetch_company_news(ticker, start, end)
    except FinnhubConfigError:
        return 0, None

    if not result.get("ok"):
        return 0, str(result.get("reason"))

    headlines = result.get("headlines") or []
    upserted = news_repository.upsert_news_headlines(asset_id, headlines)
    return upserted, None


def _score_pending_headlines(
    news_repository: NewsRepository,
    asset_id: str,
    *,
    scorer: Callable[[list[str]], list[dict[str, Any]]] | None,
) -> int:
    """Score every stored headline for `asset_id` that has no
    `sentiment_score` yet, and persist the result. `scorer` is forwarded
    to `brain.sentiment_factors.score_headlines` unchanged -- `None` here
    means "use the real, lazily-loaded FinBERT pipeline" (production
    default); tests always inject a fake. Returns the number of headlines
    scored (0 when there was nothing pending)."""
    pending = news_repository.get_unscored_headline_ids(asset_id)
    if pending.empty:
        return 0

    scores = score_headlines(pending["headline"].tolist(), scorer=scorer)
    updates = [
        {
            "id": row_id,
            "sentiment_score": score,
            "sentiment_label": label_for_score(score),
        }
        for row_id, score in zip(pending["id"].tolist(), scores)
    ]
    return news_repository.update_sentiment_scores(updates)


@dataclass(frozen=True)
class SentimentMaterializationConfig:
    ticker: str
    feature_set: str = DEFAULT_FEATURE_SET
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    limit: int | None = None
    batch_size: int = 500


@dataclass(frozen=True)
class SentimentMaterializationResult:
    ticker: str
    asset_id: str
    asset_class: str
    price_rows: int
    headline_rows: int
    headlines_ingested: int
    headlines_scored: int
    feature_rows_loaded: int
    ingestion_error: str | None


def materialize_asset_sentiment(
    repository: LocalPostgresRepository,
    news_repository: NewsRepository,
    config: SentimentMaterializationConfig,
    *,
    provider: FinnhubNewsProvider | None = None,
    scorer: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> SentimentMaterializationResult:
    """I/O wrapper: ingest -> score -> build the overlay -> upsert features.

    No stock-only restriction (like `technical_alpha_v1`, unlike
    `fundamental_v1`): every asset class can have news coverage, so this
    never skips an asset by `asset_class`. An asset with zero headlines
    (ingestion skipped/failed AND nothing was ever stored before) simply
    produces an all-NaN overlay, which `upsert_features`' existing
    `dropna(subset=feature_columns)` drops -- zero feature rows loaded,
    never an error.
    """
    asset = repository.get_asset(config.ticker)
    asset_id = asset["id"]
    asset_class = (asset.get("asset_class") or "").strip().lower()
    normalized_ticker = config.ticker.upper()

    headlines_ingested, ingestion_error = _ingest_new_headlines(
        news_repository,
        asset_id,
        normalized_ticker,
        provider=provider,
        lookback_days=config.lookback_days,
    )
    headlines_scored = _score_pending_headlines(news_repository, asset_id, scorer=scorer)

    prices = repository.get_prices(asset_id, limit=config.limit)
    spine = build_features(prices)
    headlines = news_repository.get_news_headlines(asset_id)

    overlay = build_sentiment_overlay(spine, headlines)

    feature_columns = feature_columns_for_set(config.feature_set)
    feature_rows_loaded = repository.upsert_features(
        asset_id=asset_id,
        features=overlay,
        feature_columns=feature_columns,
        feature_set=config.feature_set,
        batch_size=config.batch_size,
    )

    return SentimentMaterializationResult(
        ticker=normalized_ticker,
        asset_id=asset_id,
        asset_class=asset_class,
        price_rows=len(prices),
        headline_rows=len(headlines),
        headlines_ingested=headlines_ingested,
        headlines_scored=headlines_scored,
        feature_rows_loaded=feature_rows_loaded,
        ingestion_error=ingestion_error,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize the sentiment_v1 overlay from Finnhub news + local Postgres"
    )
    parser.add_argument("--ticker", required=True, help="Asset ticker stored locally, e.g. AAPL")
    parser.add_argument("--feature-set", default=DEFAULT_FEATURE_SET)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--limit", type=int, help="Optional max number of price rows")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        news_repository = NewsRepository(connection=connection)
        result = materialize_asset_sentiment(
            repository,
            news_repository,
            SentimentMaterializationConfig(
                ticker=args.ticker,
                feature_set=args.feature_set,
                lookback_days=args.lookback_days,
                limit=args.limit,
                batch_size=args.batch_size,
            ),
        )

    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
