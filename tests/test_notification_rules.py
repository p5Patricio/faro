from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ops.notification_rules import (
    DEFAULT_MAX_PRICE_AGE_HOURS,
    DEFAULT_MIN_ACCURACY,
    DEFAULT_MIN_FEEDBACK_SAMPLES,
    DEFAULT_MIN_MEAN_OUTCOME_RETURN,
    SEEDED_RULE_PARAMS,
    evaluate_job_failure,
    evaluate_model_degradation,
    evaluate_signal_transition,
    evaluate_stale_data,
    job_failure_dedupe_key,
    model_degradation_dedupe_key,
    signal_transition_dedupe_key,
    stale_data_dedupe_key,
)

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "db" / "migrations" / "0007_notifications.sql"


# -- Dedupe key recipes (task 3.2 / 3.4, parametrized) --------------------------


@pytest.mark.parametrize(
    "job_mode,failing_steps,run_date,expected",
    [
        (
            "full_retrain",
            ["brain.retraining_job"],
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            "job_failure|-|full_retrain|brain.retraining_job|2026-01-15",
        ),
        (
            None,
            ["a", "b"],
            "2026-01-15T23:59:00+00:00",
            "job_failure|-|-|a,b|2026-01-15",
        ),
    ],
)
def test_job_failure_dedupe_key_recipe(job_mode, failing_steps, run_date, expected) -> None:
    assert job_failure_dedupe_key(job_mode, failing_steps, run_date=run_date) == expected


def test_job_failure_dedupe_key_sorts_failing_steps_regardless_of_input_order() -> None:
    run_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
    key_a = job_failure_dedupe_key("mode", ["b", "a"], run_date=run_date)
    key_b = job_failure_dedupe_key("mode", ["a", "b"], run_date=run_date)
    assert key_a == key_b


def test_job_failure_dedupe_key_excludes_failure_count() -> None:
    run_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
    key_three = job_failure_dedupe_key("mode", ["a"], run_date=run_date)
    key_four = job_failure_dedupe_key("mode", ["a"], run_date=run_date)
    assert key_three == key_four  # count is not part of the key at all


def test_signal_transition_dedupe_key_recipe() -> None:
    key = signal_transition_dedupe_key(
        "aapl", "baseline", "HOLD", "BUY", prediction_date=datetime(2026, 1, 15, tzinfo=timezone.utc)
    )
    assert key == "signal_transition|AAPL|baseline|HOLD>BUY|2026-01-15"


def test_signal_transition_dedupe_key_uses_none_literal_for_first_prediction() -> None:
    key = signal_transition_dedupe_key(
        "aapl", "baseline", None, "BUY", prediction_date=datetime(2026, 1, 15, tzinfo=timezone.utc)
    )
    assert key == "signal_transition|AAPL|baseline|NONE>BUY|2026-01-15"


def test_model_degradation_dedupe_key_recipe() -> None:
    key = model_degradation_dedupe_key("baseline", "low_accuracy", now=datetime(2026, 1, 15, tzinfo=timezone.utc))
    assert key == "model_degradation|-|baseline|low_accuracy|2026-01-15"


def test_stale_data_dedupe_key_recipe_with_a_last_price_date() -> None:
    key = stale_data_dedupe_key("aapl", datetime(2026, 1, 10, tzinfo=timezone.utc))
    assert key == "stale_data|AAPL|-|-|2026-01-10"


def test_stale_data_dedupe_key_uses_none_literal_for_zero_prices() -> None:
    key = stale_data_dedupe_key("aapl", None)
    assert key == "stale_data|AAPL|-|-|none"


def test_stale_data_dedupe_key_unchanged_when_now_advances_a_week() -> None:
    """The fatigue assertion: the staleness key depends only on the last
    observed price date, never on `now`."""
    last_price_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

    key_today = stale_data_dedupe_key("aapl", last_price_date)
    # `now` isn't even a parameter here -- the key only ever depends on
    # last_price_date, so "a week later" cannot change it.
    key_a_week_later = stale_data_dedupe_key("aapl", last_price_date)

    assert key_today == key_a_week_later


def test_stale_data_dedupe_key_changes_only_when_last_price_date_changes() -> None:
    key_a = stale_data_dedupe_key("aapl", datetime(2026, 1, 1, tzinfo=timezone.utc))
    key_b = stale_data_dedupe_key("aapl", datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert key_a != key_b


# -- evaluate_signal_transition (task 3.3 / 3.4) --------------------------------


def test_signal_transition_hold_to_hold_produces_no_event() -> None:
    event = evaluate_signal_transition(
        ticker="aapl",
        model_name="baseline",
        previous_action="HOLD",
        predicted_action="HOLD",
        prediction_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert event is None


def test_signal_transition_buy_to_sell_produces_one_event() -> None:
    event = evaluate_signal_transition(
        ticker="aapl",
        model_name="baseline",
        previous_action="BUY",
        predicted_action="SELL",
        prediction_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert event is not None
    assert event.rule_type == "signal_transition"
    assert event.ticker == "AAPL"


def test_signal_transition_first_prediction_hold_produces_no_event() -> None:
    event = evaluate_signal_transition(
        ticker="aapl",
        model_name="baseline",
        previous_action=None,
        predicted_action="HOLD",
        prediction_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert event is None


def test_signal_transition_first_prediction_buy_produces_one_event() -> None:
    event = evaluate_signal_transition(
        ticker="aapl",
        model_name="baseline",
        previous_action=None,
        predicted_action="BUY",
        prediction_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert event is not None
    assert "NONE" in event.dedupe_key


# -- evaluate_job_failure --------------------------------------------------------


def test_job_failure_below_min_failed_produces_no_event() -> None:
    event = evaluate_job_failure(
        job_mode="full_retrain",
        failed_count=0,
        failing_steps=[],
        run_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert event is None


def test_job_failure_at_or_above_min_failed_produces_one_event() -> None:
    event = evaluate_job_failure(
        job_mode="full_retrain",
        failed_count=1,
        failing_steps=["brain.retraining_job"],
        run_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert event is not None
    assert event.severity == "critical"


# -- evaluate_model_degradation --------------------------------------------------


def test_model_degradation_below_min_accuracy_fires_low_accuracy() -> None:
    event = evaluate_model_degradation(
        model_name="baseline",
        accuracy=0.30,
        mean_outcome_return=0.02,
        evaluated=50,
        now=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert event is not None
    assert "low_accuracy" in event.dedupe_key


def test_model_degradation_below_min_mean_outcome_return_fires_negative_edge() -> None:
    event = evaluate_model_degradation(
        model_name="baseline",
        accuracy=0.60,
        mean_outcome_return=-0.01,
        evaluated=50,
        now=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert event is not None
    assert "negative_edge" in event.dedupe_key


def test_model_degradation_below_min_feedback_samples_produces_no_event() -> None:
    event = evaluate_model_degradation(
        model_name="baseline",
        accuracy=0.10,
        mean_outcome_return=-0.5,
        evaluated=5,
        now=datetime(2026, 1, 15, tzinfo=timezone.utc),
        min_feedback_samples=20,
    )
    assert event is None


def test_model_degradation_healthy_model_produces_no_event() -> None:
    event = evaluate_model_degradation(
        model_name="baseline",
        accuracy=0.80,
        mean_outcome_return=0.05,
        evaluated=50,
        now=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert event is None


# -- evaluate_stale_data ----------------------------------------------------------


def test_stale_data_within_max_age_produces_no_event() -> None:
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    event = evaluate_stale_data(
        ticker="aapl", last_price_at=now, now=now, max_price_age_hours=DEFAULT_MAX_PRICE_AGE_HOURS
    )
    assert event is None


def test_stale_data_beyond_max_age_produces_one_event() -> None:
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    stale_since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = evaluate_stale_data(
        ticker="aapl", last_price_at=stale_since, now=now, max_price_age_hours=DEFAULT_MAX_PRICE_AGE_HOURS
    )
    assert event is not None
    assert event.severity == "warning"


def test_stale_data_zero_prices_produces_critical_event() -> None:
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    event = evaluate_stale_data(ticker="aapl", last_price_at=None, now=now)
    assert event is not None
    assert event.severity == "critical"
    assert event.dedupe_key.endswith("|none")


# -- Drift test (task 3.5): migration seed must equal SEEDED_RULE_PARAMS ---------


def test_seeded_rule_params_match_migration_jsonb_literals_in_order() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    # No re.DOTALL: every real jsonb literal in this migration sits on one
    # line, so restricting `.` to a single line prevents an unrelated `'{}'`
    # mention elsewhere in a comment from bridging across lines to a much
    # later `}'::jsonb` and corrupting the match.
    literals = re.findall(r"'(\{.*?\})'::jsonb", sql)
    # The two `default '{}'::jsonb` column defaults are empty objects, never
    # a real seed parameter set -- filtered out so only the four insert
    # values remain, in file order.
    parsed = [json.loads(literal) for literal in literals if literal != "{}"]

    assert parsed == list(SEEDED_RULE_PARAMS.values())


def test_seeded_rule_params_dashboard_defaults_match_shared_source() -> None:
    """Req: Degradation Thresholds Share One Default Source -- the seeded
    model_degradation/stale_data params must equal the module constants
    that api/main.py's Query(default=...) values also bind to."""
    assert SEEDED_RULE_PARAMS["model_degradation"]["min_accuracy"] == DEFAULT_MIN_ACCURACY
    assert (
        SEEDED_RULE_PARAMS["model_degradation"]["min_mean_outcome_return"] == DEFAULT_MIN_MEAN_OUTCOME_RETURN
    )
    assert (
        SEEDED_RULE_PARAMS["model_degradation"]["min_feedback_samples"] == DEFAULT_MIN_FEEDBACK_SAMPLES
    )
    assert SEEDED_RULE_PARAMS["stale_data"]["max_price_age_hours"] == DEFAULT_MAX_PRICE_AGE_HOURS
