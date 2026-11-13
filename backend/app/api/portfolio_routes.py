"""API surface for problem portfolio serialization and narrative analysis."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import PortfolioNarrativeRegenerateRequest, PortfolioRunRequest
from ..services.problem_portfolio import ProblemPortfolioService

router = APIRouter(prefix="/problem-portfolio", tags=["problem-portfolio"])


def _service(request: Request) -> ProblemPortfolioService:
    return request.app.state.problem_portfolio


@router.get("/status")
def portfolio_status(request: Request) -> dict[str, Any]:
    return _service(request).status()


@router.post("/runs")
def start_portfolio_run(
    payload: PortfolioRunRequest,
    request: Request,
    background: bool = Query(default=True),
) -> dict[str, Any]:
    service = _service(request)
    try:
        run_id = service.start(
            feedback_run_id=payload.feedback_run_id,
            dimension_run_id=payload.dimension_run_id,
            mds_id=payload.mds_id,
            force_rerun=payload.force_rerun,
            generate_narrative=payload.generate_narrative,
            run_in_thread=background,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run = service.get_run(run_id)
    return {"run_id": run_id, "status": run["status"], "stage": run["stage"]}


@router.get("/runs")
def list_portfolio_runs(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    return _service(request).list_runs(limit=limit)


@router.get("/runs/{run_id}")
def get_portfolio_run(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portfolio run not found") from exc


@router.get("/runs/{run_id}/serialization")
def get_portfolio_serialization(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).serialization_payload(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portfolio serialization not found") from exc


@router.get("/runs/{run_id}/narrative")
def get_portfolio_narrative(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).narrative_payload(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portfolio narrative not found") from exc


@router.post("/runs/{run_id}/narrative/regenerate")
def regenerate_portfolio_narrative(
    run_id: str,
    payload: PortfolioNarrativeRegenerateRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _service(request).regenerate_narrative(run_id, force=payload.force)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portfolio run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}/validation")
def get_narrative_validation(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).validation_payload(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Narrative validation not found") from exc


@router.get("/latest")
def get_latest_portfolio_run(request: Request) -> dict[str, Any]:
    service = _service(request)
    runs = service.list_runs(limit=1)
    if not runs:
        raise HTTPException(status_code=404, detail="No portfolio run is available")
    return service.get_run(runs[0]["run_id"])


@router.get("/latest/narrative")
def get_latest_portfolio_narrative(request: Request) -> dict[str, Any]:
    service = _service(request)
    runs = service.list_runs(limit=1)
    if not runs:
        raise HTTPException(status_code=404, detail="No portfolio run is available")
    try:
        return service.narrative_payload(runs[0]["run_id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portfolio narrative not found") from exc
