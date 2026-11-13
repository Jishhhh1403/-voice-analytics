from __future__ import annotations

from app.intelligence.problem_dimensions.data_quality import run_quality_checks
from app.intelligence.problem_dimensions.feature_builder import FEATURE_SPECS, FORBIDDEN_FEATURES, FeatureRow


def test_feature_contract_has_no_identifiers_or_priority_fields():
    names = {spec.name for spec in FEATURE_SPECS}
    assert not (names & FORBIDDEN_FEATURES)
    assert "problem_id" not in names
    assert "mds_x" not in names and "mds_y" not in names
    assert "priority_score" not in names
    assert "feedback_text" not in names


def test_quality_check_detects_forbidden_feature_values():
    rows = [
        FeatureRow(
            problem_id="P1",
            values={
                "aspect": "reliability",
                "evidence_volume": 1.0,
                "priority_score": 0.9,
            },
        )
    ]
    checks = run_quality_checks(rows, FEATURE_SPECS, min_problems=1)
    forbidden = next(check for check in checks if check["name"] == "forbidden_features")
    assert forbidden["status"] == "FAIL"
