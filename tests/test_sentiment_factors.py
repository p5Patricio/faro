"""`brain/sentiment_factors.py`: point-in-time news-sentiment factor
computation and FinBERT scoring.

Two concerns, mirroring `tests/test_fundamental_lookahead.py`'s layering for
`fundamental_factors.py`:

- **Laziness** (`score_headlines`): every test here injects a fake `scorer`
  and never triggers `_default_finbert_scorer`. `transformers`/`torch` are
  NOT installed in this environment (confirmed by
  `test_module_import_never_requires_transformers_or_torch` below), so any
  accidental eager/top-level import of either package would fail this
  entire test file at COLLECTION time, before a single test body ran --
  the strongest possible proof that the import really is lazy.
- **Point-in-time discipline** (`compute_sentiment_factors_as_of`): a
  headline published AFTER the cutoff must never affect the factor value AT
  that cutoff (C1, mirroring `fundamental_factors.py`'s `filed_date <=
  cutoff` rule, keyed on `published_at` here instead).
"""

from __future__ import annotations

import importlib.util
import sys

import numpy as np
import pandas as pd
import pytest

from brain.sentiment_factors import (
    FACTOR_KEYS,
    SENTIMENT_HALF_LIFE_DAYS,
    SENTIMENT_WINDOW_DAYS,
    compute_sentiment_factors_as_of,
    label_for_score,
    score_headlines,
)


def _headlines(rows: list[dict]) -> pd.DataFrame:
    """Build a headlines frame with the columns
    `compute_sentiment_factors_as_of` reads: `published_at`
    (`YYYY-MM-DD` strings are fine -- `_to_date` normalizes them) and
    `sentiment_score`."""
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Laziness: transformers/torch are never imported for an injected scorer,
# and never at module import time either way.
# ---------------------------------------------------------------------------


def test_module_import_never_requires_transformers_or_torch():
    """Sanity precondition for every other laziness assertion in this file:
    this dev/CI environment genuinely does not have transformers/torch
    installed, so `import brain.sentiment_factors` succeeding at all (it
    already did, above, to collect this file) is itself proof the module
    never imports them at the top level."""
    assert importlib.util.find_spec("transformers") is None
    assert importlib.util.find_spec("torch") is None
    assert "transformers" not in sys.modules
    assert "torch" not in sys.modules


def test_score_headlines_empty_list_returns_empty_without_calling_scorer():
    def _boom(_texts):
        raise AssertionError("scorer must not be called for an empty headlines list")

    assert score_headlines([], scorer=_boom) == []


def test_score_headlines_uses_injected_scorer_never_touches_transformers():
    calls: list[list[str]] = []

    def fake_scorer(texts: list[str]) -> list[dict]:
        calls.append(list(texts))
        return [
            {"label": "Positive", "score": 0.91},
            {"label": "Negative", "score": 0.80},
            {"label": "Neutral", "score": 0.60},
        ]

    scores = score_headlines(
        ["Company beats earnings", "Company misses guidance", "Company holds investor day"],
        scorer=fake_scorer,
    )

    assert scores == pytest.approx([0.91, -0.80, 0.0])
    assert calls == [["Company beats earnings", "Company misses guidance", "Company holds investor day"]]
    # Still true after a real call through the injected path.
    assert "transformers" not in sys.modules
    assert "torch" not in sys.modules


def test_score_headlines_label_matching_is_case_insensitive():
    def fake_scorer(texts: list[str]) -> list[dict]:
        return [{"label": "POSITIVE", "score": 0.5} for _ in texts]

    assert score_headlines(["x"], scorer=fake_scorer) == pytest.approx([0.5])


def test_score_headlines_without_scorer_lazily_attempts_real_finbert():
    """The production (no-injected-scorer) path DOES try to build the real
    FinBERT pipeline, lazily, on this call -- proven here by the fact that
    it fails with an import error (transformers is not installed in this
    environment) rather than succeeding or failing for any other reason,
    and that this failure only happens now, at call time, not back when
    `brain.sentiment_factors` was imported at the top of this file."""
    if importlib.util.find_spec("transformers") is not None:
        pytest.skip("transformers is installed in this environment; lazy-failure path not exercisable")

    with pytest.raises(ModuleNotFoundError):
        score_headlines(["some headline"])


# ---------------------------------------------------------------------------
# label_for_score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.5, "positive"),
        (-0.5, "negative"),
        (0.0, "neutral"),
        (0.04, "neutral"),
        (-0.04, "neutral"),
        (np.nan, "neutral"),
    ],
)
def test_label_for_score(score, expected):
    assert label_for_score(score) == expected


# ---------------------------------------------------------------------------
# compute_sentiment_factors_as_of: dead ends
# ---------------------------------------------------------------------------


def test_none_or_empty_headlines_frame_returns_nan_and_zero_count():
    for frame in (None, _headlines([])):
        result = compute_sentiment_factors_as_of(frame, "2026-01-15")
        assert np.isnan(result["sentiment_score_7d"])
        assert result["sentiment_headline_count_7d"] == 0
        assert result["max_published_at"] is None


def test_headlines_entirely_outside_window_return_nan_and_zero_count():
    headlines = _headlines(
        [{"published_at": "2025-01-01", "sentiment_score": 0.9}]
    )
    result = compute_sentiment_factors_as_of(headlines, "2026-01-15")
    assert np.isnan(result["sentiment_score_7d"])
    assert result["sentiment_headline_count_7d"] == 0
    assert result["max_published_at"] is None


def test_headlines_in_window_but_all_unscored_return_nan_with_zero_count_but_real_max_published_at():
    """An unscored headline (stored by ingestion, not yet scored) must still
    surface via `max_published_at` (provenance) even though it contributes
    nothing to the score/count -- see the function's own docstring."""
    headlines = _headlines(
        [{"published_at": "2026-01-14", "sentiment_score": np.nan}]
    )
    result = compute_sentiment_factors_as_of(headlines, "2026-01-15")
    assert np.isnan(result["sentiment_score_7d"])
    assert result["sentiment_headline_count_7d"] == 0
    assert result["max_published_at"] is not None


# ---------------------------------------------------------------------------
# C1 point-in-time discipline: a headline published AFTER the cutoff must
# never affect the factor value AT that cutoff.
# ---------------------------------------------------------------------------


def test_headline_published_after_cutoff_never_affects_factor_at_cutoff():
    cutoff = "2026-01-15"

    past_only = _headlines([{"published_at": "2026-01-14", "sentiment_score": 0.5}])
    past_and_future = _headlines(
        [
            {"published_at": "2026-01-14", "sentiment_score": 0.5},
            # Published the day AFTER cutoff, with a wildly different score --
            # if this leaked in, the result below would visibly change.
            {"published_at": "2026-01-16", "sentiment_score": -1.0},
        ]
    )

    result_past_only = compute_sentiment_factors_as_of(past_only, cutoff)
    result_with_future = compute_sentiment_factors_as_of(past_and_future, cutoff)

    assert result_past_only["sentiment_score_7d"] == pytest.approx(result_with_future["sentiment_score_7d"])
    assert result_past_only["sentiment_headline_count_7d"] == result_with_future["sentiment_headline_count_7d"]
    assert result_past_only["max_published_at"] == result_with_future["max_published_at"]


def test_headline_published_exactly_on_cutoff_is_included():
    """`published_at <= cutoff` -- same-day publication counts."""
    headlines = _headlines([{"published_at": "2026-01-15", "sentiment_score": 0.7}])
    result = compute_sentiment_factors_as_of(headlines, "2026-01-15")
    assert result["sentiment_score_7d"] == pytest.approx(0.7)
    assert result["sentiment_headline_count_7d"] == 1


def test_headline_older_than_window_is_excluded_one_day_past_the_boundary():
    cutoff = "2026-01-15"
    # SENTIMENT_WINDOW_DAYS + 1 days before cutoff -> outside the window.
    outside_date = (pd.Timestamp(cutoff) - pd.Timedelta(days=SENTIMENT_WINDOW_DAYS + 1)).date().isoformat()
    inside_date = (pd.Timestamp(cutoff) - pd.Timedelta(days=SENTIMENT_WINDOW_DAYS)).date().isoformat()

    outside_only = _headlines([{"published_at": outside_date, "sentiment_score": 1.0}])
    inside_only = _headlines([{"published_at": inside_date, "sentiment_score": 1.0}])

    result_outside = compute_sentiment_factors_as_of(outside_only, cutoff)
    assert np.isnan(result_outside["sentiment_score_7d"])
    assert result_outside["sentiment_headline_count_7d"] == 0

    result_inside = compute_sentiment_factors_as_of(inside_only, cutoff)
    # A single-headline weighted mean is just that headline's own score,
    # regardless of its weight (weight cancels in a one-element average) --
    # the point of this assertion is that it is a real number, not NaN.
    assert result_inside["sentiment_score_7d"] == pytest.approx(1.0)
    assert result_inside["sentiment_headline_count_7d"] == 1


# ---------------------------------------------------------------------------
# Exponential-decay weighting
# ---------------------------------------------------------------------------


def test_same_day_headline_has_full_weight_one():
    headlines = _headlines([{"published_at": "2026-01-15", "sentiment_score": 0.6}])
    result = compute_sentiment_factors_as_of(headlines, "2026-01-15")
    assert result["sentiment_score_7d"] == pytest.approx(0.6)


def test_headline_one_half_life_old_is_weighted_half_as_much_as_same_day():
    """Two headlines, opposite sign, one same-day (weight 1.0) and one
    exactly `SENTIMENT_HALF_LIFE_DAYS` old (weight 0.5) -- the weighted mean
    must land 1/3 of the way from the recent score to the old score
    (weights 1.0 and 0.5 normalize to 2/3 and 1/3)."""
    cutoff = "2026-01-15"
    half_life_date = (pd.Timestamp(cutoff) - pd.Timedelta(days=int(SENTIMENT_HALF_LIFE_DAYS))).date().isoformat()
    headlines = _headlines(
        [
            {"published_at": cutoff, "sentiment_score": 1.0},
            {"published_at": half_life_date, "sentiment_score": -1.0},
        ]
    )
    result = compute_sentiment_factors_as_of(headlines, cutoff)
    expected = (1.0 * 1.0 + 0.5 * -1.0) / (1.0 + 0.5)
    assert result["sentiment_score_7d"] == pytest.approx(expected)
    assert result["sentiment_headline_count_7d"] == 2


def test_more_recent_headline_dominates_a_stale_opposite_headline():
    cutoff = "2026-01-15"
    headlines = _headlines(
        [
            {"published_at": cutoff, "sentiment_score": 1.0},
            {"published_at": "2026-01-09", "sentiment_score": -1.0},  # near the edge of the window
        ]
    )
    result = compute_sentiment_factors_as_of(headlines, cutoff)
    assert result["sentiment_score_7d"] > 0


# ---------------------------------------------------------------------------
# Unscored headlines within the window are excluded from score/count.
# ---------------------------------------------------------------------------


def test_unscored_headline_in_window_does_not_affect_score_or_count():
    cutoff = "2026-01-15"
    only_scored = _headlines([{"published_at": cutoff, "sentiment_score": 0.4}])
    scored_plus_unscored = _headlines(
        [
            {"published_at": cutoff, "sentiment_score": 0.4},
            {"published_at": cutoff, "sentiment_score": np.nan},
        ]
    )

    result_scored = compute_sentiment_factors_as_of(only_scored, cutoff)
    result_mixed = compute_sentiment_factors_as_of(scored_plus_unscored, cutoff)

    assert result_scored["sentiment_score_7d"] == pytest.approx(result_mixed["sentiment_score_7d"])
    assert result_scored["sentiment_headline_count_7d"] == result_mixed["sentiment_headline_count_7d"] == 1


def test_factor_keys_matches_returned_dict_keys():
    cutoff = "2026-01-15"
    result = compute_sentiment_factors_as_of(_headlines([{"published_at": cutoff, "sentiment_score": 0.1}]), cutoff)
    assert set(FACTOR_KEYS).issubset(result.keys())
    assert "max_published_at" not in FACTOR_KEYS
