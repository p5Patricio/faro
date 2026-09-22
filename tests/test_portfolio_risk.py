from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from brain.portfolio_risk import PortfolioRiskPolicy, apply_portfolio_risk_policy


def _returns_frame(n: int = 60, seed: int = 0) -> pd.DataFrame:
    """AAA/BBB share a common driver (strongly correlated); CCC/DDD are
    independent noise (near-zero correlation with everything)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    base = rng.normal(0, 0.01, n)
    return pd.DataFrame(
        {
            "AAA": base,
            "BBB": base + rng.normal(0, 0.002, n),
            "CCC": rng.normal(0, 0.01, n),
            "DDD": rng.normal(0, 0.01, n),
        },
        index=dates,
    )


def _row(ticker: str, action: str, position_size: float, confidence: float = 0.80) -> dict:
    return {
        "ticker": ticker,
        "action": action,
        "confidence": confidence,
        "position_size": position_size,
        "metadata": {
            "risk": {
                "policy": {},
                "blocked_reasons": [],
                "position_size": position_size,
                "pre_risk_action": action,
            }
        },
    }


def test_uncorrelated_tickers_pass_through_unchanged():
    predictions = pd.DataFrame([_row("CCC", "BUY", 0.05), _row("DDD", "SELL", 0.05)])
    returns = _returns_frame()

    adjusted = apply_portfolio_risk_policy(predictions, returns, PortfolioRiskPolicy())

    assert adjusted.set_index("ticker")["position_size"].to_dict() == {"CCC": 0.05, "DDD": 0.05}
    for _, row in adjusted.iterrows():
        portfolio_risk = row["metadata"]["portfolio_risk"]
        assert portfolio_risk["cluster"] is None
        assert portfolio_risk["scaled"] is False
        assert portfolio_risk["pre_adjustment_position_size"] == portfolio_risk["post_adjustment_position_size"]
        # brain.risk's own block must still agree with the (unchanged) size.
        assert row["metadata"]["risk"]["position_size"] == row["position_size"]


def test_correlated_pair_scaled_down_to_respect_cluster_cap():
    predictions = pd.DataFrame(
        [
            _row("AAA", "BUY", 0.10),
            _row("BBB", "BUY", 0.10),
            _row("CCC", "SELL", 0.05),
        ]
    )
    returns = _returns_frame()
    policy = PortfolioRiskPolicy(correlation_threshold=0.70, max_correlated_cluster_exposure=0.15)

    adjusted = apply_portfolio_risk_policy(predictions, returns, policy)
    sizes = adjusted.set_index("ticker")["position_size"].to_dict()

    # AAA/BBB are correlated above threshold and their combined 0.20 exceeds
    # the 0.15 cluster cap, so both get scaled by the same 0.75 factor.
    assert sizes["AAA"] == pytest.approx(0.075)
    assert sizes["BBB"] == pytest.approx(0.075)
    assert sizes["AAA"] + sizes["BBB"] == pytest.approx(0.15)
    # CCC is not correlated with the AAA/BBB cluster and stays untouched.
    assert sizes["CCC"] == 0.05

    for ticker in ("AAA", "BBB"):
        portfolio_risk = adjusted.set_index("ticker").loc[ticker, "metadata"]["portfolio_risk"]
        assert portfolio_risk["cluster"] == ["AAA", "BBB"]
        assert portfolio_risk["scaled"] is True
        assert portfolio_risk["pre_adjustment_position_size"] == pytest.approx(0.10)
        assert portfolio_risk["post_adjustment_position_size"] == pytest.approx(0.075)
        assert portfolio_risk["policy"]["max_correlated_cluster_exposure"] == 0.15


def test_hold_rows_are_never_touched():
    predictions = pd.DataFrame(
        [
            _row("AAA", "BUY", 0.10),
            _row("BBB", "BUY", 0.10),
            {**_row("CCC", "HOLD", 0.0), "metadata": {"risk": {"blocked_reasons": ["confidence_below_trade_threshold"], "position_size": 0.0}}},
        ]
    )
    returns = _returns_frame()
    policy = PortfolioRiskPolicy(correlation_threshold=0.70, max_correlated_cluster_exposure=0.10)

    adjusted = apply_portfolio_risk_policy(predictions, returns, policy)
    hold_row = adjusted.set_index("ticker").loc["CCC"]

    assert hold_row["action"] == "HOLD"
    assert hold_row["position_size"] == 0.0
    assert "portfolio_risk" not in hold_row["metadata"]


def test_empty_predictions_do_not_crash():
    predictions = pd.DataFrame(columns=["ticker", "action", "position_size", "metadata"])
    returns = _returns_frame()

    adjusted = apply_portfolio_risk_policy(predictions, returns, PortfolioRiskPolicy())

    assert adjusted.empty


def test_single_ticker_predictions_do_not_crash():
    predictions = pd.DataFrame([_row("AAA", "BUY", 0.10)])
    returns = _returns_frame()

    adjusted = apply_portfolio_risk_policy(predictions, returns, PortfolioRiskPolicy())

    assert adjusted.loc[0, "position_size"] == 0.10
    assert adjusted.loc[0, "metadata"]["portfolio_risk"]["cluster"] is None


def test_metadata_annotation_present_and_correct_on_adjusted_rows():
    predictions = pd.DataFrame([_row("AAA", "BUY", 0.10), _row("BBB", "BUY", 0.10)])
    returns = _returns_frame()
    policy = PortfolioRiskPolicy(correlation_threshold=0.70, max_correlated_cluster_exposure=0.12)

    adjusted = apply_portfolio_risk_policy(predictions, returns, policy)
    row = adjusted.set_index("ticker").loc["AAA"]
    portfolio_risk = row["metadata"]["portfolio_risk"]

    assert set(portfolio_risk) == {
        "policy",
        "pre_adjustment_position_size",
        "post_adjustment_position_size",
        "cluster",
        "scaled",
    }
    assert portfolio_risk["policy"] == {
        "correlation_threshold": 0.70,
        "max_correlated_cluster_exposure": 0.12,
        "min_returns_observations": 20,
    }
    assert portfolio_risk["pre_adjustment_position_size"] == pytest.approx(0.10)
    assert portfolio_risk["post_adjustment_position_size"] < portfolio_risk["pre_adjustment_position_size"]
    assert row["metadata"]["risk"]["position_size"] == pytest.approx(portfolio_risk["post_adjustment_position_size"])
