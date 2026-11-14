from __future__ import annotations


def _create_factor_run(client, feedback_run_id: str) -> str:
    created = client.post(
        "/api/v1/problem-dimensions/runs",
        params={"background": False},
        json={"feedback_run_id": feedback_run_id, "max_components": 5, "force_rerun": True},
    )
    assert created.status_code == 200, created.text
    return created.json()["run_id"]


def test_factor_prioritisation_lifecycle_and_explainability(dimension_client):
    client, app, feedback_run_id = dimension_client
    famd_run_id = _create_factor_run(client, feedback_run_id)

    status = client.get("/api/v1/factor-prioritisation/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is True
    assert status.json()["weights"]["prevalence"] == 0.30

    created = client.post(
        "/api/v1/factor-prioritisation/runs",
        params={"background": False},
        json={"famd_run_id": famd_run_id, "force_rerun": True},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]

    run = client.get(f"/api/v1/factor-prioritisation/runs/{run_id}")
    assert run.status_code == 200, run.text
    payload = run.json()
    assert payload["status"] == "COMPLETED"
    assert payload["scoring_model_version"] == "factor-evidence-v1"
    assert payload["total_factor_count"] == 5
    assert len(payload["scores"]) == 5
    assert payload["summary"]["model_version"] == "factor-evidence-v1"

    scores = payload["scores"]
    assert [item["rank"] for item in scores] == [1, 2, 3, 4, 5]
    for item in scores:
        assert item["score_status"] in {"VALIDATED", "PROVISIONAL"}
        assert item["evidence_coverage"] == 100
        assert item["weights"]["prevalence"] == 0.30
        assert 0 <= item["final_priority_score"] <= 100
        assert len(item["explanation"]["components"]) == 4
        assert item["explanation"]["why"]
        assert item["explanation"]["formula"]
        assert item["explanation"]["caveats"]

    top = scores[0]
    detail = client.get(f"/api/v1/factor-prioritisation/runs/{run_id}/factors/{top['factor_id']}")
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert len(detail_payload["evidence"]) == 4
    assert detail_payload["semantic_assessment"]["semantic_evaluation"]["subdimensions"]
    assert detail_payload["semantic_assessment"]["review_status"] == "UNREVIEWED"

    latest = client.get("/api/v1/factor-prioritisation/runs/latest")
    assert latest.status_code == 200
    assert latest.json()["prioritisation_run_id"] == run_id

    reviewed = client.post(
        f"/api/v1/factor-prioritisation/runs/{run_id}/factors/{top['factor_id']}"
        "/semantic-assessment/review",
        json={"reviewer": "analyst@example.com", "decision": "approve", "note": "Coherent theme"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review_status"] == "APPROVED"

    assert app.state.repo.db.query(
        "SELECT * FROM factor_prioritisation_evidence WHERE prioritisation_run_id=?", (run_id,)
    )
    assert app.state.repo.db.query(
        "SELECT * FROM factor_semantic_assessments WHERE prioritisation_run_id=?", (run_id,)
    )


def test_factor_prioritisation_is_reusable_and_validates_weights(dimension_client):
    client, _, feedback_run_id = dimension_client
    famd_run_id = _create_factor_run(client, feedback_run_id)

    first = client.post(
        "/api/v1/factor-prioritisation/runs",
        params={"background": False},
        json={"famd_run_id": famd_run_id},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/api/v1/factor-prioritisation/runs",
        params={"background": False},
        json={"famd_run_id": famd_run_id},
    )
    assert second.status_code == 200
    assert second.json()["run_id"] == first.json()["run_id"]

    invalid = client.post(
        "/api/v1/factor-prioritisation/runs",
        params={"background": False},
        json={"famd_run_id": famd_run_id, "weights": {"unknown": 1.0}},
    )
    assert invalid.status_code == 400

    weighted = client.post(
        "/api/v1/factor-prioritisation/runs",
        params={"background": False},
        json={
            "famd_run_id": famd_run_id,
            "weights": {
                "prevalence": 0.5,
                "statistical_importance": 0.5,
                "representation_strength": 0.0,
                "semantic_coherence": 0.0,
            },
        },
    )
    assert weighted.status_code == 200, weighted.text
    payload = client.get(f"/api/v1/factor-prioritisation/runs/{weighted.json()['run_id']}").json()
    assert payload["scores"][0]["weights"]["prevalence"] == 0.5


def test_factor_prioritisation_requires_completed_factor_run(dimension_client):
    client, _, feedback_run_id = dimension_client
    response = client.post(
        "/api/v1/factor-prioritisation/runs",
        params={"background": False},
        json={"feedback_run_id": feedback_run_id},
    )
    assert response.status_code == 400
    assert "factor run" in response.json()["detail"].lower()


def test_factor_prioritisation_uses_serialization_llm_names_only(dimension_client):
    client, app, feedback_run_id = dimension_client
    famd_run_id = _create_factor_run(client, feedback_run_id)
    factor_run = client.get(f"/api/v1/problem-dimensions/runs/{famd_run_id}").json()

    created = client.post(
        "/api/v1/factor-prioritisation/runs",
        params={"background": False},
        json={"famd_run_id": famd_run_id, "force_rerun": True},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]

    before = client.get(f"/api/v1/factor-prioritisation/runs/{run_id}").json()
    assert all(item["factor_name"] is None for item in before["scores"])

    app.state.repo.save_dimension_narrative_serialization(
        famd_run_id,
        {
            "status": "COMPLETED",
            "summary": "Serialized factor narratives",
            "total_factors": len(factor_run["definitions"]),
            "factors": [
                {
                    "factor_id": f"F{definition['dimension_number']}",
                    "dimension_id": definition["dimension_id"],
                    "name": f"LLM serialized factor {definition['dimension_number']}",
                    "short_name": f"Serialized {definition['dimension_number']}",
                    "description": (
                        f"LLM serialized description {definition['dimension_number']}"
                    ),
                }
                for definition in factor_run["definitions"]
            ],
        },
        status="COMPLETED",
        prompt_version="factor-narrative-test",
        agent_version="test-agent",
        model_name="test-model",
        content_hash="test-hash",
    )

    after = client.get(f"/api/v1/factor-prioritisation/runs/{run_id}").json()
    for item in after["scores"]:
        assert item["factor_name"] == f"LLM serialized factor {item['dimension_number']}"
        assert item["explanation"]["factor_name"] == item["factor_name"]
        assert item["explanation"]["nomenclature"]["description"] == (
            f"LLM serialized description {item['dimension_number']}"
        )
        assert item["explanation"]["nomenclature"]["source"] == (
            "dimension_narrative_serialization"
        )
        assert item["explanation"]["nomenclature"]["model_name"] == "test-model"
        assert not item["factor_name"].startswith("Factor F")
