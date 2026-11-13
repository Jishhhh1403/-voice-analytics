from __future__ import annotations

from app.services.backlog import parse_backlog_csv, split_criteria


def test_split_criteria_handles_pipes_and_newlines():
    assert split_criteria("Show status; Explain next step\nAvoid retry") == [
        "Show status",
        "Explain next step",
        "Avoid retry",
    ]


def test_backlog_parser_quarantines_invalid_rows(app_client):
    _, app, _ = app_client
    settings = app.state.settings
    parsed = parse_backlog_csv(settings.sample_backlog_path.read_bytes(), "UP-test", settings)

    assert parsed["valid_rows"] == 3
    assert parsed["invalid_rows"] == 0
    assert all(item["backlog_id"].startswith("BL-T") for item in parsed["items"])
    assert all("acceptance_criteria_items" in item["structured"] for item in parsed["items"])


def test_backlog_validation_produces_report_with_evidence(app_client):
    client, app, run_id = app_client
    settings = app.state.settings
    service = app.state.backlog
    repo = app.state.repo

    upload = service.upload("backlog.csv", settings.sample_backlog_path.read_bytes())
    validation_run_id = "VRUN-test"
    repo.create_validation_run(validation_run_id, upload["upload_id"])
    service.execute(validation_run_id, upload["upload_id"])

    validation_run = repo.get_validation_run(validation_run_id)
    assert validation_run["status"] == "completed"
    assert validation_run["report_id"]
    report_id = validation_run["report_id"]

    report = repo.get_report(report_id)
    assert report is not None
    findings = report["report"]["findings"]
    assert len(findings) >= 3
    assert {finding["backlog_id"] for finding in findings} == {"BL-T001", "BL-T002", "BL-T003"}
    assert report["summary"]["backlog_count"] == 3
    assert all(
        isinstance(value, str | int | float) for value in report["report"]["versions"].values()
    )
    for finding in report["report"]["findings"]:
        assert finding["relationship"] in {
            "ADDRESSES",
            "PARTIALLY_ADDRESSES",
            "RELATED_BUT_NOT_SOLVING",
            "NO_CLEAR_RELATIONSHIP",
            "CONTRADICTS_OR_OUT_OF_SCOPE",
            "NEEDS_REVIEW",
        }
        assert 0.0 <= finding["alignment_score"] <= 1.0

    coverage = client.get(f"/api/v1/backlog-validation-reports/{report_id}/coverage")
    assert coverage.status_code == 200
    coverage_body = coverage.json()
    assert coverage_body["summary"]["total"] == 3
    assert coverage_body["matrix"]
    assert coverage_body["candidates"]
    assert coverage_body["note"].startswith("Coverage is customer-evidence coverage")

    response = client.get(f"/api/v1/backlog-validation-reports/{report_id}/download", params={"format": "csv"})
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "backlog_id" in response.text.lower()

    review = client.post(
        f"/api/v1/backlog-validation-reports/{report_id}/review",
        json={
            "reviewer": "po@example.com",
            "decision": "accept_recommendation",
            "note": "Reviewed in test",
            "backlog_id": None,
        },
    )
    assert review.status_code == 200
    assert repo.get_report(report_id)["reviewer_status"] == "accept_recommendation"

    problems = client.get("/api/v1/problems", params={"run_id": run_id}).json()
    assert problems["total"] > 0
