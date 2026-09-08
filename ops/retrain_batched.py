"""Resumable, progress-reporting wrapper around ``brain.run_retraining_job``.

Runs ONE ticker per child process, so a hang or crash on a single name never
blocks the rest, and every finished ticker is durable immediately. Re-running
the wrapper skips tickers already recorded in the state file, so an
interrupted run just picks up where it stopped.

Usage
-----
    py -3.14 -m ops.retrain_batched --feature-set fundamental_v1 \
        --targets-file config/targets.stocks.json --scopes local

Extra ``run_retraining_job`` flags after ``--`` are forwarded verbatim to
every child, e.g. ``... -- --min-objective-improvement 0.01 --skip-upload``.

Files (under logs/, gitignored)
-------------------------------
    retrain_<feature_set>_progress.log   one human line per ticker  (tail this)
    retrain_<feature_set>_state.json     {ticker: {outcome, detail, seconds}}
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / "logs"


def _load_targets(args: argparse.Namespace) -> list[str]:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    raw = json.loads((REPO_ROOT / args.targets_file).read_text(encoding="utf-8"))
    return [str(t).strip().upper() for t in raw if str(t).strip()]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%m-%d %H:%M:%S")


def _classify(report: dict, ticker: str) -> tuple[str, str]:
    """(outcome, detail) for THIS ticker from a single-ticker report.

    ``skipped_assets`` always lists every no-dataset asset in the universe
    regardless of ``--tickers``, so it is checked last and only for an entry
    that names this ticker.
    """
    want = ticker.upper()
    if report.get("results"):
        r = report["results"][0]
        cmp_ = r.get("incumbent_comparison") or {}
        return "promoted", f"{r.get('model_name')} {r.get('scope')} vs incumbent={cmp_.get('reason')}"
    for s in report.get("skipped") or []:
        if str(s.get("ticker", "")).upper() != want:
            continue
        reason = s.get("reason", "skipped")
        cand, inc = s.get("candidate_objective_score"), s.get("incumbent_objective_score")
        extra = f" cand={cand} inc={inc}" if (cand is not None or inc is not None) else ""
        bucket = "not_better" if reason == "candidate_not_better_than_incumbent" else reason
        return bucket, f"{reason}{extra} {s.get('detail', '')}".strip()
    for e in report.get("errors") or []:
        return "error", str(e.get("error"))[:200]
    for sa in report.get("skipped_assets") or []:
        if str(sa.get("ticker", "")).upper() == want:
            return "no_dataset", str(sa.get("reason", "no materialized dataset"))
    if not report.get("attempted"):
        return "no_dataset", "ticker not in the materialized universe"
    return "empty", "report had no entry for this ticker"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feature-set", required=True)
    parser.add_argument("--targets-file", default="config/targets.stocks.json")
    parser.add_argument("--tickers", help="Comma list; overrides --targets-file")
    parser.add_argument("--scopes", default="local")
    parser.add_argument("--restart", action="store_true", help="Ignore the state file and redo every ticker")
    parser.add_argument("passthrough", nargs="*", help="Flags after -- forwarded to run_retraining_job")
    args = parser.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    progress_path = LOG_DIR / f"retrain_{args.feature_set}_progress.log"
    state_path = LOG_DIR / f"retrain_{args.feature_set}_state.json"
    tmp_out = LOG_DIR / f"retrain_{args.feature_set}_last_child.json"

    state: dict[str, dict] = {}
    if state_path.exists() and not args.restart:
        state = json.loads(state_path.read_text(encoding="utf-8"))

    targets = _load_targets(args)
    todo = [t for t in targets if t not in state]

    def log(line: str) -> None:
        stamped = f"{_now()}  {line}"
        print(stamped, flush=True)
        with progress_path.open("a", encoding="utf-8") as fh:
            fh.write(stamped + "\n")

    log(f"=== batch start: {len(todo)} to do, {len(state)} already done, {len(targets)} total ===")

    forwarded = [a for a in args.passthrough if a != "--"]
    for i, ticker in enumerate(todo, 1):
        started = time.monotonic()
        cmd = [
            sys.executable, "-m", "brain.run_retraining_job",
            "--feature-set", args.feature_set,
            "--tickers", ticker,
            "--scopes", args.scopes,
            "--out", str(tmp_out),
            *forwarded,
        ]
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
        seconds = round(time.monotonic() - started, 1)

        if proc.returncode != 0 or not tmp_out.exists():
            outcome, detail = "error", (proc.stderr or proc.stdout or "no output")[-300:].strip()
        else:
            try:
                outcome, detail = _classify(json.loads(tmp_out.read_text(encoding="utf-8")), ticker)
            except Exception as exc:  # noqa: BLE001 - wrapper must never abort mid-batch
                outcome, detail = "error", f"unparseable report: {exc}"

        state[ticker] = {"outcome": outcome, "detail": detail, "seconds": seconds, "at": _now()}
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        done = len(state)
        log(f"[{done}/{len(targets)}] {ticker:6} {outcome:11} {seconds:6.1f}s  {detail}")

    counts: dict[str, int] = {}
    for entry in state.values():
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
    log(f"=== batch done: {counts} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
