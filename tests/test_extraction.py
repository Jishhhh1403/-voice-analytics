from __future__ import annotations

from app.intelligence.contracts import CleanFeedback
from app.intelligence.extractor import extract_insights
from app.intelligence.text import redact_pii


def feedback(text: str, title: str = "") -> CleanFeedback:
    redacted, _ = redact_pii(text)
    return CleanFeedback(
        feedback_id="FB-UNIT-1",
        source_feedback_id="FB-UNIT-1",
        submitted_at="2026-01-01T00:00:00+00:00",
        source_type="in_app_feedback",
        source_channel="in_app",
        platform="Android",
        language="en",
        rating=1,
        feedback_title=title,
        feedback_text_redacted=redacted,
        content_fingerprint="fingerprint",
    )


def test_redacts_pii_and_removes_source_values():
    redacted, kinds = redact_pii(
        "My name is Anita Sharma. Call 9876543210 or email anita@example.com about transfer status."
    )
    assert "Anita Sharma" not in redacted
    assert "9876543210" not in redacted
    assert "anita@example.com" not in redacted
    assert {"NAME", "PHONE", "EMAIL"} <= set(kinds)


def test_extracts_transfer_status_problem_with_exact_evidence():
    record = feedback("My IMPS transfer is still pending and I cannot see what to do next.")
    insights = extract_insights(record)

    assert insights
    problems = [item for item in insights if item.is_problem]
    assert problems
    assert problems[0].journey_node_id is not None
    assert problems[0].journey_node_id.startswith("payments")
    for item in insights:
        assert item.evidence_span in record.feedback_text_redacted


def test_statement_issue_maps_to_statement_journey():
    record = feedback("The statement PDF will not generate and the screen just shows a spinner.")
    insights = extract_insights(record)

    assert insights
    assert any((item.journey_node_id or "").startswith("statements") for item in insights)
    assert any(item.is_problem for item in insights)


def test_positive_feedback_is_not_marked_as_problem():
    record = feedback("The new transfer flow is smooth and fast.")
    insights = extract_insights(record)

    assert insights
    assert not any(item.is_problem for item in insights)


def test_filler_sentence_does_not_become_evidence():
    record = feedback("This is frustrating. The transfer status is unclear.")
    insights = extract_insights(record)

    assert len(insights) == 1
    assert "frustrating" not in insights[0].evidence_span.lower()
    assert insights[0].evidence_span in record.feedback_text_redacted
