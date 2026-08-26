from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from collector.local_repository import LocalPostgresRepository

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
