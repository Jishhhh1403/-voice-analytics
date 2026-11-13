from __future__ import annotations

import pytest

from app.intelligence.problem_dimensions.publisher import PublicationError, validate_publishable


def test_publish_requires_every_dimension_approved():
    run = {"run_id": "DIM-1", "status": "PENDING_REVIEW"}
    definitions = [
        {"dimension_id": "D1", "review_status": "APPROVED"},
        {"dimension_id": "D2", "review_status": "DRAFT"},
    ]
    with pytest.raises(PublicationError, match="approved"):
        validate_publishable(run, definitions)


def test_publish_rejects_failed_or_empty_runs():
    with pytest.raises(PublicationError, match="cannot be published"):
        validate_publishable({"run_id": "DIM-1", "status": "FAILED"}, [])
    with pytest.raises(PublicationError, match="no dimension definitions"):
        validate_publishable({"run_id": "DIM-1", "status": "PENDING_REVIEW"}, [])


def test_publish_accepts_fully_approved_run_and_republish_for_rollback():
    validate_publishable(
        {"run_id": "DIM-1", "status": "APPROVED"},
        [
            {"dimension_id": "D1", "review_status": "APPROVED", "analyst_name": "Payments reliability"},
            {"dimension_id": "D2", "review_status": "APPROVED", "analyst_name": "Servicing clarity"},
        ],
    )
    validate_publishable(
        {"run_id": "DIM-1", "status": "PUBLISHED"},
        [{"dimension_id": "D1", "review_status": "APPROVED", "analyst_name": "Payments reliability"}],
    )


def test_publish_rejects_approved_but_unnamed_factors():
    with pytest.raises(PublicationError, match="needs an LLM or analyst-approved name"):
        validate_publishable(
            {"run_id": "DIM-1", "status": "APPROVED"},
            [{"dimension_id": "D1", "review_status": "APPROVED", "analyst_name": ""}],
        )
