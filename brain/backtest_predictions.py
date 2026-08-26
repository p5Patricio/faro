from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from brain.backtesting import BacktestConfig, run_prediction_backtest
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest evaluated model predictions")
    parser.add_argument("--ticker", help="Optional asset ticker stored locally")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--name", help="Backtest name. Defaults to model/ticker/version")
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--position-size", type=float, default=1.0)
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--no-short", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--persist", action="store_true", help="Store backtest summary and trades in the database")
    parser.add_argument("--out", help="Optional JSON report path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        asset_id = repository.get_asset_id(args.ticker) if args.ticker else None
        model_run = repository.get_model_run(args.model_name, args.model_version)
        feedback = repository.get_prediction_feedback(
            model_name=args.model_name,
            model_version=args.model_version,
            asset_id=asset_id,
            only_evaluated=True,
            limit=args.limit,
        )
        config = BacktestConfig(
            initial_capital=args.initial_capital,
            position_size=args.position_size,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
            allow_short=not args.no_short,
        )
        result = run_prediction_backtest(feedback, config)
        name = args.name or f"{args.model_name}:{args.model_version}:{args.ticker or 'all'}"

        backtest_id = None
        if args.persist:
            started_at = result.trades["timestamp"].min() if not result.trades.empty else None
            ended_at = result.trades["timestamp"].max() if not result.trades.empty else None
            backtest_id = repository.create_backtest(
                name=name,
                model_run_id=model_run["id"],
                asset_id=asset_id,
                metrics=result.metrics,
                params={
                    "initial_capital": args.initial_capital,
                    "position_size": args.position_size,
                    "fee_bps": args.fee_bps,
                    "slippage_bps": args.slippage_bps,
                    "allow_short": not args.no_short,
                    "limit": args.limit,
                },
                started_at=started_at,
                ended_at=ended_at,
            )
            repository.insert_backtest_trades(backtest_id, asset_id, result.trades)

    payload = {
        "backtest_id": backtest_id,
        "name": name,
        "model_run_id": model_run["id"],
        "metrics": result.metrics,
        "trades": result.trades.to_dict(orient="records"),
    }

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
