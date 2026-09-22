# Operational Notifications Specification

## Purpose

Rule-driven outbound alerting for the local operational scheduler. Persisted
rules and a delivery log turn "run a job, hope someone looks" into an
auditable push channel, while cooldown/dedupe/transition semantics prevent
alert fatigue from muting the channel that also carries P0 failures.

## Requirements

### Requirement: Four-Trigger Rule Catalog Ships Active

The system MUST support exactly four `rule_type` values at launch: P0
`job_failure`, P0 `signal_transition`, P1 `model_degradation`, P1
`stale_data`. The system MUST seed all four as `is_active = true` on a fresh
install so alerting works without manual SQL. Additional rule types MUST be
addable later via `rule_type` + `params jsonb` alone, with no schema change.

#### Scenario: Fresh install alerts without manual configuration

- GIVEN a database that has just applied the notifications migration
- WHEN the scheduler, inference job, or feedback report next runs
- THEN all four default rules are evaluated because each is already active

### Requirement: P0 Alerts Deliver Immediately

P0 alerts (`job_failure`, `signal_transition`) MUST be dispatched as soon as
the triggering condition is detected, with no quiet hours and no batching
with other events.

#### Scenario: Job failure alerts without delay

- GIVEN a scheduler run reports `failed > 0`
- WHEN the run completes
- THEN a P0 notification is dispatched in that same run, not deferred or
  bundled into a later digest

### Requirement: Signal Alerts Fire Only on Action Transition

The `signal_transition` rule MUST compare the current run's predicted action
for an asset against that asset's previous run's action. It MUST notify only
when the two differ, and MUST NOT notify when the action is unchanged
(including repeated HOLD or repeated BUY/SELL).

#### Scenario: Unchanged action does not notify

- GIVEN the previous run's action for TICKER was BUY
- WHEN the current run's action for TICKER is also BUY
- THEN no notification is dispatched

#### Scenario: Changed action notifies

- GIVEN the previous run's action for TICKER was HOLD
- WHEN the current run's action for TICKER is BUY
- THEN a P0 notification is dispatched describing the transition

### Requirement: Per-Rule Cooldown Suppression

Each rule MUST carry a `cooldown_minutes` value. P1 condition-style rules
(`model_degradation`, `stale_data`) default to `1440`. P0 rules default to a
short/zero cooldown because each triggering run is a distinct event, not a
persisted condition. A rule MUST NOT notify again for the same scope before
its cooldown elapses.

#### Scenario: Persistent degradation notifies once per cooldown window

- GIVEN `model_degradation` fired for an asset and its cooldown has not
  elapsed
- WHEN the same degraded condition is evaluated on a later run within the
  window
- THEN no new notification is dispatched

#### Scenario: Cooldown expiry re-arms the rule

- GIVEN the cooldown window from the last `model_degradation` alert has
  elapsed and the condition still holds
- WHEN the rule is evaluated again
- THEN a new notification is dispatched

### Requirement: Deterministic Dedupe Prevents Duplicate Delivery

Every notification MUST derive a deterministic `dedupe_key` from rule,
asset scope, and trigger bucket, enforced by a unique constraint. The same
logical alert MUST NOT be delivered twice even if the triggering job is
re-run or retried.

#### Scenario: Re-run of the same job does not resend

- GIVEN a notification for a given rule/asset/trigger bucket already exists
- WHEN the producing job is re-run or retried with the same trigger bucket
- THEN no second delivery is attempted for that `dedupe_key`

### Requirement: Degradation Thresholds Share One Default Source

The default values for `min_accuracy`, `min_mean_outcome_return`, and
`max_price_age_hours` MUST originate from exactly one shared source consumed
both by the dashboard's operational-alerts endpoint and by the seeded
`model_degradation`/`stale_data` rule `params`, so the dashboard's and the
notifier's definitions of "degraded" cannot drift apart. Each rule's
`params` MUST remain independently tunable per rule after seeding, without a
deploy.

#### Scenario: Seeded thresholds match dashboard defaults

- GIVEN the shared threshold source and the migration seed both exist
- WHEN the `model_degradation` rule's seeded `params` are compared to the
  dashboard alert endpoint's defaults
- THEN the numeric values are identical

#### Scenario: Overriding one rule does not move the shared default

- GIVEN an operator updates `notification_rules.params` for one asset's
  `model_degradation` rule
- WHEN the dashboard alert endpoint is queried with no override
- THEN it still uses the unchanged shared default threshold

### Requirement: Every Delivery Attempt Is Logged

Every notification attempt MUST be recorded in the delivery log with its
outcome (sent/failed) and, on failure, an error value. A send failure MUST
NOT raise out of the calling job.

#### Scenario: Successful delivery is logged

- GIVEN a notification is dispatched and Telegram accepts it
- WHEN the send completes
- THEN a log row records status sent and the dispatch time

#### Scenario: Failed delivery is logged without crashing the caller

- GIVEN Telegram is unreachable or returns a non-retryable error
- WHEN the send is attempted and exhausts its retry budget
- THEN a log row records status failed with a redacted error
- AND the calling job continues to completion

### Requirement: Long Messages Are Chunked, Not Truncated or Rejected

A message body exceeding 4096 characters MUST be split into ordered chunks
at line boundaries, each chunk with balanced HTML entities and counted
conservatively against the limit. No content MUST be dropped or truncated.

#### Scenario: Oversized payload arrives as ordered chunks

- GIVEN a rendered alert body exceeds 4096 characters
- WHEN it is sent
- THEN it is delivered as multiple ordered messages, each valid HTML, whose
  combined content matches the original body

### Requirement: Rate Limiting Is Honored With Bounded Retry

The transport MUST serialize sends with a minimum inter-send interval (~1
msg/sec per chat). On HTTP 429, it MUST honor `parameters.retry_after` and
retry a bounded number of times before recording a failed delivery instead
of raising.

#### Scenario: 429 triggers backoff then succeeds

- GIVEN Telegram responds 429 with `retry_after`
- WHEN the client waits at least that long and retries
- THEN the message is delivered and logged as sent

#### Scenario: Retries exhausted records a failure, not a crash

- GIVEN Telegram keeps responding 429 past the bounded retry limit
- WHEN the retry budget is exhausted
- THEN the delivery is logged as failed
- AND no exception propagates to the caller

### Requirement: Missing Telegram Configuration Is a Silent No-Op

When `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` is absent, sending MUST
return `{"sent": False, "reason": "missing_telegram_config"}` without
raising and without attempting an HTTP call, matching the existing
`missing_webhook_url` contract.

#### Scenario: Unconfigured install behaves as today

- GIVEN neither `TELEGRAM_BOT_TOKEN` nor `TELEGRAM_CHAT_ID` is set
- WHEN any job attempts to send a Telegram notification
- THEN it returns `{"sent": False, "reason": "missing_telegram_config"}`
- AND the job's own result is unaffected

### Requirement: The Bot Token Is Redacted From Every Surface

The token sits in the request path (`/bot{TOKEN}/sendMessage`). Any
exception message, log line, persisted `notifications.error` value, or
generic-webhook payload MUST have the token redacted. The generic-webhook
transport MUST NOT carry Telegram credentials in its payload.

#### Scenario: An exception during send never leaks the token

- GIVEN a send raises an exception whose message or `response.url` contains
  the request path with the bot token embedded
- WHEN the error is logged or persisted to `notifications.error`
- THEN the token segment is replaced with a redaction marker in every
  surface it would otherwise appear

### Requirement: Best-Effort Delivery Never Fails the Calling Job

A notification send failure or Telegram outage MUST NOT propagate as an
exception into the scheduler, inference job, or feedback report that
triggered it.

#### Scenario: Telegram outage does not fail the job

- GIVEN Telegram is unreachable for the whole retry window
- WHEN the calling job finishes its own work
- THEN the job's own exit status reflects its own work only, not the
  notification outcome
