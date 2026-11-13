"""Spec-compatible alias for canonical-problem factor coefficient analysis."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import ProblemDimensionRunRequest
from ..services.problem_dimensions import ProblemDimensionService

router = APIRouter(prefix="/factor-analysis", tags=["factor-analysis"])


def _service(request: Request) -> ProblemDimensionService:
    return request.app.state.problem_dimensions


@router.get("/status")
def factor_status(request: Request) -> dict[str, Any]:
    service = _service(request)
    latest = service.latest_published()
    return {
        "enabled": service.settings.enable_problem_dimensions,
        "method": service.settings.problem_dimension_method,
        "methodology_version": service.settings.problem_dimension_methodology_version,
        "feature_schema_version": service.settings.problem_dimension_feature_schema_version,
        "review_required": service.settings.problem_dimension_require_review,
        "latest_published_run_id": latest["run"]["run_id"] if latest else None,
        "latest_runs": service.list_runs(limit=5),
    }


@router.post("/runs")
def start_factor_run(
    payload: ProblemDimensionRunRequest,
    request: Request,
    background: bool = Query(default=True),
) -> dict[str, Any]:
    service = _service(request)
    try:
        run_id = service.start(
            feedback_run_id=payload.feedback_run_id,
            max_components=payload.max_components,
            force_rerun=payload.force_rerun,
            run_in_thread=background,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run = service.get_run(run_id)
    return {"run_id": run_id, "status": run["status"], "stage": run["stage"]}


@router.get("/runs")
def list_factor_runs(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    return _service(request).list_runs(limit=limit)


@router.get("/runs/{run_id}")
def get_factor_run(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Factor run not found") from exc


@router.get("/runs/{run_id}/coefficients")
def get_factor_coefficients(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).coefficient_matrix(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Factor run not found") from exc


@router.get("/runs/{run_id}/variables")
def get_factor_variables(
    run_id: str,
    request: Request,
    dimension_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        return _service(request).variables_payload(run_id, dimension_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Factor run not found") from exc


@router.get("/runs/{run_id}/problems/{problem_id}")
def get_factor_problem(run_id: str, problem_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).problem_profile(run_id, problem_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Factor run or problem not found") from exc
