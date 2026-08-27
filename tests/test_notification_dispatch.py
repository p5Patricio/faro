from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from collector.local_repository import LocalPostgresRepository
from ops import notification_dispatch
from ops.notification_rules import NotificationEvent
from ops.telegram_notifier import TelegramConfig

SEEDED_RULE_TYPES = {"job_failure", "signal_transition", "model_degradation", "stale_data"}


# -- Threat matrix: SQL injection (task 1.1, RED before repository methods existed) --


def test_injection_payload_round_trips_as_literal_data_via_insert_notification(
    repository: LocalPostgresRepository,
    db_connection,
) -> None:
    malicious = "'; drop table notifications; --"

    inserted = repository.insert_notification(
        rule_id=None,
        rule_type=malicious,
        asset_id=None,
        scope_key="",
        channel="telegram",
        dedupe_key="injection-test-key",
        severity="info",
        title="test",
        body="test body",
        status="failed",
        error_reason=malicious,
        payload={"ticker": malicious},
    )

    assert inserted is not None
    assert inserted["rule_type"] == malicious
    assert inserted["error_reason"] == malicious
    assert inserted["payload"]["ticker"] == malicious

    with db_connection.cursor() as cur:
        cur.execute("SELECT to_regclass('notifications') IS NOT NULL")
        (notifications_exists,) = cur.fetchone()
        cur.execute("SELECT to_regclass('notification_rules') IS NOT NULL")
        (rules_exists,) = cur.fetchone()
    assert notifications_exists is True
    assert rules_exists is True


# -- notification_rules seeding -----------------------------------------------


def test_get_active_notification_rules_returns_all_four_seeded_rules(
    repository: LocalPostgresRepository,
) -> None:
    rules = repository.get_active_notification_rules()

    rule_types = {rule["rule_type"] for rule in rules}
    assert rule_types == SEEDED_RULE_TYPES
    assert all(rule["channel"] == "telegram" for rule in rules)


def test_get_active_notification_rules_filters_by_rule_type_and_channel(
    repository: LocalPostgresRepository,
) -> None:
    rules = repository.get_active_notification_rules(rule_type="job_failure", channel="telegram")

    assert len(rules) == 1
    assert rules[0]["rule_type"] == "job_failure"
    assert rules[0]["cooldown_minutes"] == 0


# -- insert_notification / dedupe -----------------------------------------------


def test_insert_notification_second_sent_with_same_dedupe_key_returns_none(
    repository: LocalPostgresRepository,
) -> None:
    kwargs = dict(
        rule_id=None,
        rule_type="job_failure",
        asset_id=None,
        scope_key="",
        channel="telegram",
        dedupe_key="dedupe-sent-key",
        severity="critical",
        title="Job failed",
        body="body",
        status="sent",
    )

    first = repository.insert_notification(**kwargs)
    second = repository.insert_notification(**kwargs)

    assert first is not None
    assert second is None


def test_insert_notification_two_failed_inserts_both_persist_then_sent_succeeds(
    repository: LocalPostgresRepository,
) -> None:
    kwargs = dict(
        rule_id=None,
        rule_type="job_failure",
        asset_id=None,
        scope_key="",
        channel="telegram",
        dedupe_key="dedupe-failed-key",
        severity="critical",
        title="Job failed",
        body="body",
        status="failed",
        error_reason="boom",
    )

    first = repository.insert_notification(**kwargs)
    second = repository.insert_notification(**kwargs)

    assert first is not None
    assert second is not None
    assert first["id"] != second["id"]

    sent = repository.insert_notification(**{**kwargs, "status": "sent", "error_reason": None})
    assert sent is not None


def test_get_last_notification_fired_at_ignores_failed_rows(
    repository: LocalPostgresRepository,
) -> None:
    repository.insert_notification(
        rule_id=None,
        rule_type="stale_data",
        asset_id=None,
        scope_key="",
        channel="telegram",
        dedupe_key="only-failed-key",
        severity="warning",
        title="Stale",
        body="body",
        status="failed",
        error_reason="boom",
    )

    assert repository.get_last_notification_fired_at("stale_data", asset_id=None, scope_key="") is None


def test_get_last_notification_fired_at_sees_sent_row_within_cooldown(
    repository: LocalPostgresRepository,
    db_connection,
) -> None:
    repository.insert_notification(
        rule_id=None,
        rule_type="model_degradation",
        asset_id=None,
        scope_key="baseline",
        channel="telegram",
        dedupe_key="cooldown-key",
        severity="warning",
        title="Degraded",
        body="body",
        status="sent",
    )
    thirty_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=30)
    with db_connection.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET fired_at = %s WHERE dedupe_key = %s",
            (thirty_minutes_ago, "cooldown-key"),
        )

    fired_at = repository.get_last_notification_fired_at(
        "model_degradation", asset_id=None, scope_key="baseline"
    )

    assert fired_at is not None
    cooldown_minutes = 1440
    assert (datetime.now(timezone.utc) - fired_at) < timedelta(minutes=cooldown_minutes)


def test_get_latest_price_timestamps_includes_assets_with_zero_prices(
    repository: LocalPostgresRepository,
) -> None:
    repository.get_or_create_asset("aapl", asset_class="stock")

    rows = repository.get_latest_price_timestamps()

    matches = [row for row in rows if row["ticker"] == "AAPL"]
    assert len(matches) == 1
    assert matches[0]["latest_price_at"] is None


# -- Phase 6a: ops/notification_dispatch orchestration ---------------------------

TOKEN = "123456789:AAFakeTokenForTestingPurposesOnly12"


class FakeDispatchResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def json(self) -> dict:
        return {}


class FakeDispatchSession:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def post(self, url: str, json: dict, timeout: int):
        self.requests.append({"url": url, "json": json, "timeout": timeout})
        return FakeDispatchResponse(status_code=200)


class FakeDispatchRepository:
    """Stand-in repository for unit-testing the pure wiring functions
    (tasks 6a.2/6a.3/6a.4) without a real database."""

    def __init__(
        self,
        *,
        latest_price_timestamps: list[dict] | None = None,
        prediction_feedback: pd.DataFrame | None = None,
        asset_ids: dict[str, str] | None = None,
    ) -> None:
        self._latest_price_timestamps = latest_price_timestamps or []
        self._prediction_feedback = (
            prediction_feedback if prediction_feedback is not None else pd.DataFrame()
        )
        self._asset_ids = asset_ids or {}

    def get_asset_id(self, ticker: str) -> str:
        return self._asset_ids[ticker]

    def get_latest_price_timestamps(self) -> list[dict]:
        return self._latest_price_timestamps

    def get_prediction_feedback(self, asset_id: str | None = None, only_evaluated: bool = True) -> pd.DataFrame:
        frame = self._prediction_feedback
        if asset_id is not None and not frame.empty:
            frame = frame[frame["asset_id"] == asset_id]
        return frame


def _telegram_config() -> TelegramConfig:
    return TelegramConfig(bot_token=TOKEN, chat_id="-100999")


def _dispatch_rule(
    rule_type: str,
    *,
    asset_id: str | None = None,
    cooldown_minutes: int = 1440,
    params: dict | None = None,
    rule_id: str | None = None,
) -> dict:
    return {
        "id": rule_id,
        "rule_type": rule_type,
        "asset_id": asset_id,
        "channel": "telegram",
        "params": params or {},
        "cooldown_minutes": cooldown_minutes,
    }


# -- 6a.2: stale_data wiring --


def test_stale_data_events_fan_out_a_global_rule_to_every_stale_asset_with_its_own_asset_id() -> None:
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    repository = FakeDispatchRepository(
        latest_price_timestamps=[
            {"asset_id": "asset-aapl", "ticker": "AAPL", "latest_price_at": now - timedelta(hours=1)},
            {"asset_id": "asset-msft", "ticker": "MSFT", "latest_price_at": now - timedelta(hours=200)},
        ]
    )
    rule = _dispatch_rule("stale_data", params={"max_price_age_hours": 72.0})

    events = notification_dispatch._stale_data_events(rule, repository, now=now)

    assert [event.ticker for event in events] == ["MSFT"]
    assert events[0].asset_id == "asset-msft"


def test_stale_data_events_scoped_rule_checks_only_its_own_asset() -> None:
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    repository = FakeDispatchRepository(
        latest_price_timestamps=[
            {"asset_id": "asset-aapl", "ticker": "AAPL", "latest_price_at": None},
            {"asset_id": "asset-msft", "ticker": "MSFT", "latest_price_at": None},
        ]
    )
    rule = _dispatch_rule("stale_data", asset_id="asset-msft")

    events = notification_dispatch._stale_data_events(rule, repository, now=now)

    assert [event.ticker for event in events] == ["MSFT"]


# -- 6a.3: model_degradation wiring --


def test_model_degradation_events_grouped_by_model_name_via_analyze_prediction_feedback() -> None:
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    feedback = pd.DataFrame(
        {
            "model_name": ["model-a"] * 25 + ["model-b"] * 25,
            "predicted_action": ["BUY"] * 50,
            "actual_label": ["SELL"] * 25 + ["BUY"] * 25,
            "is_correct": [False] * 25 + [True] * 25,
            "confidence": [0.6] * 50,
            "outcome_return": [-0.01] * 25 + [0.01] * 25,
        }
    )
    repository = FakeDispatchRepository(prediction_feedback=feedback)
    rule = _dispatch_rule("model_degradation")

    events = notification_dispatch._model_degradation_events(rule, repository, now=now)

    assert {event.scope_key for event in events} == {"model-a"}


def test_model_degradation_events_below_min_feedback_samples_emits_nothing() -> None:
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    feedback = pd.DataFrame(
        {
            "model_name": ["model-a"] * 5,
            "predicted_action": ["BUY"] * 5,
            "actual_label": ["SELL"] * 5,
            "is_correct": [False] * 5,
            "confidence": [0.6] * 5,
            "outcome_return": [-0.01] * 5,
        }
    )
    repository = FakeDispatchRepository(prediction_feedback=feedback)
    rule = _dispatch_rule("model_degradation")

    events = notification_dispatch._model_degradation_events(rule, repository, now=now)

    assert events == []


# -- 6a.4: signal_transition wiring (stubbed report input) --


def test_signal_transition_events_read_from_the_loaded_inference_job_report() -> None:
    repository = FakeDispatchRepository(asset_ids={"AAPL": "asset-aapl", "MSFT": "asset-msft"})
    reports = {
        "inference_job.json": {
            "results": [
                {
                    "ticker": "AAPL",
                    "model_name": "extra_trees",
                    "previous_action": "HOLD",
                    "latest_prediction": {
                        "action": "BUY",
                        "confidence": 0.7,
                        "timestamp": "2026-01-10 00:00:00+00:00",
                    },
                },
                {
                    "ticker": "MSFT",
                    "model_name": "extra_trees",
                    "previous_action": "BUY",
                    "latest_prediction": {
                        "action": "BUY",
                        "confidence": 0.7,
                        "timestamp": "2026-01-10 00:00:00+00:00",
                    },
                },
            ]
        }
    }
    rule = _dispatch_rule("signal_transition")

    events = notification_dispatch._signal_transition_events(rule, reports, repository=repository)

    assert [event.ticker for event in events] == ["AAPL"]
    assert events[0].asset_id == "asset-aapl"


def test_signal_transition_events_missing_report_emits_nothing() -> None:
    rule = _dispatch_rule("signal_transition")

    events = notification_dispatch._signal_transition_events(rule, {}, repository=FakeDispatchRepository())

    assert events == []


# -- job_failure wiring (folded into 6a.1's orchestration loop) --


def test_job_failure_events_sum_failed_across_reports_and_list_failing_report_names() -> None:
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    reports = {
        "market_data_job.json": {"failed": 2},
        "inference_job.json": {"failed": 0},
    }
    rule = _dispatch_rule("job_failure")

    events = notification_dispatch._job_failure_events(rule, reports, job_mode="daily", now=now)

    assert len(events) == 1
    assert "market_data_job.json" in events[0].body
    assert events[0].severity == "critical"


def test_job_failure_events_nothing_failed_emits_nothing() -> None:
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    reports = {"market_data_job.json": {"failed": 0}}
    rule = _dispatch_rule("job_failure")

    events = notification_dispatch._job_failure_events(rule, reports, job_mode="daily", now=now)

    assert events == []


# -- 7.3: pre-report failed_steps gap-filling (ops.run_local_scheduler --failed-steps) --


def test_job_failure_events_fires_from_failed_steps_alone_when_no_report_shows_it() -> None:
    """collector.schema_check crashes with no --out report at all: reports is
    empty, so only the scheduler-supplied failed_steps name can surface the
    failure."""
    now = datetime(2026, 1, 16, tzinfo=timezone.utc)
    rule = _dispatch_rule("job_failure")

    events = notification_dispatch._job_failure_events(
        rule, {}, job_mode="market_data", failed_steps=["schema_check"], now=now
    )

    assert len(events) == 1
    assert "schema_check" in events[0].dedupe_key
    assert "schema_check" in events[0].body


def test_job_failure_events_merges_report_derived_and_failed_steps_without_double_counting() -> None:
    now = datetime(2026, 1, 16, tzinfo=timezone.utc)
    reports = {"market_data_job.json": {"failed": 2}}
    rule = _dispatch_rule("job_failure")

    events = notification_dispatch._job_failure_events(
        rule, reports, job_mode="market_data", failed_steps=["market_data_job.json", "paper_trading"], now=now
    )

    assert len(events) == 1
    body = events[0].body
    assert body.startswith("3 step(s) failed")  # 2 report-derived + 1 new from failed_steps
    assert "paper_trading" in events[0].dedupe_key
    assert "market_data_job.json" in events[0].dedupe_key


# -- 6a.5: dedupe-first-then-cooldown suppression semantics, real test DB --


def test_process_event_two_model_degradation_events_with_different_scope_key_do_not_suppress_each_other(
    repository: LocalPostgresRepository,
) -> None:
    now = datetime.now(timezone.utc)
    session = FakeDispatchSession()
    bucket = now.date().isoformat()

    event_a = NotificationEvent(
        rule_type="model_degradation",
        dedupe_key=f"model_degradation|-|model-a|low_accuracy|{bucket}",
        scope_key="model-a",
        title="Model A degraded",
        body="body a",
        severity="warning",
    )
    event_b = NotificationEvent(
        rule_type="model_degradation",
        dedupe_key=f"model_degradation|-|model-b|low_accuracy|{bucket}",
        scope_key="model-b",
        title="Model B degraded",
        body="body b",
        severity="warning",
    )
    rule = _dispatch_rule("model_degradation", cooldown_minutes=1440)

    outcome_a = notification_dispatch._process_event(
        event_a, rule=rule, repository=repository, telegram_config=_telegram_config(),
        now=now, session=session, sleep=lambda *_args: None,
    )
    outcome_b = notification_dispatch._process_event(
        event_b, rule=rule, repository=repository, telegram_config=_telegram_config(),
        now=now, session=session, sleep=lambda *_args: None,
    )

    assert outcome_a["outcome"] == "sent"
    assert outcome_b["outcome"] == "sent"
    assert len(session.requests) == 2


def test_process_event_global_and_scoped_rule_of_the_same_type_do_not_suppress_each_other(
    repository: LocalPostgresRepository,
) -> None:
    now = datetime.now(timezone.utc)
    session = FakeDispatchSession()
    asset_id = repository.get_or_create_asset("aapl", asset_class="stock")
    bucket = now.date().isoformat()

    global_event = NotificationEvent(
        rule_type="stale_data",
        dedupe_key=f"stale_data|-|-|-|{bucket}",
        scope_key="",
        title="Global stale",
        body="body",
        severity="warning",
    )
    scoped_event = NotificationEvent(
        rule_type="stale_data",
        dedupe_key=f"stale_data|AAPL|-|-|{bucket}",
        scope_key="",
        ticker="AAPL",
        asset_id=asset_id,
        title="AAPL stale",
        body="body",
        severity="warning",
    )
    global_rule = _dispatch_rule("stale_data", asset_id=None, cooldown_minutes=1440)
    scoped_rule = _dispatch_rule("stale_data", asset_id=asset_id, cooldown_minutes=1440)

    outcome_global = notification_dispatch._process_event(
        global_event, rule=global_rule, repository=repository, telegram_config=_telegram_config(),
        now=now, session=session, sleep=lambda *_args: None,
    )
    outcome_scoped = notification_dispatch._process_event(
        scoped_event, rule=scoped_rule, repository=repository, telegram_config=_telegram_config(),
        now=now, session=session, sleep=lambda *_args: None,
    )

    assert outcome_global["outcome"] == "sent"
    assert outcome_scoped["outcome"] == "sent"


def test_process_event_zero_cooldown_always_proceeds_past_the_cooldown_check(
    repository: LocalPostgresRepository,
) -> None:
    now = datetime.now(timezone.utc)
    session = FakeDispatchSession()
    rule = _dispatch_rule("job_failure", asset_id=None, cooldown_minutes=0)

    # A prior *sent* row for the same (rule_type, asset_id, scope_key), fired
    # moments ago -- with a non-zero cooldown this would suppress a new event.
    repository.insert_notification(
        rule_id=None,
        rule_type="job_failure",
        asset_id=None,
        scope_key="",
        channel="telegram",
        dedupe_key="job_failure|-|-|step-a|2020-01-01",
        severity="critical",
        title="prev",
        body="prev body",
        status="sent",
    )

    new_event = NotificationEvent(
        rule_type="job_failure",
        dedupe_key=f"job_failure|-|-|step-a|{now.date().isoformat()}",
        scope_key="",
        title="Job failed",
        body="body",
        severity="critical",
    )

    outcome = notification_dispatch._process_event(
        new_event, rule=rule, repository=repository, telegram_config=_telegram_config(),
        now=now, session=session, sleep=lambda *_args: None,
    )

    assert outcome["outcome"] == "sent"


def test_process_event_cooldown_elapsed_proceeds_to_send(
    repository: LocalPostgresRepository,
    db_connection,
) -> None:
    """Req: Per-Rule Cooldown Suppression -- 'Cooldown expiry re-arms the
    rule' scenario. A prior *sent* row exists for this (rule_type, asset_id,
    scope_key), but its fired_at is older than cooldown_minutes, so the
    cooldown window has elapsed and the rule must fire again."""
    now = datetime.now(timezone.utc)
    session = FakeDispatchSession()
    rule = _dispatch_rule("model_degradation", cooldown_minutes=60)

    repository.insert_notification(
        rule_id=None,
        rule_type="model_degradation",
        asset_id=None,
        scope_key="model-a",
        channel="telegram",
        dedupe_key="model_degradation|-|model-a|low_accuracy|2020-01-01",
        severity="warning",
        title="prev",
        body="prev body",
        status="sent",
    )
    two_hours_ago = now - timedelta(hours=2)
    with db_connection.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET fired_at = %s WHERE dedupe_key = %s",
            (two_hours_ago, "model_degradation|-|model-a|low_accuracy|2020-01-01"),
        )

    new_event = NotificationEvent(
        rule_type="model_degradation",
        # A different dedupe_key (different bucket) so only the cooldown
        # check, not dedupe, is exercised here.
        dedupe_key=f"model_degradation|-|model-a|low_accuracy|{now.date().isoformat()}",
        scope_key="model-a",
        title="Model A degraded again",
        body="body",
        severity="warning",
    )

    outcome = notification_dispatch._process_event(
        new_event, rule=rule, repository=repository, telegram_config=_telegram_config(),
        now=now, session=session, sleep=lambda *_args: None,
    )

    assert outcome["outcome"] == "sent"
    assert len(session.requests) == 1


def test_process_event_cooldown_suppresses_and_is_never_persisted(
    repository: LocalPostgresRepository,
) -> None:
    now = datetime.now(timezone.utc)
    session = FakeDispatchSession()
    rule = _dispatch_rule("model_degradation", cooldown_minutes=1440)

    repository.insert_notification(
        rule_id=None,
        rule_type="model_degradation",
        asset_id=None,
        scope_key="model-a",
        channel="telegram",
        dedupe_key="model_degradation|-|model-a|low_accuracy|2020-01-01",
        severity="warning",
        title="prev",
        body="prev body",
        status="sent",
    )

    new_event = NotificationEvent(
        rule_type="model_degradation",
        # A different dedupe_key (different bucket) so this is a genuinely
        # new event that only the cooldown check, not dedupe, can suppress.
        dedupe_key=f"model_degradation|-|model-a|low_accuracy|{now.date().isoformat()}",
        scope_key="model-a",
        title="Model A degraded again",
        body="body",
        severity="warning",
    )

    outcome = notification_dispatch._process_event(
        new_event, rule=rule, repository=repository, telegram_config=_telegram_config(),
        now=now, session=session, sleep=lambda *_args: None,
    )

    assert outcome["outcome"] == "cooldown"
    assert len(session.requests) == 0
    assert repository.notification_already_sent(new_event.dedupe_key) is False


# -- 6a.5: end-to-end via the public dispatch_notifications entrypoint --


def test_dispatch_notifications_end_to_end_job_failure_sends_once_and_dedupes_on_rerun(
    repository: LocalPostgresRepository,
) -> None:
    session = FakeDispatchSession()
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    reports = {"market_data_job.json": {"attempted": 3, "succeeded": 1, "failed": 2, "errors": []}}

    first = notification_dispatch.dispatch_notifications(
        repository,
        reports=reports,
        telegram_config=_telegram_config(),
        rule_types={"job_failure"},
        now=now,
        session=session,
        sleep=lambda *_args: None,
    )
    second = notification_dispatch.dispatch_notifications(
        repository,
        reports=reports,
        telegram_config=_telegram_config(),
        rule_types={"job_failure"},
        now=now,
        session=session,
        sleep=lambda *_args: None,
    )

    assert len(session.requests) == 1
    assert first["outcomes"][0]["outcome"] == "sent"
    assert second["outcomes"][0]["outcome"] == "deduped"

    dedupe_key = first["outcomes"][0]["dedupe_key"]
    assert repository.notification_already_sent(dedupe_key) is True


def test_dispatch_notifications_end_to_end_job_failure_from_failed_steps_writes_a_notifications_row(
    repository: LocalPostgresRepository,
) -> None:
    """Task 7: proves the `ops.run_local_scheduler` --failed-steps seam
    reaches `ops.notification_dispatch`'s dedupe/cooldown/send pipeline and
    produces a real `notifications` row with `rule_type = 'job_failure'`,
    even when no report JSON shows `failed > 0` -- the exact gap `--out`-less
    steps like `collector.schema_check` leave (design.md section 7-A)."""
    session = FakeDispatchSession()
    now = datetime(2026, 1, 17, tzinfo=timezone.utc)

    result = notification_dispatch.dispatch_notifications(
        repository,
        reports={},
        failed_steps=["schema_check"],
        telegram_config=_telegram_config(),
        rule_types={"job_failure"},
        now=now,
        session=session,
        sleep=lambda *_args: None,
    )

    assert len(session.requests) == 1
    assert result["outcomes"][0]["outcome"] == "sent"

    dedupe_key = result["outcomes"][0]["dedupe_key"]
    assert "schema_check" in dedupe_key
    assert repository.notification_already_sent(dedupe_key) is True


def test_dispatch_notifications_never_raises_when_repository_lookup_fails() -> None:
    class BrokenRepository:
        def get_active_notification_rules(self, **kwargs):
            raise RuntimeError("connection refused")

    result = notification_dispatch.dispatch_notifications(BrokenRepository())

    assert result == {"dispatched": False, "reason": "database_unavailable", "detail": "connection refused"}
