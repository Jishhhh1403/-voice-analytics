from __future__ import annotations

from app.intelligence.problem_dimensions.coefficients import build_equations, calculate_relative_shares
from app.intelligence.problem_dimensions.feature_builder import FeatureRow, resolve_feature_specs
from app.intelligence.problem_dimensions.preprocessing import prepare_frame


def test_relative_squared_coordinate_shares_are_signed_agnostic_and_ranked():
    dimensions = [
        {"dimension_id": "D1", "dimension_number": 1, "factor_id": "F1"},
        {"dimension_id": "D2", "dimension_number": 2, "factor_id": "F2"},
    ]
    scores = [
        {"problem_id": "P1", "dimension_id": "D1", "coordinate": -3.0},
        {"problem_id": "P1", "dimension_id": "D2", "coordinate": 4.0},
        {"problem_id": "P2", "dimension_id": "D1", "coordinate": 0.0},
        {"problem_id": "P2", "dimension_id": "D2", "coordinate": 0.0},
    ]

    enriched = calculate_relative_shares(scores, dimensions)
    p1 = {item["dimension_id"]: item for item in enriched if item["problem_id"] == "P1"}
    p2 = {item["dimension_id"]: item for item in enriched if item["problem_id"] == "P2"}

    assert p1["D1"]["relative_squared_coordinate_share_pct"] == 36.0
    assert p1["D2"]["relative_squared_coordinate_share_pct"] == 64.0
    assert p1["D1"]["coordinate_rank"] == 2
    assert p1["D2"]["coordinate_rank"] == 1
    assert p2["D1"]["relative_squared_coordinate_share_pct"] is None
    assert p2["D2"]["relative_squared_coordinate_share_pct"] is None


def test_equations_preserve_signed_coefficients():
    dimensions = [
        {"dimension_id": "D1", "dimension_number": 1, "factor_id": "F1"},
        {"dimension_id": "D2", "dimension_number": 2, "factor_id": "F2"},
    ]
    scores = [
        {
            "problem_id": "P1",
            "dimension_id": "D1",
            "coordinate": -0.5,
            "relative_squared_coordinate_share_pct": 20.0,
            "coordinate_rank": 2,
        },
        {
            "problem_id": "P1",
            "dimension_id": "D2",
            "coordinate": 1.25,
            "relative_squared_coordinate_share_pct": 80.0,
            "coordinate_rank": 1,
        },
    ]

    equation = build_equations(scores, dimensions)[0]
    assert equation["equation_text"] == "P1 = - 0.500000*F1 + 1.250000*F2"
    assert equation["number_of_dimensions"] == 2
    assert equation["coefficient_representation"][0]["coefficient"] == -0.5


def test_feature_roles_are_configurable_and_constant_features_are_dropped():
    specs = resolve_feature_specs(
        active_features="journey_module,evidence_volume",
        supplementary_features="evidence_confidence",
        excluded_features="",
    )
    assert [spec.name for spec in specs] == ["journey_module", "evidence_volume", "evidence_confidence"]
    assert specs[-1].role == "supplementary"

    rows = [
        FeatureRow(problem_id="P1", values={"journey_module": "payments", "evidence_volume": 1.0}),
        FeatureRow(problem_id="P2", values={"journey_module": "payments", "evidence_volume": 2.0}),
    ]
    prepared = prepare_frame(rows, specs)
    assert "journey_module" not in prepared.frame.columns
    assert "journey_module" in prepared.metadata["dropped_constant_features"]
    assert "evidence_confidence" not in prepared.frame.columns
