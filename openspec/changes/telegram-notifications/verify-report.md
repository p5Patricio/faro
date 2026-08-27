# Verify Report: Telegram Notifications

**Change**: telegram-notifications
**Mode**: openspec (full artifact set - proposal, specs, design, tasks, apply-progress all present)
**Verified**: 2026-08-26
**Verdict**: FAIL - 1 CRITICAL (narrow, low-risk), 3 WARNING, 1 SUGGESTION

## Completeness

All 8 phases / 40 sub-tasks in tasks.md are marked [x]. Cross-checked against
apply-progress.md's 3 batches (commits 58738e1 through 80cbf51 for batch 1-2, plus the
batch-3 Phase 7/8 work) and the actual working tree. No unchecked task found.

| Phase | Tasks | State |
|---|---|---|
| 1 Foundation (migration+repo) | 1.1-1.7 | done, code present, tests pass |
| 2 Telegram client | 2.1-2.6 | done, code present, tests pass |
| 3 Rules and policy | 3.1-3.5 | done, code present, tests pass |
| 4 Signal-transition emission | 4.1-4.3 | done, code present, tests pass |
| 5 Dashboard threshold binding | 5.1-5.2 | done, code present, tests pass |
| 6a Dispatch orchestration | 6a.1-6a.5 | done, code present, tests pass |
| 6b Notifier transport refactor | 6b.1-6b.6 | done, code present, tests pass |
| 7 Scheduler integration | 7.1-7.4 | done, code present, tests pass |
| 8 Documentation | 8.1-8.2 | done, present (see Warning 3) |

## Test Execution (real run, this session)

Command run (password never written to any file, exported inline for the session only):

    export LOCAL_DATABASE_URL='postgresql://postgres:***@localhost:5432/ia_inversiones'
    export TEST_DATABASE_URL='postgresql://postgres:***@localhost:5432/ia_inversiones_test'
    py -3.14 -m pytest -q

Result: 241 passed, 0 failed, 1 pre-existing unrelated warning (joblib core-count), 60.84s.
Matches apply-progress.md's own final count exactly. Also re-ran the notification-specific
and touched files in isolation (test_telegram_notifier.py, test_notification_rules.py,
test_notification_dispatch.py, test_operational_notifications.py,
test_run_local_scheduler.py, test_brain_pipeline.py, test_api.py): 170 passed, 0 failed.

Additional runtime evidence gathered independently this session (not just re-reading
apply-progress's claims):

- `py -3.14 -m db.migrate --dry-run` against LOCAL_DATABASE_URL -> "No pending migrations."
  (0007 already applied, no checksum drift).
- `py -3.14 -m db.migrate --dry-run` against TEST_DATABASE_URL -> "No pending migrations."
- `py -3.14 -m collector.schema_check` against LOCAL_DATABASE_URL -> all 12 required relations
  OK, including notification_rules and notifications.

## Redaction: independently triggered failure path (not just trusting the test)

Wrote and ran a standalone throwaway script (not committed, not saved anywhere) that
constructs a TelegramConfig with a realistic-looking fake token, injects a session.post
that raises requests.exceptions.ConnectionError with the full request URL - including the
token - embedded in the exception message (the exact leak vector the spec's "Bot Token Is
Redacted From Every Surface" requirement targets), and calls
ops.telegram_notifier.send_telegram_message for real. Result:

    RESULT: {'sent': False, 'reason': 'telegram_request_failed',
             'detail': 'Failed to establish a new connection to
                        https://api.telegram.org/bot***/sendMessage: [Errno 11001] getaddrinfo failed'}
    TOKEN IN SERIALIZED RESULT? False
    TOKEN IN DETAIL FIELD? False
    REDACTION MARKER PRESENT? True
    error_reason for notifications.error_reason column (mirrors
        ops/notification_dispatch.py's _process_event exactly):
        'Failed to establish a new connection to
        https://api.telegram.org/bot***/sendMessage: [Errno 11001] getaddrinfo failed'
    TOKEN IN error_reason (what would be persisted to DB)? False

Read redact()'s implementation directly (ops/telegram_notifier.py lines 58-64): exact
str.replace(token, "***") first, then a re.sub(r"bot\d+:[\w-]+", "bot***", ...) structural
fallback. Confirmed every except/error branch in send_telegram_message (429-exhausted, 5xx,
4xx, RequestException) routes its `detail` through redact(..., config.bot_token) before
returning, and _process_event in ops/notification_dispatch.py never touches the raw
result["detail"] before it becomes notifications.error_reason - it passes the
already-redacted string straight through. The token genuinely never reaches the returned
dict, and the exact string that would be persisted to notifications.error_reason is
confirmed clean. This requirement is fully satisfied, verified independently of the
existing test suite (which also covers this correctly -
tests/test_telegram_notifier.py::test_http_error_containing_token_in_url_never_leaks_token_in_result
asserts the same contract via json.dumps(result) plus "***" in result["detail"]).

## Cooldown vs. dedupe: confirmed genuinely separate mechanisms

Read ops/notification_dispatch.py::_process_event directly (lines 138-196). Two distinct,
sequential checks, matching design.md section 5:

1. Dedupe (line 150): repository.notification_already_sent(event.dedupe_key) - a database
   read against the partial unique index notifications_dedupe_sent_key
   (dedupe_key) WHERE status='sent'. Runs unconditionally, first.
2. Cooldown (lines 153-163): only entered `if cooldown_minutes:` (skipped entirely when 0),
   calls repository.get_last_notification_fired_at(rule_type, asset_id, scope_key) - a
   different query, scoped by (rule_type, asset_id, scope_key) with no bucket component -
   then compares (now - last_fired_at) < timedelta(minutes=cooldown_minutes) in Python.

These are not collapsed: dedupe is a DB-enforced uniqueness check on the full dedupe_key
(scope+bucket); cooldown is a Python-side time-window comparison on scope alone,
independently configurable per rule (cooldown_minutes), backed by a separate SQL query
(notifications_cooldown_idx). Confirmed via a real-DB test
(test_process_event_zero_cooldown_always_proceeds_past_the_cooldown_check) that a prior
sent row with the same scope but a different dedupe_key does not block a
cooldown_minutes=0 rule (dedupe alone gates P0), and via
test_process_event_cooldown_suppresses_and_is_never_persisted that a non-zero-cooldown
rule correctly suppresses a scope-colliding, bucket-distinct event within its window.

## Signal-transition semantics: confirmed by reading the evaluator, not just test names

ops/notification_rules.py::evaluate_signal_transition (lines 160-189):

    if previous_action == predicted_action:
        return None
    if predicted_action not in actions:
        return None

- BUY to BUY: previous_action == predicted_action is True -> returns None -> silent. Confirmed.
- HOLD to BUY: "HOLD" != "BUY" and "BUY" is in ("BUY","SELL") -> an event is built and
  returned -> notifies. Confirmed.
- BUY to HOLD (not explicitly asked, checked anyway): differs, but "HOLD" not in actions ->
  None -> silent. Consistent with "P0 rule fires only for BUY/SELL", not a bug.
- previous_action=None (first-ever prediction) + HOLD -> None; + BUY -> fires. Confirmed via
  brain/inference_job.py reading get_latest_prediction *before* generate_latest_prediction
  upserts (lines 81-82), so a genuinely first-ever prediction has no row to read back and
  previous_action is None by construction - verified by reading the call order directly,
  not inferring it from the design doc.

## Naming deviation: confirmed consistently applied (not a partial rename)

`grep -rn "signal_action_change|stale_prices" --include=*.py` returns hits only in
api/main.py and tests/test_api.py, and inspection shows this is build_operational_alerts'
pre-existing dashboard alert `code` field ("stale_prices" as an alert-classification string
for /api/alerts/{ticker}, introduced in commit 04bdb32, long before this change, and
untouched by this change's own commit bdf7c8a) - an unrelated naming domain, not the
notification rule_type value. Every genuine rule_type reference -
db/migrations/0007_notifications.sql's seed rows, ops/notification_rules.py's
SEEDED_RULE_PARAMS/evaluators/dedupe-key recipes, and ops/notification_dispatch.py's
_events_for_rule dispatch table - uses signal_transition / stale_data uniformly.
No partial rename found.

## Migration numbering: confirmed by reading db/migrate.py directly, not trusting the claim

db/migrate.py:
- discover_migrations() (lines 66-68): sorted(migrations_dir.glob("*.sql"), key=lambda
  path: path.name) - pure lexicographic filename sort, no numeric-sequence assumption.
- pending_migrations() (lines 94-95): [m for m in migrations if m.name not in applied] -
  keyed by filename against schema_migrations.version, not by a sequence check.
- apply_migrations() applies every element of `pending` in that lexicographic order inside
  its own transaction, with a checksum recorded per filename, and raises
  migration_checksum_mismatch only if an already-applied file's bytes changed.

There is no gap-detection or contiguity requirement anywhere in this file. 0007 applying
while 0005/0006 are absent, and 0005/0006 applying later without re-applying 0007, is
exactly what this logic does. financial-intelligence-expansion (the sibling reserving 0005)
is confirmed still at exploration/proposal stage only - no design.md/tasks.md, and its
migration file does not exist on disk. tests/test_migrate.py's
test_discover_migrations_orders_lexicographically and
test_pending_migrations_excludes_applied_versions independently cover this runner behavior
and pass. Confirmed true, not just asserted.

## Spec Compliance Matrix: operational-notifications (12 requirements, 20 scenarios)

| Requirement | Scenario(s) | Status | Evidence |
|---|---|---|---|
| Four-Trigger Rule Catalog Ships Active | Fresh install alerts w/o config | PASS | migration seed (4 rows, is_active=true); schema_check OK; get_active_notification_rules tests |
| P0 Alerts Deliver Immediately | Job failure alerts w/o delay | PASS | cooldown_minutes=0 seeded for both P0 rules; end-to-end dispatch test, same-run send |
| Signal Alerts Fire Only on Action Transition | Unchanged -> no notify; Changed -> notify | PASS | evaluate_signal_transition read directly (above); parametrized tests |
| Per-Rule Cooldown Suppression | Persistent condition -> no resend within window | PASS | real-DB test, fired_at UPDATEd to 30 min ago, cooldown 1440 |
| Per-Rule Cooldown Suppression | Cooldown expiry re-arms the rule | UNTESTED (CRITICAL, see Issues) | no covering test found |
| Deterministic Dedupe Prevents Duplicate Delivery | Re-run doesn't resend | PASS | notifications_dedupe_sent_key partial unique index; real-DB round-trip test |
| Degradation Thresholds Share One Default Source | Seeded==dashboard defaults; override doesn't move default | PASS | drift test parses SQL literals == SEEDED_RULE_PARAMS; test_api.py inspects Query defaults via inspect.signature |
| Every Delivery Attempt Is Logged | Success logged; failure logged, caller unaffected | PASS | insert_notification called both branches of _process_event; tests for both |
| Long Messages Are Chunked, Not Truncated or Rejected | Oversized -> ordered chunks | PASS | chunk_message read directly; hard-split test for 5000-char line |
| Rate Limiting Is Honored With Bounded Retry | 429 -> backoff -> success; retries exhausted -> failure not crash | PASS | code read directly; tests assert exact post call counts |
| Missing Telegram Configuration Is a Silent No-Op | Unconfigured -> no-op, job unaffected | PASS | config is None short-circuit before any HTTP call, read directly |
| The Bot Token Is Redacted From Every Surface | Exception never leaks token | PASS | independently triggered this session (see above) + existing test |
| Best-Effort Delivery Never Fails the Calling Job | Outage doesn't fail job | PASS | dispatch_notifications/_process_event/send_telegram_message all catch-and-return, never raise; tests confirm |

## Spec Compliance Matrix: local-persistence delta (2 requirements, 5 scenarios)

| Requirement | Scenario(s) | Status | Evidence |
|---|---|---|---|
| Notification Rule and Delivery Log Persistence | Fresh DB seeds 4 active rules | PASS | schema_check + seed-read tests |
| Notification Rule and Delivery Log Persistence | Duplicate dedupe_key rejected at DB level | PASS-with-note | notifications_dedupe_sent_key (partial, WHERE status='sent') - see SUGGESTION below |
| Notification Rule and Delivery Log Persistence | Rule reads scoped by type/asset | PASS | get_active_notification_rules real-DB test |
| Migration Runner Tolerates Non-Contiguous Numbering | Later lower-numbered migration still applies | PASS | db/migrate.py read directly (above) + tests/test_migrate.py |

Note on the "PASS-with-note" row: the spec scenario's literal wording ("a second insert...
same dedupe_key... THEN the unique constraint prevents a duplicate row") doesn't mention
delivery status. The actual constraint is a partial unique index scoped to status='sent',
so two failed rows with the same dedupe_key are both allowed to exist - a deliberate,
well-justified design choice (design.md section 3: a plain unique(dedupe_key) would let one
failed attempt permanently block retrying that same alert, silently swallowing a P0
forever). This is the correct engineering choice for the stated goal ("prevent
double-delivery", not "prevent double-attempt"), and is exactly what
tests/test_notification_dispatch.py proves (two failed inserts same key -> both rows, then
a sent with that key succeeds). See SUGGESTION section below.

## Issues

### CRITICAL

1. Untested scenario: "Cooldown expiry re-arms the rule." The spec's own scenario (GIVEN
   the cooldown window from the last model_degradation alert has elapsed and the condition
   still holds, WHEN the rule is evaluated again, THEN a new notification is dispatched)
   has no covering test. ops/notification_dispatch.py::_process_event's cooldown check is:

       if last_fired_at is not None:
           ...
           if (now - last_fired_at) < timedelta(minutes=cooldown_minutes):
               return {..., "outcome": "cooldown"}
       # falls through to send when the condition above is False

   Every existing cooldown test either (a) has no prior sent row at all
   (last_fired_at is None, a different branch), (b) sets cooldown_minutes=0 (skips the
   whole `if` block, a different branch), or (c) sets a prior sent row within the window
   (the True branch, correctly proven suppressed). No test sets a prior sent row further in
   the past than cooldown_minutes and asserts the outcome is "sent" - the specific
   False-comparison branch that re-arms the rule is never exercised. I read the code
   directly and the logic is a straightforward, almost certainly correct boolean
   comparison (both operands are independently tested elsewhere:
   get_last_notification_fired_at's SQL read is tested, and timedelta comparison is
   standard library), so this is a low-risk gap in practice - but per the verify skill's
   hard rule ("a spec scenario is compliant only when a covering test passed at runtime"),
   it is not yet proven and must be reported as such rather than assumed correct.

   Fix: add one real-DB test in tests/test_notification_dispatch.py mirroring
   test_get_last_notification_fired_at_sees_sent_row_within_cooldown's
   "UPDATE notifications SET fired_at = %s" pattern, but with a timestamp older than
   cooldown_minutes, calling _process_event (not just the repository method) and
   asserting outcome == "sent". Small, isolated, no design change needed.

### WARNING

2. Dependency's own verify has not run. openspec/changes/local-postgres-migration/state.yaml
   shows progress.apply: complete but progress.verify: pending - no verify-report.md exists
   for that change yet. Functionally this does not block telegram-notifications: this
   session independently re-confirmed that the migration runner, LocalPostgresRepository,
   ops/run_local_scheduler.py, and the full local Postgres schema all work correctly
   (schema check, dry-run migrate, and the full 241-test suite all pass against the real
   local/test databases). But per SDD pipeline discipline, a dependency's own quality gate
   should also run. Recommend running sdd-verify for local-postgres-migration before or
   shortly after archiving this change.

3. min_confidence: 0.55 in the seeded signal_transition.params is dead configuration.
   SEEDED_RULE_PARAMS["signal_transition"] and the migration's jsonb literal both carry
   min_confidence, and a drift test asserts the two stay equal - but no code ever reads
   this key. ops/notification_dispatch.py::_signal_transition_events only reads
   params["actions"]; ops/notification_rules.py::evaluate_signal_transition's confidence
   parameter is used only for the message's display text, never compared against a
   threshold. An operator editing notification_rules.params.min_confidence via psql (which
   the design explicitly promises is possible - "params jsonb still overrides at runtime")
   will find it has zero effect on whether a notification fires. This is not a spec
   violation (the Signal Alerts Fire Only on Action Transition requirement only mandates
   transition detection, not confidence gating), but it is a real, silent gap between the
   seeded configuration's apparent intent and actual behavior. Recommend either wiring
   min_confidence into evaluate_signal_transition/_signal_transition_events, or dropping it
   from SEEDED_RULE_PARAMS and the migration seed so it stops implying a control that does
   not exist.

4. .env.example still lists stale SUPABASE_URL/SUPABASE_KEY/VITE_SUPABASE_URL/
   VITE_SUPABASE_ANON_KEY even after this change appended the two commented Telegram lines.
   Confirmed via `git show HEAD:.env.example`. Already self-flagged as an out-of-scope risk
   in this change's own apply-progress.md (batch 3, "Issues Found") - the Supabase cleanup
   belongs to local-postgres-migration's Phase 10, which removed all other Supabase
   code/config but did not touch .env.example's stale lines either (both agents hit the
   harness's .env* write-deny guard). Still true today; purely cosmetic (the app already
   runs on LOCAL_DATABASE_URL per README.md), but confusing for a new developer. Recommend
   a small follow-up task in either change to delete the four stale lines.

### SUGGESTION

5. Tighten the local-persistence spec's "Duplicate dedupe_key is rejected at the database
   level" scenario wording to specify status='sent', matching the actual (correct) partial
   -index implementation - see the compliance matrix note above.

## Design Coherence

| Design decision | Code state | Match |
|---|---|---|
| rule_type naming signal_action_change/stale_prices (design.md) vs. spec's signal_transition/stale_data | Code consistently uses spec's names everywhere in the notification pipeline | Deviation, already flagged and accepted by apply-progress across 3 batches; confirmed consistent, not partial |
| Dedupe-first-then-cooldown order | _process_event checks dedupe (line 150) before cooldown (line 153) | Match |
| Cooldown-suppressed events never persisted | Confirmed: the "cooldown" return happens before any insert_notification call | Match |
| _UNREADABLE_MARKER internal sentinel (not in design.md) | Present in ops/notify_operational_job.py's load_reports, internal only | Additive, no spec impact |
| rule_types filter param on dispatch_notifications (not in design.md/tasks.md) | Present, defaults to None (no behavior change) | Additive, test-only convenience, no spec impact |
| --failed-steps merge-not-overwrite semantics (design.md ambiguous on this) | _job_failure_events unions report-derived + explicit failed steps, no double-count | Reasonable, documented, no spec impact |

## Full Suite Counts (this session, real evidence)

| Command | Result |
|---|---|
| py -3.14 -m pytest -q (full suite) | 241 passed, 0 failed, 60.84s |
| py -3.14 -m pytest -q (7 notification/touched files) | 170 passed, 0 failed |
| py -3.14 -m db.migrate --dry-run (LOCAL_DATABASE_URL) | No pending migrations |
| py -3.14 -m db.migrate --dry-run (TEST_DATABASE_URL) | No pending migrations |
| py -3.14 -m collector.schema_check (LOCAL_DATABASE_URL) | 12/12 relations OK |

## Final Verdict

FAIL - one CRITICAL finding (untested "cooldown expiry re-arms" scenario branch) blocks a
clean pass under the verify skill's hard rule that a spec scenario is compliant only when a
covering test passed at runtime. This is narrow and low-risk (the underlying comparison
logic was read directly and is correct), and does not indicate a broader implementation
problem - 19 of 20 spec scenarios across both delta specs are fully covered and passing,
the full 241-test suite passes, redaction was independently re-verified by forcing a real
failure path, and no partial naming rename or migration-ordering defect was found.
Recommend a minimal follow-up (sdd-apply, one new test in
tests/test_notification_dispatch.py) before archiving, plus addressing the 3 WARNING items
opportunistically.

state.yaml's progress.verify is left as `pending` (not set to `complete`) pending that fix.

## Remediation (sdd-apply, post-verify batch)

Addressed after this verify pass, before re-verify:

- **CRITICAL #1** (untested "cooldown expiry re-arms the rule" scenario): added
  `test_process_event_cooldown_elapsed_proceeds_to_send` to `tests/test_notification_dispatch.py`,
  mirroring `test_get_last_notification_fired_at_sees_sent_row_within_cooldown`'s
  `UPDATE notifications SET fired_at = %s` pattern but with a timestamp (2 hours ago) older than
  the rule's `cooldown_minutes` (60). Calls `_process_event` directly (not just the repository
  method) and asserts `outcome == "sent"` with exactly one `session.post` call. Passes in
  isolation and as part of the full suite.
- **WARNING #3** (dead `min_confidence: 0.55` seed field): investigated but **not removed**.
  `SEEDED_RULE_PARAMS["signal_transition"]` in `ops/notification_rules.py` and the jsonb literal
  in `db/migrations/0007_notifications.sql` both carry `min_confidence`, and
  `tests/test_notification_rules.py::test_seeded_rule_params_match_migration_jsonb_literals_in_order`
  intentionally asserts they stay equal (a deliberate drift guard, not incidental duplication).
  This is not a case of "Python-side constant, nothing in SQL" — it lives in both, by design.
  Editing `db/migrations/0007_notifications.sql` in place is explicitly forbidden (it is
  already applied against both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL`, tracked by
  `db/migrate.py`'s checksum guard — any byte change trips `migration_checksum_mismatch` the
  next time `tests/conftest.py`'s session fixture runs `apply_migrations`). Removing
  `min_confidence` from only the Python side would break the drift test; removing it from only
  the SQL side is the forbidden edit. **Decision**: leave both as-is. This is accepted as a
  harmless, unread configuration key — not worth a new migration file (e.g. `0008_...sql`)
  solely to drop one dead key from an already-correct, already-tested seed row. If
  `min_confidence` gating is ever wanted for real, wire it into
  `evaluate_signal_transition`/`_signal_transition_events` in a future change instead of
  removing it.
- **WARNING #4** (`.env.example` stale Supabase vars): resolved directly by the orchestrator as
  part of the shared `local-postgres-migration` remediation (see that change's verify-report.md
  Remediation section) — confirmed via `git diff -- .env.example`.
- **WARNING #2** (dependency's own verify not yet run): `local-postgres-migration`'s
  `verify-report.md` exists and has its own remediation section in this same batch; re-running
  `sdd-verify` for both changes is the recommended next step for both, not something this apply
  batch can self-certify.

Full suite re-run after these fixes: `py -3.14 -m pytest -q` → **243 passed** (241 baseline + 1
new test from this batch; the sibling change local-postgres-migration's own new test accounts for
the remaining +1 of the combined +2 across both changes this batch closed).

`state.yaml`'s `progress.verify` is intentionally left untouched by this apply batch — re-running
`sdd-verify` is required to confirm these fixes and flip it to `complete`.
