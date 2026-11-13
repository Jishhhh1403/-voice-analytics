from __future__ import annotations

import json
from typing import Any

import pytest

from app.intelligence.portfolio.serialization import build_portfolio_serialization
from app.intelligence.problem_dimensions.llm import LLMFactorInterpretationPipeline
from app.intelligence.problem_dimensions.llm.equation_serializer import FactorEquationSerializer
from app.intelligence.problem_dimensions.llm.taxonomy_context import BankingTaxonomyContextBuilder
from app.intelligence.problem_dimensions.llm.validation import NomenclatureValidationService

_NAMES = [
    "Payment completion reliability",
    "Card servicing clarity",
    "Account information confidence",
    "Digital onboarding friction",
    "Customer support resolution",
    "Statement access continuity",
    "Transfer status transparency",
    "Beneficiary setup reliability",
    "Authentication recovery experience",
    "Loan application guidance",
    "Deposit servicing continuity",
    "Notification usefulness",
    "App navigation stability",
    "Profile update effort",
    "Security verification experience",
    "Dispute handling confidence",
]


class FakeStructuredProvider:
    provider = "fake"
    model_id = "fake-gemini-model"

    def __init__(self, *, fail_nomenclature: bool = False) -> None:
        self.fail_nomenclature = fail_nomenclature
        self.calls: list[str] = []
        self.payloads: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        prompt_version: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        title = schema.get("title", "")
        self.calls.append(title)
        payload = json.loads(prompt)
        self.payloads.append(payload)
        if title == "FactorNomenclatureProposal":
            if self.fail_nomenclature:
                raise RuntimeError("simulated nomenclature failure")
            equation = payload["factor_equation"]
            factor_id = payload["required_factor_id"]
            dimension_id = payload["required_dimension_id"]
            number = int(factor_id.removeprefix("F")) if factor_id.startswith("F") else 1
            name = _NAMES[(number - 1) % len(_NAMES)]
            variables = [
                item["variable_name"] for item in equation.get("variable_contributions") or []
            ]
            categories = [
                f"{item['variable_name']}={item['category_level']}"
                for item in equation.get("category_contributions") or []
            ]
            return {
                "factor_id": factor_id,
                "dimension_id": dimension_id,
                "proposed_name": name,
                "short_name": name.split()[0],
                "formal_definition": "A customer-experience construct supported by the factor equation.",
                "business_interpretation": "Customers need a clearer and more reliable journey.",
                "banking_domain": "Payments",
                "journey_scope": "Digital self-service journey",
                "core_customer_experience": "Confidence and completion when using the journey.",
                "supporting_variables": variables[:5],
                "supporting_categories": categories[:5],
                "representative_problem_ids": equation["representative_problem_ids"][:10],
                "contradictory_problem_ids": equation["negative_problem_ids"][:5],
                "distinguishing_characteristics": "Supported by a distinct journey and variable pattern.",
                "confidence": 0.82,
                "confidence_explanation": "Consistent variable contributions and problem equations.",
                "nomenclature_status": "PROVISIONAL",
            }
        if title == "CrossDimensionReview":
            return {
                "status": "PASSED",
                "findings": [],
                "summary": "All retained factors have distinct business interpretations.",
            }
        raise AssertionError(f"unexpected schema {title}")


@pytest.fixture
def llm_dimension_client(dimension_client):
    client, app, feedback_run_id = dimension_client
    provider = FakeStructuredProvider()
    app.state.problem_dimensions.factor_interpretation = LLMFactorInterpretationPipeline(
        app.state.settings, app.state.repo, provider=provider
    )
    created = client.post(
        "/api/v1/problem-dimensions/runs",
        params={"background": False},
        json={"feedback_run_id": feedback_run_id, "max_components": 4, "force_rerun": True},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]
    return client, app, run_id, provider


def test_equation_serializer_preserves_all_signed_coordinates(llm_dimension_client):
    _, app, run_id, _ = llm_dimension_client
    contract = FactorEquationSerializer(app.state.repo).serialize(run_id)
    assert contract["schema_version"] == "factor-equation-serialization-1.0.0"
    assert len(contract["retained_dimension_ids"]) == 4
    assert contract["problems"]
    for problem in contract["problems"]:
        assert len(problem["coefficients"]) == 4
        assert len(problem["dimension_evidence"]) == 4
        assert "=" in problem["equation_text"]
    signed = [
        coefficient["coefficient"]
        for problem in contract["problems"]
        for coefficient in problem["coefficients"]
    ]
    assert any(value < 0 for value in signed)
    assert any(value > 0 for value in signed)


def test_taxonomy_context_uses_repository_taxonomy_and_marks_missing(llm_dimension_client):
    _, app, run_id, _ = llm_dimension_client
    run = app.state.repo.get_dimension_run(run_id)
    feedback_run = app.state.repo.get_run(run["feedback_run_id"])
    context = BankingTaxonomyContextBuilder(app.state.settings, app.state.repo).build(
        feedback_run.get("taxonomy_version")
    )
    assert context["version"]
    assert context["banking_domains"]
    assert context["journey_context_fields"]
    assert context["process_knowledge"]
    labels = " ".join(item["display_name"] for item in context["banking_domains"]).casefold()
    assert "payments" in labels
    assert isinstance(context["missing_supported_domains"], list)


def test_pipeline_makes_one_factor_nomenclature_call_per_factor(llm_dimension_client):
    client, app, run_id, provider = llm_dimension_client
    status = client.get(f"/api/v1/problem-dimensions/runs/{run_id}/interpretation")
    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["provider_configured"] is True
    assert len(payload["dimensions"]) == 4
    assert all(item["processed_problems"] > 0 for item in payload["dimensions"])
    assert all(item["failed_problems"] == 0 for item in payload["dimensions"])
    assert provider.calls.count("FactorNomenclatureProposal") == 4
    assert "ProblemObservationBatch" not in provider.calls
    assert "DimensionEvidenceAggregation" not in provider.calls

    run = client.get(f"/api/v1/problem-dimensions/runs/{run_id}").json()
    for definition in run["definitions"]:
        detail = client.get(
            f"/api/v1/problem-dimensions/runs/{run_id}/dimensions/{definition['dimension_id']}/interpretation"
        )
        assert detail.status_code == 200, detail.text
        equation = detail.json()["factor_equation"]
        assert equation["problem_count"] > 0
        assert equation["variable_contributions"]
        assert equation["representative_problem_equations"]
        assert detail.json()["proposal"]["proposal"]["proposed_name"]


def test_problem_focused_naming_uses_problem_equation_and_taxonomy(llm_dimension_client):
    client, _, run_id, provider = llm_dimension_client
    matrix = client.get(f"/api/v1/problem-dimensions/runs/{run_id}/coefficients").json()
    problem_id = matrix["coefficients"][0]["problem_id"]
    calls_before = len(provider.calls)
    payloads_before = len(provider.payloads)

    response = client.post(
        f"/api/v1/problem-dimensions/runs/{run_id}/problems/{problem_id}/name-factors",
        json={"force": True},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "COMPLETED"
    assert result["focused_problem_id"] == problem_id
    assert all(item["status"] == "COMPLETED" for item in result["dimensions"].values())
    assert provider.calls[calls_before:].count("FactorNomenclatureProposal") == 4

    focused_payloads = [
        payload
        for payload in provider.payloads[payloads_before:]
        if "factor_equation" in payload
    ]
    assert len(focused_payloads) == 4
    for payload in focused_payloads:
        equation = payload["factor_equation"]
        assert equation["focused_problem_id"] == problem_id
        assert equation["focused_problem_equation"]["canonical_problem_id"] == problem_id
        assert equation["representative_problem_ids"][0] == problem_id
        assert payload["banking_taxonomy_context"]["banking_domains"]


def test_llm_names_remain_draft_and_portfolio_resolves_them_as_provisional(llm_dimension_client):
    client, app, run_id, _ = llm_dimension_client
    run = client.get(f"/api/v1/problem-dimensions/runs/{run_id}").json()
    assert run["status"] == "PENDING_REVIEW"
    assert run["definitions"]
    assert all(item["review_status"] == "DRAFT" for item in run["definitions"])
    assert all(item["nomenclature_source"] == "LLM" for item in run["definitions"])
    assert all(item["proposed_label"] for item in run["definitions"])

    serialization = build_portfolio_serialization(
        app.state.repo,
        run["feedback_run_id"],
        run_id,
        require_approved_factors=False,
    )
    assert serialization["factor_nomenclature"]
    assert all(item["nomenclature_status"] == "PROVISIONAL" for item in serialization["factor_nomenclature"])
    assert all(item["source"] == "LLM" for item in serialization["factor_nomenclature"])

    definition = run["definitions"][0]
    response = client.post(
        f"/api/v1/problem-dimensions/runs/{run_id}/dimensions/{definition['dimension_id']}/review",
        json={
            "reviewer": "analyst@example.com",
            "decision": "approve",
            "name": "Approved payment reliability",
            "note": "Approved after reviewing the factor equation.",
        },
    )
    assert response.status_code == 200, response.text
    reviewed = response.json()
    approved = next(
        item for item in reviewed["definitions"] if item["dimension_id"] == definition["dimension_id"]
    )
    assert approved["analyst_name"] == "Approved payment reliability"
    history = app.state.repo.db.query(
        "SELECT * FROM human_review_decisions WHERE entity_type='problem_dimension' AND entity_id=?",
        (f"{run_id}:{definition['dimension_id']}",),
    )
    assert history
    assert history[-1]["original_value"] == definition["analyst_name"]


def test_resume_does_not_repeat_successful_work(llm_dimension_client):
    client, app, run_id, provider = llm_dimension_client
    calls_before = len(provider.calls)
    response = client.post(
        f"/api/v1/problem-dimensions/runs/{run_id}/interpretation/regenerate",
        json={"force": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETED"
    assert len(provider.calls) == calls_before


def test_validation_detects_technical_and_overlapping_names(dimension_client):
    validator = NomenclatureValidationService()
    proposal = {
        "factor_id": "F1",
        "dimension_id": "D1",
        "proposed_name": "F1",
        "short_name": "F1",
        "formal_definition": "A valid definition.",
        "business_interpretation": "A valid interpretation.",
        "banking_domain": "Payments",
        "journey_scope": "Payments",
        "core_customer_experience": "Completion.",
        "supporting_variables": ["journey_module"],
        "supporting_categories": [],
        "representative_problem_ids": ["PRB-DIM-000"],
        "contradictory_problem_ids": [],
        "distinguishing_characteristics": "Distinct.",
        "confidence": 0.8,
        "confidence_explanation": "Evidence.",
        "nomenclature_status": "PROVISIONAL",
    }
    result = validator.validate_proposal(
        proposal,
        dimension_id="D1",
        factor_id="F1",
        known_variables={"journey_module"},
        known_categories=set(),
        known_problem_ids={"PRB-DIM-000"},
    )
    assert result["status"] == "FAILED"
    overlap = validator.detect_overlaps(
        [
            {"dimension_id": "D1", "factor_id": "F1", "proposed_name": "Payment reliability"},
            {"dimension_id": "D2", "factor_id": "F2", "proposed_name": "Payment reliability"},
        ]
    )
    assert overlap["status"] == "REVIEW_REQUIRED"
    assert overlap["findings"]


def test_failed_nomenclature_leaves_factors_unnamed(dimension_client):
    client, app, feedback_run_id = dimension_client
    provider = FakeStructuredProvider(fail_nomenclature=True)
    app.state.problem_dimensions.factor_interpretation = LLMFactorInterpretationPipeline(
        app.state.settings, app.state.repo, provider=provider
    )
    created = client.post(
        "/api/v1/problem-dimensions/runs",
        params={"background": False},
        json={"feedback_run_id": feedback_run_id, "max_components": 2, "force_rerun": True},
    )
    run_id = created.json()["run_id"]
    run = client.get(f"/api/v1/problem-dimensions/runs/{run_id}").json()
    assert run["status"] == "PENDING_REVIEW"
    assert len(run["definitions"]) == 2
    assert all(item["nomenclature_source"] != "LLM" for item in run["definitions"])
    assert all(not item["analyst_name"] for item in run["definitions"])
    assert all(item["proposed_label"] is None for item in run["definitions"])
    assert run["diagnostics"]["llm_interpretation"]["status"] in {"FAILED", "PARTIAL"}


def test_provider_factory_supports_openai_compatible_local_endpoint(tmp_path):
    from app.config import Settings
    from app.intelligence.problem_dimensions.llm.gemini_client import (
        OpenAICompatibleStructuredProvider,
        build_structured_provider,
    )

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "factory.db",
        local_object_root=tmp_path / "objects",
        sample_feedback_path=tmp_path / "feedback.csv",
        sample_backlog_path=tmp_path / "backlog.csv",
        auto_seed_source=False,
        auto_run_sample=False,
        object_store="local",
        problem_dimension_llm_enabled=True,
        problem_dimension_llm_provider="openai_compatible",
        problem_dimension_llm_base_url="http://localhost:11434/v1",
        problem_dimension_llm_model="llama3.1",
        problem_dimension_llm_api_key="local",
    )
    provider = build_structured_provider(settings)
    assert isinstance(provider, OpenAICompatibleStructuredProvider)
    assert provider.model_id == "llama3.1"


def test_provider_factory_falls_back_when_gemini_key_is_missing():
    from app.config import Settings
    from app.intelligence.problem_dimensions.llm.gemini_client import (
        OpenAICompatibleStructuredProvider,
        build_structured_provider,
    )

    settings = Settings(
        problem_dimension_llm_enabled=True,
        problem_dimension_llm_provider="gemini",
        problem_dimension_llm_fallback_provider="openai_compatible",
        problem_dimension_llm_base_url="http://localhost:11434/v1",
        problem_dimension_llm_model="llama3.1",
        gemini_api_key="",
    )
    provider = build_structured_provider(settings)
    assert isinstance(provider, OpenAICompatibleStructuredProvider)


class FakeNarrativeAgent:
    available = True

    def __init__(self, settings: Any, repo: Any) -> None:
        from app.intelligence.problem_dimensions.llm.narrative_agent import (
            FactorNarrativeEvidenceBuilder,
        )

        self.settings = settings
        self.evidence = FactorNarrativeEvidenceBuilder(settings, repo)

    def generate(self, run_id: str) -> dict[str, Any]:
        evidence = self.evidence.build(run_id)
        factors = []
        for index, item in enumerate(evidence["factors"], start=1):
            factors.append(
                {
                    "factor_id": item["factor_id"],
                    "dimension_id": item["dimension_id"],
                    "name": f"Narrative factor {index}",
                    "short_name": f"Narrative {index}",
                    "description": "A customer-experience construct grounded in the problem equations.",
                    "business_interpretation": "Customers experience a distinct journey pattern.",
                    "banking_domain": "Payments",
                    "journey_scope": "Digital banking journey",
                    "core_customer_experience": "Completion and confidence.",
                    "confidence": 0.8,
                    "confidence_explanation": "The factor separates consistent positive and negative problem patterns.",
                }
            )
        return {
            "status": "COMPLETED",
            "summary": "All factors were named from the complete problem population.",
            "factors": factors,
            "taxonomy_version": evidence["taxonomy_version"],
            "total_problems": evidence["total_problems"],
            "total_factors": evidence["total_factors"],
            "model_name": "fake-langchain-agent",
            "prompt_version": self.settings.problem_dimension_factor_narrative_prompt_version,
            "agent_version": "fake-agent-1.0.0",
        }


def test_narrative_evidence_covers_every_problem_equation(llm_dimension_client):
    _, app, run_id, _ = llm_dimension_client
    from app.intelligence.problem_dimensions.llm.narrative_agent import (
        FactorNarrativeEvidenceBuilder,
    )

    serializer = FactorEquationSerializer(app.state.repo)
    contract = serializer.serialize(run_id)
    evidence = FactorNarrativeEvidenceBuilder(app.state.settings, app.state.repo).build(run_id)
    assert evidence["total_problems"] == len(contract["problems"])
    assert evidence["total_factors"] == len(contract["retained_dimension_ids"]) == 4
    assert len(evidence["problems"]) == evidence["total_problems"]
    assert {item["factor_id"] for item in evidence["factors"]} == set(contract["factor_by_dimension"].values())
    for problem in evidence["problems"]:
        assert len(problem["coefficients"]) == evidence["total_factors"]
    assert evidence["banking_taxonomy_context"]["banking_domains"]


def test_narrative_serialization_persists_all_factors_and_applies_names(llm_dimension_client):
    client, app, run_id, _ = llm_dimension_client
    app.state.problem_dimensions.factor_narrative = FakeNarrativeAgent(
        app.state.settings,
        app.state.repo,
    )
    before = client.get(f"/api/v1/problem-dimensions/runs/{run_id}/narrative-serialization")
    assert before.status_code == 200, before.text
    assert before.json()["available"] is True
    assert before.json()["serialization"] is None

    response = client.post(f"/api/v1/problem-dimensions/runs/{run_id}/narrative-serialization")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["serialization"]["status"] == "COMPLETED"
    assert body["serialization"]["agent_version"] == "fake-agent-1.0.0"
    assert len(body["serialization"]["payload"]["factors"]) == 4
    assert body["serialization"]["payload"]["total_problems"] > 0

    latest = client.get(f"/api/v1/problem-dimensions/runs/{run_id}/narrative-serialization").json()
    assert latest["serialization"]["serialization_id"] == body["serialization"]["serialization_id"]
    run = client.get(f"/api/v1/problem-dimensions/runs/{run_id}").json()
    assert all(item["nomenclature_source"] == "LANGCHAIN_AGENT" for item in run["definitions"])
    assert all(item["review_status"] == "DRAFT" for item in run["definitions"])
    assert all(item["analyst_name"].startswith("Narrative factor") for item in run["definitions"])


def test_narrative_agent_classifies_upstream_errors_without_exposing_raw_details():
    from app.intelligence.problem_dimensions.llm.narrative_agent import (
        _error_kind,
        _friendly_error,
    )

    quota = RuntimeError(
        "429 RESOURCE_EXHAUSTED. Quota exceeded. Please retry in 14h13m44.16487868s."
    )
    assert _error_kind(quota) == "quota"
    quota_message = _friendly_error("gemini-3.8-flash", quota, 1)
    assert "quota is exhausted" in quota_message
    assert "14h13m44" in quota_message
    assert "RESOURCE_EXHAUSTED" not in quota_message

    transient = RuntimeError(
        "[SSL: UNEXPECTED_EOF_WHILE_READING] unexpected eof while reading"
    )
    assert _error_kind(transient) == "transient"
    transient_message = _friendly_error("gemini-3.8-flash", transient, 3)
    assert "closed the connection" in transient_message
    assert "3 attempt(s)" in transient_message
    assert "UNEXPECTED_EOF" not in transient_message

    invalid = ValueError("Agent factor coverage mismatch; missing=['F1']")
    assert _error_kind(invalid) == "invalid"
    assert "incomplete or invalid" in _friendly_error("model", invalid, 2)


def test_narrative_agent_retries_transient_ssl_failure(monkeypatch, llm_dimension_client):
    from app.intelligence.problem_dimensions.llm import narrative_agent as narrative_module
    from app.intelligence.problem_dimensions.llm.contracts import (
        FactorNarrativeSerializationProposal,
    )
    from app.intelligence.problem_dimensions.llm.narrative_agent import FactorNarrativeAgent

    _, app, run_id, _ = llm_dimension_client
    agent = FactorNarrativeAgent(app.state.settings, app.state.repo, models=[object()])
    evidence = agent.evidence_builder.build(run_id)
    factors = []
    for index, item in enumerate(evidence["factors"], start=1):
        factors.append(
            {
                "factor_id": item["factor_id"],
                "dimension_id": item["dimension_id"],
                "name": f"Retry narrative factor {index}",
                "short_name": f"Retry {index}",
                "description": "A grounded factor description.",
                "business_interpretation": "A grounded business interpretation.",
                "banking_domain": "Payments",
                "journey_scope": "Digital journey",
                "core_customer_experience": "Completion and confidence.",
                "problem_count": item["problem_count"],
                "problem_share_pct": item["problem_share_pct"],
                "explained_variance_pct": item["explained_variance_pct"],
                "cumulative_variance_pct": item["cumulative_variance_pct"],
                "mean_coefficient": item["mean_coefficient"],
                "mean_abs_coefficient": item["mean_abs_coefficient"],
                "min_coefficient": item["min_coefficient"],
                "max_coefficient": item["max_coefficient"],
                "max_abs_coefficient": item["max_abs_coefficient"],
                "top_features": item["top_features"],
                "positive_problem_pattern": "Positive problem pattern.",
                "negative_problem_pattern": "Negative problem pattern.",
                "representative_problem_ids": item["representative_problem_ids"],
                "confidence": 0.8,
                "confidence_explanation": "Grounded in the supplied equations.",
            }
        )
    proposal = FactorNarrativeSerializationProposal.model_validate(
        {"summary": "A grounded narrative.", "factors": factors}
    )
    calls = {"count": 0}

    def fake_create_agent(**_: Any) -> Any:
        class FakeAgent:
            def invoke(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise RuntimeError("[SSL: UNEXPECTED_EOF_WHILE_READING] unexpected eof while reading")
                return {"structured_response": proposal}

        return FakeAgent()

    monkeypatch.setattr(narrative_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(narrative_module.time, "sleep", lambda _: None)
    result = agent.generate(run_id)
    assert result["status"] == "COMPLETED"
    assert calls["count"] == 2
    assert len(result["factors"]) == 4


def test_narrative_agent_builds_gemini_model_fallbacks():
    from app.config import Settings
    from app.intelligence.problem_dimensions.llm.narrative_agent import build_chat_models

    settings = Settings(
        problem_dimension_llm_enabled=True,
        problem_dimension_llm_provider="gemini",
        problem_dimension_llm_model="gemini-3.8-flash",
        problem_dimension_factor_narrative_model_fallbacks="gemini-3.6-flash,gemini-3.5-flash",
        gemini_api_key="test-key",
    )
    models = build_chat_models(settings)
    assert [getattr(model, "model", None) for model in models] == [
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ]
    assert all(getattr(model, "max_retries", None) == 0 for model in models)


def test_narrative_prompt_uses_compact_complete_evidence(llm_dimension_client):
    from app.intelligence.problem_dimensions.llm.narrative_agent import (
        FactorNarrativeEvidenceBuilder,
        _compact_prompt_evidence,
    )

    _, app, run_id, _ = llm_dimension_client
    evidence = FactorNarrativeEvidenceBuilder(app.state.settings, app.state.repo).build(run_id)
    compact = _compact_prompt_evidence(evidence)
    assert len(compact["problems"]) == evidence["total_problems"]
    assert compact["factor_order"] == [item["factor_id"] for item in evidence["factors"]]
    assert all(len(problem[-1]) == evidence["total_factors"] for problem in compact["problems"])
    assert compact["problem_columns"][-1] == "coefficients"
    assert "banking_features" not in compact["banking_taxonomy_context"]
    assert "equation" not in compact["problem_columns"]


def test_narrative_agent_falls_back_to_next_model_on_transient_failure(
    monkeypatch, llm_dimension_client
):
    from app.intelligence.problem_dimensions.llm import narrative_agent as narrative_module
    from app.intelligence.problem_dimensions.llm.contracts import (
        FactorNarrativeSerializationProposal,
    )
    from app.intelligence.problem_dimensions.llm.narrative_agent import FactorNarrativeAgent

    _, app, run_id, _ = llm_dimension_client
    agent = FactorNarrativeAgent(app.state.settings, app.state.repo, models=[object(), object()])
    evidence = agent.evidence_builder.build(run_id)
    factors = []
    for index, item in enumerate(evidence["factors"], start=1):
        factors.append(
            {
                "factor_id": item["factor_id"],
                "dimension_id": item["dimension_id"],
                "name": f"Fallback narrative factor {index}",
                "short_name": f"Fallback {index}",
                "description": "A grounded factor description.",
                "business_interpretation": "A grounded business interpretation.",
                "banking_domain": "Payments",
                "journey_scope": "Digital journey",
                "core_customer_experience": "Completion and confidence.",
                "problem_count": item["problem_count"],
                "problem_share_pct": item["problem_share_pct"],
                "explained_variance_pct": item["explained_variance_pct"],
                "cumulative_variance_pct": item["cumulative_variance_pct"],
                "mean_coefficient": item["mean_coefficient"],
                "mean_abs_coefficient": item["mean_abs_coefficient"],
                "min_coefficient": item["min_coefficient"],
                "max_coefficient": item["max_coefficient"],
                "max_abs_coefficient": item["max_abs_coefficient"],
                "top_features": item["top_features"],
                "positive_problem_pattern": "Positive problem pattern.",
                "negative_problem_pattern": "Negative problem pattern.",
                "representative_problem_ids": item["representative_problem_ids"],
                "confidence": 0.8,
                "confidence_explanation": "Grounded in the supplied coefficients.",
            }
        )
    proposal = FactorNarrativeSerializationProposal.model_validate(
        {"summary": "A grounded narrative.", "factors": factors}
    )
    calls = {"count": 0}

    def fake_create_agent(**kwargs: Any) -> Any:
        calls["count"] += 1
        current = calls["count"]

        class FakeAgent:
            def invoke(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                if current == 1:
                    raise RuntimeError("503 UNAVAILABLE: high demand")
                return {"structured_response": proposal}

        return FakeAgent()

    monkeypatch.setattr(narrative_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        narrative_module.time,
        "sleep",
        lambda _: (_ for _ in ()).throw(AssertionError("fallback should run before sleeping")),
    )
    result = agent.generate(run_id)
    assert result["status"] == "COMPLETED"
    assert calls["count"] == 2
