"""Publication gates for reviewed dimension runs."""

from __future__ import annotations

from typing import Any


class PublicationError(ValueError):
    pass


def validate_publishable(run: dict[str, Any], definitions: list[dict[str, Any]]) -> None:
    if run.get("status") not in {"PENDING_REVIEW", "APPROVED", "PUBLISHED"}:
        raise PublicationError(f"Run {run.get('run_id')} cannot be published from status {run.get('status')}.")
    if not definitions:
        raise PublicationError("The run has no dimension definitions to publish.")
    rejected = [item["dimension_id"] for item in definitions if item.get("review_status") == "REJECTED"]
    if rejected:
        raise PublicationError(f"Rejected dimensions must be resolved before publishing: {', '.join(rejected)}.")
    unnamed = [
        item["dimension_id"]
        for item in definitions
        if not (item.get("analyst_name") or "").strip()
    ]
    if unnamed:
        raise PublicationError(
            "Every retained dimension needs an LLM or analyst-approved name before publication. "
            f"Unnamed: {', '.join(unnamed)}."
        )
    pending = [item["dimension_id"] for item in definitions if item.get("review_status") != "APPROVED"]
    if pending:
        raise PublicationError(
            "Every retained dimension must be reviewed and approved before publication. "
            f"Pending: {', '.join(pending)}."
        )
