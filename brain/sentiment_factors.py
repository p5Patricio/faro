"""Point-in-time news-sentiment factor computation: scored headlines ->
the `sentiment_v1` factor pair, as-of a `published_at` cutoff.

Pure module -- no DB, no HTTP. Mirrors `brain/fundamental_factors.py`'s
discipline exactly, keyed on `published_at` (a news article's publish time)
instead of `filed_date` (an SEC filing's file time):

C1 discipline (the single most important rule in this module, same
principle as `fundamental_factors.py`'s "never `period_end`" rule):
`compute_sentiment_factors_as_of` filters every input row by
`published_at <= cutoff` -- **never** `ingested_at` (when this database
happened to learn about the headline). A headline published AFTER the
cutoff must never influence the factor value AT that cutoff, no matter how
early it was ingested; see `db/migrations/0011_news_sentiment.sql`'s header
comment for why `ingested_at` is not a safe substitute axis.

Non-raising is achieved BY CONSTRUCTION, not by a bare `except`: an
empty/absent `headlines` frame, an empty window, or an all-unscored window
resolves to `np.nan`/`0` (see `compute_sentiment_factors_as_of`'s docstring
for the exact dead ends), mirroring `fundamental_factors._select_as_of`'s
own dead-end return convention.

FinBERT (`yiyanghkust/finbert-tone` via `transformers`) is LAZY and
INJECTABLE, never a module-import-time cost:
- `transformers` is imported INSIDE `_default_finbert_scorer`, not at the
  top of this file -- importing `brain.sentiment_factors`, or calling
  `score_headlines([...], scorer=some_fake)`, never imports `transformers`
  or `torch`.
- `score_headlines` accepts an optional `scorer` callable; only when it is
  omitted does this module construct (and cache) the real HuggingFace
  pipeline, on that first real call. Every test in
  `tests/test_sentiment_factors.py` injects a fake scorer and never
  triggers `_default_finbert_scorer`, so the suite never downloads model
  weights or pays the `transformers`/`torch` import cost.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

FACTOR_KEYS: tuple[str, ...] = ("sentiment_score_7d", "sentiment_headline_count_7d")

# The one canonical trailing-window definition for sentiment_v1 -- mirrors
# fundamental_factors.py hardcoding its Piotroski/Altman coefficients rather
# than exposing them as call-time parameters. A different window is a
# different feature set (sentiment_v2), not a parameter of this one.
SENTIMENT_WINDOW_DAYS = 7
SENTIMENT_HALF_LIFE_DAYS = 3.0

FINBERT_MODEL_NAME = "yiyanghkust/finbert-tone"

# Lazily populated by `_default_finbert_scorer` on first real (non-injected)
# call -- never at import time. A plain dict, not `functools.lru_cache`, so
# tests can freely construct/import this module without ever touching it.
_PIPELINE_CACHE: dict[str, Any] = {}


def _to_date(value: Any) -> date:
    """Normalize a `published_at`/cutoff value to a plain `date`. Mirrors
    `fundamental_factors._to_date` exactly -- same four accepted shapes."""
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _default_finbert_scorer() -> Callable[[list[str]], list[dict[str, Any]]]:
    """Lazily construct (and cache) the real FinBERT-tone HuggingFace
    pipeline. `transformers` is imported HERE, inside this function body --
    deliberately never at this module's top level -- so importing
    `brain.sentiment_factors` never requires `transformers`/`torch` to be
    installed, let alone the ~400MB of FinBERT weights to be downloaded.
    Only a genuine production call to `score_headlines(...)` with no
    injected `scorer` reaches this function."""
    if "pipeline" not in _PIPELINE_CACHE:
        from transformers import pipeline  # local import: see module + function docstrings

        _PIPELINE_CACHE["pipeline"] = pipeline("text-classification", model=FINBERT_MODEL_NAME)
    return _PIPELINE_CACHE["pipeline"]


def score_headlines(
    headlines: list[str],
    scorer: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> list[float]:
    """Score each headline's sentiment as one float in `[-1, 1]`.

    Collapses FinBERT-tone's 3-class output (`"Positive"` / `"Negative"` /
    `"Neutral"`, each with a confidence `score`) into a single signed
    scalar: `+score` for Positive, `-score` for Negative, `0.0` for Neutral
    -- the standard way to turn a 3-class sentiment head into one factor
    input, matching this module's `[-1, 1]` factor scale.

    `scorer` is INJECTABLE: any callable matching a HuggingFace
    `text-classification` pipeline's call signature -- `texts -> [{"label":
    ..., "score": ...}, ...]`, one result per input text, in order -- works.
    Every test supplies a small deterministic fake here, so the test suite
    never imports `transformers`/`torch` or downloads FinBERT's weights (see
    module docstring). When `scorer` is omitted (the production default),
    the real FinBERT-tone pipeline is constructed lazily on THIS call via
    `_default_finbert_scorer` -- never at import time, never for an empty
    `headlines` list (see below).

    Returns `[]` for `[]` input without constructing any scorer at all, not
    even the real one -- an empty batch needs no model loaded.
    """
    if not headlines:
        return []

    active_scorer = scorer if scorer is not None else _default_finbert_scorer()
    raw_results = active_scorer(headlines)

    scores: list[float] = []
    for result in raw_results:
        label = str(result.get("label", "")).strip().lower()
        confidence = float(result.get("score", 0.0))
        if label == "positive":
            scores.append(confidence)
        elif label == "negative":
            scores.append(-confidence)
        else:
            scores.append(0.0)
    return scores


def label_for_score(score: float, *, neutral_epsilon: float = 0.05) -> str:
    """Map a collapsed `[-1, 1]` score back to a storable
    `"positive"`/`"negative"`/`"neutral"` label -- what
    `db/migrations/0011_news_sentiment.sql`'s `sentiment_label` column
    stores alongside `sentiment_score`. `NaN` (a score that could not be
    computed) maps to `"neutral"`, the same "unevaluable is not a signal"
    convention `fundamental_factors._binary` uses for `None`."""
    if pd.isna(score):
        return "neutral"
    if score > neutral_epsilon:
        return "positive"
    if score < -neutral_epsilon:
        return "negative"
    return "neutral"


def compute_sentiment_factors_as_of(headlines: pd.DataFrame, as_of_date: Any) -> dict[str, Any]:
    """Compute the `sentiment_v1` factor pair as-of a `published_at` cutoff
    `as_of_date`, from a `headlines` frame with `published_at` and
    `sentiment_score` columns (one row per stored headline; extra columns
    are ignored).

    Algorithm -- the point-in-time selection primitive for this module,
    mirroring `fundamental_factors._select_as_of`'s role:

    1. **As-of + window filter**: keep rows with
       `cutoff - SENTIMENT_WINDOW_DAYS <= published_at <= cutoff`. The
       as-of half (`<= cutoff`) is C1's non-negotiable rule; the trailing
       half (`>= cutoff - window`) is what makes this a MOVING window
       rather than an ever-growing all-time average.
    2. **Score validity filter**: within that window, drop any row whose
       `sentiment_score` is missing/NaN (a headline stored before scoring
       ran -- see `db/migrations/0011_news_sentiment.sql`'s header comment).
       `sentiment_headline_count_7d` counts only SCORED headlines in the
       window, so it never overstates how much signal actually backs the
       score.
    3. **Exponential-decay weighted mean**: each scored headline's weight is
       `0.5 ** (age_days / SENTIMENT_HALF_LIFE_DAYS)`, `age_days = cutoff -
       published_at.date()` -- a same-day headline gets weight 1.0, a
       headline `SENTIMENT_HALF_LIFE_DAYS` days old gets weight 0.5, and so
       on. `sentiment_score_7d` is the weight-normalized mean of
       `sentiment_score` over the window.

    Returns `{"sentiment_score_7d": np.nan, "sentiment_headline_count_7d":
    0, "max_published_at": None}` at any dead end: no headlines at all, an
    empty as-of+window filter result, or a window with headlines but none
    yet scored. `max_published_at` is the greatest `published_at` (as a
    plain `date`) among rows the window actually kept (scored or not) --
    provenance only, mirroring `compute_factors_as_of`'s `max_filed_date`;
    it is deliberately NOT one of `FACTOR_KEYS` and must never reach
    `features_daily.features`.

    Never raises: a malformed/empty frame, a fully-NaN score column, or a
    cutoff before any headline all resolve to the dead-end dict above, by
    construction, the same non-raising philosophy
    `fundamental_factors.py`'s module docstring describes.
    """
    cutoff = _to_date(as_of_date)
    dead_end = {"sentiment_score_7d": np.nan, "sentiment_headline_count_7d": 0, "max_published_at": None}

    if headlines is None or headlines.empty:
        return dead_end

    published = headlines["published_at"].apply(_to_date)
    window_start = cutoff - timedelta(days=SENTIMENT_WINDOW_DAYS)
    mask = (published <= cutoff) & (published >= window_start)
    if not mask.any():
        return dead_end

    windowed_published = published.loc[mask]
    max_published_at = windowed_published.max()

    scores = pd.to_numeric(headlines.loc[mask, "sentiment_score"], errors="coerce")
    valid = scores.notna()
    headline_count = int(valid.sum())
    if headline_count == 0:
        return {**dead_end, "max_published_at": max_published_at}

    scored_published = windowed_published.loc[valid]
    age_days = scored_published.apply(lambda published_date: (cutoff - published_date).days)
    weight = 0.5 ** (age_days / SENTIMENT_HALF_LIFE_DAYS)
    weight_sum = float(weight.sum())
    if weight_sum <= 0:
        return {
            "sentiment_score_7d": np.nan,
            "sentiment_headline_count_7d": headline_count,
            "max_published_at": max_published_at,
        }

    weighted_score = float((weight * scores.loc[valid]).sum() / weight_sum)
    return {
        "sentiment_score_7d": weighted_score,
        "sentiment_headline_count_7d": headline_count,
        "max_published_at": max_published_at,
    }
