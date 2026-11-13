from __future__ import annotations

from app.services.ingestion import parse_feedback_csv


def test_ingestion_counts_accepts_duplicates_and_quarantine(app_client):
    _, app, _ = app_client
    settings = app.state.settings
    data = settings.sample_feedback_path.read_bytes()
    parsed = parse_feedback_csv(data, settings.tenant_id, settings)

    assert len(parsed.accepted) == 5
    assert len(parsed.duplicates) == 1
    assert len(parsed.rejected) == 2
    assert any(item.duplicate_type == "exact" for item in parsed.accepted)
    assert parsed.manifest["duplicate_policy"] == "linked_not_discarded"
    assert parsed.manifest["data_quality"]["total_checks"] >= 6
    assert {"EMAIL", "PHONE"} <= set(parsed.pii_types)
    assert all(item.feedback_text_original for item in parsed.accepted)
    assert all("anita@example.com" not in item.feedback_text_redacted for item in parsed.accepted)
    assert all("9876543210" not in item.feedback_text_redacted for item in parsed.accepted)


def test_pipeline_persists_evidence_backed_problems(app_client):
    _, app, run_id = app_client
    run = app.state.repo.get_run(run_id)

    assert run is not None
    assert run["status"] == "completed"
    assert run["summary"]["accepted_feedback"] == 5
    assert run["summary"]["duplicate_feedback"] == 1
    assert run["summary"]["rejected_feedback"] == 2
    assert run["summary"]["insights"] > 0
    assert run["summary"]["problems"] > 0
    assert run["summary"]["evidence_links"] > 0
    assert run["summary"]["measurement_snapshots"] > 0
    assert run["summary"]["prioritised_problems"] > 0
    assert run["summary"]["priority_top"]

    stages = app.state.repo.admin_overview()["runs"][0]["stages"]
    assert stages
    assert {stage["status"] for stage in stages} == {"succeeded"}
    assert len(stages) == 9
    assert {stage["stage"] for stage in stages} >= {"measurement_engine", "priority_engine", "mds_engine"}
    assert app.state.repo.db.query_one("SELECT COUNT(*) AS n FROM model_execution_history")["n"] >= 2
    assert app.state.repo.db.query_one("SELECT COUNT(*) AS n FROM problem_journey_mappings")["n"] > 0
    priority_snapshot = app.state.repo.db.query_one(
        "SELECT measurement_window_start, measurement_window_end FROM problem_priority_snapshots LIMIT 1"
    )
    assert priority_snapshot["measurement_window_start"]
    assert priority_snapshot["measurement_window_end"]
    assert run["summary"]["theme_map_status"] == "OK"
    assert run["summary"]["themes_mapped"] > 0
    assert app.state.repo.db.query_one("SELECT COUNT(*) AS n FROM problem_mds_points")["n"] > 0


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
    assert any(evidence.get("insights") for evidence in detail["evidence"])
    signal = next(evidence for evidence in detail["evidence"] if evidence.get("insights"))["insights"][0]
    assert {"intents", "aspects", "sentiment", "reported_symptom", "field_confidence"} <= set(signal)

    journey = client.get("/api/v1/journey", params={"run_id": run_id}).json()
    assert journey["tree"]
    assert journey["version"] == "1.0.0"
