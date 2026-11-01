from __future__ import annotations

import time


def test_health_and_meta_are_local_first(app_client):
    client, _, run_id = app_client
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["provider"] == "rules-v1"
    assert health.json()["object_store"] == "local"

    meta = client.get("/api/v1/meta/source").json()
    assert "synthetic" in meta["synthetic_warning"].lower()
    assert meta["latest_completed_run"]["run_id"] == run_id
    assert meta["sample_feedback_exists"] is True


def test_problem_review_is_persisted_with_audit_trail(app_client):
    client, app, run_id = app_client
    problem = client.get("/api/v1/problems", params={"run_id": run_id}).json()["items"][0]

    response = client.post(
        f"/api/v1/problems/{problem['problem_id']}/review",
        json={
            "reviewer": "journey@example.com",
            "decision": "mark_in_review",
            "note": "Journey expert review requested",
        },
    )
    assert response.status_code == 200
    detail = client.get(f"/api/v1/problems/{problem['problem_id']}").json()
    assert detail["reviews"]
    assert detail["reviews"][0]["decision"] in {"mark_in_review", "accept"}
    assert any(event["action"] == "problem_review" for event in app.state.repo.db.query("SELECT action FROM audit_log"))


def test_sample_backlog_upload_validation_and_idempotency(app_client):
    client, app, _ = app_client
    upload = client.post("/api/v1/backlog-uploads/sample")
    assert upload.status_code == 201
    upload_id = upload.json()["upload_id"]
    assert upload.json()["valid_rows"] == 3

    key = {"Idempotency-Key": f"test-{time.time()}"}
    first = client.post(f"/api/v1/backlog-uploads/{upload_id}/validate", json={"force_rerun": False}, headers=key)
    second = client.post(f"/api/v1/backlog-uploads/{upload_id}/validate", json={"force_rerun": False}, headers=key)
    assert first.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]

    run_id = first.json()["run_id"]
    status = "queued"
    for _ in range(80):
        run = client.get(f"/api/v1/backlog-validation-runs/{run_id}").json()
        status = run["status"]
        if status in {"completed", "failed"}:
            break
        time.sleep(0.25)
    assert status == "completed"
    assert run["report_id"]

    report = client.get(f"/api/v1/backlog-validation-reports/{run['report_id']}")
    assert report.status_code == 200
    assert report.json()["report"]["findings"]
    assert report.json()["report"]["summary"]["backlog_count"] == 3

    stored = app.state.repo.get_report(run["report_id"])
    assert stored["reviewer_status"] == "pending"
