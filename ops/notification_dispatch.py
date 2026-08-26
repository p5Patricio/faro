"""Notification dispatch: orchestrates rules -> evaluate -> dedupe -> cooldown
-> send -> log for the four notification triggers (design.md section 5).

Ties together, per the project's layering (no cycles):

    collector.local_repository.LocalPostgresRepository  (rules, dedupe, cooldown, log)
    ops.notification_rules                              (pure evaluators + dedupe keys)
    ops.telegram_notifier                                (transport)

Evaluation order is **dedupe first, then cooldown** (design.md section 5):
a genuinely new event (a new ``dedupe_key``) must never be swallowed inside
another event's cooldown window. Cooldown-suppressed events are reported in
the returned outcome list only -- never persisted -- because a suppression
row would collide with ``notifications_dedupe_sent_key`` and make the
eventual real send impossible.

Best-effort delivery (Req: Best-Effort Delivery Never Fails the Calling
Job): ``dispatch_notifications`` never raises. Database errors and
per-event failures are captured as an ``"outcome"`` entry instead of
propagating.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from brain.feedback import analyze_prediction_feedback
from ops.notification_rules import (
    DEFAULT_MAX_PRICE_AGE_HOURS,
    DEFAULT_MIN_ACCURACY,
    DEFAULT_MIN_FEEDBACK_SAMPLES,
    DEFAULT_MIN_MEAN_OUTCOME_RETURN,
    NotificationEvent,
    evaluate_job_failure,
    evaluate_model_degradation,
    evaluate_signal_transition,
    evaluate_stale_data,
)
from ops.telegram_notifier import TelegramConfig, escape_html, send_telegram_message

# The scheduler's inference step writes its report under this name (design.md
# section 7-B: "The dispatcher reads reports/inference_job.json via the
# shared load_reports").
INFERENCE_JOB_REPORT_NAME = "inference_job.json"

# Same pacing the transport uses between its own chunks -- here it paces
# between *logical* messages (design.md section 4/5).
MIN_SEND_INTERVAL_SECONDS = 1.05


def dispatch_notifications(
    repository: Any,
    *,
    reports: dict[str, Any] | None = None,
    job_mode: str | None = None,
    telegram_config: TelegramConfig | None = None,
    rule_types: set[str] | None = None,
    now: datetime | None = None,
    session: Any = requests,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """Evaluate every active ``channel="telegram"`` rule, dedupe, apply
    cooldown, send, and log. Never raises.

    ``rule_types`` optionally narrows the evaluated rules to a subset (for
    example, to isolate a single trigger in a test or a future targeted
    invocation); the default ``None`` evaluates every active rule, matching
    design.md's full four-trigger dispatch loop.
    """
    now = now or datetime.now(tz=UTC)
    reports = reports or {}

    try:
        rules = repository.get_active_notification_rules(channel="telegram")
    except Exception as error:  # pragma: no cover - defense in depth; the
        # documented boundary for this failure is notify_operational_job's
        # own connection try/except (design.md section 2), this is a second
        # line of defense if dispatch_notifications is ever called directly.
        return {"dispatched": False, "reason": "database_unavailable", "detail": str(error)}

    if rule_types is not None:
        rules = [rule for rule in rules if rule.get("rule_type") in rule_types]

    outcomes: list[dict[str, Any]] = []
    for rule in rules:
        try:
            events = _events_for_rule(rule, repository=repository, reports=reports, job_mode=job_mode, now=now)
        except Exception as error:
            outcomes.append(
                {"rule_type": rule.get("rule_type"), "outcome": "evaluation_error", "detail": str(error)}
            )
            continue

        for event in events:
            try:
                outcome = _process_event(
                    event,
                    rule=rule,
                    repository=repository,
                    telegram_config=telegram_config,
                    now=now,
                    session=session,
                    sleep=sleep,
                )
            except Exception as error:
                outcome = {
                    "rule_type": event.rule_type,
                    "dedupe_key": event.dedupe_key,
                    "outcome": "dispatch_error",
                    "detail": str(error),
                }
            outcomes.append(outcome)

    return {"dispatched": True, "evaluated_rules": len(rules), "outcomes": outcomes}


def _process_event(
    event: NotificationEvent,
    *,
    rule: dict[str, Any],
    repository: Any,
    telegram_config: TelegramConfig | None,
    now: datetime,
    session: Any,
    sleep: Any,
) -> dict[str, Any]:
    # Dedupe first: a cheap, permanent rejection of an exact repeat that
    # must never consume a cooldown decision (design.md section 5).
    if repository.notification_already_sent(event.dedupe_key):
        return {"rule_type": event.rule_type, "dedupe_key": event.dedupe_key, "outcome": "deduped"}

    cooldown_minutes = int(rule.get("cooldown_minutes") or 0)
    if cooldown_minutes:
        last_fired_at = repository.get_last_notification_fired_at(event.rule_type, event.asset_id, event.scope_key)
        if last_fired_at is not None:
            if last_fired_at.tzinfo is None:
                last_fired_at = last_fired_at.replace(tzinfo=UTC)
            if (now - last_fired_at) < timedelta(minutes=cooldown_minutes):
                # NOT persisted: a suppression row would carry the same
                # dedupe_key as the eventual real send and collide with the
                # partial unique index, making suppression permanent.
                return {"rule_type": event.rule_type, "dedupe_key": event.dedupe_key, "outcome": "cooldown"}

    message = _render_event_message(event)
    result = send_telegram_message(message, telegram_config, session=session, sleep=sleep)
    status = "sent" if result.get("sent") else "failed"
    # `result` already went through ops.telegram_notifier.redact() on every
    # failure path -- pass it through as-is, never touch the raw token here.
    error_reason = None if result.get("sent") else str(result.get("detail") or result.get("reason"))

    inserted = repository.insert_notification(
        rule_id=rule.get("id"),
        rule_type=event.rule_type,
        asset_id=event.asset_id,
        scope_key=event.scope_key,
        channel=rule.get("channel") or "telegram",
        dedupe_key=event.dedupe_key,
        severity=event.severity,
        title=event.title,
        body=event.body,
        status=status,
        error_reason=error_reason,
        payload={"result": result},
    )
    outcome = "raced_duplicate" if status == "sent" and inserted is None else status

    if telegram_config is not None:
        sleep(MIN_SEND_INTERVAL_SECONDS)

    return {
        "rule_type": event.rule_type,
        "dedupe_key": event.dedupe_key,
        "outcome": outcome,
        "status_code": result.get("status_code"),
    }


def _render_event_message(event: NotificationEvent) -> str:
    """Line-scoped HTML, matching the renderer invariant `chunk_message`
    relies on: every `<b>` opens and closes inside one line."""
    return f"<b>{escape_html(event.title)}</b>\n{escape_html(event.body)}"


def _events_for_rule(
    rule: dict[str, Any],
    *,
    repository: Any,
    reports: dict[str, Any],
    job_mode: str | None,
    now: datetime,
) -> list[NotificationEvent]:
    rule_type = rule.get("rule_type")
    if rule_type == "job_failure":
        return _job_failure_events(rule, reports, job_mode=job_mode, now=now)
    if rule_type == "signal_transition":
        return _signal_transition_events(rule, reports, repository=repository)
    if rule_type == "model_degradation":
        return _model_degradation_events(rule, repository, now=now)
    if rule_type == "stale_data":
        return _stale_data_events(rule, repository, now=now)
    return []


def _job_failure_events(
    rule: dict[str, Any], reports: dict[str, Any], *, job_mode: str | None, now: datetime
) -> list[NotificationEvent]:
    if rule.get("asset_id") is not None:
        # A job failure is not asset-scoped; only the global seeded rule applies.
        return []

    params = rule.get("params") or {}
    failed_count = 0
    failing_steps: list[str] = []
    for name, raw in reports.items():
        if not isinstance(raw, dict):
            continue
        report_failed = int(raw.get("failed") or 0)
        failed_count += report_failed
        if report_failed:
            failing_steps.append(name)

    event = evaluate_job_failure(
        job_mode=job_mode,
        failed_count=failed_count,
        failing_steps=failing_steps,
        run_date=now,
        min_failed=int(params.get("min_failed", 1)),
    )
    return [event] if event else []


def _signal_transition_events(
    rule: dict[str, Any], reports: dict[str, Any], *, repository: Any
) -> list[NotificationEvent]:
    params = rule.get("params") or {}
    actions = tuple(params.get("actions") or ("BUY", "SELL"))
    rule_asset_id = rule.get("asset_id")

    inference_report = reports.get(INFERENCE_JOB_REPORT_NAME) or {}
    events: list[NotificationEvent] = []
    for result in inference_report.get("results") or []:
        latest_prediction = result.get("latest_prediction")
        ticker = result.get("ticker")
        if not latest_prediction or not ticker:
            continue

        resolved_asset_id: str | None
        try:
            resolved_asset_id = repository.get_asset_id(ticker)
        except Exception:
            resolved_asset_id = None

        if rule_asset_id is not None and resolved_asset_id != rule_asset_id:
            continue

        event = evaluate_signal_transition(
            ticker=ticker,
            model_name=result.get("model_name") or "",
            previous_action=result.get("previous_action"),
            predicted_action=latest_prediction.get("action"),
            prediction_date=_parse_timestamp(latest_prediction.get("timestamp")) or datetime.now(tz=UTC),
            confidence=latest_prediction.get("confidence"),
            actions=actions,
        )
        if event:
            events.append(replace(event, asset_id=resolved_asset_id))

    return events


def _model_degradation_events(rule: dict[str, Any], repository: Any, *, now: datetime) -> list[NotificationEvent]:
    params = rule.get("params") or {}
    rule_asset_id = rule.get("asset_id")

    feedback = repository.get_prediction_feedback(asset_id=rule_asset_id, only_evaluated=True)
    if feedback is None or feedback.empty:
        return []

    events: list[NotificationEvent] = []
    for model_name, group in feedback.groupby("model_name"):
        summary = analyze_prediction_feedback(group).summary
        event = evaluate_model_degradation(
            model_name=model_name,
            accuracy=summary.get("accuracy"),
            mean_outcome_return=summary.get("mean_outcome_return"),
            evaluated=summary.get("evaluated_predictions", 0),
            now=now,
            min_feedback_samples=int(params.get("min_feedback_samples", DEFAULT_MIN_FEEDBACK_SAMPLES)),
            min_accuracy=float(params.get("min_accuracy", DEFAULT_MIN_ACCURACY)),
            min_mean_outcome_return=float(params.get("min_mean_outcome_return", DEFAULT_MIN_MEAN_OUTCOME_RETURN)),
        )
        if event:
            events.append(replace(event, asset_id=rule_asset_id))

    return events


def _stale_data_events(rule: dict[str, Any], repository: Any, *, now: datetime) -> list[NotificationEvent]:
    params = rule.get("params") or {}
    max_price_age_hours = float(params.get("max_price_age_hours", DEFAULT_MAX_PRICE_AGE_HOURS))
    rule_asset_id = rule.get("asset_id")

    rows = repository.get_latest_price_timestamps()
    if rule_asset_id is not None:
        rows = [row for row in rows if row.get("asset_id") == rule_asset_id]

    events: list[NotificationEvent] = []
    for row in rows:
        event = evaluate_stale_data(
            ticker=row["ticker"],
            last_price_at=row.get("latest_price_at"),
            now=now,
            max_price_age_hours=max_price_age_hours,
        )
        if event:
            # One event per stale asset, carrying *that* asset's id
            # (design.md section 7-D) -- required so the cooldown check
            # scopes per-asset instead of colliding across every ticker.
            events.append(replace(event, asset_id=row["asset_id"]))

    return events


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
