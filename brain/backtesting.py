from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from brain.features import FEATURE_COLUMNS
from brain.inference import PredictionPolicy, predict_actions
from brain.models import DEFAULT_MODEL_NAME, create_model


TRADE_ACTIONS = {"BUY", "SELL"}


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0
    position_size: float = 1.0
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    allow_short: bool = True
    # Bars per year used to annualize `_sharpe_like`. Defaults to ~252 (NYSE
    # trading days/year), correct for the stock universe every existing
    # caller trains on. A 24/7 market (e.g. crypto, one daily bar every
    # calendar day via BinanceProvider) trades ~365 bars/year, not 252 --
    # left at the stock default here since no caller yet threads asset_class
    # into which BacktestConfig gets built (feature_set has the same
    # single-config-per-job shape; see brain.features.
    # FEATURE_SET_OVERLAYS_BY_ASSET_CLASS). A caller that DOES know the
    # asset class can pass periods_per_year=365 explicitly today.
    periods_per_year: int = 252

    @property
    def round_trip_cost(self) -> float:
        return 2 * (self.fee_bps + self.slippage_bps) / 10_000


@dataclass(frozen=True)
class BacktestResult:
    metrics: dict
    trades: pd.DataFrame


@dataclass(frozen=True)
class WalkForwardBacktestResult:
    summary: dict
    folds: list[dict]
    predictions: pd.DataFrame
    model_backtest: BacktestResult
    baselines: dict[str, BacktestResult]


def run_prediction_backtest(feedback: pd.DataFrame, config: BacktestConfig | None = None) -> BacktestResult:
    """Backtest evaluated predictions using label outcome returns as trade outcomes."""
    config = config or BacktestConfig()
    if feedback.empty:
        return BacktestResult(metrics=_empty_metrics(config), trades=pd.DataFrame())

    required = {"timestamp", "predicted_action", "confidence", "outcome_return"}
    missing = required - set(feedback.columns)
    if missing:
        raise ValueError(f"feedback missing columns: {sorted(missing)}")

    evaluated = feedback.dropna(subset=["outcome_return"]).copy()
    evaluated["timestamp"] = pd.to_datetime(evaluated["timestamp"], utc=True)
    evaluated["confidence"] = pd.to_numeric(evaluated["confidence"], errors="coerce")
    evaluated["outcome_return"] = pd.to_numeric(evaluated["outcome_return"], errors="coerce")
    evaluated = evaluated.sort_values("timestamp")

    rows = []
    equity = config.initial_capital
    for _, row in evaluated.iterrows():
        action = str(row["predicted_action"])
        gross_return = _gross_return_for_action(action, row["outcome_return"], config)
        cost = config.round_trip_cost if action in TRADE_ACTIONS else 0.0
        net_return = (gross_return * config.position_size) - cost
        equity *= 1 + net_return
        rows.append(
            {
                "timestamp": row["timestamp"],
                "action": action,
                "confidence": row["confidence"],
                "gross_return": gross_return,
                "net_return": net_return,
                "cost": cost,
                "equity": equity,
                "metadata": {
                    "actual_label": row.get("actual_label"),
                    "model_name": row.get("model_name"),
                    "model_version": row.get("model_version"),
                },
            }
        )

    trades = pd.DataFrame(rows)
    return BacktestResult(metrics=_metrics_from_trades(trades, config), trades=trades)


def run_walk_forward_model_backtest(
    dataset: pd.DataFrame,
    n_splits: int = 5,
    test_size: int | None = None,
    embargo_rows: int = 0,
    trade_stride: int = 1,
    model_name: str = DEFAULT_MODEL_NAME,
    feature_columns: list[str] | None = None,
    prediction_policy: PredictionPolicy | None = None,
    config: BacktestConfig | None = None,
) -> WalkForwardBacktestResult:
    """Train on chronological folds and backtest only out-of-sample predictions."""
    config = config or BacktestConfig()
    prediction_policy = prediction_policy or PredictionPolicy()
    columns = feature_columns or FEATURE_COLUMNS
    _validate_walk_forward_dataset(dataset, columns)

    ordered = dataset.sort_values("timestamp").reset_index(drop=True)
    if len(ordered) < max(30, n_splits + 2):
        raise ValueError("Not enough rows for walk-forward backtest")
    if embargo_rows < 0:
        raise ValueError("embargo_rows must be non-negative")
    if trade_stride < 1:
        raise ValueError("trade_stride must be at least 1")

    splitter = TimeSeriesSplit(n_splits=n_splits, test_size=test_size, gap=embargo_rows)
    fold_summaries = []
    prediction_frames = []

    for fold, (train_idx, test_idx) in enumerate(splitter.split(ordered), start=1):
        train = ordered.iloc[train_idx]
        test = ordered.iloc[test_idx].copy()
        model = create_model(model_name)
        model.fit(train[columns], train["label"])

        predicted = predict_actions(
            model,
            test[["timestamp", *columns]],
            policy=prediction_policy,
            feature_columns=columns,
        )
        feedback = _prediction_feedback_frame(predicted, test)
        if trade_stride > 1:
            feedback = feedback.iloc[::trade_stride].reset_index(drop=True)
        feedback["fold"] = fold
        prediction_frames.append(feedback)

        fold_backtest = run_prediction_backtest(feedback, config)
        fold_summaries.append(
            {
                "fold": fold,
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
                "test_start": _timestamp_or_none(test["timestamp"].min()),
                "test_end": _timestamp_or_none(test["timestamp"].max()),
                "model_total_return": fold_backtest.metrics["total_return"],
                "model_max_drawdown": fold_backtest.metrics["max_drawdown"],
                "model_active_trade_count": fold_backtest.metrics["active_trade_count"],
                "model_win_rate": fold_backtest.metrics["win_rate"],
            }
        )

    predictions = pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
    model_backtest = run_prediction_backtest(predictions, config)
    baselines = {
        "no_trade": run_prediction_backtest(_baseline_feedback(predictions, "HOLD"), config),
        "always_buy": run_prediction_backtest(_baseline_feedback(predictions, "BUY"), config),
    }
    if config.allow_short:
        baselines["always_sell"] = run_prediction_backtest(_baseline_feedback(predictions, "SELL"), config)

    summary = {
        "rows": int(len(ordered)),
        "evaluated_rows": int(len(predictions)),
        "n_splits": int(n_splits),
        "test_size": test_size,
        "embargo_rows": int(embargo_rows),
        "trade_stride": int(trade_stride),
        "min_confidence": prediction_policy.min_confidence,
        "model_name": model_name,
        "features": columns,
        "model": model_backtest.metrics,
        "baselines": {name: result.metrics for name, result in baselines.items()},
    }
    return WalkForwardBacktestResult(
        summary=summary,
        folds=fold_summaries,
        predictions=predictions,
        model_backtest=model_backtest,
        baselines=baselines,
    )


def run_confidence_threshold_sweep(
    dataset: pd.DataFrame,
    thresholds: list[float],
    n_splits: int = 5,
    test_size: int | None = None,
    embargo_rows: int = 0,
    trade_stride: int = 1,
    model_name: str = DEFAULT_MODEL_NAME,
    feature_columns: list[str] | None = None,
    config: BacktestConfig | None = None,
) -> list[dict]:
    """Evaluate the same model setup across confidence thresholds."""
    rows = []
    for threshold in thresholds:
        result = run_walk_forward_model_backtest(
            dataset,
            n_splits=n_splits,
            test_size=test_size,
            embargo_rows=embargo_rows,
            trade_stride=trade_stride,
            model_name=model_name,
            feature_columns=feature_columns,
            prediction_policy=PredictionPolicy(min_confidence=threshold),
            config=config,
        )
        metrics = result.model_backtest.metrics
        rows.append(
            {
                "min_confidence": threshold,
                "total_return": metrics["total_return"],
                "final_equity": metrics["final_equity"],
                "max_drawdown": metrics["max_drawdown"],
                "profit_factor": metrics["profit_factor"],
                "active_trade_count": metrics["active_trade_count"],
                "exposure": metrics["exposure"],
                "win_rate": metrics["win_rate"],
            }
        )
    return sorted(rows, key=lambda row: row["total_return"], reverse=True)


def _gross_return_for_action(action: str, outcome_return: float, config: BacktestConfig) -> float:
    if action == "BUY":
        return float(outcome_return)
    if action == "SELL" and config.allow_short:
        return float(-outcome_return)
    return 0.0


def _prediction_feedback_frame(predictions: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    frame = predictions.rename(columns={"action": "predicted_action"}).copy()
    label_columns = ["timestamp", "label", "outcome_return"]
    merged = frame.merge(labels[label_columns], on="timestamp", how="left")
    merged = merged.rename(columns={"label": "actual_label"})
    merged["is_correct"] = merged["predicted_action"] == merged["actual_label"]
    return merged


def _baseline_feedback(predictions: pd.DataFrame, action: str) -> pd.DataFrame:
    if predictions.empty:
        return predictions.copy()
    baseline = predictions.copy()
    baseline["predicted_action"] = action
    baseline["confidence"] = 1.0
    baseline["is_correct"] = baseline["predicted_action"] == baseline["actual_label"]
    return baseline


def _validate_walk_forward_dataset(dataset: pd.DataFrame, feature_columns: list[str]) -> None:
    required = {"timestamp", "label", "outcome_return", *feature_columns}
    missing = required - set(dataset.columns)
    if missing:
        raise ValueError(f"dataset missing columns: {sorted(missing)}")
    if dataset["outcome_return"].isna().all():
        raise ValueError("dataset has no outcome_return values to backtest")


def _metrics_from_trades(trades: pd.DataFrame, config: BacktestConfig) -> dict:
    if trades.empty:
        return _empty_metrics(config)

    returns = trades["net_return"]
    equity = trades["equity"]
    peaks = equity.cummax()
    drawdowns = equity / peaks - 1
    gains = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()
    traded = trades[trades["action"].isin(TRADE_ACTIONS)]

    return {
        "initial_capital": config.initial_capital,
        "final_equity": float(equity.iloc[-1]),
        "total_return": float(equity.iloc[-1] / config.initial_capital - 1),
        "max_drawdown": float(drawdowns.min()),
        "trade_count": int(len(trades)),
        "active_trade_count": int(len(traded)),
        "exposure": float(len(traded) / len(trades)),
        "win_rate": _nullable_float((returns > 0).mean()),
        "average_net_return": _nullable_float(returns.mean()),
        "profit_factor": None if losses == 0 else float(gains / abs(losses)),
        "sharpe_like": _sharpe_like(returns, periods_per_year=config.periods_per_year),
        "fee_bps": config.fee_bps,
        "slippage_bps": config.slippage_bps,
        "position_size": config.position_size,
        "allow_short": config.allow_short,
    }


def _empty_metrics(config: BacktestConfig) -> dict:
    return {
        "initial_capital": config.initial_capital,
        "final_equity": config.initial_capital,
        "total_return": 0.0,
        "max_drawdown": 0.0,
        "trade_count": 0,
        "active_trade_count": 0,
        "exposure": 0.0,
        "win_rate": None,
        "average_net_return": None,
        "profit_factor": None,
        "sharpe_like": None,
        "fee_bps": config.fee_bps,
        "slippage_bps": config.slippage_bps,
        "position_size": config.position_size,
        "allow_short": config.allow_short,
    }


def _sharpe_like(returns: pd.Series, periods_per_year: int = 252) -> float | None:
    std = returns.std()
    if pd.isna(std) or std == 0:
        return None
    return float((returns.mean() / std) * np.sqrt(periods_per_year))


def _nullable_float(value) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _timestamp_or_none(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()
