"""Notification policy: canonical thresholds, dedupe-key recipes, and the
four pure rule evaluators for the Telegram notification system.

Stdlib only -- this module imports nothing else from this project, so
`api/main.py` (FastAPI) and `brain/inference_job.py` (a CLI job) can both
depend on it without pulling the other's import graph along.

rule_type naming (`job_failure`, `signal_transition`, `model_degradation`,
`stale_data`) matches the operational-notifications spec's Four-Trigger Rule
Catalog requirement wording exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

# -- Shared threshold defaults (Req: Degradation Thresholds Share One Default Source) --
#
# The dashboard's `api/main.py:get_operational_alerts` Query defaults and the
# `model_degradation`/`stale_data` seeded rule params in
# `db/migrations/0007_notifications.sql` both originate here. A drift test in
# `tests/test_notification_rules.py` parses the migration's jsonb literals
# and asserts equality with SEEDED_RULE_PARAMS below, so the two can never
# silently diverge.

DEFAULT_MAX_PRICE_AGE_HOURS = 72.0
DEFAULT_MIN_FEEDBACK_SAMPLES = 20
DEFAULT_MIN_ACCURACY = 0.45
DEFAULT_MIN_MEAN_OUTCOME_RETURN = 0.0

SEEDED_RULE_PARAMS: dict[str, dict[str, Any]] = {
    "job_failure": {"min_failed": 1},
    "signal_transition": {"min_confidence": 0.55, "actions": ["BUY", "SELL"]},
    "model_degradation": {
        "min_feedback_samples": DEFAULT_MIN_FEEDBACK_SAMPLES,
        "min_accuracy": DEFAULT_MIN_ACCURACY,
        "min_mean_outcome_return": DEFAULT_MIN_MEAN_OUTCOME_RETURN,
    },
    "stale_data": {"max_price_age_hours": DEFAULT_MAX_PRICE_AGE_HOURS},
}


@dataclass(frozen=True)
class NotificationEvent:
    """One evaluated, ready-to-dispatch alert. Pure data -- no I/O."""

    rule_type: str
    dedupe_key: str
    scope_key: str
    title: str
    body: str
    severity: str = "info"
    ticker: str | None = None
    asset_id: str | None = None


# -- Dedupe key composition (design §4) -----------------------------------------
#
# dedupe_key = "|".join([rule_type, ticker or "-", scope_key or "-",
#                         discriminator or "-", bucket])
#
# `|` not `:` -- ISO timestamps contain `:`. Tickers uppercased, rule_type
# lowercased, all dates YYYY-MM-DD UTC (a local-time bucket would double-fire
# or skip a day around midnight/DST).


def _utc_date(value: datetime | date | str | None) -> str:
    """Format a date-like input as an ISO ``YYYY-MM-DD`` string in UTC, or
    the literal string ``"none"`` when there is nothing to bucket on (the
    zero-prices staleness case)."""
    if value is None:
        return "none"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.date().isoformat()
    return value.isoformat()


def _dedupe_key(rule_type: str, ticker: str | None, scope_key: str, discriminator: str, bucket: str) -> str:
    return "|".join(
        [
            rule_type.lower(),
            ticker.upper() if ticker else "-",
            scope_key or "-",
            discriminator or "-",
            bucket,
        ]
    )


def job_failure_dedupe_key(
    job_mode: str | None,
    failing_steps: list[str],
    *,
    run_date: datetime | date | str,
) -> str:
    # Counts excluded from the discriminator: 3 failures ticking to 4 is the
    # same incident. A different step failing fires immediately.
    discriminator = ",".join(sorted(failing_steps))
    return _dedupe_key("job_failure", None, job_mode or "", discriminator, _utc_date(run_date))


def signal_transition_dedupe_key(
    ticker: str,
    model_name: str,
    previous_action: str | None,
    new_action: str,
    *,
    prediction_date: datetime | date | str,
) -> str:
    # Confidence excluded: 0.61 re-scoring to 0.63 is the same signal.
    # model_name not model_run_id: a version bump should not re-announce a
    # position you already hold.
    discriminator = f"{previous_action or 'NONE'}>{new_action}"
    return _dedupe_key("signal_transition", ticker, model_name, discriminator, _utc_date(prediction_date))


def model_degradation_dedupe_key(model_name: str, alert_code: str, *, now: datetime) -> str:
    # Measured value excluded: a drifting number is the same condition.
    return _dedupe_key("model_degradation", None, model_name, alert_code, _utc_date(now))


def stale_data_dedupe_key(ticker: str, last_price_date: datetime | date | str | None) -> str:
    # Bucketing on the *last observed price date* (not `now()`) fires once
    # per staleness episode; bucketing on today would alert forever on a
    # dead feed and no cooldown could stop it.
    return _dedupe_key("stale_data", ticker, "", "", _utc_date(last_price_date))


# -- Pure evaluators (no I/O) -----------------------------------------------------


def evaluate_job_failure(
    *,
    job_mode: str | None,
    failed_count: int,
    failing_steps: list[str],
    run_date: datetime,
    min_failed: int = 1,
) -> NotificationEvent | None:
    if failed_count < min_failed:
        return None
    dedupe_key = job_failure_dedupe_key(job_mode, failing_steps, run_date=run_date)
    steps_text = ", ".join(sorted(failing_steps)) if failing_steps else "unspecified step(s)"
    return NotificationEvent(
        rule_type="job_failure",
        dedupe_key=dedupe_key,
        scope_key=job_mode or "",
        title="Operational job failure",
        body=f"{failed_count} step(s) failed in job_mode={job_mode or 'unknown'}: {steps_text}",
        severity="critical",
    )


def evaluate_signal_transition(
    *,
    ticker: str,
    model_name: str,
    previous_action: str | None,
    predicted_action: str,
    prediction_date: datetime,
    confidence: float | None = None,
    actions: tuple[str, ...] = ("BUY", "SELL"),
) -> NotificationEvent | None:
    if previous_action == predicted_action:
        return None
    if predicted_action not in actions:
        return None
    dedupe_key = signal_transition_dedupe_key(
        ticker, model_name, previous_action, predicted_action, prediction_date=prediction_date
    )
    confidence_text = f" (confidence {confidence:.2f})" if confidence is not None else ""
    return NotificationEvent(
        rule_type="signal_transition",
        dedupe_key=dedupe_key,
        ticker=ticker.upper(),
        scope_key=model_name,
        title=f"{ticker.upper()} signal changed to {predicted_action}",
        body=(
            f"{model_name} changed {ticker.upper()} from {previous_action or 'NONE'} "
            f"to {predicted_action}{confidence_text}"
        ),
        severity="warning",
    )


def evaluate_model_degradation(
    *,
    model_name: str,
    accuracy: float | None,
    mean_outcome_return: float | None,
    evaluated: int,
    now: datetime,
    min_feedback_samples: int = DEFAULT_MIN_FEEDBACK_SAMPLES,
    min_accuracy: float = DEFAULT_MIN_ACCURACY,
    min_mean_outcome_return: float = DEFAULT_MIN_MEAN_OUTCOME_RETURN,
) -> NotificationEvent | None:
    if evaluated < min_feedback_samples:
        return None

    if accuracy is not None and accuracy < min_accuracy:
        alert_code = "low_accuracy"
    elif mean_outcome_return is not None and mean_outcome_return < min_mean_outcome_return:
        alert_code = "negative_edge"
    else:
        return None

    dedupe_key = model_degradation_dedupe_key(model_name, alert_code, now=now)
    return NotificationEvent(
        rule_type="model_degradation",
        dedupe_key=dedupe_key,
        scope_key=model_name,
        title=f"Model {model_name} degraded: {alert_code}",
        body=(
            f"{model_name} evaluated={evaluated} accuracy={accuracy} "
            f"mean_outcome_return={mean_outcome_return} ({alert_code})"
        ),
        severity="warning",
    )


def evaluate_stale_data(
    *,
    ticker: str,
    last_price_at: datetime | None,
    now: datetime,
    max_price_age_hours: float = DEFAULT_MAX_PRICE_AGE_HOURS,
) -> NotificationEvent | None:
    if last_price_at is not None:
        checked = last_price_at if last_price_at.tzinfo else last_price_at.replace(tzinfo=timezone.utc)
        age_hours = (now - checked).total_seconds() / 3600.0
        if age_hours <= max_price_age_hours:
            return None
        severity = "warning"
        body = f"{ticker.upper()} has no new price in {age_hours:.1f}h (limit {max_price_age_hours}h)"
    else:
        # No prices at all is the fatigue-critical case: bucket "none" fires
        # exactly once per (permanent, until data arrives) episode, matching
        # `build_operational_alerts`' `no_prices` treatment as critical.
        severity = "critical"
        body = f"{ticker.upper()} has zero recorded prices"

    dedupe_key = stale_data_dedupe_key(ticker, last_price_at)
    return NotificationEvent(
        rule_type="stale_data",
        dedupe_key=dedupe_key,
        ticker=ticker.upper(),
        scope_key="",
        title=f"{ticker.upper()} price data is stale",
        body=body,
        severity=severity,
    )
