from __future__ import annotations


def _create_factor_run(client, feedback_run_id: str) -> str:
    created = client.post(
        "/api/v1/problem-dimensions/runs",
        params={"background": False},
        json={"feedback_run_id": feedback_run_id, "max_components": 12, "force_rerun": True},
    )
    assert created.status_code == 200, created.text
    return created.json()["run_id"]


def test_backlog_validation_reports_factor_coverage_and_priority(dimension_client):
    client, app, feedback_run_id = dimension_client
    famd_run_id = _create_factor_run(client, feedback_run_id)
    factor_run = client.get(f"/api/v1/problem-dimensions/runs/{famd_run_id}").json()

    app.state.repo.save_dimension_narrative_serialization(
        famd_run_id,
        {
            "status": "COMPLETED",
            "summary": "Factor narratives for backlog coverage",
            "total_factors": len(factor_run["definitions"]),
            "factors": [
                {
                    "factor_id": f"F{definition['dimension_number']}",
                    "dimension_id": definition["dimension_id"],
                    "name": (
                        "Transfer status clarity and pending payment explanation"
                        if index == 0
                        else f"Unrelated banking capability {index}"
                    ),
                    "short_name": (
                        "Transfer status clarity" if index == 0 else f"Capability {index}"
                    ),
                    "description": (
                        "Customers need pending and failed transfer states explained with clear "
                        "next steps and error recovery."
                        if index == 0
                        else "Generic banking capability unrelated to transfer status clarity."
                    ),
                }
                for index, definition in enumerate(factor_run["definitions"])
            ],
        },
        status="COMPLETED",
        prompt_version="factor-narrative-test",
        agent_version="test-agent",
        model_name="test-model",
        content_hash=f"factor-backlog-{famd_run_id}",
    )

    prioritisation = client.post(
        "/api/v1/factor-prioritisation/runs",
        params={"background": False},
        json={"famd_run_id": famd_run_id, "force_rerun": True},
    )
    assert prioritisation.status_code == 200, prioritisation.text

    backlog_csv = (
        b"backlog_id,title,description,acceptance_criteria,product_area,priority,business_goal,source_system\n"
        b"BL-F001,Improve transfer status clarity,"
        b"Make pending and failed transfer states clear and explain the next step,"
        b"Show pending and failed states; Explain what the customer should do next,"
        b"Payments,High,Reduce transfer complaints,Jira\n"
        b"BL-F002,Add loyalty shopping rewards,"
        b"Introduce gamified shopping badges and reward points,"
        b"Show reward points after purchase,Rewards,Low,Increase engagement,Jira\n"
    )
    upload = app.state.backlog.upload("factor-backlog.csv", backlog_csv)
    validation_run_id = "VRUN-factor-coverage"
    app.state.repo.create_validation_run(validation_run_id, upload["upload_id"])
    app.state.backlog.execute(validation_run_id, upload["upload_id"])

    validation_run = app.state.repo.get_validation_run(validation_run_id)
    assert validation_run["status"] == "completed", validation_run
    report_id = validation_run["report_id"]
    stored = app.state.repo.get_report(report_id)
    report = stored["report"]

    assert report["validation_basis"] == "factor_prioritisation"
    assert report["summary"]["factor_count"] >= 1
    assert report["summary"]["backlog_count"] == 2
    assert report["factor_coverage"]
    assert any(item["covered_by_count"] > 0 for item in report["factor_coverage"])

    items = {item["backlog_id"]: item for item in report["backlog_items"]}
    transfer = items["BL-F001"]
    other = items["BL-F002"]
    assert transfer["priority_alignment_score"] > other["priority_alignment_score"]
    assert transfer["backlog_priority_rank"] == 1
    assert transfer["covered_factor_count"] >= 1
    finding = transfer["findings"][0]
    assert finding["factor_name"]
    assert 0.0 <= finding["embedding_similarity"] <= 1.0
    assert 0.0 <= finding["embedding_distance"] <= 1.0
    assert finding["covered_problem_count"] >= 1
    assert finding["covered_problems"]

    coverage = client.get(f"/api/v1/backlog-validation-reports/{report_id}/coverage")
    assert coverage.status_code == 200
    body = coverage.json()
    assert body["validation_basis"] == "factor_prioritisation"
    assert body["factor_coverage"]
    assert "factor" in body["note"].lower()

    download = client.get(
        f"/api/v1/backlog-validation-reports/{report_id}/download", params={"format": "csv"}
    )
    assert download.status_code == 200
    assert "factor_id" in download.text
    assert "embedding_distance" in download.text

    mappings = client.get("/api/v1/mappings")
    assert mappings.status_code == 200, mappings.text
    graph = mappings.json()
    assert graph["status"] == "READY"
    assert graph["report_id"] == report_id
    assert graph["prioritisation_run_id"]
    assert graph["counts"]["feedback_total"] > 0
    assert graph["counts"]["themes"] > 0
    assert graph["counts"]["factors"] >= 1
    assert graph["counts"]["backlogs"] == 2
    assert graph["links"]["feedback_theme"]
    assert graph["links"]["theme_factor"]
    assert any(item["target"] == "BL-F001" for item in graph["links"]["factor_backlog"])
    assert all(theme["primary_factor_id"] for theme in graph["themes"])
    assert graph["feedback"][0]["primary_theme_id"]
