"""`brain/materialize_sentiment.py`.

Mirrors `tests/test_materialize_technical_alpha.py`'s layering, adapted for
`sentiment_v1`'s two extra I/O steps (ingest from Finnhub, score via
FinBERT) that neither sibling materializer has:

- the pure `build_sentiment_overlay` function is tested directly, including
  the C1 no-look-ahead guarantee (a headline published after a spine row's
  own date must never affect that row);
- the I/O wrapper `materialize_asset_sentiment` is tested against FAKE
  `LocalPostgresRepository`/`NewsRepository`/`FinnhubNewsProvider`
  stand-ins, so this file needs neither a live Postgres nor a real Finnhub
  API key/network call to pass -- only `test_db_round_trip` (real Postgres,
  rolled back, skipped when unreachable) touches a real database, mirroring
  every other `test_db_round_trip*` test in this suite;
- every injected `scorer` here is a small deterministic fake -- this file
  never imports `transformers`/`torch` either.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from brain.features import SENTIMENT_OVERLAY_COLUMNS, build_features, feature_columns_for_set
from brain.materialize_sentiment import (
    OVERLAY_COLUMNS,
    SentimentMaterializationConfig,
    build_sentiment_overlay,
    materialize_asset_sentiment,
)
from brain.sentiment_factors import FACTOR_KEYS
from collector.news_repository import NewsRepository
from collector.providers.finnhub_news_provider import FinnhubConfigError, NewsHeadline


def _price_history(start: str, periods: int) -> pd.DataFrame:
    """Same deterministic synthetic OHLCV shape as
    `tests/test_materialize_technical_alpha.py::_price_history`."""
    timestamps = pd.date_range(start, periods=periods, freq="D", tz="UTC")
    wave = np.sin(np.arange(periods) / 3) * 2.5
    trend = np.arange(periods) * 0.03
    close = 100 + wave + trend
    open_ = close + np.cos(np.arange(periods)) * 0.2
    high = np.maximum(open_, close) + 1.0
    low = np.minimum(open_, close) - 1.0
    volume = 1_000_000 + (np.arange(periods) % 9) * 10_000
    return pd.DataFrame(
        {"timestamp": timestamps, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


def _headline(ticker: str, published_at: str, score: float | None = None) -> NewsHeadline:
    return NewsHeadline(
        ticker=ticker,
        source="finnhub",
        headline=f"{ticker} headline on {published_at}",
        published_at=datetime.fromisoformat(published_at).replace(tzinfo=timezone.utc),
    )


class FakeRepository:
    """Duck-typed stand-in for `LocalPostgresRepository`: only the three
    methods `materialize_asset_sentiment` actually calls."""

    def __init__(self, asset_id: str = "asset-1", asset_class: str = "stock", prices: pd.DataFrame | None = None):
        self.asset_id = asset_id
        self.asset_class = asset_class
        self.prices = prices if prices is not None else pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        self.last_upsert: dict | None = None

    def get_asset(self, ticker: str) -> dict:
        return {"id": self.asset_id, "ticker": ticker.upper(), "asset_class": self.asset_class}

    def get_prices(self, asset_id: str, limit: int | None = None) -> pd.DataFrame:
        assert asset_id == self.asset_id
        return self.prices

    def upsert_features(self, *, asset_id, features, feature_columns, feature_set, batch_size=500):
        clean = features.dropna(subset=feature_columns)
        self.last_upsert = {
            "asset_id": asset_id,
            "feature_set": feature_set,
            "feature_columns": feature_columns,
            "rows": clean,
        }
        return len(clean)


class FakeProvider:
    """Duck-typed stand-in for `FinnhubNewsProvider`."""

    def __init__(self, result=None, raise_config_error: bool = False):
        self.result = result if result is not None else {"ok": True, "headlines": []}
        self.raise_config_error = raise_config_error
        self.calls: list[tuple] = []

    def fetch_company_news(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        if self.raise_config_error:
            raise FinnhubConfigError("no key configured")
        return self.result


def _fake_scorer(texts: list[str]) -> list[dict]:
    return [{"label": "Positive", "score": 0.6} for _ in texts]


# ---------------------------------------------------------------------------
# build_sentiment_overlay: pure function, shape + no-look-ahead
# ---------------------------------------------------------------------------


def test_overlay_columns_are_exactly_spine_plus_overlay_columns():
    prices = _price_history("2026-01-01", 40)
    spine = build_features(prices)
    overlay = build_sentiment_overlay(spine, pd.DataFrame(columns=["published_at", "sentiment_score"]))

    assert set(spine.columns).issubset(set(overlay.columns))
    for key in OVERLAY_COLUMNS:
        assert key in overlay.columns
    assert set(OVERLAY_COLUMNS[:-1]) == set(FACTOR_KEYS) == set(SENTIMENT_OVERLAY_COLUMNS)


def test_overlay_row_count_matches_spine_row_count():
    prices = _price_history("2026-01-01", 40)
    spine = build_features(prices)
    overlay = build_sentiment_overlay(spine, pd.DataFrame(columns=["published_at", "sentiment_score"]))
    assert len(overlay) == len(spine)


def test_overlay_with_no_headlines_is_all_nan_sentiment_columns():
    prices = _price_history("2026-01-01", 10)
    spine = build_features(prices)
    overlay = build_sentiment_overlay(spine, pd.DataFrame(columns=["published_at", "sentiment_score"]))
    assert overlay["sentiment_score_7d"].isna().all()
    assert (overlay["sentiment_headline_count_7d"] == 0).all()


def test_overlay_picks_up_a_same_day_headline():
    prices = _price_history("2026-01-01", 10)
    spine = build_features(prices)
    target_date = spine["timestamp"].iloc[5]
    headlines = pd.DataFrame(
        [{"published_at": target_date, "sentiment_score": 0.8}]
    )
    overlay = build_sentiment_overlay(spine, headlines)
    assert overlay.loc[5, "sentiment_score_7d"] == pytest.approx(0.8)
    assert overlay.loc[5, "sentiment_headline_count_7d"] == 1
    # Rows before the headline's date are unaffected.
    assert overlay.loc[0, "sentiment_headline_count_7d"] == 0


def test_headline_published_after_a_row_never_affects_that_rows_value():
    """C1 at the materialization layer: build the overlay ONCE with the full
    headlines frame (including a headline dated after row 3), and compare
    row 3 against an independent overlay built with that future headline
    removed entirely. They must match exactly."""
    prices = _price_history("2026-01-01", 15)
    spine = build_features(prices)

    early_date = spine["timestamp"].iloc[2]
    future_date = spine["timestamp"].iloc[10]

    headlines_with_future = pd.DataFrame(
        [
            {"published_at": early_date, "sentiment_score": 0.5},
            {"published_at": future_date, "sentiment_score": -1.0},
        ]
    )
    headlines_without_future = pd.DataFrame([{"published_at": early_date, "sentiment_score": 0.5}])

    overlay_with_future = build_sentiment_overlay(spine, headlines_with_future)
    overlay_without_future = build_sentiment_overlay(spine, headlines_without_future)

    row = 3
    pd.testing.assert_series_equal(
        overlay_with_future.loc[row, list(OVERLAY_COLUMNS)],
        overlay_without_future.loc[row, list(OVERLAY_COLUMNS)],
        check_names=False,
    )


def test_missing_timestamp_column_raises_value_error():
    with pytest.raises(ValueError, match="timestamp"):
        build_sentiment_overlay(pd.DataFrame({"close": [1, 2, 3]}), pd.DataFrame(columns=["published_at", "sentiment_score"]))


# ---------------------------------------------------------------------------
# materialize_asset_sentiment: I/O wrapper against fakes
# ---------------------------------------------------------------------------


def test_ingestion_skipped_when_provider_has_no_config_recorded_as_no_error():
    repository = FakeRepository(prices=_price_history("2026-01-01", 10))
    news_repository = _InMemoryNewsRepository()
    provider = FakeProvider(raise_config_error=True)

    result = materialize_asset_sentiment(
        repository,
        news_repository,
        SentimentMaterializationConfig(ticker="acme"),
        provider=provider,
        scorer=_fake_scorer,
    )

    assert result.headlines_ingested == 0
    assert result.ingestion_error is None


def test_ingestion_failure_reason_is_recorded_but_never_raises():
    repository = FakeRepository(prices=_price_history("2026-01-01", 10))
    news_repository = _InMemoryNewsRepository()
    provider = FakeProvider(result={"ok": False, "reason": "finnhub_rate_limited", "detail": "..."})

    result = materialize_asset_sentiment(
        repository,
        news_repository,
        SentimentMaterializationConfig(ticker="acme"),
        provider=provider,
        scorer=_fake_scorer,
    )

    assert result.headlines_ingested == 0
    assert result.ingestion_error == "finnhub_rate_limited"
    assert result.feature_rows_loaded == 0  # no headlines at all -> all-NaN overlay -> nothing survives dropna


def test_ingestion_upserts_headlines_returned_by_provider():
    repository = FakeRepository(prices=_price_history("2026-01-01", 60))
    news_repository = _InMemoryNewsRepository()
    provider = FakeProvider(
        result={
            "ok": True,
            "headlines": [_headline("ACME", "2026-01-30"), _headline("ACME", "2026-02-01")],
        }
    )

    result = materialize_asset_sentiment(
        repository,
        news_repository,
        SentimentMaterializationConfig(ticker="acme"),
        provider=provider,
        scorer=_fake_scorer,
    )

    assert result.headlines_ingested == 2
    assert result.headline_rows == 2


def test_pending_headlines_are_scored_via_injected_scorer_and_persisted():
    repository = FakeRepository(prices=_price_history("2026-01-01", 30))
    news_repository = _InMemoryNewsRepository()
    news_repository.seed(repository.asset_id, [_headline("ACME", "2026-01-15")])

    result = materialize_asset_sentiment(
        repository,
        news_repository,
        SentimentMaterializationConfig(ticker="acme"),
        provider=FakeProvider(),  # ok:True, empty headlines -> nothing new ingested
        scorer=_fake_scorer,
    )

    assert result.headlines_scored == 1
    stored = news_repository.get_news_headlines(repository.asset_id)
    assert stored.iloc[0]["sentiment_score"] == pytest.approx(0.6)
    assert stored.iloc[0]["sentiment_label"] == "positive"


def test_already_scored_headlines_are_never_rescored():
    repository = FakeRepository(prices=_price_history("2026-01-01", 30))
    news_repository = _InMemoryNewsRepository()
    news_repository.seed(repository.asset_id, [_headline("ACME", "2026-01-15")])
    news_repository.score_all(repository.asset_id, score=0.2, label="positive")

    def _boom(_texts):
        raise AssertionError("scorer must not be called when nothing is pending")

    result = materialize_asset_sentiment(
        repository,
        news_repository,
        SentimentMaterializationConfig(ticker="acme"),
        provider=FakeProvider(),
        scorer=_boom,
    )

    assert result.headlines_scored == 0


def test_feature_columns_written_match_registered_sentiment_v1_set():
    repository = FakeRepository(prices=_price_history("2026-01-01", 60))
    news_repository = _InMemoryNewsRepository()
    news_repository.seed(repository.asset_id, [_headline("ACME", "2026-02-10")])

    materialize_asset_sentiment(
        repository,
        news_repository,
        SentimentMaterializationConfig(ticker="acme"),
        provider=FakeProvider(),
        scorer=_fake_scorer,
    )

    assert repository.last_upsert["feature_columns"] == feature_columns_for_set("sentiment_v1")
    assert repository.last_upsert["feature_set"] == "sentiment_v1"


def test_no_headlines_ever_yields_zero_feature_rows_without_error():
    repository = FakeRepository(prices=_price_history("2026-01-01", 60))
    news_repository = _InMemoryNewsRepository()

    result = materialize_asset_sentiment(
        repository,
        news_repository,
        SentimentMaterializationConfig(ticker="acme"),
        provider=FakeProvider(),
        scorer=_fake_scorer,
    )

    assert result.feature_rows_loaded == 0


def test_crypto_asset_is_not_skipped_no_stock_only_restriction():
    repository = FakeRepository(asset_class="crypto", prices=_price_history("2026-01-01", 60))
    news_repository = _InMemoryNewsRepository()
    news_repository.seed(repository.asset_id, [_headline("BTC-USD", "2026-02-10")])

    result = materialize_asset_sentiment(
        repository,
        news_repository,
        SentimentMaterializationConfig(ticker="btc-usd"),
        provider=FakeProvider(),
        scorer=_fake_scorer,
    )

    assert result.asset_class == "crypto"
    assert result.headlines_scored == 1


class _InMemoryNewsRepository:
    """A minimal in-memory double satisfying the same surface as
    `collector.news_repository.NewsRepository` -- used instead of a real
    Postgres connection so every test above except `test_db_round_trip`
    needs no database."""

    def __init__(self):
        self._rows: list[dict] = []
        self._next_id = 1

    def seed(self, asset_id: str, headlines: list[NewsHeadline]) -> None:
        self.upsert_news_headlines(asset_id, headlines)

    def score_all(self, asset_id: str, *, score: float, label: str) -> None:
        for row in self._rows:
            if row["asset_id"] == asset_id:
                row["sentiment_score"] = score
                row["sentiment_label"] = label

    def upsert_news_headlines(self, asset_id, headlines, batch_size=500):
        count = 0
        for headline in headlines:
            key = (asset_id, headline.source, headline.published_at.isoformat(), headline.headline)
            existing = next(
                (
                    row
                    for row in self._rows
                    if (row["asset_id"], row["source"], row["published_at"], row["headline"]) == key
                ),
                None,
            )
            if existing is not None:
                existing["summary"] = headline.summary
                existing["url"] = headline.url
            else:
                self._rows.append(
                    {
                        "id": self._next_id,
                        "asset_id": asset_id,
                        "source": headline.source,
                        "headline": headline.headline,
                        "published_at": headline.published_at.isoformat(),
                        "summary": headline.summary,
                        "url": headline.url,
                        "sentiment_score": None,
                        "sentiment_label": None,
                    }
                )
                self._next_id += 1
            count += 1
        return count

    def get_news_headlines(self, asset_id):
        columns = ["id", "source", "headline", "published_at", "summary", "url", "sentiment_score", "sentiment_label"]
        rows = [row for row in self._rows if row["asset_id"] == asset_id]
        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(rows, columns=columns)

    def get_unscored_headline_ids(self, asset_id):
        rows = [row for row in self._rows if row["asset_id"] == asset_id and row["sentiment_score"] is None]
        if not rows:
            return pd.DataFrame(columns=["id", "headline"])
        return pd.DataFrame([{"id": row["id"], "headline": row["headline"]} for row in rows])

    def update_sentiment_scores(self, scored):
        by_id = {row["id"]: row for row in self._rows}
        count = 0
        for item in scored:
            row = by_id.get(item["id"])
            if row is not None:
                row["sentiment_score"] = item["sentiment_score"]
                row["sentiment_label"] = item["sentiment_label"]
                count += 1
        return count


# ---------------------------------------------------------------------------
# DB round trip (real Postgres, rolled back) -- skipped when unreachable,
# mirroring every other test_db_round_trip* test in this suite.
# ---------------------------------------------------------------------------


def test_db_round_trip(repository, db_connection):
    asset_id = repository.get_or_create_asset("acme-sent", asset_class="stock")
    prices = _price_history("2025-11-01", 90)
    repository.upsert_prices(asset_id, prices)

    news_repository = NewsRepository(connection=db_connection)
    spine_dates = build_features(prices)["timestamp"]
    # Published well past technical_v2's longest warm-up window (sma_50_ratio
    # needs 50 rows), so the rows the headline's trailing window touches
    # still have every OTHER feature column populated too -- otherwise
    # upsert_features' dropna(subset=feature_columns) would drop them for an
    # unrelated reason (spine warm-up, not sentiment) and this assertion
    # would flake.
    published_at = spine_dates.iloc[70]
    news_repository.upsert_news_headlines(
        asset_id,
        [
            NewsHeadline(
                ticker="ACME-SENT",
                source="finnhub",
                headline="Acme Sent Co reports strong quarter",
                published_at=published_at.to_pydatetime(),
            )
        ],
    )

    result = materialize_asset_sentiment(
        repository,
        news_repository,
        SentimentMaterializationConfig(ticker="acme-sent"),
        provider=FakeProvider(),  # skip real Finnhub network call
        scorer=_fake_scorer,
    )

    assert result.headlines_scored == 1
    assert result.feature_rows_loaded > 0

    stored = repository.get_features(asset_id, "sentiment_v1")
    assert not stored.empty
    for _, row in stored.iterrows():
        assert -1.0 <= row["features"]["sentiment_score_7d"] <= 1.0
