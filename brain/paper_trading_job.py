from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from brain.paper_trading import PaperTradingConfig, run_paper_trading
from collector.local_repository import LocalPostgresRepository


def run_paper_trading_job(
    repository: LocalPostgresRepository,
    tickers: list[str] | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    limit: int = 250,
    config: PaperTradingConfig | None = None,
    persist_empty: bool = False,
    continue_on_error: bool = True,
) -> dict[str, Any]:
    started_at = datetime.now(tz=UTC)
    paper_config = config or PaperTradingConfig()
    assets = _selected_assets(repository, tickers)
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for asset in assets:
        ticker = str(asset["ticker"]).upper()
        asset_id = asset["id"]
        context = {"ticker": ticker, "asset_id": asset_id}
        try:
            predictions = repository.get_prediction_feedback(
                asset_id=asset_id,
                model_name=model_name,
                model_version=model_version,
                only_evaluated=False,
                limit=limit,
                ascending=True,
            )
            if predictions.empty and not persist_empty:
                skipped.append({**context, "reason": "no_predictions"})
                continue

            prices = repository.get_prices(asset_id, limit=max(limit * 3, limit), ascending=True)
            result = run_paper_trading(predictions, prices, paper_config)
            if result.timeline.empty and not persist_empty:
                skipped.append({**context, "reason": "empty_timeline"})
                continue

            model_run_id = _single_non_null_value(predictions, "model_run_id")
            resolved_model_name = model_name or _single_non_null_value(predictions, "model_name") or "model"
            resolved_model_version = model_version or _single_non_null_value(predictions, "model_version") or "latest"
            run_id = repository.create_paper_trading_run(
                name=f"{resolved_model_name}:{resolved_model_version}:{ticker}:paper",
                model_run_id=model_run_id,
                asset_id=asset_id,
                metrics=result.metrics,
                params={
                    "limit": limit,
                    "model_name": model_name,
                    "model_version": model_version,
                    "initial_capital": paper_config.initial_capital,
                    "default_position_size": paper_config.default_position_size,
                    "fee_bps": paper_config.fee_bps,
                    "slippage_bps": paper_config.slippage_bps,
                    "allow_short": paper_config.allow_short,
                    "persist_empty": persist_empty,
                },
                started_at=result.timeline["timestamp"].min() if not result.timeline.empty else None,
                ended_at=result.timeline["timestamp"].max() if not result.timeline.empty else None,
            )
            inserted_events = repository.insert_paper_trading_events(run_id, asset_id, result.timeline)
            results.append(
                {
                    **context,
                    "paper_trading_run_id": run_id,
                    "events_inserted": inserted_events,
                    "metrics": result.metrics,
                }
            )
        except Exception as error:
            errors.append({**context, "error": str(error)})
            if not continue_on_error:
                raise

    ended_at = datetime.now(tz=UTC)
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "attempted": len(assets),
        "succeeded": len(results),
        "skipped": skipped,
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


def _selected_assets(repository: LocalPostgresRepository, tickers: list[str] | None) -> list[dict[str, Any]]:
    assets = repository.get_assets()
    if not tickers:
        return assets
    selected = {ticker.strip().upper() for ticker in tickers if ticker.strip()}
    return [asset for asset in assets if str(asset.get("ticker", "")).upper() in selected]


def _single_non_null_value(frame: pd.DataFrame, column: str) -> str | None:
    if frame.empty or column not in frame.columns:
        return None
    values = [value for value in frame[column].dropna().unique().tolist() if value]
    return str(values[0]) if len(values) == 1 else None
