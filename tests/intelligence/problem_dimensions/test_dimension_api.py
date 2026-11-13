from __future__ import annotations


def test_dimension_lifecycle_requires_review_then_publishes(dimension_client):
    client, app, feedback_run_id = dimension_client

    status = client.get("/api/v1/problem-dimensions/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is True

    created = client.post(
        "/api/v1/problem-dimensions/runs",
        params={"background": False},
        json={"feedback_run_id": feedback_run_id, "max_components": 5, "force_rerun": True},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]
    run = client.get(f"/api/v1/problem-dimensions/runs/{run_id}").json()
    assert run["status"] == "PENDING_REVIEW"
    assert run["input_snapshot_id"].startswith("SNAP-")
    assert run["diagnostics"]["n_problems"] == 40
    assert len(run["definitions"]) == 5

    latest = client.get("/api/v1/problem-dimensions/latest")
    assert latest.status_code == 404

    for definition in run["definitions"]:
        response = client.post(
            f"/api/v1/problem-dimensions/runs/{run_id}/dimensions/{definition['dimension_id']}/review",
            json={
                "reviewer": "analyst@example.com",
                "decision": "approve",
                "name": f"Reviewed {definition['dimension_id']}",
                "note": "Reviewed against representative problems",
            },
        )
        assert response.status_code == 200, response.text

    reviewed = client.get(f"/api/v1/problem-dimensions/runs/{run_id}").json()
    assert reviewed["status"] == "APPROVED"
    assert all(item["review_status"] == "APPROVED" for item in reviewed["definitions"])

    published = client.post(
        f"/api/v1/problem-dimensions/runs/{run_id}/publish",
        json={"published_by": "analyst@example.com", "note": "Approved for publication"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "PUBLISHED"
    assert published.json()["publication_id"].startswith("DPUB-")

    latest = client.get("/api/v1/problem-dimensions/latest")
    assert latest.status_code == 200
    assert latest.json()["run"]["run_id"] == run_id

    problem_id = reviewed["definitions"][0]["representative_problem_ids"][0]
    problem = client.get(f"/api/v1/problem-dimensions/latest/problems/{problem_id}")
    assert problem.status_code == 200
    assert problem.json()["dominant_dimension"] is not None
    assert len(problem.json()["scores"]) == 5

    dimension = client.get("/api/v1/problem-dimensions/latest/dimensions/D1")
    assert dimension.status_code == 200
    assert dimension.json()["contributions"]
    assert dimension.json()["trends"]

    assert app.state.repo.db.query("SELECT * FROM dimension_publications WHERE run_id=?", (run_id,))
    assert app.state.repo.db.query(
        "SELECT * FROM audit_log WHERE action='dimension_publish' AND entity_id=?", (run_id,)
    )

    republished = client.post(
        f"/api/v1/problem-dimensions/runs/{run_id}/publish",
        json={"published_by": "analyst@example.com", "note": "Restore as latest publication"},
    )
    assert republished.status_code == 200, republished.text
    assert republished.json()["status"] == "PUBLISHED"
    assert len(app.state.repo.db.query("SELECT * FROM dimension_publications WHERE run_id=?", (run_id,))) == 2


def test_dimension_run_without_approved_review_cannot_publish(dimension_client):
    client, _, feedback_run_id = dimension_client
    created = client.post(
        "/api/v1/problem-dimensions/runs",
        params={"background": False},
        json={"feedback_run_id": feedback_run_id, "force_rerun": True},
    )
    run_id = created.json()["run_id"]
    response = client.post(
        f"/api/v1/problem-dimensions/runs/{run_id}/publish",
        json={"published_by": "analyst@example.com"},
    )
    assert response.status_code == 409

def test_run_scoped_dimension_and_problem_endpoints(dimension_client):
    client, _, feedback_run_id = dimension_client
    created = client.post(
        "/api/v1/problem-dimensions/runs",
        params={"background": False},
        json={"feedback_run_id": feedback_run_id, "force_rerun": True},
    )
    run_id = created.json()["run_id"]
    run = client.get(f"/api/v1/problem-dimensions/runs/{run_id}").json()
    dimension_id = run["definitions"][0]["dimension_id"]

    detail = client.get(f"/api/v1/problem-dimensions/runs/{run_id}/dimensions/{dimension_id}")
    assert detail.status_code == 200
    assert detail.json()["definition"]["dimension_id"] == dimension_id
    assert detail.json()["contributions"]
    assert detail.json()["top_problems"]

    problem_id = detail.json()["top_problems"][0]["problem_id"]
    problem = client.get(f"/api/v1/problem-dimensions/runs/{run_id}/problems/{problem_id}")
    assert problem.status_code == 200
    assert problem.json()["scores"]


def test_coefficient_matrix_equation_and_csv(dimension_client):
    client, _, feedback_run_id = dimension_client
    created = client.post(
        "/api/v1/problem-dimensions/runs",
        params={"background": False},
        json={"feedback_run_id": feedback_run_id, "force_rerun": True},
    )
    run_id = created.json()["run_id"]

    matrix = client.get(f"/api/v1/problem-dimensions/runs/{run_id}/coefficients")
    assert matrix.status_code == 200
    payload = matrix.json()
    assert payload["dimensions"]
    assert payload["coefficients"]
    assert payload["coefficients"][0]["coefficient"] is not None
    assert "not causal" in payload["interpretation_warning"]
    assert payload["share_definition"].startswith("relative_squared_coordinate_share_pct")

    problem_id = payload["coefficients"][0]["problem_id"]
    profile = client.get(f"/api/v1/problem-dimensions/runs/{run_id}/problems/{problem_id}/profile")
    assert profile.status_code == 200
    assert profile.json()["equation"]["equation_text"].startswith(f"{problem_id} = ")
    assert profile.json()["coefficients"]

    csv_response = client.get(f"/api/v1/problem-dimensions/runs/{run_id}/coefficients.csv")
    assert csv_response.status_code == 200
    assert csv_response.text.splitlines()[0].startswith("problem_id,dimension_id")

    alias = client.get(f"/api/v1/factor-analysis/runs/{run_id}/coefficients")
    assert alias.status_code == 200
    assert alias.json()["run_id"] == run_id
