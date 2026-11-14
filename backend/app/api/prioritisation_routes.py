"""API surface for deterministic factor evidence prioritisation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import FactorPrioritisationRunRequest, FactorSemanticReviewRequest
from ..services.factor_prioritisation import FactorPrioritisationService

router = APIRouter(prefix="/factor-prioritisation", tags=["factor-prioritisation"])


def _service(request: Request) -> FactorPrioritisationService:
    return request.app.state.factor_prioritisation


@router.get("/status")
def prioritisation_status(request: Request) -> dict[str, Any]:
    service = _service(request)
    settings = service.settings
    latest = service.repo.latest_factor_prioritisation_run()
    return {
        "enabled": settings.enable_factor_prioritisation,
        "model_version": settings.factor_prioritisation_model_version,
        "weights": {
            "prevalence": settings.factor_prioritisation_weight_prevalence,
            "statistical_importance": settings.factor_prioritisation_weight_statistical,
            "representation_strength": settings.factor_prioritisation_weight_representation,
            "semantic_coherence": settings.factor_prioritisation_weight_semantic,
        },
        "rules": {
            "membership": settings.factor_prioritisation_membership_rule_version,
            "representation": settings.factor_prioritisation_representation_rule_version,
            "semantic": settings.factor_prioritisation_semantic_rule_version,
        },
        "allow_provisional": settings.factor_prioritisation_allow_provisional,
        "representation_multiplier": settings.factor_prioritisation_representation_multiplier,
        "latest_run_id": latest["prioritisation_run_id"] if latest else None,
        "latest_run": latest,
    }


@router.post("/runs")
def start_prioritisation_run(
    payload: FactorPrioritisationRunRequest,
    request: Request,
    background: bool = Query(default=True),
) -> dict[str, Any]:
    service = _service(request)
    try:
        run_id = service.start(
            famd_run_id=payload.famd_run_id,
            feedback_run_id=payload.feedback_run_id,
            weights=payload.weights,
            force_rerun=payload.force_rerun,
            run_in_thread=background,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run = service.repo.get_factor_prioritisation_run(run_id)
    return {"run_id": run_id, "status": run["status"] if run else "QUEUED"}


@router.get("/runs")
def list_prioritisation_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return _service(request).list_runs(limit=limit)


@router.get("/runs/latest")
def latest_prioritisation_run(request: Request) -> dict[str, Any]:
    run = _service(request).latest_run()
    if not run:
        raise HTTPException(status_code=404, detail="No completed prioritisation run is available.")
    return run


@router.get("/runs/{run_id}")
def get_prioritisation_run(run_id: str, request: Request) -> dict[str, Any]:
    run = _service(request).get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Prioritisation run not found.")
    return run


@router.get("/runs/{run_id}/scores")
def get_prioritisation_scores(run_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        return _service(request).get_scores(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/factors/{factor_id}")
def get_prioritisation_factor(run_id: str, factor_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).get_factor(run_id, factor_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/factors/{factor_id}/semantic-assessment/review")
def review_semantic_assessment(
    run_id: str,
    factor_id: str,
    payload: FactorSemanticReviewRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _service(request).review_semantic(
            run_id,
            factor_id,
            reviewer=payload.reviewer,
            decision=payload.decision,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
