from __future__ import annotations

from app.services.ingestion import parse_feedback_csv


def test_ingestion_counts_accepts_duplicates_and_quarantine(app_client):
    _, app, _ = app_client
    settings = app.state.settings
    data = settings.sample_feedback_path.read_bytes()
    parsed = parse_feedback_csv(data, settings.tenant_id, settings)

    assert len(parsed.accepted) == 4
    assert len(parsed.duplicates) == 1
    assert len(parsed.rejected) == 2
    assert {"EMAIL", "PHONE"} <= set(parsed.pii_types)
    assert all("anita@example.com" not in item.feedback_text_redacted for item in parsed.accepted)
    assert all("9876543210" not in item.feedback_text_redacted for item in parsed.accepted)


def test_pipeline_persists_evidence_backed_problems(app_client):
    _, app, run_id = app_client
    run = app.state.repo.get_run(run_id)

    assert run is not None
    assert run["status"] == "completed"
    assert run["summary"]["accepted_feedback"] == 4
    assert run["summary"]["duplicate_feedback"] == 1
    assert run["summary"]["rejected_feedback"] == 2
    assert run["summary"]["insights"] > 0
    assert run["summary"]["problems"] > 0
    assert run["summary"]["evidence_links"] > 0

    stages = app.state.repo.admin_overview()["runs"][0]["stages"]
    assert stages
    assert {stage["status"] for stage in stages} == {"succeeded"}
    assert len(stages) == 6


def test_admin_overview_always_returns_stage_arrays(app_client):
    client, _, run_id = app_client
    response = client.get("/api/v1/admin/overview")

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert runs
    for run in runs:
        assert isinstance(run["stages"], list)
    assert any(run["run_id"] == run_id for run in runs)


def test_problem_and_journey_endpoints_expose_pipeline_output(app_client):
    client, _, run_id = app_client

    problems = client.get("/api/v1/problems", params={"run_id": run_id}).json()
    assert problems["total"] > 0
    problem = problems["items"][0]
    detail = client.get(f"/api/v1/problems/{problem['problem_id']}").json()
    assert detail["problem_id"] == problem["problem_id"]
    assert detail["insights"]
    assert detail["evidence"]

    journey = client.get("/api/v1/journey", params={"run_id": run_id}).json()
    assert journey["tree"]
    assert journey["version"] == "1.0.0"
