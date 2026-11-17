from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from ..services.whitespace import WhitespaceDiscoveryService

router = APIRouter(prefix="/whitespace", tags=["whitespace"])


def _service(request: Request) -> WhitespaceDiscoveryService:
    return request.app.state.whitespace


@router.get("")
def discover_whitespace(
    request: Request,
    run_id: str | None = Query(default=None),
    report_id: str | None = Query(default=None),
    upload_id: str | None = Query(default=None),
) -> dict[str, Any]:
    return _service(request).discover_dict(run_id=run_id, report_id=report_id, upload_id=upload_id)
