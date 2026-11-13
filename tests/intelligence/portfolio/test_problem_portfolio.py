from __future__ import annotations

from app.intelligence.portfolio.contracts import (
    EvidenceReference,
    FactorInterpretation,
    NarrativeFinding,
    PortfolioAction,
    PortfolioNarrative,
)
from app.intelligence.portfolio.serialization import build_narrative_context, build_portfolio_serialization
from app.intelligence.portfolio.validation import validate_portfolio_narrative


def _valid_narrative() -> PortfolioNarrative:
    return PortfolioNarrative(
        title="Customer problem portfolio",
        executive_summary=(
            "The portfolio groups recurring customer friction into two approved themes. "
            "The evidence is associative and does not establish causal effects."
        ),
        key_findings=[
            NarrativeFinding(
                title="Payment friction is the most concentrated theme",
                narrative=(
                    "Payment transfer problems carry the strongest payment reliability signal "
                    "and also show high customer impact."
                ),
                business_implication="Prioritise payment reliability remediation before broader clarity work.",
                confidence="high",
                evidence=[
                    EvidenceReference(problem_id="PRB-001", factor_name="Payments reliability"),
                    EvidenceReference(problem_id="PRB-001", metric_name="negative_share"),
                ],
            )
        ],
        factor_interpretations=[
            FactorInterpretation(
                factor_name="Payments reliability",
                interpretation="This theme groups problems where payment task completion is unreliable.",
                common_problem_patterns=["Pending transfers", "Failed payment confirmation"],
                business_implication="Reduce repeat payment failures and unclear transfer status.",
                confidence="high",
                evidence=[EvidenceReference(problem_id="PRB-001", factor_name="Payments reliability")],
            ),
            FactorInterpretation(
                factor_name="Self-service clarity",
                interpretation="This theme groups problems where customers cannot complete self-service tasks.",
                common_problem_patterns=["Statement download failure", "Unclear card activation"],
                business_implication="Improve task guidance and recovery paths in digital servicing.",
                confidence="medium",
                evidence=[EvidenceReference(problem_id="PRB-002", factor_name="Self-service clarity")],
            ),
        ],
        recommended_actions=[
            PortfolioAction(
                action="Investigate payment transfer status handling and customer recovery messaging.",
                rationale="Payment problems have the highest priority rank and the strongest payment theme signal.",
                horizon="now",
                evidence=[EvidenceReference(problem_id="PRB-001", factor_name="Payments reliability")],
            )
        ],
        data_limitations=[
            "Some measurements are missing and remain missing rather than zero.",
            "FAMD factor scores and coordinate shares are statistical associations, not causal effects.",
        ],
        methodology_notes=[
            "Portfolio themes come from an approved factor nomenclature.",
            "MDS coordinates provide relative positioning only and have no business axis meaning.",
        ],
    )


class FakeNarrativeProvider:
    provider = "fake"
    model_id = "fake-model"

    def __init__(self, narrative: PortfolioNarrative) -> None:
        self.narrative = narrative
        self.calls = 0

    def generate(self, serialization, correction=None):
        self.calls += 1
        return self.narrative


def test_serialization_preserves_missing_values_and_uses_euclidean_distances(portfolio_client):
    _, app, feedback_run_id, dimension_run_id = portfolio_client

    payload = build_portfolio_serialization(
        app.state.repo,
        feedback_run_id,
        dimension_run_id,
        mds_id="MDS-PORTFOLIO-TEST",
        neighbor_limit=8,
    )

    assert payload["source"]["counts"]["problems_in_run"] == 3
    assert [item["business_name"] for item in payload["factor_nomenclature"]] == [
        "Payments reliability",
        "Self-service clarity",
    ]
    problem = next(item for item in payload["problems"] if item["problem_id"] == "PRB-001")
    missing = problem["measurements"]["assessment_velocity_delta"]
    assert missing["value"] is None
    assert missing["status"] == "NO_DATA"

    relationship = next(
        item
        for item in payload["mds_relationships"]
        if item["problem_id"] == "PRB-001" and item["neighbor_problem_id"] == "PRB-002"
    )
    assert relationship["euclidean_distance"] == 5.0
    assert relationship["distance_space"] == "raw_mds_coordinates"
    assert payload["source"]["portfolio_distance_metric"] == "euclidean"
    assert payload["interpretation_constraints"]


def test_validation_rejects_technical_ids_and_causal_language(portfolio_client):
    _, app, feedback_run_id, dimension_run_id = portfolio_client
    serialization = build_portfolio_serialization(
        app.state.repo,
        feedback_run_id,
        dimension_run_id,
        mds_id="MDS-PORTFOLIO-TEST",
    )

    valid = validate_portfolio_narrative(_valid_narrative(), serialization)
    assert valid["status"] == "PASSED", valid

    invalid_narrative = _valid_narrative().model_copy(deep=True)
    invalid_narrative.key_findings[0].narrative = "F1 causes payment failures because of D1."
    invalid = validate_portfolio_narrative(invalid_narrative, serialization)
    assert invalid["status"] == "FAILED"
    assert invalid["errors"]


def test_portfolio_run_generates_serialization_narrative_and_validation(portfolio_client):
    client, app, feedback_run_id, dimension_run_id = portfolio_client
    provider = FakeNarrativeProvider(_valid_narrative())
    app.state.problem_portfolio.narrative_provider = provider

    response = client.post(
        "/api/v1/problem-portfolio/runs?background=false",
        json={
            "feedback_run_id": feedback_run_id,
            "dimension_run_id": dimension_run_id,
            "mds_id": "MDS-PORTFOLIO-TEST",
            "force_rerun": True,
            "generate_narrative": True,
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]

    run_response = client.get(f"/api/v1/problem-portfolio/runs/{run_id}")
    assert run_response.status_code == 200, run_response.text
    run = run_response.json()
    assert run["status"] == "COMPLETED"
    assert run["stage"] == "COMPLETED"
    assert run["narrative"]["status"] == "PASSED"
    assert len(run["factor_nomenclature"]) == 2

    serialization_response = client.get(f"/api/v1/problem-portfolio/runs/{run_id}/serialization")
    assert serialization_response.status_code == 200, serialization_response.text
    serialization = serialization_response.json()["payload"]
    assert serialization["source"]["counts"]["problems_in_run"] == 3
    assert serialization["portfolio_summary"]["provisional_factor_names"] == []

    narrative_response = client.get(f"/api/v1/problem-portfolio/runs/{run_id}/narrative")
    assert narrative_response.status_code == 200, narrative_response.text
    narrative = narrative_response.json()
    assert narrative["status"] == "PASSED"
    assert narrative["narrative"]["title"] == "Customer problem portfolio"

    validation_response = client.get(f"/api/v1/problem-portfolio/runs/{run_id}/validation")
    assert validation_response.status_code == 200, validation_response.text
    assert validation_response.json()["status"] == "PASSED"

    regenerate = client.post(
        f"/api/v1/problem-portfolio/runs/{run_id}/narrative/regenerate",
        json={"force": True},
    )
    assert regenerate.status_code == 200, regenerate.text
    assert regenerate.json()["narrative"]["status"] == "PASSED"
    assert provider.calls == 2


def test_portfolio_run_without_provider_keeps_serialization_available(portfolio_client):
    client, app, feedback_run_id, dimension_run_id = portfolio_client
    app.state.problem_portfolio.narrative_provider = None

    response = client.post(
        "/api/v1/problem-portfolio/runs?background=false",
        json={
            "feedback_run_id": feedback_run_id,
            "dimension_run_id": dimension_run_id,
            "mds_id": "MDS-PORTFOLIO-TEST",
            "force_rerun": True,
            "generate_narrative": True,
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]

    run = client.get(f"/api/v1/problem-portfolio/runs/{run_id}").json()
    assert run["status"] == "SERIALIZED"
    assert run["narrative"]["status"] == "UNAVAILABLE"
    assert client.get(f"/api/v1/problem-portfolio/runs/{run_id}/serialization").status_code == 200


def test_narrative_context_is_bounded_but_indexes_every_problem(portfolio_client):
    _, app, feedback_run_id, dimension_run_id = portfolio_client
    serialization = build_portfolio_serialization(
        app.state.repo,
        feedback_run_id,
        dimension_run_id,
        mds_id="MDS-PORTFOLIO-TEST",
    )

    context = build_narrative_context(serialization, max_problems=2, max_neighbors=1)

    assert context["context_scope"]["full_serialization_retained"] is True
    assert len(context["problems"]) == 2
    assert len(context["problem_index"]) == 3
    assert len(context["factor_nomenclature"]) == 2
    assert all(len(problem["mds_neighbors"]) <= 1 for problem in context["problems"])
