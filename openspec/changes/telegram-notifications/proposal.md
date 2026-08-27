# Proposal: Telegram Notifications

## Intent

Every operational outcome is pull-only: a report JSON, a log file, or the dashboard.
`ops/notify_operational_job.py` can POST a summary to one generic webhook, but nothing routes
per-event. Once the scheduler runs unattended on a local machine, a failed collector run or a
fresh BUY signal is invisible until the operator looks. This adds a push channel the operator
already carries, plus a persisted rule/delivery model so alerting is auditable, not ad hoc.

## Scope

### In Scope

- `ops/telegram_notifier.py` — outbound-only thin `requests` client: `POST /sendMessage`,
  `parse_mode=HTML`, chunking, pacing, 429 backoff, injectable session.
- Generalize `ops/notify_operational_job.py` into transport dispatch (generic webhook +
  Telegram) reusing `build_notification_payload` / `summarize_report`.
- `db/migrations/0007_notifications.sql`: `notification_rules` (rule_type, nullable
  asset_id, params jsonb, channel, is_active, cooldown_minutes) + `notifications`
  delivery log with a unique `dedupe_key`; repository methods for both.
- Rule evaluation + wiring for the P0/P1 triggers below into `ops/run_local_scheduler.py`,
  `brain/inference_job.py`, `brain/feedback_report.py`.

### Out of Scope

- **Inbound commands** (`/signals`, `/portfolio`) and any `getUpdates` polling loop.
- Multi-user / multi-chat routing, per-recipient preferences, quiet hours.
- Rich formatting: charts, images, inline keyboards, message editing.
- Triggers owned by sibling changes (insider cluster, 13F consensus) and P2/P3 triggers.

## Trigger set for this change

| P | Trigger | Source | Cadence |
|---|---|---|---|
| P0 | Job failure / `failed > 0` | `ops/run_local_scheduler.py` | per run |
| P0 | BUY/SELL crossing the confidence threshold | `brain/inference_job.py` | daily |
| P1 | Model degradation below accuracy / return floor | `brain/feedback_report.py` | daily |
| P1 | Stale data — no new price row for N days | freshness check | daily |

**Cut, deliberately:** insider cluster buy (needs change #4 data), model promotion, 13F
consensus, price thresholds, weekly digest. Four triggers exercise every mechanism
(scheduler, inference, feedback, freshness) with data that exists today. `rule_type` +
`params jsonb` is an open registry, so each deferred trigger is later code-only — no DDL.

## Alert fatigue is the primary design constraint

A channel that cries wolf gets muted, and a muted channel loses the **P0 job-failure**
alerts too. Volume control is therefore a correctness requirement, not polish:

- **No notification on every HOLD, every price tick, or any steady state.** Only
  transitions and threshold crossings emit.
- **Per-rule `cooldown_minutes`**: a persistent condition fires once, not once per run.
- **`dedupe_key`** derived deterministically from rule + asset + trigger bucket, enforced by
  a unique constraint, so a re-run or retry of the same job cannot re-send.
- Delivery is logged with its outcome; a send failure never fails the calling job.

## Transport constraints

~1 msg/sec per chat (serialize with a minimum inter-send interval); 4096 characters per
message, chunked on line boundaries with HTML entities balanced per chunk and formatting
counted conservatively; HTTP 429 honors `parameters.retry_after` with bounded retries, then
records a failed delivery instead of raising.

## Secret handling

`TELEGRAM_BOT_TOKEN` grants full control of the bot. It lives only in `.env` (gitignored),
**never** in `notification_rules`, `notifications`, or any `reports/*.json`. The token sits
in the request **path** (`/bot{TOKEN}/sendMessage`), so any log line, exception, or
`response.url` echo leaks it by default — every error path must redact it. The existing
generic-webhook transport posts payloads to a third-party URL and MUST NOT carry Telegram
credentials in that payload.

## Capabilities

### New Capabilities

- `operational-notifications`: rule-driven outbound alerting — trigger catalog, cooldown and
  dedupe semantics, delivery logging, transport limits, and credential handling.

### Modified Capabilities

- `local-persistence`: migration `0007` and the `LocalPostgresRepository` method contract
  extend with notification rules and the delivery log.

## Approach

Telegram is a **transport**, not a second notifier. `notify_operational_job` keeps owning
payload construction; the transport renders it to HTML and dispatches. Missing
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` returns `{"sent": False, "reason": "missing_telegram_config"}`,
matching today's `missing_webhook_url` no-op, so an unconfigured install behaves as now. The
injectable-session signature keeps the existing `FakeSession` test pattern.

**Migration number:** `0007` is free — `db/migrations/` holds only `0001`–`0004` and the only
live reservation is `0005_shared_ingestion.sql` in `financial-intelligence-expansion`. Because
this change ships first, `0005`/`0006` will not yet exist; `db/migrate.py` applies *pending*
files lexicographically, so the gap is tolerated and later-arriving `0005`/`0006` still apply.
Accepted rather than renumbering to `0005`.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `ops/telegram_notifier.py` | New | Client: HTML, chunking, pacing, 429 backoff, redaction |
| `ops/notify_operational_job.py` | Modified | Transport dispatch; shared payload builders |
| `db/migrations/0007_notifications.sql` | New | `notification_rules`, `notifications` |
| `collector/local_repository.py` | Modified | Rule reads; dedupe-aware delivery writes |
| `ops/run_local_scheduler.py` | Modified | P0 failure dispatch |
| `brain/inference_job.py`, `brain/feedback_report.py` | Modified | Emit trigger events |
| `.env.example`, `README.md` | Modified | Two new optional variables |
| `tests/` | New | Chunking, 429, redaction, dedupe, unconfigured no-op |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Alert fatigue** mutes the channel, losing P0 alerts | High | Cooldown + dedupe + no steady-state alerts, specified not conventional |
| **Token leaked** into a log, report, or webhook payload | Med | Redaction on every error path; a dedicated test; BotFather `/revoke` if it happens |
| Notification failure or Telegram outage breaks the calling job | Med | Best-effort send; bounded retry, outcome logged, exception never propagates |
| Thresholds wrong at launch (too loud or silent) | Med | Thresholds live in `params jsonb`, tunable without a deploy |
| Dedupe key too coarse — a real second event suppressed | Low | Key includes the trigger bucket, not just rule + asset |

## Rollback Plan

1. **Disable without a deploy**: unset `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`, or set
   `notification_rules.is_active = false`. The path reverts to the existing no-op.
2. **Revert the code**: additive change; reverting restores webhook-only behavior. No job's
   control flow depends on a notification result.
3. **Revert the schema**: `0007` is additive and unreferenced — drop `notifications` then
   `notification_rules`, delete the `0007` row from `schema_migrations`. `pg_dump` first.
4. **Credential compromise**: BotFather `/revoke` invalidates the token immediately,
   independent of code rollback.

Not reversible: delivered messages cannot be unsent and reside on Telegram's servers. Keep
alert bodies to tickers, actions, and counts.

## Dependencies

- **`local-postgres-migration` must land first** — supplies `db/migrations/`,
  `db/migrate.py`, `LocalPostgresRepository`, and `ops/run_local_scheduler.py`.
- A BotFather bot token and the operator's numeric chat id, obtained manually.

## Success Criteria

- [ ] `py -3.14 -m db.migrate` applies `0007` on a clean database; `collector.schema_check` passes.
- [ ] With no Telegram variables set, every job behaves identically to today.
- [ ] A forced `failed > 0` scheduler run delivers exactly one message.
- [ ] A re-run sends nothing (dedupe); a condition persisting across runs sends nothing
      within its cooldown.
- [ ] A >4096-character payload arrives as ordered chunks, valid HTML in each; a simulated
      429 is retried per `retry_after` and never crashes the caller.
- [ ] No log, report, or webhook payload contains the bot token; a redaction test asserts it.
