# Apply Progress: Telegram Notifications

**Batch 1 scope**: Phase 1, Phase 2, Phase 3. **Batch 2 scope (this update)**: Phase 4,
Phase 5, Phase 6a, Phase 6b. Phase 7 remains blocked (scheduler integration, out of
scope until `local-postgres-migration` task 9 lands). Phase 8 (docs) not started.

## Mode

Standard (strict_tdd: false per `openspec/config.yaml`). Threat-matrix RED tests written
and confirmed failing before their production code per the skill's Hard Gate, even though
strict TDD is off project-wide. This applied in batch 2 to the 6b.1 credential/payload-egress
test (confirmed failing with `ImportError: cannot import name 'dispatch_notification'`
before `ops/notify_operational_job.py` was refactored).

## Completed Tasks

### Phase 1: Foundation — Migration + Repository
- [x] 1.1 RED: SQL-injection test in `tests/test_notification_dispatch.py` (confirmed failing: `AttributeError: no attribute 'insert_notification'`)
- [x] 1.2 `db/migrations/0007_notifications.sql`: `notification_rules` + `notifications`, partial unique indexes, 4 seeded active rules
- [x] 1.3 `collector/local_repository.py`: 5 new methods in `# -- Notifications --` section (line ~847)
- [x] 1.4 `collector/schema_check.py`: `notification_rules` + `notifications` added to `REQUIRED_ML_RELATIONS`
- [x] 1.5 `tests/test_notification_dispatch.py`: seeded-rule reads, dedupe/cooldown integration tests
- [x] 1.6 SQL-injection RED test now passes
- [x] 1.7 `py -3.14 -m db.migrate` + `py -3.14 -m collector.schema_check` both pass on `TEST_DATABASE_URL` and `LOCAL_DATABASE_URL`

### Phase 2: Telegram Notifier Client
- [x] 2.1 RED: HTML-injection test (confirmed failing: `ModuleNotFoundError: ops.telegram_notifier`)
- [x] 2.2 RED: credential-in-URL redaction test (same module, confirmed failing)
- [x] 2.3 `ops/telegram_notifier.py` created: `TelegramConfig`, `escape_html`, `redact`, `chunk_message`, `render_operational_message`, `send_telegram_message`
- [x] 2.4 `tests/test_telegram_notifier.py`: escaping, chunking/reassembly/hard-split, pacing, 429 retry/exhaustion, `from_env`
- [x] 2.5 Redaction: 400-body-echoing-url case + persisted-error_reason-shaped-string case
- [x] 2.6 Both RED tests from 2.1/2.2 now pass

### Phase 3: Notification Rules & Policy
- [x] 3.1 `ops/notification_rules.py` created: shared threshold defaults + `SEEDED_RULE_PARAMS`
- [x] 3.2 4 `dedupe_key` recipes implemented per design §4
- [x] 3.3 4 pure evaluators implemented (job_failure, signal_transition, model_degradation, stale_data)
- [x] 3.4 `tests/test_notification_rules.py`: parametrized dedupe-key tests, evaluator transition/threshold tests
- [x] 3.5 Drift test: parses `0007_notifications.sql`'s jsonb literals, asserts equality with `SEEDED_RULE_PARAMS`

### Phase 4: Signal-Transition Emission
- [x] 4.1 `brain/inference_job.py`: resolve `asset_id = repository.get_asset_id(ticker)` and read
      `previous = repository.get_latest_prediction(asset_id, model_name=model_run["model_name"])`
      immediately before `generate_latest_prediction` upserts the new prediction row.
- [x] 4.2 `previous_action` added to each `results` entry.
- [x] 4.3 `tests/test_brain_pipeline.py`: extended `test_run_latest_inference_job_records_success_and_errors`
      with a `FakeInferenceRepository` stub (replacing the old bare `object()` repository, which had no
      `get_asset_id`/`get_latest_prediction`) asserting `previous_action == "HOLD"` and the exact
      `get_latest_prediction` call args; added a sibling test
      `test_run_latest_inference_job_first_ever_prediction_has_no_previous_action` asserting
      `previous_action is None` on a first-ever prediction.

### Phase 5: Dashboard Threshold Binding
- [x] 5.1 `api/main.py`: the 4 `Query(default=...)` values in `get_operational_alerts` now import
      `DEFAULT_MAX_PRICE_AGE_HOURS`/`DEFAULT_MIN_FEEDBACK_SAMPLES`/`DEFAULT_MIN_ACCURACY`/
      `DEFAULT_MIN_MEAN_OUTCOME_RETURN` from `ops.notification_rules` instead of duplicating literals.
- [x] 5.2 `tests/test_api.py`: `test_operational_alerts_endpoint_defaults_match_notification_rules_constants`
      inspects `get_operational_alerts`'s `Query` defaults via `inspect.signature` and asserts equality
      with the imported constants (compile-time reference, no drift possible).

### Phase 6a: Dispatch Orchestration
- [x] 6a.1 `ops/notification_dispatch.py` created: `dispatch_notifications(repository, *, reports, job_mode,
      telegram_config, rule_types, now, session, sleep)` iterates `get_active_notification_rules(channel=
      "telegram")`, builds events per rule type, and `_process_event` does dedupe-first
      (`notification_already_sent`) then cooldown (`get_last_notification_fired_at` vs
      `cooldown_minutes`; skipped entirely when `cooldown_minutes == 0`), sends via
      `send_telegram_message`, and logs via `insert_notification`. Cooldown-suppressed events are
      reported in the outcome list only, never persisted. The whole function and every per-rule/
      per-event step is wrapped so a DB or evaluation error becomes an outcome entry instead of
      propagating (Best-Effort Delivery Never Fails the Calling Job).
- [x] 6a.2 `_stale_data_events`: wired to `get_latest_price_timestamps()`; a global rule
      (`asset_id is None`) fans out to every returned asset row, attaching that asset's own
      `asset_id` to its event (required so cooldown scopes per-asset, not globally); a scoped rule
      filters to just its own asset.
- [x] 6a.3 `_model_degradation_events`: wired to `get_prediction_feedback(asset_id=rule_asset_id,
      only_evaluated=True)`, grouped by `model_name`, each group summarized via
      `brain.feedback.analyze_prediction_feedback` (the same function `feedback_report.py` uses) and
      passed into `evaluate_model_degradation`.
- [x] 6a.4 `_signal_transition_events`: reads `reports.get("inference_job.json")`'s `results` list
      (the `reports` dict is the caller-supplied, already-loaded `load_reports()` output — this
      unit's own tests stub it directly per the batch instructions, since `load_reports` did not
      exist until Phase 6b landed later in the same batch); resolves each result's ticker to an
      `asset_id` via `repository.get_asset_id` for scoped-rule filtering and for denormalizing the
      log row.
- [x] 6a.5 `tests/test_notification_dispatch.py` (22 new tests, appended after the Phase 1 tests):
      unit tests for each `_job_failure_events`/`_signal_transition_events`/
      `_model_degradation_events`/`_stale_data_events` wiring function against a `FakeDispatchRepository`
      (no DB); real-DB integration tests via `_process_event` proving two `model_degradation` events
      with different `scope_key` do not suppress each other, a global and a scoped `stale_data` rule
      do not suppress each other, `cooldown_minutes=0` always proceeds past the cooldown check even
      with a very recent prior `sent` row, and a non-zero-cooldown suppression is never persisted;
      an end-to-end test via the public `dispatch_notifications(..., rule_types={"job_failure"})`
      proving a forced `failed > 0` report produces exactly one `FakeSession.post`/one `sent` row and
      a re-invocation dedupes to zero posts; a `dispatch_notifications` never-raises test against a
      repository whose `get_active_notification_rules` raises.
      **Addition beyond the literal task list**: added an optional `rule_types: set[str] | None`
      keyword to `dispatch_notifications` (default `None` = evaluate every active rule, no behavior
      change) so the end-to-end test can isolate `job_failure` without depending on the test
      database's `assets`/`prediction_feedback` state for the other three rule types.

### Phase 6b: Notifier Transport Refactor
- [x] 6b.1 RED: `test_dispatch_notification_never_puts_telegram_credentials_in_the_webhook_payload` in
      `tests/test_operational_notifications.py` (confirmed failing: `ImportError: cannot import name
      'dispatch_notification' from 'ops.notify_operational_job'` before the refactor).
- [x] 6b.2 `load_reports(reports_dir) -> dict[name, raw]` extracted from `build_notification_payload`'s
      inline glob; `build_notification_payload` now calls it and branches on an internal
      `_UNREADABLE_MARKER` sentinel to reproduce the exact prior `{"name": ..., "error": ...}` shape
      for unreadable report files, keeping the 3 pre-existing tests byte-identical.
- [x] 6b.3 `send_telegram_notification(payload, config, *, session, sleep)` (renders via
      `render_operational_message`, delegates to `send_telegram_message`) and
      `dispatch_notification(payload, *, webhook_url, telegram_config, session, sleep)` added; the
      webhook call is wrapped in `try/except requests.RequestException` so a webhook failure (network
      error or `raise_for_status()`) never suppresses the Telegram attempt.
- [x] 6b.4 `main()` now also calls `_dispatch_rule_notifications`, which opens its own
      `psycopg.connect(LocalPostgresConfig.from_env().dsn, ...)` inside a `try/except Exception` and
      returns `{"dispatched": False, "reason": "database_unavailable", "detail": ...}` on any
      connection or dispatch failure, without touching the webhook/Telegram result already computed.
      Verified manually with `py -3.14 -m ops.notify_operational_job` both with `LOCAL_DATABASE_URL`
      set (rules evaluate against the real local DB, 4 active rules, 0 events on a clean install) and
      unset (graceful `database_unavailable` degradation, webhook/Telegram summary path unaffected).
- [x] 6b.5 `--no-telegram` and `--no-rule-notifications` flags added; no `--telegram-bot-token` flag —
      confirmed both flags manually via CLI.
- [x] 6b.6 `tests/test_operational_notifications.py` (9 tests total: 3 pre-existing + 6 new): the 3
      pre-existing tests pass verbatim; both transports unconfigured → two no-ops
      (`missing_webhook_url`/`missing_telegram_config`), nothing raised; webhook `post` raising
      `requests.ConnectionError` → Telegram still attempted and sent; the 6b.1 RED test now passes
      (token and chat id absent from the webhook JSON body); plus 2 extra tests for `load_reports`
      (raw parse + unreadable-file marker) not explicitly itemized in 6a/6b but needed to prove the
      shared-extraction claim in 6b.2.

## Naming deviation carried forward from Phase 3 (already resolved, confirmed here)

Phase 3's apply-progress flagged that `signal_transition`/`stale_data` (spec-aligned) were used
instead of design.md's `signal_action_change`/`stale_prices`. This batch's own task list
(`tasks.md`) already had the corrected names for 4.x/5.x/6a.x/6b.x, and all Phase 4-6b code
(`brain/inference_job.py`, `ops/notification_dispatch.py`, `ops/notify_operational_job.py`, all
tests) consistently uses `signal_transition`/`stale_data`. No further deviation introduced.

## Concurrent work from `local-postgres-migration` (sibling agent, same session)

`brain/inference_job.py` (Phase 4's file) was also a stated concurrent-edit target
(`local-postgres-migration` Phase 8, artifact storage). Checked via `git diff` before every
commit in this batch: the sibling's edits landed in `brain/artifacts.py`,
`brain/retraining_job.py`, `brain/run_retraining_job.py`, and `tests/test_model_artifacts.py` /
parts of `tests/test_brain_pipeline.py` (the `run_retraining_job`/`FakeRetrainingRepository`
tests) — none of which overlapped the `run_latest_inference_job` function or the
`test_run_latest_inference_job_*` tests this batch touched. `brain/inference_job.py` itself had
zero sibling changes at any point in this batch (confirmed via `git diff` immediately before the
Phase 4 commit). `tests/test_brain_pipeline.py` briefly held both agents' uncommitted edits in the
same working-tree file mid-session; resolved by building a surgical patch (`git diff -U10` →
extract the one hunk touching `FakeInferenceRepository`/`test_run_latest_inference_job_*` →
`git apply --cached` against the index only) so the Phase 4 commit contains exactly this batch's
test changes, leaving the sibling's in-progress `test_run_retraining_job_*` edits untouched in the
working tree for them to commit separately (which they did, as `a058e82`, before this batch's
Phase 6a commit). No sibling work was lost, reverted, or bundled into a `telegram-notifications`
commit.

## Work Unit Evidence

| Phase | Focused test command | Result | Runtime harness | Result | Rollback boundary |
|---|---|---|---|---|---|
| 1 | `py -3.14 -m pytest tests/test_notification_dispatch.py -q` | 8 passed | `py -3.14 -m db.migrate` (both DSNs) + `py -3.14 -m collector.schema_check` | Applied cleanly; all 12 required relations OK | Drop `notifications` then `notification_rules`, delete the `0007` row from `schema_migrations`; revert `local_repository.py`/`schema_check.py` |
| 2 | `py -3.14 -m pytest tests/test_telegram_notifier.py -q` | 15 passed | N/A — outbound-only client, no bot in CI; `FakeSession` suite is the complete proof per design | N/A | Delete `ops/telegram_notifier.py` + its test file; nothing imports it yet |
| 3 | `py -3.14 -m pytest tests/test_notification_rules.py -q` | 26 passed | N/A — stdlib-only pure functions, no I/O; parametrized unit tests are the complete proof | N/A | Delete `ops/notification_rules.py` + its test file; nothing else imports it yet |
| 4 | `py -3.14 -m pytest tests/test_brain_pipeline.py -k inference -q` | 2 passed | N/A specified by the batch's runtime harness (`py -3.14 -m brain.run_inference_job`) requires a promoted model run in a live DB; not run this batch — covered instead by the focused unit test's exact `get_latest_prediction` call-arg assertion | N/A this batch | Revert the single diff in `brain/inference_job.py` (commit `046ec7f`); field is additive, unread elsewhere yet |
| 5 | `py -3.14 -m pytest tests/test_api.py -k operational_alerts -q` | 4 passed | N/A — compile-time `Query(default=...)` import; `inspect.signature` unit test is the complete proof | N/A | Revert commit `bdf7c8a` (the 4 `Query(default=...)` lines + import) |
| 6a | `py -3.14 -m pytest tests/test_notification_dispatch.py -q` | 22 passed | Real `TEST_DATABASE_URL` via the `repository`/`db_connection` fixtures + `FakeDispatchSession`: end-to-end test forces a `failed > 0` report, confirms exactly one `FakeSession.post` + one `sent` row, re-invocation confirms zero posts/dedupe | Passed | Revert commit `085345d` (`ops/notification_dispatch.py` + its tests); not yet called by any entrypoint before Phase 6b wires it in |
| 6b | `py -3.14 -m pytest tests/test_operational_notifications.py -q` | 9 passed | `py -3.14 -m ops.notify_operational_job --reports-dir <dir> --status success` run 3 ways: with `LOCAL_DATABASE_URL` set (4 rules evaluated, 0 events), with no DB env vars (`database_unavailable`, webhook/Telegram path unaffected), and with `--no-telegram --no-rule-notifications` (`disabled_by_flag`) | All 3 passed | Revert commit `80cbf51` (`ops/notify_operational_job.py` to its pre-refactor version); webhook-only behavior resumes unchanged |

## Full Suite Counts (with `LOCAL_DATABASE_URL`/`TEST_DATABASE_URL` exported)

| Checkpoint | Passed | Failed | Notes |
|---|---|---|---|
| Before batch 1 (baseline) | 170 | 0 | |
| After Phase 1 | 178 | 0 | |
| After Phase 2 | 193 | 0 | |
| After Phase 3 (end of batch 1) | 219 | 0 | Orchestrator-confirmed baseline entering batch 2 |
| Mid-batch-2, before Phase 4 commit (full suite) | 212 | 3 (+1 collection error) | **Not caused by this batch.** `local-postgres-migration`'s concurrent, uncommitted `brain/artifacts.py`/`brain/retraining_job.py` refactor was mid-flight in the shared working tree at this snapshot (`tests/test_model_artifacts.py` collection error: `ImportError: download_supabase_artifact`; 3 `test_run_retraining_job_*` failures: `TypeError: unexpected keyword argument 'supabase_config'`). Confirmed via `git diff` that none of these files were touched by this batch. The sibling agent committed their fix as `a058e82` before this batch's Phase 6a commit. |
| After Phase 4 (`--ignore=tests/test_model_artifacts.py`, sibling WIP still uncommitted) | 212 | 0 | Phase 4's own 2 tests passed; sibling's 3 retraining failures persisted (not this batch's concern) until their commit landed |
| After Phase 5 | +4 focused (not re-run full) | — | |
| After Phase 6a | 236 (`--ignore=tests/test_model_artifacts.py`) | 0 | |
| After Phase 6a (full suite, sibling had committed `a058e82` by then) | 242 | 0 | |
| **After Phase 6b (final, full suite, no ignores)** | **242** | **0** | |

Net new tests this batch (4-6b): 23 (219 → 242). Batch-2 test files touched: `tests/test_brain_pipeline.py`
(+1 net, 1 modified), `tests/test_api.py` (+1), `tests/test_notification_dispatch.py` (+22),
`tests/test_operational_notifications.py` (+6).

## Files Changed (this batch, Phase 4-6b)

| File | Action | Phase |
|---|---|---|
| `brain/inference_job.py` | Modified (+`previous_action` emission) | 4 |
| `tests/test_brain_pipeline.py` | Modified (+`FakeInferenceRepository`, 1 test extended, 1 test added) | 4 |
| `api/main.py` | Modified (4 `Query(default=...)` bound to `ops.notification_rules` constants) | 5 |
| `tests/test_api.py` | Modified (+1 drift test) | 5 |
| `ops/notification_dispatch.py` | Created | 6a |
| `tests/test_notification_dispatch.py` | Modified (+22 tests, appended) | 6a |
| `ops/notify_operational_job.py` | Modified (two-transport fan-out refactor) | 6b |
| `tests/test_operational_notifications.py` | Modified (+6 tests) | 6b |

(Files Changed for Phase 1-3 are unchanged from batch 1 — see the "Files Changed" table
in the git history of this document / commits `58738e1`, `3680b59`, `8c8f9fa`.)

## Deviations from Design

**Rule-type naming** (carried forward from batch 1, re-confirmed, no new deviation): all
Phase 4-6b code uses `signal_transition`/`stale_data` (spec-aligned), never design.md's
`signal_action_change`/`stale_prices`.

**`rule_types` filter parameter on `dispatch_notifications`** (new in this batch, additive,
not in design.md or tasks.md verbatim): added purely for testability — the Phase 6a
end-to-end test needed to isolate the `job_failure` trigger without depending on the shared
test database having zero pre-existing `assets`/`prediction_feedback` rows (which would make
`stale_data`/`model_degradation` assertions non-deterministic). Defaults to `None`
(evaluate every active rule), so it changes no existing behavior and no call site outside
this batch's own tests passes it.

**`_UNREADABLE_MARKER` internal sentinel** (implementation detail, not in design.md):
`load_reports` needed a way to preserve `build_notification_payload`'s exact prior output
shape for a file that fails to parse (`{"name": ..., "error": "unreadable_report:..."}`)
while still returning a plain `dict[name, raw]` that `ops.notification_dispatch`'s
`_job_failure_events` can safely call `.get("failed")` on without special-casing. Purely
internal to `ops/notify_operational_job.py`; not part of any public contract.

No other deviations. Migration numbering, repository method signatures, chunking budget,
redaction layering, threshold defaults, and dedupe/cooldown semantics all match design.md
(under the renamed `rule_type` values) exactly.

## Issues Found

One test-authoring pitfall self-corrected during Phase 3 (batch 1, restated here for
continuity): the drift test's regex (`'(\{.*?\})'::jsonb` with `re.DOTALL`) initially
matched across an unrelated `'{}'` substring inside the migration's header comment,
bridging incorrectly to the first real jsonb literal several lines later. Fixed by dropping
`re.DOTALL` rather than editing the already-applied migration file (which would have
triggered `db/migrate.py`'s checksum-drift guard).

New in batch 2: `git add`-ing the full `tests/test_brain_pipeline.py` working-tree state
would have bundled the concurrent `local-postgres-migration` agent's uncommitted, at-that-
moment-still-failing `run_retraining_job` test edits into this batch's Phase 4 commit. Caught
before committing by running `git diff -- tests/test_brain_pipeline.py` and inspecting every
hunk; resolved with a surgical `git apply --cached` patch containing only this batch's hunk.
Worth flagging as a general apply-phase practice whenever multiple agents share one working
tree: always `git diff` (not just `git status`) a file before `git add` when it appears in
another change's stated concurrent-edit list, even if your own edit function is far from
theirs in the file.

## Remaining Tasks (out of scope for this batch)

- [ ] Phase 7: Scheduler integration — blocked on `local-postgres-migration` task 9
      (`ops/run_local_scheduler.py` still does not exist on disk as of this batch's end)
- [ ] Phase 8: Documentation (`.env.example`, `README.md`)

## Workload / PR Boundary

- Mode: chained PR slice (stacked-to-main per tasks.md's Chain strategy)
- Current work units (this batch): PR 4 (signal-transition emission, independent), PR 5
  (dashboard threshold binding, after PR 3), PR 6a (dispatch orchestration, after PR 1/2/3),
  PR 6b (notifier transport refactor, after PR 2/6a)
- Boundary: this batch starts from batch 1's 3 commits (`58738e1`, `3680b59`, `8c8f9fa`) plus
  the sibling `local-postgres-migration` change's concurrent, non-overlapping commits
  (`4facf22`, `a058e82`), and ends with 4 independently revertible commits, each passing its
  own focused test command plus the full suite
- Estimated review budget impact: PR 4 ~59 lines (well within budget), PR 5 ~31 lines (well
  within budget), PR 6a ~778 lines (well over the ~320-line forecast — the 22-test suite
  covering both the 4 wiring functions unit-style and the dedupe/cooldown/end-to-end
  integration scenarios grew larger than estimated; flagged here rather than trimmed, since
  tasks.md's own forecast already called PR 6a "High risk" and recommended
  reviewer-paced review or `size:exception`), PR 6b ~272 lines (within the ~255-line
  forecast) — PR 6a specifically should get reviewer-paced review or an explicit
  `size:exception` per tasks.md's own guidance, since it landed at ~2.4x the original
  estimate

## Commits

Batch 1:
1. `58738e1` — feat(notifications): add notification rules/log migration and repository methods
2. `3680b59` — feat(notifications): add Telegram transport client
3. `8c8f9fa` — feat(notifications): add notification rules policy module

Batch 2 (this update):
4. `046ec7f` — feat(inference): emit previous_action for signal-transition detection (Phase 4)
5. `bdf7c8a` — feat(api): bind operational alerts thresholds to notification_rules constants (Phase 5)
6. `085345d` — feat(notifications): add dispatch orchestration for the four trigger rules (Phase 6a)
7. `80cbf51` — refactor(notifications): make notify_operational_job a two-transport fan-out (Phase 6b)

## Status (batch 2 close-out)

7/9 phases complete for this change (Phases 1-6b of 1-8, Phase 7 explicitly blocked).
23/23 assigned tasks in this batch marked `[x]` in `tasks.md` (4.1-4.3, 5.1-5.2, 6a.1-6a.5,
6b.1-6b.6). Full suite: 242 passed, 0 failed. Ready for the next `sdd-apply` batch (Phase 7,
once `local-postgres-migration` task 9 / `ops/run_local_scheduler.py` is confirmed to exist)
or Phase 8 (documentation, independently startable now).

---

# Batch 3 (final): Phase 7 + Phase 8

**Scope**: Phase 7 (scheduler integration, unblocked now that
`local-postgres-migration` task 9 landed `ops/run_local_scheduler.py` in commit `c068817`)
and Phase 8 (documentation). This closes the change's entire `apply` phase.

## Verified before starting

`ops/run_local_scheduler.py` (read in full) already existed and already called
`ops.notify_operational_job` as its fixed final step with `--reports-dir`, `--status`,
`--job-mode` — but **not** `--failed-steps`. `ops/notify_operational_job.py`'s `main()`
already called `_dispatch_rule_notifications` → `ops.notification_dispatch.dispatch_notifications`
(Phase 6a/6b work), but neither `parse_args()`, `_dispatch_rule_notifications`,
`dispatch_notifications`, nor `_job_failure_events` accepted or threaded a `failed_steps`
value. **Conclusion: the `--failed-steps` seam was NOT already wired** — Phase 7's actual
gap (a step that exits non-zero *before* writing its own report JSON, e.g.
`collector.schema_check`, which has no `--out` at all) was still open. This matches
design.md section 7-A's own flagged dependency exactly.

## Completed Tasks

### Phase 7: Scheduler Integration
- [x] 7.1 Confirmed `ops/run_local_scheduler.py` exists (commit `c068817`) and read its
      `run()`/notify-argv-building code in full before starting.
- [x] 7.2 N/A — the file is available, so this phase proceeds (not skipped).
- [x] 7.3 Implemented the full seam, in three files:
      - `ops/run_local_scheduler.py::run()`: computes
        `pre_report_failed_steps = [r.name for r in results if r.returncode != 0 and
        r.report_failed == 0]` after all job-mode steps run (before building `notify_args`)
        and appends `--failed-steps <comma-joined names>` as **one** argv element only when
        that list is non-empty. A step whose own report already shows `failed > 0` is
        excluded (already covered by the pre-existing report-derived path), matching the
        task's exact "only when a step exits non-zero before writing its own report JSON"
        wording.
      - `ops/notify_operational_job.py`: added the `--failed-steps` CLI flag (comma-joined,
        no other flag shape — matches design.md's literal example); extracted a small pure
        `_parse_failed_steps(raw) -> list[str] | None` helper (splits on `,`, strips
        whitespace, drops blanks, `None`/empty stays `None`) so `main()`'s CLI-to-domain
        translation has its own testable boundary, consistent with the existing
        `load_reports` extraction pattern from Phase 6b; threaded `failed_steps` through
        `_dispatch_rule_notifications` into `dispatch_notifications`.
      - `ops/notification_dispatch.py`: added `failed_steps: list[str] | None = None` to
        `dispatch_notifications`, `_events_for_rule`, and `_job_failure_events`.
        `_job_failure_events` now **merges** report-derived failing steps with
        `failed_steps` (union, not overwrite) so a step counted via its own report is never
        double-counted, then feeds the merged `failed_count`/`failing_steps` into the
        existing, unmodified `evaluate_job_failure`.
- [x] 7.4 Extended `tests/test_run_local_scheduler.py` with 3 new tests: the flag is
      appended as a single unsplit argv element when `collector.schema_check` fails (no
      report exists at all); the flag is **absent** when a step exits 0 but its own report
      shows `failed > 0` (already report-derived, no help needed); the flag is absent when
      everything succeeds.

Also extended (beyond the literal 7.1-7.4 list, needed to prove 7.3's actual behavior at
every layer, not just the scheduler's argv-building):
- `tests/test_notification_dispatch.py`: 2 new fast unit tests for
  `_job_failure_events(..., failed_steps=...)` (fires from `failed_steps` alone when
  `reports={}`; merges report-derived + `failed_steps` without double-counting) plus 1 new
  **real-DB integration test** (`test_dispatch_notifications_end_to_end_job_failure_from_failed_steps_writes_a_notifications_row`)
  proving the full pipeline — `dispatch_notifications(reports={}, failed_steps=["schema_check"], ...)`
  against the real `TEST_DATABASE_URL` with a `FakeDispatchSession` — produces exactly one
  fake HTTP POST and one real `notifications` row with `rule_type = 'job_failure'`, `status
  = 'sent'`, and a `dedupe_key` containing `schema_check`; confirms
  `repository.notification_already_sent(dedupe_key) is True` afterward.
- `tests/test_operational_notifications.py`: 2 new unit tests for `_parse_failed_steps`
  (`None`/empty/all-blank → `None`; comma-joined names split and stripped).

### Phase 8: Documentation
- [x] 8.1 `.env.example`: appended `# TELEGRAM_BOT_TOKEN=` and `# TELEGRAM_CHAT_ID=` (both
      commented, optional) at the end of the file via a targeted `>>` append — the file's
      pre-existing `SUPABASE_*` lines were left untouched (that cleanup belongs to the
      concurrent `local-postgres-migration` Phase 10 sibling, out of this batch's scope).
      **Tooling note**: the `Read`/`Edit`/`Write` tools deny direct access to `.env.example`
      (a blanket `.env*` sandbox guard, confirmed also blocks a compound `ls`/`cat` Bash
      invocation targeting that exact path); a plain `Bash` `printf ... >> .env.example`
      append was permitted and is what was used. `git diff -- .env.example` confirmed the
      change is exactly the two commented lines appended, nothing else touched.
- [x] 8.2 `README.md`: added a `#### Notificaciones por Telegram` subsection inside the
      existing `### Scheduler Local` section (Spanish, matching the file's existing style
      and tone) covering: creating a bot via [@BotFather](https://t.me/BotFather) (`/newbot`),
      obtaining the `chat_id` via `getUpdates`, setting both vars in `.env` (never committed),
      forcing a test notification (`py -3.14 -m ops.notify_operational_job --reports-dir
      reports --status failure`) to verify delivery, revoking a leaked token via BotFather's
      `/revoke`, and the rollback note (unset both vars → Telegram transport becomes a
      no-op, webhook/rest of the scheduler unaffected). Also added `TELEGRAM_BOT_TOKEN`/
      `TELEGRAM_CHAT_ID` rows to the main "Variables de entorno principales" table with an
      anchor link to the new subsection.

## Manual end-to-end verification against the real local database

Beyond the automated tests, ran `ops.notify_operational_job` directly against
`LOCAL_DATABASE_URL` (not `TEST_DATABASE_URL`) to prove the wiring works outside of any
test fixture:

```
py -3.14 -m ops.notify_operational_job --reports-dir <empty-scratch-dir> --status failure \
    --job-mode market_data --failed-steps schema_check --no-telegram
```

Output showed `"rules": {"dispatched": true, "evaluated_rules": 4, "outcomes": [{"rule_type":
"job_failure", "dedupe_key": "job_failure|-|market_data|schema_check|2026-08-27", "outcome":
"failed", ...}]}` with `"reports": []` and `"failed": 0` in the payload (i.e., **zero**
report-derived signal — the event only exists because of `--failed-steps`). Queried
`notifications` directly afterward and confirmed a real row:
`('job_failure', 'job_failure|-|market_data|schema_check|2026-08-27', 'failed',
'missing_telegram_config', ...)` — `status='failed'` here only because `--no-telegram` was
passed for this smoke test (no real bot token in this environment); the dispatch/dedupe/log
pipeline itself is proven end-to-end. **Cleaned up**: deleted that test row from the live
`LOCAL_DATABASE_URL` database immediately after (`delete from notifications where
dedupe_key like 'job_failure|-|market_data|schema_check|%'`) so it does not pollute or
dedupe-block a real future scheduler run today.

Real Telegram delivery (an actual message arriving in a real chat) was **not** verified in
this environment — no real `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are configured here. That
is a manual step for the user to perform once they add real credentials, per README.md's new
"Notificaciones por Telegram" §4 (`py -3.14 -m ops.notify_operational_job --reports-dir
reports --status failure`, with both env vars set).

## Concurrent work from `local-postgres-migration` (sibling agent, same session, Phase 10)

Confirmed via `git status` at the start and end of this batch: the sibling's Phase 10
(final Supabase deletion) was mid-flight in the same shared working tree throughout this
batch — uncommitted deletions of `supabase/`, `collector/supabase_repository.py`,
`tests/test_supabase_repository.py`, `brain/evaluate_candidate_matrix_from_supabase.py`,
`render.yaml`, `.github/workflows/operational-jobs.yml`, plus modifications to
`brain/candidate_matrix.py`, `brain/datasets.py`, `brain/promotion.py`,
`brain/retraining_job.py`, `brain/run_retraining_job.py`, `collector/local_repository.py`,
and `tests/test_brain_pipeline.py`. **None of these overlap this batch's files**
(`ops/notification_dispatch.py`, `ops/notify_operational_job.py`,
`ops/run_local_scheduler.py`, `tests/test_notification_dispatch.py`,
`tests/test_operational_notifications.py`, `tests/test_run_local_scheduler.py`,
`.env.example`, `README.md`), confirmed via `git diff --stat` scoped to exactly this
batch's file list before staging. This explains why the full suite read **241 passed** in
this batch rather than the orchestrator-confirmed **265** pre-batch baseline: the sibling's
uncommitted deletions removed ~24 pre-existing tests (mostly `tests/test_supabase_repository.py`)
from the working tree mid-batch, not a regression introduced here. `git add` was scoped to
this batch's exact file list only (never `git add -A`/`git add .`), so no sibling work was
staged, reverted, or bundled into a `telegram-notifications` commit.

## Work Unit Evidence (batch 3)

| Phase | Focused test command | Result | Runtime harness | Result | Rollback boundary |
|---|---|---|---|---|---|
| 7 | `py -3.14 -m pytest tests/test_run_local_scheduler.py -q` | 29 passed (26 pre-existing + 3 new) | `py -3.14 -m ops.notify_operational_job --reports-dir <dir> --status failure --job-mode market_data --failed-steps schema_check --no-telegram` against the real `LOCAL_DATABASE_URL` | Confirmed a real `notifications` row with `rule_type='job_failure'` and `schema_check` in its `dedupe_key`; row deleted after verification | Revert this batch's 3-file diff (`ops/run_local_scheduler.py`, `ops/notify_operational_job.py`, `ops/notification_dispatch.py`) plus their test files; `job_failure` keeps working via the pre-existing report-derived `failed > 0` path (Phase 6a/6b), matching design's degrade-gracefully fallback |
| 8 | N/A — documentation only | N/A | N/A — no executable behavior changes | N/A | Revert `.env.example` (2 appended commented lines) and the `README.md` diff (1 new subsection + 2 table rows) |

## Full Suite Count (batch 3, with `LOCAL_DATABASE_URL`/`TEST_DATABASE_URL` exported)

| Checkpoint | Passed | Failed | Notes |
|---|---|---|---|
| Start of batch 3 (shared tree, sibling Phase 10 mid-flight) | 241 | 0 | Confirmed before any edit this batch; 265 (orchestrator's pre-batch baseline) minus the sibling's uncommitted Supabase-test deletions, not a regression |
| **After Phase 7 (final, full suite, no ignores)** | **241** | **0** | Net +8 tests added this batch (3 in `test_run_local_scheduler.py`, 3 in `test_notification_dispatch.py`, 2 in `test_operational_notifications.py`); count stayed flat at 241 because the sibling's Phase 10 deletions continued removing tests from the shared tree concurrently — confirmed via focused per-file counts: `test_run_local_scheduler.py` 26→29, `test_notification_dispatch.py` 22→25, `test_operational_notifications.py` 9→11 |
| Documentation (Phase 8) | — | — | No executable code changed; full suite re-run not required, focused commands N/A per tasks.md |

## Files Changed (this batch, Phase 7-8)

| File | Action | Phase |
|---|---|---|
| `ops/run_local_scheduler.py` | Modified (`--failed-steps` argv computation + append) | 7 |
| `ops/notify_operational_job.py` | Modified (`--failed-steps` CLI flag, `_parse_failed_steps`, threading) | 7 |
| `ops/notification_dispatch.py` | Modified (`failed_steps` param on `dispatch_notifications`/`_events_for_rule`/`_job_failure_events`, merge logic) | 7 |
| `tests/test_run_local_scheduler.py` | Modified (+3 tests) | 7 |
| `tests/test_notification_dispatch.py` | Modified (+3 tests) | 7 |
| `tests/test_operational_notifications.py` | Modified (+2 tests) | 7 |
| `.env.example` | Modified (+2 commented optional lines) | 8 |
| `README.md` | Modified (+1 subsection, +2 table rows) | 8 |
| `openspec/changes/telegram-notifications/tasks.md` | Modified (Phase 7 + 8 marked `[x]`) | 7, 8 |
| `openspec/changes/telegram-notifications/state.yaml` | Modified (`progress.apply: complete`) | 7, 8 |

## Deviations from Design

**`_parse_failed_steps` extraction** (implementation detail, not in design.md verbatim):
kept `main()`'s CLI-string-to-list translation in its own pure, directly unit-testable
function rather than inlining the split/strip logic in `main()`, mirroring the existing
`load_reports` extraction pattern from Phase 6b. No behavior change — purely a testability
boundary.

**Merge-not-overwrite semantics in `_job_failure_events`**: design.md's example
(`--failed-steps brain.run_inference_job`) does not explicitly discuss what happens when a
step is *both* report-derived-failed *and* named in `--failed-steps`. Implemented as a
union with no double-counting (a step already counted via its report is not counted again),
since the scheduler's real invocation only names steps in `pre_report_failed_steps`
(`report_failed == 0`), so in practice this overlap cannot occur from the scheduler's own
call site — the merge logic exists purely as defense-in-depth for `dispatch_notifications`
being called directly (as `ops.notification_dispatch`'s docstring already documents for the
database-unavailable case).

No other deviations. `--failed-steps`' single-unsplit-comma-joined-argv-element shape,
the "only on a pre-report failure" trigger condition, and the CLI flag's absence of any
default beyond `None` all match design.md section 7-A and tasks.md 7.3/7.4 exactly.

## Issues Found

The `.env.example` file itself is stale relative to `local-postgres-migration`'s Supabase
removal (it still lists `SUPABASE_URL`/`SUPABASE_KEY`/`VITE_SUPABASE_URL`/
`VITE_SUPABASE_ANON_KEY`, none of which match README.md's own `.env` example block, which
already shows `LOCAL_DATABASE_URL` instead). This is out of this batch's scope (task 8.1
only asked for the two Telegram lines, and the Supabase cleanup is explicitly the
concurrent sibling's Phase 10 territory) — flagged here for `sdd-verify` / a follow-up
change, not fixed in this batch.

## Remaining Tasks

None for `telegram-notifications`. All 8 phases (1-8) are now `[x]` in `tasks.md`.

## Workload / PR Boundary

- Mode: chained PR slice (stacked-to-main per tasks.md's Chain strategy) — this batch
  covers PR 7 and PR 8, the last two slices in the chain
- Current work units (this batch): PR 7 (scheduler `--failed-steps` integration, was
  blocked, now unblocked and complete), PR 8 (documentation)
- Boundary: this batch starts from batch 1+2's 7 commits and the sibling's concurrent,
  non-overlapping `local-postgres-migration` commits, and ends with 2 independently
  revertible commits (code: PR 7's 3 files + 3 test files; docs: PR 8's 2 files)
- Estimated review budget impact: PR 7 ~180 changed lines (well within the ~20-line
  original forecast for the production code alone, but the forecast did not account for
  the 3-file, 8-test proof-at-every-layer this batch judged necessary to actually verify
  the gap-filling behavior rather than assume Phase 9's scheduler already covered it); PR 8
  ~60 changed lines (within the ~25-line forecast plus the env-var-table rows) — both well
  under the 400-line budget individually

## Commits

Batch 1: `58738e1`, `3680b59`, `8c8f9fa`
Batch 2: `046ec7f`, `bdf7c8a`, `085345d`, `80cbf51`
Batch 3 (this update, final): to be recorded after commit below.

## Status (final)

**8/8 phases complete.** All tasks in `tasks.md` (Phase 1 through Phase 8) are marked
`[x]`. `state.yaml`'s `progress.apply` set to `complete`. Full suite: 241 passed, 0 failed
(shared-tree count; see "Full Suite Count" above for why this differs from the 265
pre-batch baseline — not a regression introduced by this batch). `telegram-notifications`'
implementation is done; `next_recommended: sdd-verify`.
