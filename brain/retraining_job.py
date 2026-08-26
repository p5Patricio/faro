from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain.artifacts import store_model_artifact
from brain.backtesting import BacktestConfig
from brain.candidate_matrix import load_candidate_datasets_from_supabase, run_candidate_matrix
from brain.features import feature_columns_for_set
from brain.inference_job import is_promoted_model_run, target_ticker_for_model_run
from brain.models import available_model_names
from brain.promotion import default_promotion_version, promote_candidate_from_report, select_candidate
from brain.risk import RiskPolicy
from brain.scoped_evaluation import SCOPES
from brain.selection import PromotionCriteria
from collector.local_repository import LocalPostgresRepository


@dataclass(frozen=True)
class RetrainingJobConfig:
    feature_set: str = "technical_v2"
    label_method: str = "triple_barrier"
    horizon: int = 5
    model_names: list[str] = field(default_factory=available_model_names)
    confidence_thresholds: list[float] = field(default_factory=lambda: [0.55, 0.60, 0.65, 0.70])
    scopes: list[str] = field(default_factory=lambda: ["local", "asset_class", "global"])
    splits: int = 5
    test_size: int | None = None
    embargo_rows: int | None = None
    trade_stride: int | None = None
    limit: int | None = None
    min_rows: int = 120
    initial_capital: float = 10_000.0
    position_size: float = 1.0
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    allow_short: bool = True
    min_total_return: float = 0.0
    min_profit_factor: float = 1.0
    max_drawdown_floor: float = -0.25
    min_active_trades: int = 20
    drawdown_penalty: float = 1.0
    generate_prediction: bool = True
    latest_feature_limit: int = 1
    max_position_size: float = 0.10
    min_confidence_to_trade: float = 0.60
    max_expected_risk: float = 0.05
    stop_loss: float = 0.02
    take_profit: float = 0.04
    upload_artifacts: bool = True
    model_dir: str = "models"
    continue_on_error: bool = True
    require_incumbent_improvement: bool = True
    min_objective_improvement: float = 0.0
    incumbent_lookup_limit: int = 100


def run_retraining_job(
    repository: LocalPostgresRepository,
    tickers: list[str] | None = None,
    config: RetrainingJobConfig | None = None,
) -> dict[str, Any]:
    job_config = config or RetrainingJobConfig()
    started_at = datetime.now(tz=UTC)
    feature_columns = feature_columns_for_set(job_config.feature_set)
    promotion_criteria = PromotionCriteria(
        min_total_return=job_config.min_total_return,
        min_profit_factor=job_config.min_profit_factor,
        max_drawdown_floor=job_config.max_drawdown_floor,
        min_active_trades=job_config.min_active_trades,
    )
    datasets, skipped_assets = load_candidate_datasets_from_supabase(
        repository,
        feature_set=job_config.feature_set,
        label_method=job_config.label_method,
        horizon=job_config.horizon,
        feature_columns=feature_columns,
        limit=job_config.limit,
        min_rows=job_config.min_rows,
    )
    selected_tickers = resolve_target_tickers(datasets, tickers)

    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for ticker in selected_tickers:
        context = {"ticker": ticker}
        try:
            report = build_candidate_report(
                datasets=datasets,
                ticker=ticker,
                config=job_config,
                feature_columns=feature_columns,
                promotion_criteria=promotion_criteria,
            )
            try:
                candidate = select_candidate(report)
            except ValueError as error:
                skipped.append(
                    {
                        **context,
                        "reason": "no_promotable_candidate",
                        "detail": str(error),
                        "ranking_count": len(report.get("ranking") or []),
                    }
                )
                continue

            incumbent = find_incumbent_model_run(
                repository,
                ticker=ticker,
                feature_set=job_config.feature_set,
                label_method=job_config.label_method,
                horizon=job_config.horizon,
                limit=job_config.incumbent_lookup_limit,
            )
            incumbent_comparison = compare_candidate_to_incumbent(
                candidate,
                incumbent,
                min_objective_improvement=job_config.min_objective_improvement,
            )
            if job_config.require_incumbent_improvement and incumbent_comparison["status"] == "fail":
                skipped.append(
                    {
                        **context,
                        "reason": "candidate_not_better_than_incumbent",
                        "detail": incumbent_comparison["reason"],
                        "candidate_id": candidate.get("candidate_id"),
                        "candidate_objective_score": incumbent_comparison.get("candidate_objective_score"),
                        "incumbent_model_run_id": incumbent_comparison.get("incumbent_model_run_id"),
                        "incumbent_objective_score": incumbent_comparison.get("incumbent_objective_score"),
                        "required_objective_improvement": job_config.min_objective_improvement,
                        "ranking_count": len(report.get("ranking") or []),
                    }
                )
                continue

            model_version = build_model_version(ticker)
            artifact_path = build_artifact_path(ticker, candidate, report, model_version, job_config.model_dir)
            promotion = promote_candidate_from_report(
                repository=repository,
                report=report,
                candidate=candidate,
                model_version=model_version,
                artifact_uri=artifact_path,
                limit=job_config.limit,
                min_rows=job_config.min_rows,
                persist=True,
                generate_prediction=job_config.generate_prediction,
                latest_feature_limit=job_config.latest_feature_limit,
                risk_policy=RiskPolicy(
                    max_position_size=job_config.max_position_size,
                    min_confidence_to_trade=job_config.min_confidence_to_trade,
                    max_expected_risk=job_config.max_expected_risk,
                    stop_loss=job_config.stop_loss,
                    take_profit=job_config.take_profit,
                    allow_short=job_config.allow_short,
                ),
            )

            stored_artifact_uri = promotion.artifact_uri
            if job_config.upload_artifacts and promotion.model_run_id:
                stored_artifact_uri = store_model_artifact(promotion.artifact_uri)
                repository.update_model_run_artifact_uri(promotion.model_run_id, stored_artifact_uri)

            results.append(
                {
                    **context,
                    "model_run_id": promotion.model_run_id,
                    "model_name": candidate.get("model_name"),
                    "model_version": model_version,
                    "candidate_id": candidate.get("candidate_id"),
                    "scope": candidate.get("scope"),
                    "min_confidence": candidate.get("min_confidence"),
                    "objective_score": candidate.get("objective_score"),
                    "local_artifact_uri": promotion.artifact_uri,
                    "artifact_uri": stored_artifact_uri,
                    "prediction_loaded": bool(promotion.prediction),
                    "ranking_count": len(report.get("ranking") or []),
                    "incumbent_comparison": incumbent_comparison,
                }
            )
        except Exception as error:
            errors.append({**context, "error": str(error)})
            if not job_config.continue_on_error:
                raise

    ended_at = datetime.now(tz=UTC)
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "attempted": len(selected_tickers),
        "succeeded": len(results),
        "skipped": skipped,
        "failed": len(errors),
        "results": results,
        "errors": errors,
        "skipped_assets": skipped_assets,
        "config": summarize_config(job_config),
    }


def build_candidate_report(
    datasets,
    ticker: str,
    config: RetrainingJobConfig,
    feature_columns: list[str],
    promotion_criteria: PromotionCriteria,
) -> dict[str, Any]:
    matrix = run_candidate_matrix(
        datasets,
        target_ticker=ticker,
        scopes=config.scopes,
        model_names=config.model_names,
        confidence_thresholds=config.confidence_thresholds,
        n_splits=config.splits,
        test_size=config.test_size,
        embargo_rows=config.embargo_rows if config.embargo_rows is not None else config.horizon,
        trade_stride=config.trade_stride if config.trade_stride is not None else config.horizon,
        feature_columns=feature_columns,
        backtest_config=BacktestConfig(
            initial_capital=config.initial_capital,
            position_size=config.position_size,
            fee_bps=config.fee_bps,
            slippage_bps=config.slippage_bps,
            allow_short=config.allow_short,
        ),
        promotion_criteria=promotion_criteria,
        drawdown_penalty=config.drawdown_penalty,
        include_details=False,
        continue_on_error=config.continue_on_error,
    )
    return {
        "ticker": ticker.upper(),
        "feature_set": config.feature_set,
        "label_method": config.label_method,
        "horizon": config.horizon,
        "models": config.model_names,
        "confidence_thresholds": config.confidence_thresholds,
        "scopes": config.scopes,
        "selection": {
            "drawdown_penalty": config.drawdown_penalty,
            "criteria": {
                "min_total_return": promotion_criteria.min_total_return,
                "min_profit_factor": promotion_criteria.min_profit_factor,
                "max_drawdown_floor": promotion_criteria.max_drawdown_floor,
                "min_active_trades": promotion_criteria.min_active_trades,
                "require_positive_edge_vs_no_trade": promotion_criteria.require_positive_edge_vs_no_trade,
            },
        },
        "available_dataset_count": len(datasets),
        **matrix,
    }


def resolve_target_tickers(datasets, tickers: list[str] | None) -> list[str]:
    available = {item.ticker.upper() for item in datasets}
    if not tickers:
        return sorted(available)
    requested = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
    return [ticker for ticker in requested if ticker in available]


def build_model_version(ticker: str) -> str:
    safe_ticker = ticker.upper().replace("-", "_").replace("/", "_")
    return f"auto_{safe_ticker}_{default_promotion_version()}"


def build_artifact_path(ticker: str, candidate: dict[str, Any], report: dict[str, Any], model_version: str, model_dir: str) -> str:
    safe_ticker = ticker.upper().replace("-", "_").replace("/", "_")
    return str(
        Path(model_dir)
        / f"{safe_ticker}_{candidate['model_name']}_{report['feature_set']}_{candidate['scope']}_{model_version}.joblib"
    )


def find_incumbent_model_run(
    repository: LocalPostgresRepository,
    *,
    ticker: str,
    feature_set: str,
    label_method: str,
    horizon: int,
    limit: int = 100,
) -> dict[str, Any] | None:
    model_runs = repository.get_model_runs(limit=limit, ascending=False)
    for model_run in model_runs:
        if not is_promoted_model_run(model_run):
            continue
        if target_ticker_for_model_run(model_run, required=False) != ticker.upper():
            continue
        if model_run.get("feature_set") != feature_set:
            continue
        if model_run.get("label_method") != label_method:
            continue
        if int(model_run.get("horizon") or 0) != int(horizon):
            continue
        return model_run
    return None


def compare_candidate_to_incumbent(
    candidate: dict[str, Any],
    incumbent: dict[str, Any] | None,
    *,
    min_objective_improvement: float = 0.0,
) -> dict[str, Any]:
    candidate_score = _optional_float(candidate.get("objective_score"))
    if incumbent is None:
        return {
            "status": "pass",
            "reason": "no_incumbent",
            "candidate_objective_score": candidate_score,
            "incumbent_model_run_id": None,
            "incumbent_objective_score": None,
        }

    incumbent_candidate = ((incumbent.get("metrics") or {}).get("promotion") or {}).get("candidate") or {}
    incumbent_score = _optional_float(incumbent_candidate.get("objective_score"))
    comparison = {
        "candidate_objective_score": candidate_score,
        "incumbent_model_run_id": incumbent.get("id"),
        "incumbent_model_name": incumbent.get("model_name"),
        "incumbent_model_version": incumbent.get("model_version"),
        "incumbent_candidate_id": incumbent_candidate.get("candidate_id"),
        "incumbent_objective_score": incumbent_score,
        "required_objective_improvement": min_objective_improvement,
    }
    if candidate_score is None:
        return {**comparison, "status": "fail", "reason": "candidate_missing_objective_score"}
    if incumbent_score is None:
        return {**comparison, "status": "pass", "reason": "incumbent_missing_objective_score"}
    if candidate_score > incumbent_score + min_objective_improvement:
        return {**comparison, "status": "pass", "reason": "candidate_improves_incumbent"}
    return {**comparison, "status": "fail", "reason": "candidate_does_not_improve_incumbent"}


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def summarize_config(config: RetrainingJobConfig) -> dict[str, Any]:
    return {
        "feature_set": config.feature_set,
        "label_method": config.label_method,
        "horizon": config.horizon,
        "models": config.model_names,
        "confidence_thresholds": config.confidence_thresholds,
        "scopes": config.scopes,
        "splits": config.splits,
        "min_rows": config.min_rows,
        "min_total_return": config.min_total_return,
        "min_profit_factor": config.min_profit_factor,
        "max_drawdown_floor": config.max_drawdown_floor,
        "min_active_trades": config.min_active_trades,
        "upload_artifacts": config.upload_artifacts,
        "require_incumbent_improvement": config.require_incumbent_improvement,
        "min_objective_improvement": config.min_objective_improvement,
        "incumbent_lookup_limit": config.incumbent_lookup_limit,
    }
