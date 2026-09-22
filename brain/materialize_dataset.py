from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

import psycopg

from brain.features import build_features, feature_columns_for_set
from brain.labeling import fixed_horizon_labels, triple_barrier_labels
from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository


@dataclass(frozen=True)
class MaterializationConfig:
    ticker: str
    feature_set: str = "technical_v1"
    label_method: str = "triple_barrier"
    horizon: int = 5
    buy_threshold: float = 0.015
    sell_threshold: float = -0.015
    profit_take: float = 0.03
    stop_loss: float = 0.015
    limit: int | None = None
    batch_size: int = 500


@dataclass(frozen=True)
class MaterializationResult:
    ticker: str
    asset_id: str
    price_rows: int
    feature_rows_loaded: int
    label_rows_loaded: int
    feature_set: str
    label_method: str
    horizon: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize ML features and labels from local Postgres prices")
    parser.add_argument("--ticker", required=True, help="Asset ticker stored locally, e.g. AAPL")
    parser.add_argument("--feature-set", default="technical_v1")
    parser.add_argument("--label-method", choices=["fixed_horizon", "triple_barrier"], default="triple_barrier")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--buy-threshold", type=float, default=0.015)
    parser.add_argument("--sell-threshold", type=float, default=-0.015)
    parser.add_argument("--profit-take", type=float, default=0.03)
    parser.add_argument("--stop-loss", type=float, default=0.015)
    parser.add_argument("--limit", type=int, help="Optional max number of price rows")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def build_labels(config: MaterializationConfig, prices):
    if config.label_method == "fixed_horizon":
        return fixed_horizon_labels(
            prices,
            horizon=config.horizon,
            buy_threshold=config.buy_threshold,
            sell_threshold=config.sell_threshold,
        )

    return triple_barrier_labels(
        prices,
        horizon=config.horizon,
        profit_take=config.profit_take,
        stop_loss=config.stop_loss,
    )


def materialize_asset_dataset(
    repository: LocalPostgresRepository,
    config: MaterializationConfig,
) -> MaterializationResult:
    asset_id = repository.get_asset_id(config.ticker)
    prices = repository.get_prices(asset_id, limit=config.limit)

    features = build_features(prices)
    labels = build_labels(config, prices)
    feature_columns = feature_columns_for_set(config.feature_set)

    features_loaded = repository.upsert_features(
        asset_id=asset_id,
        features=features,
        feature_columns=feature_columns,
        feature_set=config.feature_set,
        batch_size=config.batch_size,
    )
    labels_loaded = repository.upsert_labels(
        asset_id=asset_id,
        labels=labels,
        label_method=config.label_method,
        horizon=config.horizon,
        batch_size=config.batch_size,
    )

    return MaterializationResult(
        ticker=config.ticker.upper(),
        asset_id=asset_id,
        price_rows=len(prices),
        feature_rows_loaded=features_loaded,
        label_rows_loaded=labels_loaded,
        feature_set=config.feature_set,
        label_method=config.label_method,
        horizon=config.horizon,
    )


def main() -> None:
    args = parse_args()
    with psycopg.connect(LocalPostgresConfig.from_env().dsn, autocommit=True) as connection:
        repository = LocalPostgresRepository(connection=connection)
        result = materialize_asset_dataset(
            repository,
            MaterializationConfig(
                ticker=args.ticker,
                feature_set=args.feature_set,
                label_method=args.label_method,
                horizon=args.horizon,
                buy_threshold=args.buy_threshold,
                sell_threshold=args.sell_threshold,
                profit_take=args.profit_take,
                stop_loss=args.stop_loss,
                limit=args.limit,
                batch_size=args.batch_size,
            ),
        )

    print(
        json.dumps(
            asdict(result),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
