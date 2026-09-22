"""Portfolio-level correlation risk cap.

This module sits *after* `brain.risk.apply_risk_policy`: it never changes
the `action` a signal already earned (BUY/SELL/HOLD) and never raises a
`position_size` `apply_risk_policy` already capped -- it only scales
correlated positions DOWN so their combined exposure stays under
`PortfolioRiskPolicy.max_correlated_cluster_exposure`. It deliberately does
not build a mean-variance optimizer: that would let portfolio math override
the model's own directional call, which is out of scope (see
`brain/portfolio_risk.py`'s caller in `brain/inference_job.py` for how this
batch is assembled once per inference run, across every ticker's
already-risk-policy-applied prediction).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd
from pypfopt import risk_models

from brain.risk import TRADE_ACTIONS


@dataclass(frozen=True)
class PortfolioRiskPolicy:
    correlation_threshold: float = 0.70
    max_correlated_cluster_exposure: float = 0.25
    # Ledoit-Wolf shrinkage is unstable on very short return histories; below
    # this many overlapping daily observations a ticker sits out clustering
    # entirely and keeps its single-signal `position_size` unchanged, rather
    # than have `apply_portfolio_risk_policy` from a near-singular estimate.
    min_returns_observations: int = 20


def apply_portfolio_risk_policy(
    predictions: pd.DataFrame,
    returns: pd.DataFrame,
    policy: PortfolioRiskPolicy | None = None,
) -> pd.DataFrame:
    """Cap combined exposure across correlated tickers.

    `predictions` is one row per ticker, already processed by
    `brain.risk.apply_risk_policy`: required columns are `ticker`, `action`
    (BUY/SELL/HOLD), `position_size` (0.0 for HOLD/blocked signals) and
    `metadata` (a dict, normally already carrying a `risk` key). `returns`
    is a wide tickers-x-dates historical-returns frame (one column per
    ticker, one row per date) used only to estimate correlation -- it is not
    required to cover every ticker in `predictions`.

    Only BUY/SELL rows with `position_size > 0` are eligible for scaling.
    Every other row (HOLD, blocked, zero-size) passes through unchanged.
    Eligible tickers are grouped into correlation clusters (pairwise
    correlation strictly above `policy.correlation_threshold`, via
    connected components); a cluster whose *pre-adjustment* combined
    `position_size` exceeds `policy.max_correlated_cluster_exposure` has
    every member scaled by the same factor
    `max_correlated_cluster_exposure / cluster_total_position_size` -- a
    proportional, explainable haircut, never a re-optimization. A ticker
    with no usable return history, or that lands in no over-limit cluster,
    keeps its original `position_size`.
    """
    policy = policy or PortfolioRiskPolicy()
    if predictions.empty:
        return predictions.copy()
    required = {"ticker", "action", "position_size", "metadata"}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"predictions missing columns: {sorted(missing)}")

    adjusted = predictions.copy()
    eligible_mask = adjusted["action"].isin(TRADE_ACTIONS) & (
        adjusted["position_size"].apply(_safe_float).fillna(0.0) > 0.0
    )
    eligible = adjusted[eligible_mask]

    clusters: list[list[str]] = []
    if len(eligible) >= 2:
        usable_returns = _usable_returns(returns, list(eligible["ticker"]), policy)
        if usable_returns is not None:
            correlation = _correlation_matrix(usable_returns)
            clusters = _correlated_clusters(correlation, policy.correlation_threshold)

    cluster_index_by_ticker: dict[str, int] = {}
    for index, cluster in enumerate(clusters):
        for ticker in cluster:
            cluster_index_by_ticker[ticker] = index

    scale_by_cluster_index: dict[int, float] = {}
    for index, cluster in enumerate(clusters):
        cluster_total = float(
            eligible.loc[eligible["ticker"].isin(cluster), "position_size"].apply(_safe_float).sum()
        )
        if cluster_total > policy.max_correlated_cluster_exposure and cluster_total > 0:
            scale_by_cluster_index[index] = policy.max_correlated_cluster_exposure / cluster_total
        else:
            scale_by_cluster_index[index] = 1.0

    rows = []
    for _, row in adjusted.iterrows():
        metadata = dict(row.get("metadata") or {})
        pre_size = _safe_float(row.get("position_size")) or 0.0
        action = str(row["action"])

        if action not in TRADE_ACTIONS or pre_size <= 0.0:
            updated = row.copy()
            updated["metadata"] = metadata
            rows.append(updated)
            continue

        ticker = row["ticker"]
        cluster_index = cluster_index_by_ticker.get(ticker)
        scale = scale_by_cluster_index.get(cluster_index, 1.0) if cluster_index is not None else 1.0
        post_size = round(pre_size * min(scale, 1.0), 6)

        metadata["portfolio_risk"] = {
            "policy": asdict(policy),
            "pre_adjustment_position_size": pre_size,
            "post_adjustment_position_size": post_size,
            "cluster": sorted(clusters[cluster_index]) if cluster_index is not None else None,
            "scaled": post_size < pre_size,
        }
        if isinstance(metadata.get("risk"), dict):
            # Keep brain.risk's own block internally consistent: it is the
            # field downstream consumers (e.g. brain.paper_trading) read as
            # "the" position size, so it must reflect the final, portfolio-
            # capped number rather than go stale next to `portfolio_risk`.
            metadata["risk"] = {**metadata["risk"], "position_size": post_size}

        updated = row.copy()
        updated["position_size"] = post_size
        updated["metadata"] = metadata
        rows.append(updated)

    return pd.DataFrame(rows).reset_index(drop=True)


def _usable_returns(
    returns: pd.DataFrame | None,
    tickers: list[str],
    policy: PortfolioRiskPolicy,
) -> pd.DataFrame | None:
    if returns is None or returns.empty:
        return None
    available = [ticker for ticker in tickers if ticker in returns.columns]
    if len(available) < 2:
        return None
    subset = returns[available].dropna(how="any")
    if len(subset) < policy.min_returns_observations:
        return None
    # Zero-variance columns make the correlation matrix undefined (division
    # by a zero std); drop them rather than let a flat/constant series
    # poison clustering for every other ticker.
    subset = subset.loc[:, subset.std(ddof=0) > 0]
    if subset.shape[1] < 2:
        return None
    return subset


def _correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    covariance = risk_models.CovarianceShrinkage(returns, returns_data=True).ledoit_wolf()
    return risk_models.cov_to_corr(covariance)


def _correlated_clusters(correlation: pd.DataFrame, threshold: float) -> list[list[str]]:
    """Connected components over the "pairwise correlation exceeds
    threshold" graph, via union-find. A component of size 1 (a ticker
    correlated with nothing above threshold) is not a cluster."""
    tickers = list(correlation.columns)
    parent = {ticker: ticker for ticker in tickers}

    def find(ticker: str) -> str:
        while parent[ticker] != ticker:
            parent[ticker] = parent[parent[ticker]]
            ticker = parent[ticker]
        return ticker

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    for i, ticker_a in enumerate(tickers):
        for ticker_b in tickers[i + 1 :]:
            if correlation.loc[ticker_a, ticker_b] > threshold:
                union(ticker_a, ticker_b)

    groups: dict[str, list[str]] = {}
    for ticker in tickers:
        groups.setdefault(find(ticker), []).append(ticker)

    return [sorted(group) for group in groups.values() if len(group) > 1]


def _safe_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
