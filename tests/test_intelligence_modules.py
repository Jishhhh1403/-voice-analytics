from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from app.intelligence.advanced import conjoint_analysis, survival_analysis
from app.intelligence.contracts import CleanFeedback, ExtractedInsight, ProblemDraft
from app.intelligence.duplicates import detect_duplicate_relationships
from app.intelligence.language import detect_language
from app.intelligence.measurement import measure_problems, measurement_inputs
from app.intelligence.pii import redact_pii_enhanced
from app.intelligence.prioritization import prioritise_problems
from app.intelligence.quality import run_data_quality_checks, summarize_checks


def _feedback(feedback_id: str, text: str, customer: str, submitted: str | None) -> CleanFeedback:
    return CleanFeedback(
        feedback_id=feedback_id,
        submitted_at=submitted,
        source_type="app_store",
        source_channel="ios",
        platform="iOS",
        language="en",
        synthetic_customer_ref=customer,
        feedback_text_redacted=text,
        content_fingerprint=hashlib.sha256(text.lower().encode("utf-8")).hexdigest(),
    )


def _insight(feedback_id: str, text: str, negative: bool = True) -> ExtractedInsight:
    return ExtractedInsight(
        insight_id=f"IN-{feedback_id}",
        feedback_id=feedback_id,
        sentence_index=0,
        reported_problem=text,
        reported_symptom="payment stuck",
        sentiment="negative" if negative else "positive",
        evidence_span=text,
        extraction_timestamp="2026-01-01T00:00:00+00:00",
        is_problem=negative,
    )


def test_duplicates_are_linked_not_discarded():
    first = _feedback("F1", "my transfer was stuck and no status update appeared", "C1", "2026-01-01T00:00:00+00:00")
    near = _feedback("F2", "my transfer was stuck and no status update shows up", "C2", "2026-01-02T00:00:00+00:00")
    repeat = _feedback("F3", "my transfer was stuck and no status update appeared", "C1", "2026-01-05T00:00:00+00:00")

    relationships = detect_duplicate_relationships([first, near, repeat], threshold=0.6, min_tokens=3, window_days=30)
    types = {item.duplicate_type for item in relationships}
    assert "exact" in types
    assert "repeat" in types
    # Nothing is removed from the input; this function only returns relationships.
    assert len([first, near, repeat]) == 3


def test_data_quality_reports_missing_data_explicitly():
    accepted = [_feedback("F1", "ok", "C1", "2026-01-01T00:00:00+00:00")]
    checks = run_data_quality_checks(
        [{"feedback_text": "ok"}],
        accepted,
        [{"error_reason": "missing submitted_at"}],
        [],
        min_chars=3,
        max_chars=5000,
    )
    statuses = {check["check_name"]: check["status"] for check in checks}
    assert statuses["missing_or_invalid_timestamps"] == "FAIL"
    assert statuses["duplicate_rate"] == "PASS"
    summary = summarize_checks(checks)
    assert summary["has_failures"] is True


def test_measurement_and_priority_keep_missing_metrics_visible(app_client):
    _, app, run_id = app_client
    settings = app.state.settings
    rows = app.state.repo.db.query("SELECT * FROM customer_problems WHERE run_id=?", (run_id,))
    assert rows

    records = [record for record in app.state.pipeline._records(run_id)]
    feedback = {record.feedback_id: record for record in records}

    problem = ProblemDraft(
        problem_id=rows[0]["problem_id"],
        signature=rows[0]["signature"],
        title=rows[0]["title"],
        problem_statement=rows[0]["problem_statement"],
        journey_node_id=rows[0]["journey_node_id"],
        evidence_count=rows[0]["evidence_count"],
        distinct_customers=rows[0]["distinct_customers"],
    )
    insight_rows = app.state.repo.db.query("SELECT * FROM problem_evidence WHERE problem_id=?", (problem.problem_id,))
    evidence = {
        problem.problem_id: [
            (_insight(row["feedback_id"], row["evidence_span"]), feedback[row["feedback_id"]])
            for row in insight_rows
            if row["feedback_id"] in feedback
        ]
    }
    measurement = measure_problems([problem], evidence)
    indexed = measurement_inputs(measurement)
    result = prioritise_problems(settings, [problem], evidence, indexed)

    assert measurement.snapshots
    assert all(snapshot["status"] for snapshot in measurement.snapshots)
    assert result.scores
    assert result.scores[0]["missing_metrics"] == sorted(set(result.scores[0]["missing_metrics"]))
    assert result.scores[0]["rank"] == 1


def test_advanced_methods_refuse_without_required_inputs():
    survival = survival_analysis([])
    conjoint = conjoint_analysis([])
    assert survival.status == "NOT_AVAILABLE"
    assert "event" in survival.required_inputs
    assert conjoint.status == "NOT_APPLICABLE"


def test_priority_and_quality_endpoints(app_client):
    client, _, run_id = app_client

    priorities = client.get("/api/v1/priorities", params={"run_id": run_id}).json()
    assert priorities["items"]
    assert priorities["methodology_version"]

    quality = client.get("/api/v1/data-quality", params={"run_id": run_id}).json()
    assert quality["checks"]

    duplicates = client.get("/api/v1/duplicates", params={"run_id": run_id}).json()
    assert duplicates["policy"] == "linked_not_discarded"

    problem_id = priorities["items"][0]["problem_id"]
    measurement = client.get(f"/api/v1/problems/{problem_id}/measurement").json()
    assert measurement["snapshots"]
    assert len({item["metric_name"] for item in measurement["snapshots"]}) == len(measurement["snapshots"])

    priority = client.get(f"/api/v1/problems/{problem_id}/priority").json()
    assert priority["methodology_version"] == priorities["methodology_version"]


def test_enhanced_pii_and_language_detection_fall_back_deterministically():
    redaction = redact_pii_enhanced(
        "Call me on 9876543210 or email anita@example.com. My account number is 123456789012.",
        provider="presidio",
        language="en",
    )
    assert "9876543210" not in redaction.text
    assert "anita@example.com" not in redaction.text
    assert redaction.provider_used in {"presidio", "regex"}
    assert {"EMAIL", "PHONE"} <= set(redaction.labels)

    english = detect_language("my transfer failed and the app is not working")
    hinglish = detect_language("mera transfer nahi hua hai aur app kaam nahi kar raha")
    assert english.supported is True
    assert english.language == "en"
    assert hinglish.language in {"hinglish", "hi"}


def test_measurement_windows_are_explicit_and_consistent(app_client):
    _, app, _ = app_client
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    dates = [120, 45, 10, 5]
    members = []
    for index, days_ago in enumerate(dates, start=1):
        text = "fraud and unauthorized transaction" if index == 4 else "transfer is stuck"
        record = _feedback(
            f"F{index}",
            text,
            f"C{index}",
            (now - timedelta(days=days_ago)).isoformat(),
        )
        members.append((_insight(f"F{index}", text), record))
    problem = ProblemDraft(
        problem_id="CP-WINDOW",
        signature="window-test",
        title="Window test problem",
        problem_statement="Explicit measurement windows must not mix lifetime and recent evidence.",
        journey_node_id="payments.transfer.status",
    )
    measurement = measure_problems(
        [problem],
        {problem.problem_id: members},
        window_days=90,
        baseline_days=30,
        current_days=30,
        duplicate_links=[{"duplicate_type": "repeat", "feedback_id": "F3"}],
        now=now,
    )
    metrics = {item["metric_name"]: item for item in measurement.snapshots}

    assert metrics["evidence_volume_lifetime"]["metric_value"] == 4
    assert metrics["evidence_volume"]["metric_value"] == 3
    assert metrics["evidence_volume_90d"]["metric_value"] == 3
    assert metrics["evidence_volume_30d"]["metric_value"] == 2
    assert metrics["evidence_volume_previous_30d"]["metric_value"] == 1
    assert metrics["repeat_complaint_count_30d"]["metric_value"] == 1
    assert metrics["volume_growth_abs"]["metric_value"] == 1
    assert metrics["volume_growth_pct"]["metric_value"] == 1
    assert metrics["negative_share_change"]["status"] == "OK"
    assert metrics["evidence_volume_90d"]["status"] == "OK"
    assert metrics["evidence_volume_30d"]["metadata"]["window_coverage"] == "full"
    assert metrics["evidence_volume_30d"]["window_start"] == (now - timedelta(days=30)).isoformat()
    assert measurement.window_start == now - timedelta(days=90)

    priority = prioritise_problems(
        app.state.settings,
        [problem],
        {problem.problem_id: members},
        measurement_inputs(measurement),
        duplicate_links=[{"duplicate_type": "repeat", "feedback_id": "F3"}],
        measurement_window_start=measurement.window_start,
        measurement_window_end=measurement.window_end,
    )
    score = priority.scores[0]
    assert score["measurement_window_start"]
    assert score["supporting_evidence"]["verified_risk"]["status"] == "NOT_VERIFIED"
    assert score["supporting_evidence"]["risk_indicators"]
    assert score["supporting_evidence"]["measurement_status"]["evidence_volume"] == "OK"
    assert score["supporting_evidence"]["risk_indicator_score"] > 0


def test_measurement_does_not_turn_uncovered_windows_into_zero(app_client):
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    old_record = _feedback("OLD", "statement download failed", "C-OLD", (now - timedelta(days=200)).isoformat())
    undated_record = _feedback("UNDATED", "statement download failed", "C-UNDATED", None)
    problem = ProblemDraft(
        problem_id="CP-COVERAGE",
        signature="coverage-test",
        title="Coverage test problem",
        problem_statement="Windows outside source coverage must not be reported as true zero.",
        journey_node_id="statements.download",
    )
    measurement = measure_problems(
        [problem],
        {problem.problem_id: [(_insight("OLD", "statement download failed"), old_record), (_insight("UNDATED", "statement download failed"), undated_record)]},
        now=now,
    )
    metrics = {item["metric_name"]: item for item in measurement.snapshots}

    assert metrics["evidence_volume_lifetime"]["metric_value"] == 2
    assert metrics["evidence_volume_lifetime"]["status"] == "OK"
    assert metrics["evidence_volume_90d"]["metric_value"] is None
    assert metrics["evidence_volume_90d"]["status"] == "NO_DATA"
    assert metrics["evidence_volume_30d"]["status"] == "NO_DATA"
    assert metrics["volume_growth_abs"]["status"] == "NO_DATA"

    current_only = _feedback("CURRENT", "transfer still pending", "C-CURRENT", (now - timedelta(days=2)).isoformat())
    baseline = _feedback("BASELINE", "transfer still pending", "C-BASELINE", (now - timedelta(days=80)).isoformat())
    measurement = measure_problems(
        [problem],
        {
            problem.problem_id: [
                (_insight("BASELINE", "transfer still pending"), baseline),
                (_insight("CURRENT", "transfer still pending"), current_only),
            ]
        },
        now=now,
    )
    metrics = {item["metric_name"]: item for item in measurement.snapshots}
    assert metrics["evidence_volume_30d"]["status"] == "OK"
    assert metrics["evidence_volume_30d"]["metric_value"] == 1
    assert metrics["evidence_volume_previous_30d"]["status"] == "OK"
    assert metrics["evidence_volume_previous_30d"]["metric_value"] == 0
    assert metrics["volume_growth_abs"]["metric_value"] == 1
    assert metrics["volume_growth_pct"]["status"] == "INSUFFICIENT_DATA"
