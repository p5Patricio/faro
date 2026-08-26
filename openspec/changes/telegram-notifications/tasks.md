# Tasks: Telegram Notifications

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,650-1,850 total (additions + deletions) across 8 work units / 15 files |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 → PR 4 → PR 5 → PR 6a → PR 6b → PR 7 (blocked) → PR 8 |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

Units 2 and 6a stay near or slightly over 400 lines even after splitting by concern
(client + its FakeSession test suite; orchestration + its DB-integration test suite are
one behavioral contract each). Recommend reviewer-paced review or `size:exception` for
those two specifically if a strict cut is required. PR 4 (signal-transition emission) and
PR 2 (Telegram client) have no dependency on each other or on PR 1/3 completing first and
may be developed in parallel; PR 7 is explicitly blocked on `local-postgres-migration`
task 9 (`ops/run_local_scheduler.py`) and degrades to report-derived `failed > 0`
detection until that lands.

### Suggested Work Units

| # | Goal | PR | Est. lines | Risk | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|---|---|
| 1 | `db/migrations/0007_notifications.sql` (both tables, partial unique indexes, 4 seeded active rules) + 5 new `LocalPostgresRepository` methods + `collector/schema_check.py` relations + SQL-injection RED test + repo-level dedupe/cooldown integration tests | PR 1 | ~345 | Medium | `py -3.14 -m pytest tests/test_notification_dispatch.py` | `py -3.14 -m db.migrate` against `TEST_DATABASE_URL`, then `py -3.14 -m collector.schema_check` | Drop `notifications` then `notification_rules`, delete the `0007` row from `schema_migrations`; revert `local_repository.py`/`schema_check.py` |
| 2 | `ops/telegram_notifier.py` (HTML escape, chunking, pacing, 429 backoff, token redaction) + `tests/test_telegram_notifier.py` | PR 2 | ~420 | Medium-High | `py -3.14 -m pytest tests/test_telegram_notifier.py` | N/A — outbound-only client, no bot in CI; correctness proven by the `FakeSession` suite itself. Optional operator smoke: run `send_telegram_message` against a real bot token/chat once, manually | Delete `ops/telegram_notifier.py` + its test file; nothing imports it yet |
| 3 | `ops/notification_rules.py` (canonical thresholds, 4 pure evaluators, `dedupe_key` recipes) + `tests/test_notification_rules.py`, incl. the drift test parsing `db/migrations/0007_notifications.sql` | PR 3 (after PR 1) | ~380 | Medium | `py -3.14 -m pytest tests/test_notification_rules.py` | N/A — stdlib-only pure functions, no I/O; parametrized unit tests are the complete proof | Delete `ops/notification_rules.py` + its test file; nothing else imports it yet |
| 4 | `brain/inference_job.py` emits `previous_action` per prediction (resolve `asset_id` via `get_asset_id`, read `get_latest_prediction` before `generate_latest_prediction`) | PR 4 (independent) | ~35 | Low | `py -3.14 -m pytest tests/test_brain_pipeline.py -k inference` | `py -3.14 -m brain.run_inference_job --model-name <promoted-model> --limit 1`, inspect `reports/inference_job.json` for `previous_action` | Revert the single diff in `brain/inference_job.py`; field is additive, unread elsewhere yet |
| 5 | `api/main.py`: 4 `Query(default=...)` values in `get_operational_alerts` import from `ops.notification_rules` constants | PR 5 (after PR 3) | ~15 | Low | `py -3.14 -m pytest tests/test_api.py -k operational_alerts` | `uvicorn api.main:app` + `curl "http://localhost:8000/api/alerts/AAPL"`, confirm defaults unchanged | Revert the 4 `Query(default=...)` lines to their prior literals |
| 6a | `ops/notification_dispatch.py` orchestration: dedupe-first-then-cooldown loop over the 4 rule types, wiring repository + `notification_rules` + `telegram_notifier` | PR 6a (after PR 1, 2, 3) | ~320 | High | `py -3.14 -m pytest tests/test_notification_dispatch.py` | Real `TEST_DATABASE_URL` + `FakeSession`: force a `job_failure`/`stale_prices` row, confirm exactly one send + one `sent` row; re-run confirms silence | Delete `ops/notification_dispatch.py`; not yet called by any entrypoint |
| 6b | `ops/notify_operational_job.py` transport refactor: `load_reports` extraction, `send_telegram_notification`, `dispatch_notification` fan-out, rules-dispatch wiring into `ops.notification_dispatch`, `--no-telegram`/`--no-rule-notifications` flags + credential-boundary and third-party-payload-egress RED tests + `tests/test_operational_notifications.py` updates | PR 6b (after PR 2, 6a) | ~255 | Medium-High | `py -3.14 -m pytest tests/test_operational_notifications.py` | `py -3.14 -m ops.notify_operational_job --reports-dir reports` with no env vars (byte-for-byte no-op check), then with `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` set against a real test bot/chat | Revert `ops/notify_operational_job.py` to its pre-refactor version; webhook-only behavior resumes unchanged |
| 7 | `ops/run_local_scheduler.py`: append `--failed-steps <comma-joined step names>` to the notifier's fixed argv on a pre-report step failure — **BLOCKED, flagged** | PR 7 (blocked on `local-postgres-migration` task 9) | ~20 | Low | `py -3.14 -m pytest tests/test_run_local_scheduler.py -k failed_steps` (extends that suite once task 9 exists) | `py -3.14 -m ops.run_local_scheduler --job market_data --tickers AAPL` with a forced step failure; confirm `--failed-steps` reaches the notifier's argv | Drop the one argv element; `job_failure` keeps working via report-derived `failed > 0` fallback |
| 8 | `.env.example` + `README.md`: `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` setup (BotFather, chat-id lookup, `/revoke`) | PR 8 | ~25 | Low | N/A — documentation only | N/A — no executable behavior changes | Revert the two doc files |

## Phase 1: Foundation — Migration + Repository (Req: Notification Rule and Delivery Log Persistence; Migration Runner Tolerates Non-Contiguous Numbering; Four-Trigger Rule Catalog Ships Active)

- [x] 1.1 **RED**: write a failing test in `tests/test_notification_dispatch.py` asserting a `rule_type`/`ticker`/error value containing `'; drop table notifications; --` round-trips as literal data via `insert_notification` and leaves `notifications`/`notification_rules` intact (threat matrix: SQL injection).
- [x] 1.2 Write `db/migrations/0007_notifications.sql`: `notification_rules` + `notifications` tables, `notification_rules_scoped_key`/`notification_rules_global_key`/`notification_rules_active_idx` partial indexes, `notifications_dedupe_sent_key`/`notifications_cooldown_idx` partial indexes (both `where status = 'sent'`), and the 4 seeded `insert into notification_rules ... on conflict do nothing` rows.
- [x] 1.3 `collector/local_repository.py`: add a `# -- Notifications ---` section before `# -- Schema introspection --` (line ~847) with `get_active_notification_rules(rule_type=None, channel=None)`, `notification_already_sent(dedupe_key)`, `get_last_notification_fired_at(rule_type, asset_id=None, scope_key="")`, `insert_notification(...)` with `ON CONFLICT (dedupe_key) WHERE status = 'sent' DO NOTHING RETURNING *`, and `get_latest_price_timestamps()`.
- [x] 1.4 `collector/schema_check.py`: add `notification_rules` and `notifications` to `REQUIRED_ML_RELATIONS`.
- [x] 1.5 `tests/test_notification_dispatch.py`: seeded-rules read via `get_active_notification_rules()`; two `sent` inserts same key → second returns `None`, one row; two `failed` inserts same key → both rows, then a `sent` with that key succeeds; `get_last_notification_fired_at` returns `None` when only `failed` rows exist; cooldown comparison at the SQL level (`sent` row at `now - 30min`, `cooldown_minutes=1440` still visible via `max(fired_at)`).
- [x] 1.6 Confirm the SQL-injection RED test from 1.1 now passes.
- [x] 1.7 Run `py -3.14 -m db.migrate` against `TEST_DATABASE_URL`, then `py -3.14 -m collector.schema_check` — both pass on a fresh DB.

## Phase 2: Telegram Notifier Client (Req: Long Messages Are Chunked, Not Truncated or Rejected; Rate Limiting Is Honored With Bounded Retry; Missing Telegram Configuration Is a Silent No-Op; The Bot Token Is Redacted From Every Surface; Best-Effort Delivery Never Fails the Calling Job)

- [ ] 2.1 **RED**: write a failing test asserting a rendered message containing `<`, `>`, `&` in an interpolated ticker/reason value is not passed through unescaped to `session.post` (threat matrix: untrusted text in HTML).
- [ ] 2.2 **RED**: write a failing test asserting a `FakeSession.post` raising `HTTPError(f"...for url: .../bot{TOKEN}/sendMessage")` never leaks `TOKEN` in the returned dict (threat matrix: credential in the URL path).
- [ ] 2.3 Create `ops/telegram_notifier.py`: `TelegramConfig` (frozen dataclass, `from_env()` returns `None` when either var is absent/blank), `escape_html`, `redact` (exact `str.replace` + `re.sub(r"bot\d+:[\w-]+", ...)` fallback), `chunk_message` (line-boundary split at `CHUNK_BUDGET_CHARS=3800`, hard-split an over-budget single line), `render_operational_message`, `send_telegram_message` (injectable `session`/`sleep`, 429 → `retry_after` bounded at `MAX_RETRIES`, 5xx fixed 2s retry, other 4xx no retry, never raises).
- [ ] 2.4 `tests/test_telegram_notifier.py`: escaping order (`&` first); chunk order + reassembly + a single 5000-char line hard-split; injected `sleep` sees `>=1.0` gap between two chunks and zero for one chunk; 429 + `retry_after: 2` then 200 → `sent`, `post` called twice; 4×429 → `telegram_rate_limited`, never raises, exactly `MAX_RETRIES+1` posts; `from_env()` with both vars unset → `None` → `missing_telegram_config`.
- [ ] 2.5 Redaction test: second case (a 400 body echoing `response.url`); third case, the persisted `error_reason`-shaped string for that failure contains no token.
- [ ] 2.6 Confirm both RED tests from 2.1/2.2 now pass.

## Phase 3: Notification Rules & Policy (Req: Four-Trigger Rule Catalog Ships Active; Signal Alerts Fire Only on Action Transition; Per-Rule Cooldown Suppression; Deterministic Dedupe Prevents Duplicate Delivery; Degradation Thresholds Share One Default Source)

- [ ] 3.1 Create `ops/notification_rules.py` (stdlib only): `DEFAULT_MAX_PRICE_AGE_HOURS=72.0`, `DEFAULT_MIN_FEEDBACK_SAMPLES=20`, `DEFAULT_MIN_ACCURACY=0.45`, `DEFAULT_MIN_MEAN_OUTCOME_RETURN=0.0`, `SEEDED_RULE_PARAMS`.
- [ ] 3.2 Implement the 4 `dedupe_key` recipes from design §4 (`job_failure`, `signal_transition`, `model_degradation`, `stale_prices`) — `|`-joined, UTC dates, ticker uppercased, `rule_type` lowercased.
- [ ] 3.3 Implement the 4 pure evaluator functions (no I/O): job-failure-from-report, signal-transition (compare `previous_action`/`predicted_action`, `None` fires only BUY/SELL), model-degradation (below `min_accuracy` → `low_accuracy`; below `min_mean_outcome_return` → `negative_edge`; below `min_feedback_samples` → no event), staleness (bucket on last observed price date, `none` when zero prices).
- [ ] 3.4 `tests/test_notification_rules.py`: parametrized dedupe-key recipe tests; staleness key unchanged when `now` advances a week, changes only when `last_price_date` changes; HOLD→HOLD → no event, BUY→SELL → one, `previous_action=None`+HOLD → none, +BUY → one; degradation below `min_accuracy` → `low_accuracy`; `evaluated < min_feedback_samples` → none.
- [ ] 3.5 Drift test: `json.loads` every `'{...}'::jsonb` literal parsed in order out of `db/migrations/0007_notifications.sql`, assert equality with `SEEDED_RULE_PARAMS`.

## Phase 4: Signal-Transition Emission (Req: Signal Alerts Fire Only on Action Transition)

- [ ] 4.1 `brain/inference_job.py`, inside `run_latest_inference_job`, immediately before the `generate_latest_prediction` call (~line 76): resolve `asset_id = repository.get_asset_id(ticker)`, call `previous = repository.get_latest_prediction(asset_id, model_name=model_run["model_name"])`.
- [ ] 4.2 Add `"previous_action": previous.get("predicted_action") if previous else None` to the `results.append({...})` entry (~line 90).
- [ ] 4.3 `tests/test_brain_pipeline.py`: extend `test_run_latest_inference_job_records_success_and_errors` (or add a sibling test) asserting `previous_action` is present and reflects the prior stored prediction; a first-ever prediction yields `previous_action=None`.

## Phase 5: Dashboard Threshold Binding (Req: Degradation Thresholds Share One Default Source)

- [ ] 5.1 `api/main.py`, `get_operational_alerts`: replace the 4 literal `Query(default=...)` values (`max_price_age_hours`, `min_feedback_samples`, `min_accuracy`, `min_mean_outcome_return`) with references to the matching `ops.notification_rules` constants.
- [ ] 5.2 `tests/test_api.py`: assert the endpoint's effective defaults equal `ops.notification_rules`'s constants (compile-time reference, no drift possible).

## Phase 6a: Dispatch Orchestration (Req: P0 Alerts Deliver Immediately; Per-Rule Cooldown Suppression; Deterministic Dedupe Prevents Duplicate Delivery; Every Delivery Attempt Is Logged; Best-Effort Delivery Never Fails the Calling Job)

- [ ] 6a.1 Create `ops/notification_dispatch.py`: iterate `repository.get_active_notification_rules(channel="telegram")`, evaluate each rule via `ops.notification_rules`, dedupe-first (`notification_already_sent`) then cooldown (`get_last_notification_fired_at` vs `cooldown_minutes`), send via `send_telegram_message`, log via `insert_notification` with `status="sent"|"failed"` and a redacted `error_reason`; suppressed-by-cooldown events are reported in the return value only, never inserted.
- [ ] 6a.2 Wire the `stale_prices` evaluator to `repository.get_latest_price_timestamps()`, fanning a global rule (`asset_id IS NULL`) out to every asset.
- [ ] 6a.3 Wire the `model_degradation` evaluator to `repository.get_prediction_feedback(only_evaluated=True)` grouped by `model_name`, calling `brain.feedback.analyze_prediction_feedback` per group.
- [ ] 6a.4 Wire the `signal_transition` evaluator to the loaded `reports/inference_job.json` results (via the shared `load_reports` from Phase 6b once it exists — stub the report input for this unit's own tests).
- [ ] 6a.5 `tests/test_notification_dispatch.py`: two `model_degradation` events with different `scope_key` do not suppress each other; a global and a scoped rule of the same `rule_type` do not suppress each other; cooldown 0 (both P0 rules) always proceeds past the cooldown check; end-to-end — a forced `failed > 0`-shaped input produces exactly one `FakeSession.post` and one `sent` row, re-invocation produces zero posts and still one row.

## Phase 6b: Notifier Transport Refactor (Req: Missing Telegram Configuration Is a Silent No-Op; The Bot Token Is Redacted From Every Surface; Best-Effort Delivery Never Fails the Calling Job)

- [ ] 6b.1 **RED**: write a failing test asserting that with `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` set, the JSON body posted to the generic webhook contains neither the token nor the chat id (threat matrix: third-party payload egress).
- [ ] 6b.2 Extract `load_reports(dir) -> dict[name, raw]` out of the existing inline glob in `ops/notify_operational_job.py`, shared with `ops/notification_dispatch.py`.
- [ ] 6b.3 Add `send_telegram_notification(payload, config, *, session, sleep)` (renders via `render_operational_message`, delegates to `send_telegram_message`) and `dispatch_notification(payload, *, webhook_url, telegram_config, session, sleep)` (calls each transport independently, one failing transport never suppresses the other).
- [ ] 6b.4 Wire `main()` to also invoke `ops.notification_dispatch`'s rule engine (DB connection inside a `try`; on failure record `{"dispatched": False, "reason": "database_unavailable"}` without blocking the webhook/Telegram summary path); result shape becomes `{"notification": {"webhook": {...}, "telegram": {...}, "rules": {...}}, "payload": ...}`.
- [ ] 6b.5 Add `--no-telegram` and `--no-rule-notifications` CLI flags. No `--telegram-bot-token` flag — config comes only from `TelegramConfig.from_env()`.
- [ ] 6b.6 `tests/test_operational_notifications.py`: confirm the 3 existing tests pass verbatim (proof the refactor is additive); both transports unconfigured → two no-ops, nothing raised; webhook `post` raising → Telegram still attempted; confirm the credential-boundary RED test from 6b.1 now passes.

## Phase 7: Scheduler Integration — BLOCKED (Req: P0 Alerts Deliver Immediately)

- [ ] 7.1 **Prerequisite check**: confirm `ops/run_local_scheduler.py` exists (`local-postgres-migration` task 9) and inspect its final-step argv before starting this phase.
- [ ] 7.2 If unavailable, skip this phase — `job_failure` already fires from report-derived `failed > 0` (Phase 6a/6b), matching design's degrade-gracefully fallback. Do not block PR 1-6b/8 on this phase.
- [ ] 7.3 If available, append `--failed-steps <comma-joined step names>` to the scheduler's existing fixed `ops.notify_operational_job` argv only when a step exits non-zero before writing its own report JSON.
- [ ] 7.4 Extend `tests/test_run_local_scheduler.py` to assert the flag is appended only on a pre-report failure and is a single unsplit argv element.

## Phase 8: Documentation

- [ ] 8.1 `.env.example`: add `TELEGRAM_BOT_TOKEN=` and `TELEGRAM_CHAT_ID=` as optional, commented.
- [ ] 8.2 `README.md`: BotFather bot creation, chat-id lookup, `/revoke` on suspected compromise, and the "unset both vars to disable" rollback note.

## Key Learnings

1. `run_latest_inference_job` in `brain/inference_job.py` already calls `generate_latest_prediction`, which internally resolves `asset_id` via `repository.get_asset_id(ticker)` — the signal-transition wiring only needs one extra read before that call, not a new lookup path.
2. `ops/run_local_scheduler.py` does not exist on disk yet, confirming design's flagged dependency on `local-postgres-migration` task 9; the job-failure trigger's degrade-to-report-derived-`failed>0` fallback is the only path this change can rely on today.
3. `collector/local_repository.py`'s existing `conditions`/`params`/`where_clause` idiom (used by `get_model_runs`, `get_prediction_feedback`, `get_latest_prediction`) is the pattern the new `get_active_notification_rules` method must copy for consistency.
4. Splitting design's third slice (`ops/notification_rules.py` + `ops/notification_dispatch.py` + notifier refactor + wiring + tests, ~600+ lines) into Phases 3, 6a, and 6b keeps each unit closer to the 400-line budget without breaking any single unit's independent testability.
5. Four threat-matrix rows are real for this change (credential-in-URL-path, third-party-payload-egress, SQL injection, untrusted-text-in-HTML) and each now has a dedicated RED-test task preceding its production task, per the skill's threat-matrix rule.
