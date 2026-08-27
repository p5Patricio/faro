"""``ops/run_local_scheduler.py`` test suite.

RED test (task 9.1, design.md ADR D13, threat matrix "Subprocess
composition") proves ticker/model arguments containing shell metacharacters
(`&`, `"`, spaces, a trailing backslash) pass through the scheduler's argv
builders as a single, unsplit argv element. This is what makes shell
injection *structurally* impossible: every step is launched via
``subprocess.run([sys.executable, "-m", module, *args])`` -- a fixed Python
list, never a formatted/concatenated shell string, and ``shell=True`` is
never passed. A hostile value can only ever land as one literal argv
element the OS hands to the child process's ``argv[]``; there is no shell
in the middle to reinterpret ``&``, quotes, or whitespace.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ops.run_local_scheduler import (
    StepResult,
    build_inference_argv,
    build_market_data_argv,
    build_paper_trading_argv,
    build_retraining_argv,
    build_step_argv,
    main,
    parse_args,
    run,
    run_step,
    steps_for_job,
)

# Genuinely hostile: shell metacharacter (`&`), a quote, embedded spaces,
# and a trailing backslash (which, inside a naive shell-quoted string on
# Windows `cmd.exe`, can escape a closing quote). Not a placeholder.
HOSTILE_VALUE = 'AAPL & echo pwned > pwned.txt; "$(id)" \\'


# ---------------------------------------------------------------------------
# 9.1 RED: subprocess-composition threat matrix
# ---------------------------------------------------------------------------


def test_build_step_argv_is_a_fixed_list_never_a_shell_string() -> None:
    argv = build_step_argv("collector.run_market_data_job", ["--tickers", HOSTILE_VALUE])

    assert argv == [sys.executable, "-m", "collector.run_market_data_job", "--tickers", HOSTILE_VALUE]
    assert isinstance(argv, list)
    assert all(isinstance(item, str) for item in argv)


def test_market_data_argv_passes_hostile_ticker_as_single_unsplit_element() -> None:
    ns = parse_args(["--job", "market_data", "--tickers", HOSTILE_VALUE])

    argv = build_market_data_argv(ns, Path("reports"))

    assert argv.count("--tickers") == 1
    value_index = argv.index("--tickers") + 1
    assert argv[value_index] == HOSTILE_VALUE
    # Exactly one element carries the hostile payload -- it was never split
    # on its embedded spaces/`&`/quote the way a shell would tokenize it.
    assert sum(1 for item in argv if HOSTILE_VALUE in item) == 1


def test_paper_trading_argv_passes_hostile_ticker_as_single_unsplit_element() -> None:
    ns = parse_args(["--job", "paper_trading", "--tickers", HOSTILE_VALUE])

    argv = build_paper_trading_argv(ns, Path("reports"))

    value_index = argv.index("--tickers") + 1
    assert argv[value_index] == HOSTILE_VALUE


def test_retraining_argv_passes_hostile_model_name_as_single_unsplit_element() -> None:
    hostile_model = 'logistic_regression"; rm -rf / #'
    ns = parse_args(["--job", "retraining", "--models", hostile_model])

    argv = build_retraining_argv(ns, Path("reports"))

    value_index = argv.index("--models") + 1
    assert argv[value_index] == hostile_model


def test_inference_argv_passes_hostile_model_name_as_single_unsplit_element() -> None:
    hostile_model = 'default & del /f /q C:\\'
    ns = parse_args(["--job", "inference", "--model-name", hostile_model])

    argv = build_inference_argv(ns, Path("reports"))

    value_index = argv.index("--model-name") + 1
    assert argv[value_index] == hostile_model


def test_run_step_never_invokes_subprocess_with_shell_true(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(argv: list[str], **kwargs: object) -> _Completed:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _Completed()

    result = run_step(
        "market_data",
        "collector.run_market_data_job",
        ["--tickers", HOSTILE_VALUE],
        cwd=tmp_path,
        runner=fake_runner,
    )

    assert isinstance(captured["argv"], list)
    assert captured["kwargs"].get("shell") is not True  # never shell=True
    assert HOSTILE_VALUE in captured["argv"]
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# 9.2: --job branching mirrors the retired workflow's JOB_MODE conditions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "job,expected_steps",
    [
        ("market_data", ["market_data"]),
        ("inference", ["inference"]),
        ("paper_trading", ["paper_trading"]),
        ("retraining", ["retraining"]),
        ("full", ["market_data", "inference", "paper_trading"]),
        ("full_retrain", ["market_data", "retraining", "inference", "paper_trading"]),
    ],
)
def test_steps_for_job_mirrors_retired_workflow_job_mode(job: str, expected_steps: list[str]) -> None:
    assert steps_for_job(job) == expected_steps


def test_parse_args_rejects_unknown_job() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--job", "not_a_real_job"])


def test_run_step_fails_on_nonzero_exit_code(tmp_path: Path) -> None:
    class _Completed:
        returncode = 1
        stdout = "boom"
        stderr = "traceback"

    result = run_step("market_data", "collector.run_market_data_job", [], cwd=tmp_path, runner=lambda argv, **kw: _Completed())

    assert result.returncode == 1
    assert result.ok is False


def test_run_step_fails_when_report_json_has_failed_greater_than_zero(tmp_path: Path) -> None:
    report_path = tmp_path / "reports" / "market_data_job.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"attempted": 3, "succeeded": 2, "failed": 1}), encoding="utf-8")

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    result = run_step(
        "market_data",
        "collector.run_market_data_job",
        ["--out", "reports/market_data_job.json"],
        cwd=tmp_path,
        runner=lambda argv, **kw: _Completed(),
    )

    assert result.returncode == 0
    assert result.report_failed == 1
    assert result.ok is False


def test_run_step_succeeds_when_report_json_has_zero_failed(tmp_path: Path) -> None:
    report_path = tmp_path / "reports" / "market_data_job.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"attempted": 3, "succeeded": 3, "failed": 0}), encoding="utf-8")

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    result = run_step(
        "market_data",
        "collector.run_market_data_job",
        ["--out", "reports/market_data_job.json"],
        cwd=tmp_path,
        runner=lambda argv, **kw: _Completed(),
    )

    assert result.ok is True


# ---------------------------------------------------------------------------
# 9.2: end-to-end `run()` orchestration (fake runner, no real subprocess)
# ---------------------------------------------------------------------------


def test_run_skips_job_steps_when_schema_check_fails_but_still_notifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    class _Completed:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    def fake_runner(argv: list[str], **kwargs: object) -> _Completed:
        module = argv[2]
        calls.append(module)
        if module == "collector.schema_check":
            return _Completed(1)
        return _Completed(0)

    ns = parse_args(["--job", "market_data"])
    exit_code = run(ns, cwd=tmp_path, runner=fake_runner)

    assert calls == ["collector.schema_check", "ops.notify_operational_job"]
    assert exit_code == 1


def test_run_executes_full_job_mode_steps_in_order_and_notifies(tmp_path: Path) -> None:
    calls: list[str] = []

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(argv: list[str], **kwargs: object) -> _Completed:
        calls.append(argv[2])
        return _Completed()

    ns = parse_args(["--job", "full"])
    exit_code = run(ns, cwd=tmp_path, runner=fake_runner)

    assert calls == [
        "collector.schema_check",
        "collector.run_market_data_job",
        "brain.run_inference_job",
        "brain.run_paper_trading_job",
        "ops.notify_operational_job",
    ]
    assert exit_code == 0


def test_run_writes_inference_report_with_the_dispatcher_expected_filename(tmp_path: Path) -> None:
    """ops.notification_dispatch.INFERENCE_JOB_REPORT_NAME is
    'inference_job.json' -- the scheduler must write the inference step's
    report under that exact name, not the retired workflow's stale
    'inference_job_latest.json', or the signal-transition notification
    trigger silently never fires."""
    ns = parse_args(["--job", "inference"])
    argv = build_inference_argv(ns, Path("reports"))

    out_index = argv.index("--out") + 1
    assert argv[out_index] == str(Path("reports") / "inference_job.json")


def test_run_notify_step_receives_computed_status_and_job_mode(tmp_path: Path) -> None:
    captured_notify_argv: list[str] = []

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(argv: list[str], **kwargs: object) -> _Completed:
        if argv[2] == "ops.notify_operational_job":
            captured_notify_argv.extend(argv)
        return _Completed()

    ns = parse_args(["--job", "market_data"])
    run(ns, cwd=tmp_path, runner=fake_runner)

    assert "--status" in captured_notify_argv
    assert captured_notify_argv[captured_notify_argv.index("--status") + 1] == "success"
    assert "--job-mode" in captured_notify_argv
    assert captured_notify_argv[captured_notify_argv.index("--job-mode") + 1] == "market_data"


def test_run_respects_no_notify_flag(tmp_path: Path) -> None:
    calls: list[str] = []

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(argv: list[str], **kwargs: object) -> _Completed:
        calls.append(argv[2])
        return _Completed()

    ns = parse_args(["--job", "market_data", "--no-notify"])
    run(ns, cwd=tmp_path, runner=fake_runner)

    assert "ops.notify_operational_job" not in calls


def test_run_writes_a_tee_log_file(tmp_path: Path) -> None:
    class _Completed:
        returncode = 0
        stdout = "job output"
        stderr = ""

    def fake_runner(argv: list[str], **kwargs: object) -> _Completed:
        return _Completed()

    ns = parse_args(["--job", "market_data"])
    run(ns, cwd=tmp_path, runner=fake_runner)

    log_files = list((tmp_path / "logs").glob("local_scheduler_market_data_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "job output" in content


def test_main_returns_run_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        "ops.run_local_scheduler.subprocess.run",
        lambda argv, **kwargs: _Completed(),
    )

    exit_code = main(["--job", "market_data"])

    assert exit_code == 0
