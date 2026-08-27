# Archive Report: Telegram Notifications
**Date**: 2026-08-26
**Change**: telegram-notifications
**Status**: ARCHIVED AND CLOSED

## Final State Summary

All work for this change is complete, verified, and closed. Outbound Telegram alerting
(long-polling architecture, thin `requests` transport) is fully implemented, tested, and
wired into the local scheduler's failure-detection path.

## Specs Merged

### New Capability: operational-notifications
- **File**: `openspec/specs/operational-notifications/spec.md` (created)
- **Status**: All 12 requirements implemented and verified PASS
- **Naming note**: rule types shipped as `signal_transition`/`stale_data`, matching this
  spec's own wording — not design.md's original working titles
  (`signal_action_change`/`stale_prices`). The spec is the acceptance-criteria authority;
  the implementation is consistent with it end-to-end, confirmed by both verify passes.

### Modified Capability: local-persistence
- **File**: `openspec/specs/local-persistence/spec.md` (merged, ADDED-only delta)
- **Changes**: ADDED the `notification_rules`/`notifications` schema and the five
  `LocalPostgresRepository` methods (active-rule lookup, last-fired check, delivery
  insert) this change introduced. No existing requirement in the base spec (established
  by the sibling `local-postgres-migration`, archived immediately before this change) was
  modified — this delta only adds.

## Verification Status

**Final Verdict**: PASS (re-verified 2026-08-26, the sole CRITICAL finding closed)

### Test Suite
- **Final count**: 243 passed, 0 failed
- **Independent re-verification**: executed against the live local Postgres instance,
  including a real forced `ConnectionError` through `send_telegram_message` to confirm
  token redaction, and a real dispatch-pipeline run producing an actual `notifications`
  row (deleted afterward to avoid polluting the live database)
- **Baseline**: 241 passed (before the shared remediation batch); this change's own slice
  of the +2 net-new tests is the cooldown-expiry-re-arm test

### Critical Finding Remediation

1. **Untested "cooldown expiry re-arms the rule" spec scenario**
   - **Fix**: added `test_process_event_cooldown_elapsed_proceeds_to_send` to
     `tests/test_notification_dispatch.py` — a real-DB test inserting a prior notification
     row whose `sent_at` predates the rule's `cooldown_minutes` window, then asserting the
     next dispatch cycle proceeds to send rather than being suppressed.
   - **Verified**: read the test in full on re-verify; confirmed it exercises the genuinely
     distinct fourth branch (non-zero cooldown, prior row exists, window elapsed) rather
     than duplicating one of the three already-covered branches. Ran
     `py -3.14 -m pytest tests/test_notification_dispatch.py -k cooldown -v` → 4 passed.

### Warning Items (Non-blocking, Resolved or Accepted)

**Dead `min_confidence: 0.55` seed field** — ACCEPTED AS-IS
- `ops/notification_rules.py`'s seeded `signal_transition` params include a
  `min_confidence` value nothing reads.
- Removing it from the Python side would break `test_notification_rules.py`'s intentional
  drift test (asserts Python constants match the migration's seeded jsonb literals).
  Removing it from `db/migrations/0007_notifications.sql` is not possible without a new
  migration, since `db/migrate.py`'s checksum guard rejects edits to an already-applied
  file.
- Decision: leave as a harmless, documented, unread configuration key rather than spend a
  new migration on one dead field.

**`.env.example` stale Supabase vars** — RESOLVED
- Fixed as part of the shared remediation batch (same fix covers both this change and the
  sibling `local-postgres-migration`). `git show HEAD:.env.example` confirms `TELEGRAM_*`
  vars present, no Supabase references remain.

**`local-postgres-migration`'s own verify was pending at the time of this change's first
verify pass** — RESOLVED
- The sibling change's re-verify completed and passed independently; both changes archive
  in dependency order (`local-postgres-migration` first, this change second) with no
  remaining gap.

## Phase Completion

All 8 phases marked `[x]` complete in `tasks.md`:

- **Phase 1**: `0007_notifications.sql` migration + 5 repository methods, SQL-injection RED test
- **Phase 2**: `ops/telegram_notifier.py` transport client (HTML escaping, chunking, 429
  backoff, verified token redaction)
- **Phase 3**: `ops/notification_rules.py` policy module (shared threshold defaults,
  dedupe-key recipes, drift test against `api/main.py`)
- **Phase 4**: `brain/inference_job.py` signal-transition emission
- **Phase 5**: `api/main.py` threshold binding to the shared constants
- **Phase 6a**: `ops/notification_dispatch.py` orchestration (rule lookup, evaluation,
  cooldown, dedupe, send, log)
- **Phase 6b**: `ops/notify_operational_job.py` two-transport refactor (webhook + Telegram),
  payload-egress RED test confirming the token never reaches the generic webhook payload
- **Phase 7**: scheduler integration — wired `job_failure` through
  `ops/run_local_scheduler.py`'s `--failed-steps` seam once the sibling change's scheduler
  landed
- **Phase 8**: README/`.env.example` documentation for Telegram setup

## Artifacts Archived

Change folder moved from `openspec/changes/telegram-notifications/` to
`openspec/changes/archive/2026-08-26-telegram-notifications/` containing:

- ✅ proposal.md
- ✅ specs/ (operational-notifications new spec, local-persistence ADDED delta)
- ✅ design.md
- ✅ tasks.md (all 8 phases complete)
- ✅ apply-progress.md (3 batches documented)
- ✅ verify-report.md (remediation and re-verification)
- ✅ state.yaml (progress.apply = complete, progress.verify = complete)

## Dependency on Sibling Change

Depended on `local-postgres-migration` for `db/migrations/`, `LocalPostgresRepository`,
and `ops/run_local_scheduler.py`. That change archived immediately before this one, so its
`local-persistence` main spec already existed as the base this change's delta merges into.

## Key Learnings

1. A dispatch pipeline's cooldown check can have more logical branches than obvious test
   names suggest — confirming each branch is genuinely distinct (not a re-test of an
   already-covered one) requires reading the assertion and setup, not just the test name.
2. Forcing a real transport-layer exception (rather than trusting a mocked assertion) is
   the only way to prove a credential-redaction guarantee actually holds across every code
   path that might echo it.
3. A dead configuration value intentionally duplicated across an applied migration and a
   Python constant to satisfy a drift test can be a correct, accepted state — not every
   "unread field" warning needs a fix.
4. Archiving two changes that share a capability (`local-persistence`) requires strict
   dependency ordering: the change that creates the base spec must archive first, or the
   second change's delta has nothing to merge into.

## Archive Complete

This change is fully archived and closed. All work is complete, verified, and ready for
reference. No further work is required on this change.

---

**Archived by**: orchestrator (reconstructing a report the archive sub-agent claimed to
write but which was not found on disk — content matches the sub-agent's own reported
final-state facts, independently cross-checked against `verify-report.md`)
**Archive date**: 2026-08-26
**Change folder**: `openspec/changes/archive/2026-08-26-telegram-notifications/`
**Main specs updated**: `openspec/specs/operational-notifications/spec.md` (created),
`openspec/specs/local-persistence/spec.md` (merged)
