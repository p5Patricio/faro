"""Local operational-job scheduler.

Replaces the retired ``.github/workflows/operational-jobs.yml`` GitHub
Actions workflow (see that file's header comment). Windows Task Scheduler
invokes this module directly (``ops/register_local_jobs.ps1``); it mirrors
the retired workflow's ``JOB_MODE`` branching over the same, unchanged job
modules, run as local subprocesses instead of hosted CI steps.

Usage::

    py -3.14 -m ops.run_local_scheduler
        --job {market_data|inference|paper_trading|retraining|full|full_retrain}
        [--tickers BTC-USD,AAPL] [--feature-sets technical_v2] [--skip-collection]
        [--model-name ...] [--model-version ...]
        [--models logistic_regression,random_forest,extra_trees]
        [--confidence-thresholds 0.55,0.60,0.65,0.70] [--scopes local,asset_class,global]
        [--no-require-incumbent-improvement] [--min-objective-improvement 0.0]
        [--reports-dir reports] [--no-notify]

Design ADR D13 (subprocess composition, threat matrix): every step is
launched via ``subprocess.run([sys.executable, "-m", module, *args])`` -- a
fixed Python list, built from parsed argparse values, **never** a
string-formatted or concatenated shell command, and ``shell=True`` is never
passed. A ticker/model value containing `&`, `"`, spaces, or a trailing
backslash always lands as exactly one literal argv element; there is no
shell in between to reinterpret it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

JOB_MODES = ("market_data", "inference", "paper_trading", "retraining", "full", "full_retrain")

# Filename the scheduler's inference step must write its report under.
# `ops.notification_dispatch.INFERENCE_JOB_REPORT_NAME` reads this exact
# name for signal-transition detection -- NOT the retired workflow's
# `inference_job_latest.json` (that name predates the notifications change
# and would silently starve the P0 signal-transition trigger of any input).
INFERENCE_JOB_REPORT_NAME = "inference_job.json"

Runner = Callable[..., Any]


class StepResult(NamedTuple):
    name: str
    argv: list[str]
    returncode: int
    report_path: Path | None
    report_failed: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """Failed on a non-zero exit code OR a report JSON with `failed > 0`
        -- the same predicate the retired workflow applied inline via
        `python -c "...sys.exit(1 if report.get('failed', 0) else 0)"`."""
        return self.returncode == 0 and self.report_failed == 0


def build_step_argv(module: str, args: list[str]) -> list[str]:
    """Fixed argv list for one scheduler step (D13). `args` elements pass
    through untouched: this is what makes shell injection structurally
    impossible, not input sanitization -- there is no shell parsing step
    for a hostile value to escape from."""
    return [sys.executable, "-m", module, *args]


def steps_for_job(job: str) -> list[str]:
    """Which step names run for a given `--job` value, mirroring the
    retired workflow's `JOB_MODE` `if:` conditions exactly (and their
    literal step order: market_data, retraining, inference, paper_trading)."""
    steps: list[str] = []
    if job in ("market_data", "full", "full_retrain"):
        steps.append("market_data")
    if job in ("retraining", "full_retrain"):
        steps.append("retraining")
    if job in ("inference", "full", "full_retrain"):
        steps.append("inference")
    if job in ("paper_trading", "full", "full_retrain"):
        steps.append("paper_trading")
    return steps


def _first_feature_set(feature_sets: str) -> str:
    """Mirrors the retired workflow's `FEATURE_SET="${FEATURE_SETS%%,*}"`:
    the retraining step takes one feature set, not a comma list."""
    return feature_sets.split(",", 1)[0].strip()


def build_market_data_argv(ns: argparse.Namespace, reports_dir: Path) -> list[str]:
    argv = [
        "--assets-file", "config/assets.core.json",
        "--feature-sets", ns.feature_sets,
        "--out", str(reports_dir / "market_data_job.json"),
    ]
    if ns.tickers:
        argv += ["--tickers", ns.tickers]
    if ns.skip_collection:
        argv.append("--skip-collection")
    return argv


def build_retraining_argv(ns: argparse.Namespace, reports_dir: Path) -> list[str]:
    argv = [
        "--feature-set", _first_feature_set(ns.feature_sets),
        "--models", ns.models,
        "--confidence-thresholds", ns.confidence_thresholds,
        "--scopes", ns.scopes,
        "--min-objective-improvement", str(ns.min_objective_improvement),
        "--out", str(reports_dir / "retraining_job.json"),
    ]
    if ns.no_require_incumbent_improvement:
        argv.append("--no-require-incumbent-improvement")
    if ns.tickers:
        argv += ["--tickers", ns.tickers]
    return argv


def build_inference_argv(ns: argparse.Namespace, reports_dir: Path) -> list[str]:
    argv = ["--out", str(reports_dir / INFERENCE_JOB_REPORT_NAME)]
    if ns.model_name:
        argv += ["--model-name", ns.model_name]
    if ns.model_version:
        argv += ["--model-version", ns.model_version]
    return argv


def build_paper_trading_argv(ns: argparse.Namespace, reports_dir: Path) -> list[str]:
    argv = ["--out", str(reports_dir / "paper_trading_job.json")]
    if ns.tickers:
        argv += ["--tickers", ns.tickers]
    if ns.model_name:
        argv += ["--model-name", ns.model_name]
    if ns.model_version:
        argv += ["--model-version", ns.model_version]
    return argv


_STEP_BUILDERS: dict[str, tuple[str, Callable[[argparse.Namespace, Path], list[str]]]] = {
    "market_data": ("collector.run_market_data_job", build_market_data_argv),
    "retraining": ("brain.run_retraining_job", build_retraining_argv),
    "inference": ("brain.run_inference_job", build_inference_argv),
    "paper_trading": ("brain.run_paper_trading_job", build_paper_trading_argv),
}


def _report_path_from_args(args: list[str]) -> Path | None:
    if "--out" not in args:
        return None
    index = args.index("--out") + 1
    if index >= len(args):
        return None
    return Path(args[index])


def _read_report_failed(report_path: Path, *, cwd: Path) -> int:
    full_path = report_path if report_path.is_absolute() else cwd / report_path
    try:
        report = json.loads(full_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return int(report.get("failed") or 0)


def run_step(
    name: str,
    module: str,
    args: list[str],
    *,
    cwd: Path,
    runner: Runner = subprocess.run,
) -> StepResult:
    """Run one scheduler step as a subprocess with a fixed argv list --
    never `shell=True` (D13). `runner` is an injection seam for tests; the
    real caller never overrides it."""
    argv = build_step_argv(module, args)
    completed = runner(argv, cwd=str(cwd), capture_output=True, text=True)

    report_path = _report_path_from_args(args)
    report_failed = _read_report_failed(report_path, cwd=cwd) if report_path is not None else 0

    return StepResult(
        name=name,
        argv=argv,
        returncode=completed.returncode,
        report_path=report_path,
        report_failed=report_failed,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def write_log(job: str, results: list[StepResult], *, logs_dir: Path, today: date | None = None) -> Path:
    """Tee every step's argv/exit-code/output to
    `logs/local_scheduler_{job}_{YYYYMMDD}.log` (also printed to stdout)."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    today = today or date.today()
    log_path = logs_dir / f"local_scheduler_{job}_{today.strftime('%Y%m%d')}.log"

    lines: list[str] = []
    for result in results:
        lines.append(f"===== {result.name} =====")
        lines.append(f"argv: {result.argv}")
        lines.append(f"returncode: {result.returncode}")
        lines.append(f"report_failed: {result.report_failed}")
        if result.stdout:
            lines.append("--- stdout ---")
            lines.append(result.stdout.rstrip("\n"))
        if result.stderr:
            lines.append("--- stderr ---")
            lines.append(result.stderr.rstrip("\n"))
        lines.append("")

    content = "\n".join(lines)
    log_path.write_text(content, encoding="utf-8")
    print(content)
    return log_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local operational jobs (replaces the retired GitHub Actions workflow)"
    )
    parser.add_argument("--job", required=True, choices=JOB_MODES)
    parser.add_argument("--tickers", help="Comma-separated stored tickers, for example BTC-USD,AAPL")
    parser.add_argument("--feature-sets", default="technical_v2", help="Comma-separated feature sets")
    parser.add_argument("--skip-collection", action="store_true")
    parser.add_argument("--model-name")
    parser.add_argument("--model-version")
    parser.add_argument("--models", default="logistic_regression,random_forest,extra_trees")
    parser.add_argument("--confidence-thresholds", default="0.55,0.60,0.65,0.70")
    parser.add_argument("--scopes", default="local,asset_class,global")
    parser.add_argument("--no-require-incumbent-improvement", action="store_true")
    parser.add_argument("--min-objective-improvement", type=float, default=0.0)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--no-notify", action="store_true")
    return parser.parse_args(argv)


def run(ns: argparse.Namespace, *, cwd: Path = REPO_ROOT, runner: Runner = subprocess.run) -> int:
    reports_dir = Path(ns.reports_dir)
    (cwd / reports_dir).mkdir(parents=True, exist_ok=True)

    results: list[StepResult] = []

    schema_result = run_step("schema_check", "collector.schema_check", [], cwd=cwd, runner=runner)
    results.append(schema_result)

    # Fail-fast, mirroring the retired workflow's default GitHub Actions
    # step ordering: a step failure (no `continue-on-error`) skips every
    # subsequent step except ones with `if: always()`. A broken/missing
    # schema must not let job-mode steps write reports against it.
    if schema_result.ok:
        for step_name in steps_for_job(ns.job):
            module, builder = _STEP_BUILDERS[step_name]
            args = builder(ns, reports_dir)
            results.append(run_step(step_name, module, args, cwd=cwd, runner=runner))

    primary_ok = all(result.ok for result in results)
    status = "success" if primary_ok else "failure"

    # Task 7.3 (design.md section 7-A): a step that exits non-zero *before*
    # writing its own report JSON -- `collector.schema_check` never writes
    # one at all, and any other step can crash before its own `json.dump` --
    # leaves `report_failed == 0` even though the step failed, so the
    # notifier's report-derived `failed > 0` check cannot see it. Name these
    # steps explicitly so `ops.notification_dispatch`'s job_failure rule
    # still fires; a step whose own report already shows `failed > 0` needs
    # no help here.
    pre_report_failed_steps = [
        result.name for result in results if result.returncode != 0 and result.report_failed == 0
    ]

    notify_ok = True
    if not ns.no_notify:
        notify_args = ["--reports-dir", str(reports_dir), "--status", status, "--job-mode", ns.job]
        if pre_report_failed_steps:
            # Single unsplit argv element (D13): a comma-joined string, not
            # one `--failed-steps` per step name.
            notify_args += ["--failed-steps", ",".join(pre_report_failed_steps)]
        notify_result = run_step("notify", "ops.notify_operational_job", notify_args, cwd=cwd, runner=runner)
        results.append(notify_result)
        notify_ok = notify_result.returncode == 0

    write_log(ns.job, results, logs_dir=cwd / "logs")

    return 0 if (primary_ok and notify_ok) else 1


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)
    return run(ns)


if __name__ == "__main__":
    sys.exit(main())
