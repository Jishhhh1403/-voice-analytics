"""API surface for exploratory problem-dimension analysis."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from ..models import (
    DimensionPublishRequest,
    DimensionReviewRequest,
    ProblemDimensionRunRequest,
)
from ..services.problem_dimensions import ProblemDimensionService

router = APIRouter(prefix="/problem-dimensions", tags=["problem-dimensions"])


def _service(request: Request) -> ProblemDimensionService:
    return request.app.state.problem_dimensions


@router.get("/status")
def dimension_status(request: Request) -> dict[str, Any]:
    service = _service(request)
    latest = service.latest_published()
    return {
        "enabled": service.settings.enable_problem_dimensions,
        "method": service.settings.problem_dimension_method,
        "methodology_version": service.settings.problem_dimension_methodology_version,
        "feature_schema_version": service.settings.problem_dimension_feature_schema_version,
        "review_required": service.settings.problem_dimension_require_review,
        "latest_published_run_id": latest["run"]["run_id"] if latest else None,
        "latest_published_at": latest["publication"]["created_at"] if latest else None,
        "latest_runs": service.list_runs(limit=5),
    }


@router.post("/runs")
def start_dimension_run(
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
def list_dimension_runs(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    return _service(request).list_runs(limit=limit)


@router.get("/runs/{run_id}")
def get_dimension_run(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dimension run not found") from exc


@router.get("/runs/{run_id}/dimensions/{dimension_id}")
def get_run_dimension(run_id: str, dimension_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).dimension_payload(dimension_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dimension run or dimension not found") from exc


@router.get("/runs/{run_id}/problems/{problem_id}")
def get_run_problem_dimensions(run_id: str, problem_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).problem_payload(problem_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dimension run or problem not found") from exc


@router.get("/runs/{run_id}/coefficients")
def get_coefficient_matrix(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).coefficient_matrix(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dimension run not found") from exc


@router.get("/runs/{run_id}/coefficients.csv")
def download_coefficient_matrix(run_id: str, request: Request) -> Response:
    try:
        matrix = _service(request).coefficient_matrix(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dimension run not found") from exc
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "problem_id",
            "dimension_id",
            "dimension_number",
            "factor_name",
            "coefficient",
            "relative_squared_coordinate_share_pct",
            "coordinate_rank",
        ],
    )
    writer.writeheader()
    for row in matrix["coefficients"]:
        writer.writerow(
            {
                "problem_id": row["problem_id"],
                "dimension_id": row["dimension_id"],
                "dimension_number": row.get("dimension_number"),
                "factor_name": row.get("factor_name"),
                "coefficient": row.get("coefficient"),
                "relative_squared_coordinate_share_pct": row.get("relative_squared_coordinate_share_pct"),
                "coordinate_rank": row.get("coordinate_rank"),
            }
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{run_id}-coefficients.csv"'},
    )


@router.get("/runs/{run_id}/variables")
def get_dimension_variables(
    run_id: str,
    request: Request,
    dimension_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        return _service(request).variables_payload(run_id, dimension_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dimension run not found") from exc


@router.get("/runs/{run_id}/problems/{problem_id}/profile")
def get_problem_factor_profile(run_id: str, problem_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).problem_profile(run_id, problem_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dimension run or problem not found") from exc


@router.get("/latest")
def get_latest_published(request: Request) -> dict[str, Any]:
    latest = _service(request).latest_published()
    if not latest:
        raise HTTPException(status_code=404, detail="No published dimension run is available")
    return latest


@router.get("/latest/dimensions/{dimension_id}")
def get_latest_dimension(dimension_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).dimension_payload(dimension_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Published dimension not found") from exc


@router.get("/latest/problems/{problem_id}")
def get_latest_problem_dimensions(problem_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).problem_payload(problem_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Published problem dimensions not found") from exc


@router.post("/runs/{run_id}/dimensions/{dimension_id}/review")
def review_dimension(
    run_id: str,
    dimension_id: str,
    payload: DimensionReviewRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _service(request).review(
            run_id,
            dimension_id,
            reviewer=payload.reviewer,
            decision=payload.decision,
            name=payload.name,
            description=payload.description,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dimension run or dimension not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/runs/{run_id}/publish")
def publish_dimension_run(run_id: str, payload: DimensionPublishRequest, request: Request) -> dict[str, Any]:
    try:
        return _service(request).publish(run_id, payload.published_by, payload.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dimension run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
