from __future__ import annotations

import random

from app.intelligence.problem_dimensions.famd_runner import run_famd
from app.intelligence.problem_dimensions.feature_builder import FEATURE_SPECS, FeatureRow
from app.intelligence.problem_dimensions.preprocessing import prepare_frame


def _rows(count: int = 48) -> list[FeatureRow]:
    modules = ["payments", "cards", "accounts", "onboarding", "support"]
    aspects = ["reliability", "clarity", "speed", "access"]
    rng = random.Random(11)
    rows: list[FeatureRow] = []
    for index in range(count):
        rows.append(
            FeatureRow(
                problem_id=f"P-{index}",
                values={
                    "journey_module": modules[index % len(modules)],
                    "journey_feature": f"feature-{index % 7}",
                    "aspect": aspects[index % len(aspects)],
                    "symptom_category": f"symptom-{index % 5}",
                    "customer_intent": f"intent-{index % 6}",
                    "evidence_volume": float(index % 8),
                    "distinct_customers": float(index % 5),
                    "negative_share": round(rng.random(), 3),
                    "repeat_complaint_rate": round(rng.random(), 3),
                    "source_diversity": float(1 + index % 4),
                    "high_effort_share": round(rng.random(), 3),
                    "outcome_failure_share": round(rng.random(), 3),
                    "negative_emotion_share": round(rng.random(), 3),
                    "volume_growth_pct": round(rng.uniform(-1, 1), 3),
                    "negative_share_change": round(rng.uniform(-1, 1), 3),
                },
            )
        )
    return rows


def test_famd_is_reproducible_and_returns_structured_contributions():
    prepared = prepare_frame(_rows(), list(FEATURE_SPECS))
    first = run_famd(prepared, list(FEATURE_SPECS), max_components=4, random_state=42)
    second = run_famd(prepared, list(FEATURE_SPECS), max_components=4, random_state=42)

    assert first.status == "OK"
    assert second.status == "OK"
    assert first.eigenvalues == second.eigenvalues
    assert first.percentage_of_variance == second.percentage_of_variance
    assert first.problem_scores == second.problem_scores
    assert first.dimensions[0]["dimension_id"] == "D1"
    assert first.dimensions[0]["top_variables"]
    assert first.dimensions[0]["variable_contributions"][0]["contribution"] >= 0
    assert first.diagnostics["n_problems"] == 48
    assert len(first.cumulative_percentage_of_variance) == len(first.dimensions)


def test_famd_rejects_too_few_rows():
    rows = _rows(count=2)
    prepared = prepare_frame(rows, list(FEATURE_SPECS))
    result = run_famd(prepared, list(FEATURE_SPECS), max_components=4)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.n_components == 0


def test_bootstrap_stability_and_optional_efa():
    from app.intelligence.problem_dimensions.efa_runner import run_efa
    from app.intelligence.problem_dimensions.famd_runner import bootstrap_stability

    prepared = prepare_frame(_rows(), list(FEATURE_SPECS))
    fitted = run_famd(prepared, list(FEATURE_SPECS), max_components=3, random_state=42)
    stability = bootstrap_stability(prepared, list(FEATURE_SPECS), fitted, iterations=2, random_state=42)
    assert stability["status"] == "RUN"
    assert stability["successful_iterations"] == 2
    assert len(stability["components"]) == 3
    assert all(item["iterations"] == 2 for item in stability["components"])

    efa = run_efa(prepared, list(FEATURE_SPECS), max_factors=3, random_state=42)
    assert efa.status == "OK"
    assert efa.n_factors == 3
    assert efa.factors
    assert efa.to_dict()["note"].startswith("EFA is an optional")
