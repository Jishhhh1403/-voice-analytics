"""Read-only API for the feedback-to-backlog mapping graph."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from ..services.mappings import MappingGraphService

router = APIRouter(prefix="/mappings", tags=["mappings"])


def _service(request: Request) -> MappingGraphService:
    return request.app.state.mappings


@router.get("")
def get_mappings(
    request: Request,
    feedback_run_id: str | None = Query(default=None),
    report_id: str | None = Query(default=None),
) -> dict[str, Any]:
    return _service(request).build(feedback_run_id=feedback_run_id, report_id=report_id)
