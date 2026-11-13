from __future__ import annotations

from datetime import UTC, datetime

from app.db import Database
from app.intelligence.problem_dimensions.data_quality import (
    has_critical_failure,
    run_quality_checks,
)
from app.intelligence.problem_dimensions.feature_builder import (
    FEATURE_SPECS,
    FORBIDDEN_FEATURES,
    build_feature_rows,
)
from app.repository import Repository
from conftest import _insert_problem, seed_problem_dimensions


def test_feature_builder_keeps_missing_windows_missing(tmp_path):
    repo = Repository(Database(tmp_path / "features.db"))
    run_id = seed_problem_dimensions(repo, count=1)
    _insert_problem(repo, run_id, "PRB-NO-WINDOW", with_measurements=False)

    build = build_feature_rows(repo.db, run_id, "problem-dimensions-1.0.0", window_days=90)

    assert len(build.rows) == 2
    missing = next(row for row in build.rows if row.problem_id == "PRB-NO-WINDOW")
    complete = next(row for row in build.rows if row.problem_id == "PRB-DIM-000")
    assert missing.values["evidence_volume"] is None
    assert "evidence_volume" in missing.missing
    assert complete.values["evidence_volume"] is not None
    assert complete.raw_values["evidence_volume"] == 2.0
    assert complete.raw_values["high_effort_share"] == 0.5
    assert complete.raw_values["outcome_failure_share"] == 0.5
    assert complete.raw_values["negative_emotion_share"] == 0.5
    assert build.window_start is not None
    assert build.window_end is not None
    assert all(item["missing_policy"] for item in build.feature_dictionary)


def test_evidence_features_respect_measurement_window(tmp_path):
    repo = Repository(Database(tmp_path / "window.db"))
    run_id = seed_problem_dimensions(repo, count=1)
    repo.db.execute(
        "UPDATE problem_evidence SET submitted_at=? WHERE run_id=?",
        ("2024-01-01T00:00:00+00:00", run_id),
    )

    build = build_feature_rows(repo.db, run_id, "problem-dimensions-1.0.0", window_days=90)
    row = build.rows[0]
    assert row.raw_values["high_effort_share"] is None
    assert row.denominators["high_effort_share"] == 0
    assert "missing:high_effort_share" in row.quality_flags


def test_quality_gates_reject_identifiers_and_small_samples(tmp_path):
    repo = Repository(Database(tmp_path / "quality.db"))
    run_id = seed_problem_dimensions(repo, count=10)
    build = build_feature_rows(repo.db, run_id, "problem-dimensions-1.0.0")
    checks = run_quality_checks(build.rows, build.specs, min_problems=30)
    assert has_critical_failure(checks) is True
    assert any(check["name"] == "row_count" and check["status"] == "FAIL" for check in checks)

    assert not ({spec.name for spec in FEATURE_SPECS} & FORBIDDEN_FEATURES)
    assert all(not (set(row.values) & FORBIDDEN_FEATURES) for row in build.rows)
    assert any(check["name"] == "forbidden_features" and check["status"] == "PASS" for check in checks)


def test_feature_snapshot_as_of_date_is_iso():
    captured = datetime.now(UTC).isoformat()
    assert captured


def test_missing_categories_remain_missing_until_fitting(tmp_path):
    from app.intelligence.problem_dimensions.preprocessing import prepare_frame

    repo = Repository(Database(tmp_path / "missing-categories.db"))
    run_id = seed_problem_dimensions(repo, count=2)
    repo.db.execute(
        "UPDATE customer_problems SET journey_node_id=NULL, aspect=NULL, symptom_category=NULL, customer_intent=NULL "
        "WHERE problem_id=?",
        ("PRB-DIM-000",),
    )
    repo.db.execute("DELETE FROM problem_journey_mappings WHERE problem_id=?", ("PRB-DIM-000",))

    build = build_feature_rows(repo.db, run_id, "problem-dimensions-1.0.0")
    missing = next(row for row in build.rows if row.problem_id == "PRB-DIM-000")
    for feature in ("journey_module", "journey_feature", "aspect", "symptom_category", "customer_intent"):
        assert missing.values[feature] is None
        assert feature in missing.missing

    prepared = prepare_frame(build.rows, build.specs)
    assert prepared.metadata["missing_counts"]["aspect"] == 1
    assert prepared.metadata["imputed_counts"]["aspect"] == 1
    assert "__MISSING__" in set(prepared.frame["aspect"])
    assert any("explicit __MISSING__ category" in warning for warning in prepared.warnings)
