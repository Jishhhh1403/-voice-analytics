from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from app.config import Settings
from app.intelligence import llm_client as llm_client_module
from app.intelligence.canonicalisation import CanonicalisationService
from app.intelligence.cluster_assignment import assign_clusters
from app.intelligence.coverage import CoverageAssessment, GreyZoneConsortium
from app.intelligence.embeddings import WeightedTfidfEmbedder
from app.intelligence.llm_client import StructuredLLMClient, StructuredResponse


def _settings(**overrides: object) -> Settings:
    return Settings(gemini_api_key="", openai_api_key="", **overrides)


def test_weighted_tfidf_normalises_component_weights() -> None:
    embedder = WeightedTfidfEmbedder(
        dimensions=32,
        weights={"journey_node": 0.4, "symptom": 0.35, "feedback": 0.25},
    )
    assert embedder.weights == {"journey_node": 0.4, "symptom": 0.35, "feedback": 0.25}
    components = [
        {
            "journey_node": "payments transfer beneficiary",
            "symptom": "transaction failed pending error",
            "feedback": "The payment failed and no status was shown",
        },
        {
            "journey_node": "statements download pdf",
            "symptom": "blank preview display error",
            "feedback": "The statement PDF is blank when downloaded",
        },
    ]
    vectors = embedder.fit_transform(components)
    assert vectors.shape[0] == 2
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)
    assert embedder.transform(components).shape == vectors.shape
    assert embedder.transform_texts(["retry payment failed"]).shape[1] == vectors.shape[1]


def test_assign_clusters_never_exceeds_max_cluster_size() -> None:
    settings = _settings(clustering_provider="hdbscan", max_cluster_size=8)
    rng = np.random.default_rng(7)
    vectors = rng.normal(size=(41, 16)).astype(np.float32)
    assignment = assign_clusters(vectors, settings)
    assert len(assignment.labels) == 41
    for label in set(assignment.labels):
        assert sum(value == label for value in assignment.labels) <= 8
    assert assignment.params["max_cluster_size"] == 8


class _FakeLLM:
    def __init__(self, payload: dict[str, object]) -> None:
        self.available = True
        self.payload = payload
        self.prompts: list[str] = []

    def generate_json(self, prompt: str) -> StructuredResponse:
        self.prompts.append(prompt)
        return StructuredResponse({"results": [{"index": 0, **dict(self.payload)}]}, "fake-provider", "fake-model")


def test_canonicalisation_gives_llm_configured_neighbors() -> None:
    client = _FakeLLM(
        {
            "title": "Beneficiary transfers fail without status",
            "description": "A shared transfer failure with unclear status",
            "problem_statement": "Transfers fail and the customer cannot tell whether they succeeded",
            "rationale": "The ten nearest reports share the same failure mode",
            "source_problem_ids": ["IN-1"],
        }
    )
    service = CanonicalisationService(_settings(), client)
    neighbors = [
        {"problem_id": f"IN-{index}", "text": f"transfer failed report {index}", "similarity": 1.0 - index / 100}
        for index in range(1, 13)
    ]
    result = service.define(neighbors)
    assert result.fallback is False
    assert result.provider == "fake-provider"
    assert result.model == "fake-model"
    assert client.prompts[0].count('"problem_id"') == 3
    assert "IN-4" not in client.prompts[0]
    deterministic = service.define_deterministic(neighbors)
    assert deterministic.fallback is True
    assert deterministic.title.startswith("transfer failed")


def test_canonicalisation_provider_llm_uses_configured_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        gemini_api_key="test-key",
        openai_api_key="",
        canonicalisation_provider="llm",
        canonicalisation_model="test-model",
    )
    client = StructuredLLMClient(
        settings,
        provider=settings.canonicalisation_provider,
        model=settings.canonicalisation_model or None,
    )
    assert client.available is True
    assert client.kind == "gemini"
    monkeypatch.setattr(
        StructuredLLMClient,
        "generate_json",
        lambda self, prompt: StructuredResponse(
            {
                "results": [
                    {
                        "index": 0,
                        "title": "LLM defined",
                        "problem_statement": "LLM statement",
                    }
                ]
            },
            "fake",
            "test-model",
        ),
    )
    result = CanonicalisationService(settings).define([{"problem_id": "IN-1", "text": "report"}])
    assert result.fallback is False
    assert result.title == "LLM defined"


@pytest.mark.parametrize("status", [401, 429])
def test_gemini_rotates_api_key_on_auth_or_quota_error(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    settings = Settings(
        gemini_api_key="key-a",
        gemini_api_key_1="key-b",
        gemini_api_key_2="key-c",
        openai_api_key="",
        llm_timeout_seconds=1,
    )
    client = StructuredLLMClient(settings)
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/test")
    responses = [
        httpx.Response(status, json={"error": {"code": status}}, request=request),
        httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]},
            request=request,
        ),
    ]
    used_keys: list[str] = []

    def fake_post(*, timeout: float, **kwargs: object) -> httpx.Response:
        used_keys.append(kwargs["params"]["key"])
        return responses[len(used_keys) - 1]

    monkeypatch.setattr(llm_client_module.httpx, "post", fake_post)
    monkeypatch.setattr(llm_client_module.time, "sleep", lambda *_: None)

    result = client.generate_json("prompt")

    assert result.payload == {"ok": True}
    assert used_keys == ["key-a", "key-b"]


def test_canonicalisation_batch_defines_every_cluster() -> None:
    seen: list[dict[str, object]] = []

    class _BatchLLM:
        available = True

        def generate_json(self, prompt: str) -> StructuredResponse:
            payload = json.loads(prompt.split("Clusters:\n", 1)[1])
            seen.extend(payload["clusters"])
            rows = [
                {
                    "index": cluster["index"],
                    "title": f"LLM canonical {cluster['index']}",
                    "problem_statement": f"LLM statement {cluster['index']}",
                    "source_problem_ids": [item["problem_id"] for item in cluster["neighbors"]],
                }
                for cluster in payload["clusters"]
            ]
            return StructuredResponse({"results": rows}, "fake", "batch-model")

    groups = [
        [{"problem_id": f"IN-{group}-{index}", "text": f"report {group}-{index}", "similarity": 1.0} for index in range(3)]
        for group in range(5)
    ]
    results = CanonicalisationService(
        _settings(canonicalisation_batch_size=2), _BatchLLM()  # type: ignore[arg-type]
    ).define_batch(groups)
    assert [result.title for result in results] == [f"LLM canonical {index}" for index in range(5)]
    assert all(not result.fallback for result in results)
    assert sum(len(cluster["neighbors"]) for cluster in seen) == 15


def test_canonicalisation_deduplicates_and_truncates_neighbor_payload() -> None:
    prompts: list[str] = []

    class _DedupLLM:
        available = True

        def generate_json(self, prompt: str) -> StructuredResponse:
            prompts.append(prompt)
            payload = json.loads(prompt.split("Clusters:\n", 1)[1])
            rows = [
                {
                    "index": cluster["index"],
                    "title": "LLM deduplicated problem",
                    "problem_statement": "LLM deduplicated statement",
                }
                for cluster in payload["clusters"]
            ]
            return StructuredResponse({"results": rows}, "fake", "dedup-model")

    long_text = "Customer reports repeated failed payment status " * 8
    groups = [
        [{"problem_id": "IN-1", "text": long_text, "similarity": 1.0}],
        [{"problem_id": "IN-2", "text": long_text, "similarity": 0.9}],
    ]
    results = CanonicalisationService(
        _settings(canonicalisation_max_neighbor_chars=50), _DedupLLM()  # type: ignore[arg-type]
    ).define_batch(groups)
    assert len(prompts) == 1
    assert [result.source_problem_ids for result in results] == [["IN-1"], ["IN-2"]]
    assert all(not result.fallback for result in results)
    sent = json.loads(prompts[0].split("Clusters:\n", 1)[1])["clusters"]
    assert len(sent) == 1
    assert len(sent[0]["neighbors"][0]["problem_statement"]) == 50


def test_coverage_thresholds_route_grey_zone_to_consortium(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(coverage_match_threshold=0.75, coverage_mismatch_threshold=0.60)
    embedder = type("FakeEmbedder", (), {"model_name": "fake-bge-large"})()
    problem_vectors = np.asarray([[1.0, 0.0], [0.68, np.sqrt(1.0 - 0.68**2)]], dtype=np.float32)
    backlog_vectors = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    monkeypatch.setattr(
        "app.intelligence.coverage.build_coverage_embedder",
        lambda *_: (embedder, problem_vectors, backlog_vectors),
    )

    class _FakeConsortium:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, float]] = []

        def deliberate(self, problem: dict[str, object], backlog: dict[str, object], score: float) -> dict[str, object]:
            self.calls.append((str(problem["problem_id"]), str(backlog["backlog_id"]), score))
            return {
                "agents": [],
                "chair": {"decision": "MISMATCH", "confidence": 0.7, "rationale": "Material scope gap"},
                "final_decision": "MISMATCH",
                "final_confidence": 0.7,
                "rationale": "Material scope gap",
            }

    consortium = _FakeConsortium()
    result = CoverageAssessment(settings, consortium).assess(  # type: ignore[arg-type]
        [
            {"problem_id": "CP-1", "title": "Exact issue", "problem_statement": "exact issue"},
            {"problem_id": "CP-2", "title": "Partial issue", "problem_statement": "partial issue"},
        ],
        [
            {"backlog_id": "BL-1", "title": "Fix exact issue", "description": "fix exact issue"},
            {"backlog_id": "BL-2", "title": "Other work", "description": "other work"},
        ],
    )
    assert result.verdicts[0].coverage_status == "covered"
    assert result.verdicts[0].decision == "MATCH"
    assert result.verdicts[1].coverage_status == "grey_zone"
    assert result.verdicts[1].decision == "MISMATCH"
    assert consortium.calls == [("CP-2", "BL-2", pytest.approx(0.733, abs=0.002))]
    assert set(result.thresholds) == {"match", "mismatch"}


def test_grey_zone_consortium_uses_specialists_and_chair() -> None:
    calls: list[str] = []

    class _FakeLLM:
        available = True

        def generate_json(self, prompt: str) -> StructuredResponse:
            calls.append(prompt)
            if prompt.startswith("You chair"):
                return StructuredResponse(
                    {"decision": "MATCH", "confidence": 0.81, "rationale": "Specialist consensus"},
                    "fake",
                    "chair-model",
                )
            return StructuredResponse(
                {
                    "evidence_for_match": "same journey",
                    "evidence_against_match": "partial scope",
                    "gap_assessment": "small",
                    "decision": "MATCH",
                    "confidence": 0.7,
                },
                "fake",
                "agent-model",
            )

    consortium = GreyZoneConsortium(_settings(grey_zone_agent_count=3), _FakeLLM())  # type: ignore[arg-type]
    result = consortium.deliberate(
        {"problem_id": "CP-1", "title": "Transfer failed", "problem_statement": "Transfer failed"},
        {"backlog_id": "BL-1", "title": "Transfer status", "description": "Show transfer status"},
        0.68,
    )
    assert len(result["agents"]) == 3
    assert len(calls) == 4
    assert result["final_decision"] == "MATCH"
    assert result["chair"]["model"] == "chair-model"


def test_grey_zone_consortium_batches_cases() -> None:
    calls: list[str] = []

    class _FakeLLM:
        available = True

        def generate_json(self, prompt: str) -> StructuredResponse:
            calls.append(prompt)
            if prompt.startswith("You chair"):
                rows = [
                    {"index": index, "decision": "MATCH", "confidence": 0.81, "rationale": "Batched consensus"}
                    for index in range(2)
                ]
            else:
                rows = [
                    {
                        "index": index,
                        "decision": "MATCH",
                        "confidence": 0.7,
                        "evidence_for_match": "same journey",
                        "evidence_against_match": "partial scope",
                        "gap_assessment": "small",
                    }
                    for index in range(2)
                ]
            return StructuredResponse({"results": rows}, "fake", "model")

    consortium = GreyZoneConsortium(
        _settings(grey_zone_agent_count=3, grey_zone_batch_size=10), _FakeLLM()  # type: ignore[arg-type]
    )
    problems = [
        {"problem_id": "CP-1", "title": "Transfer failed", "problem_statement": "Transfer failed"},
        {"problem_id": "CP-2", "title": "Card failed", "problem_statement": "Card failed"},
    ]
    backlog = {"backlog_id": "BL-1", "title": "Transfer status", "description": "Show transfer status"}

    results = consortium.deliberate_batch([(problem, backlog, 0.68) for problem in problems])

    assert len(results) == 2
    assert len(calls) == 4
    assert all(item["final_decision"] == "MATCH" for item in results)


def test_backlog_report_exposes_canonical_coverage(app_client) -> None:
    client, app, _ = app_client
    service = app.state.backlog
    repo = app.state.repo
    upload = service.upload("backlog.csv", app.state.settings.sample_backlog_path.read_bytes())
    validation_run_id = "VRUN-canonical-coverage"
    repo.create_validation_run(validation_run_id, upload["upload_id"])
    service.execute(validation_run_id, upload["upload_id"])

    report_id = repo.get_validation_run(validation_run_id)["report_id"]
    report = repo.get_report(report_id)["report"]
    assert report["validation_basis"] == "canonical_problem_coverage"
    assert report["summary"]["canonical_problem_count"] > 0
    assert report["summary"]["retrieval"]["provider"] in {"bge_dense_cosine", "tfidf_fallback"}
    assert len(report["canonical_coverage"]) == report["summary"]["canonical_problem_count"]
    assert all("coverage_score" in finding for finding in report["findings"])
    coverage_response = client.get(f"/api/v1/backlog-validation-reports/{report_id}/coverage")
    assert coverage_response.status_code == 200
