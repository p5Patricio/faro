from __future__ import annotations

from collector.local_repository import LocalPostgresRepository
from collector.schema_check import REQUIRED_ML_RELATIONS, check_relations


def test_check_relations_marks_available_tables(repository: LocalPostgresRepository) -> None:
    statuses = check_relations(repository, relations=("features_daily", "prediction_feedback"))

    assert [status.available for status in statuses] == [True, True]


def test_check_relations_reports_missing_relation_after_drop(
    repository: LocalPostgresRepository,
    db_connection,
) -> None:
    with db_connection.cursor() as cur:
        cur.execute("DROP TABLE features_daily")

    statuses = check_relations(repository, relations=("features_daily", "model_runs"))

    assert statuses[0].name == "features_daily"
    assert statuses[0].available is False
    assert statuses[1].name == "model_runs"
    assert statuses[1].available is True


def test_required_ml_relations_excludes_dead_tables_and_uses_scope_only_name() -> None:
    assert "risk_limits" not in REQUIRED_ML_RELATIONS
    assert "signals" not in REQUIRED_ML_RELATIONS
    assert "user_risk_profiles" not in REQUIRED_ML_RELATIONS
    assert "risk_profiles" in REQUIRED_ML_RELATIONS
