from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from ..config import Settings
from ..intelligence.taxonomy import Taxonomy
from ..models import (
    FeedbackPipelineRequest,
    MessageResponse,
    PipelineRunOut,
    PipelineStartResponse,
    ProblemReviewRequest,
    ReportReviewRequest,
    TaxonomyDecisionRequest,
    ValidateBacklogRequest,
)
from ..repository import Repository
from ..services.backlog import BacklogValidationService, csv_template
from ..services.pipeline import FeedbackPipelineService

router = APIRouter()


def _svc(request: Request) -> tuple[FeedbackPipelineService, BacklogValidationService, Repository, Settings]:
    state = request.app.state
    return state.pipeline, state.backlog, state.repo, state.settings


def _idempotent(request: Request, key: str | None, scope: str) -> str | None:
    if not key:
        return None
    repo: Repository = request.app.state.repo
    return repo.db.get_meta(f"idem:{scope}:{key}")


def _remember(request: Request, key: str | None, scope: str, value: str) -> None:
    if not key:
        return
    repo: Repository = request.app.state.repo
    repo.db.set_meta(f"idem:{scope}:{key}", value)


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "environment": settings.environment,
        "object_store": settings.object_store,
        "provider": request.app.state.pipeline.provider.model_id,
        "taxonomy_version": request.app.state.pipeline.taxonomy.version,
        "schema_version": settings.schema_version,
    }


@router.get("/meta/source")
def source_meta(request: Request) -> dict[str, Any]:
    pipeline, _, repo, settings = _svc(request)
    latest = repo.latest_completed_feedback_run()
    source: dict[str, Any] = {}
    try:
        uri = pipeline.ensure_default_source()
        stat = pipeline.store.stat(uri)  # type: ignore[attr-defined]
        source = stat.to_dict()
    except Exception as exc:  # noqa: BLE001
        source = {"error": type(exc).__name__}
    return {
        "default_source": source,
        "sample_feedback_path": str(settings.sample_feedback_path),
        "sample_feedback_exists": settings.sample_feedback_path.exists(),
        "sample_backlog_path": str(settings.sample_backlog_path),
        "provider": pipeline.provider.model_id,
        "embedding_provider": settings.embedding_provider,
        "taxonomy_version": pipeline.taxonomy.version,
        "code_version": settings.code_version,
        "schema_version": settings.schema_version,
        "synthetic_dataset": True,
        "synthetic_warning": (
            "The bundled dataset is synthetic and was generated for software testing. "
            "It is not real customer feedback and is not representative of any bank."
        ),
        "latest_completed_run": latest,
        "max_feedback_bytes": settings.max_feedback_bytes,
        "max_backlog_bytes": settings.max_backlog_bytes,
    }


@router.get("/feedback-sources")
def list_feedback_sources(request: Request) -> list[dict[str, Any]]:
    pipeline, _, _, settings = _svc(request)
    objects = pipeline.store.list_prefix(settings.gcs_feedback_prefix)  # type: ignore[attr-defined]
    return [item.to_dict() for item in objects]


@router.post("/feedback-sources", status_code=201)
async def upload_feedback_source(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
    pipeline, _, repo, settings = _svc(request)
    filename = file.filename or "feedback.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv feedback files are accepted")
    data = await file.read()
    if len(data) > settings.max_feedback_bytes:
        raise HTTPException(status_code=413, detail="File exceeds the configured maximum size")
    key = f"{settings.gcs_feedback_prefix}/{filename}"
    stored = pipeline.store.put_bytes(key, data, "text/csv")  # type: ignore[attr-defined]
    repo.audit("system", "feedback_source_upload", "object", key, {"size_bytes": len(data)})
    return stored.to_dict()


# ------------------------------------------------------------------ feedback runs
@router.post("/feedback-pipelines", response_model=PipelineStartResponse, status_code=202)
def start_feedback_pipeline(
    body: FeedbackPipelineRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PipelineStartResponse:
    pipeline, _, repo, _ = _svc(request)
    existing = _idempotent(request, idempotency_key, "feedback")
    if existing:
        run = repo.get_run(existing)
        return PipelineStartResponse(run_id=existing, status=(run or {}).get("status", "queued"), correlation_id=(run or {}).get("correlation_id", ""))
    try:
        run_id = pipeline.start(
            input_uri=body.input_uri,
            object_generation=body.object_generation,
            tenant_id=body.tenant_id,
            force_rerun=body.force_rerun,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not start pipeline: {type(exc).__name__}") from exc
    _remember(request, idempotency_key, "feedback", run_id)
    run = repo.get_run(run_id) or {}
    return PipelineStartResponse(run_id=run_id, status=run.get("status", "queued"), correlation_id=run.get("correlation_id", ""))


@router.get("/feedback-pipelines", response_model=list[PipelineRunOut])
def list_feedback_pipelines(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    _, _, repo, _ = _svc(request)
    return repo.list_runs(run_type="feedback", limit=limit)


@router.get("/feedback-pipelines/{run_id}", response_model=PipelineRunOut)
def get_feedback_pipeline(run_id: str, request: Request) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    run = repo.get_run(run_id)
    if not run or run.get("run_type") != "feedback":
        raise HTTPException(status_code=404, detail="pipeline run not found")
    return run


@router.get("/feedback/summary")
def feedback_summary(
    request: Request,
    run_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    source_type: str | None = None,
    platform: str | None = None,
    journey: str | None = None,
) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    return repo.summary(run_id, start_date, end_date, source_type, platform, journey)


@router.get("/feedback/options")
def feedback_options(request: Request, run_id: str | None = None) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    return repo.filters_options(run_id)


@router.get("/problems")
def list_problems(
    request: Request,
    run_id: str | None = None,
    search: str | None = None,
    journey: str | None = None,
    status: str | None = None,
    sort: str = Query(default="evidence", pattern="^(evidence|recent|negative|title)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    return repo.list_problems(run_id, search, journey, status, sort, page, page_size)


@router.get("/problems/{problem_id}")
def get_problem(problem_id: str, request: Request) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    problem = repo.get_problem(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="problem not found")
    return problem


@router.post("/problems/{problem_id}/review", response_model=MessageResponse)
def review_problem(problem_id: str, body: ProblemReviewRequest, request: Request) -> MessageResponse:
    _, _, repo, _ = _svc(request)
    if not repo.get_problem(problem_id):
        raise HTTPException(status_code=404, detail="problem not found")
    repo.review_problem(problem_id, body.reviewer, body.decision, body.note, body.new_title)
    return MessageResponse(message="Review recorded with audit trail")


@router.get("/taxonomy")
def get_taxonomy(request: Request) -> dict[str, Any]:
    pipeline, _, _, _ = _svc(request)
    taxonomy: Taxonomy = pipeline.taxonomy
    return {"version": taxonomy.version, "nodes": taxonomy.tree()}


@router.get("/taxonomy/proposals")
def get_taxonomy_proposals(request: Request, status: str | None = None) -> list[dict[str, Any]]:
    _, _, repo, _ = _svc(request)
    return repo.proposals(status)


@router.post("/taxonomy/proposals/{proposal_id}/review", response_model=MessageResponse)
def review_taxonomy_proposal(proposal_id: str, body: TaxonomyDecisionRequest, request: Request) -> MessageResponse:
    _, _, repo, _ = _svc(request)
    repo.review_proposal(proposal_id, body.reviewer, body.decision, body.note)
    return MessageResponse(message="Taxonomy proposal decision recorded")


@router.get("/journey")
def journey_explorer(request: Request, run_id: str | None = None) -> dict[str, Any]:
    pipeline, _, repo, _ = _svc(request)
    taxonomy: Taxonomy = pipeline.taxonomy
    meta = repo.travel_metadata(run_id)
    counts = {row["journey_node_id"]: row for row in meta.get("node_counts", [])}
    direct = {node_id: int(row.get("problems") or 0) for node_id, row in counts.items() if node_id}
    evidence = {node_id: int(row.get("evidence") or 0) for node_id, row in counts.items() if node_id}

    def build(parent_id: str | None) -> list[dict[str, Any]]:
        nodes = []
        for node in taxonomy.children.get(parent_id, []):
            children = build(node.node_id)
            node_problems = direct.get(node.node_id, 0) + sum(child["problem_count"] for child in children)
            node_evidence = evidence.get(node.node_id, 0) + sum(child["evidence_count"] for child in children)
            nodes.append(
                {
                    "node_id": node.node_id,
                    "parent_id": node.parent_id,
                    "node_type": node.node_type,
                    "display_name": node.display_name,
                    "description": node.description,
                    "problem_count": node_problems,
                    "evidence_count": node_evidence,
                    "children": children,
                }
            )
        return nodes

    active_run_id = meta.get("run_id")
    unmapped = repo.db.query_one(
        "SELECT COUNT(*) AS problems, COALESCE(SUM(evidence_count), 0) AS evidence "
        "FROM customer_problems WHERE run_id=? AND (journey_node_id IS NULL OR journey_node_id='')",
        (active_run_id,),
    ) if active_run_id else None
    return {
        "version": taxonomy.version,
        "run_id": active_run_id,
        "tree": build(None),
        "unmapped": {
            "problem_count": int((unmapped or {}).get("problems") or 0),
            "evidence_count": int((unmapped or {}).get("evidence") or 0),
        },
    }


# ------------------------------------------------------------------ backlog
@router.get("/backlog-template")
def backlog_template() -> Response:
    return Response(
        content=csv_template(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="backlog_template.csv"'},
    )


@router.post("/backlog-uploads", status_code=201)
async def upload_backlog(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
    _, service, _, _ = _svc(request)
    filename = file.filename or "backlog.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv backlog files are accepted")
    data = await file.read()
    try:
        upload = service.upload(filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return upload


@router.post("/backlog-uploads/sample", status_code=201)
def upload_sample_backlog(request: Request) -> dict[str, Any]:
    _, service, _, settings = _svc(request)
    if not settings.sample_backlog_path.exists():
        raise HTTPException(status_code=404, detail="sample backlog file is not available")
    upload = service.upload(settings.sample_backlog_path.name, settings.sample_backlog_path.read_bytes())
    return upload


@router.get("/backlog-uploads")
def list_backlog_uploads(request: Request, limit: int = Query(default=25, ge=1, le=100)) -> list[dict[str, Any]]:
    _, _, repo, _ = _svc(request)
    return repo.list_backlog_uploads(limit)


@router.get("/backlog-uploads/{upload_id}")
def get_backlog_upload(upload_id: str, request: Request) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    upload = repo.get_backlog_upload(upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="backlog upload not found")
    return upload


@router.post("/backlog-uploads/{upload_id}/validate", response_model=PipelineStartResponse, status_code=202)
def validate_backlog(
    upload_id: str,
    body: ValidateBacklogRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PipelineStartResponse:
    _, service, repo, _ = _svc(request)
    if not repo.get_backlog_upload(upload_id):
        raise HTTPException(status_code=404, detail="backlog upload not found")
    existing = _idempotent(request, idempotency_key, "validate")
    if existing:
        return PipelineStartResponse(run_id=existing, status="queued", correlation_id="")
    try:
        run_id = service.start_validation(upload_id, body.force_rerun)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _remember(request, idempotency_key, "validate", run_id)
    return PipelineStartResponse(run_id=run_id, status="queued", correlation_id="")


@router.get("/backlog-validation-runs/{run_id}")
def get_validation_run(run_id: str, request: Request) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    run = repo.get_validation_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="validation run not found")
    return run


@router.get("/backlog-validation-reports")
def list_validation_reports(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    _, _, repo, _ = _svc(request)
    return repo.list_reports(limit)


def _safe_csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@router.get("/backlog-validation-reports/{report_id}")
def get_validation_report(report_id: str, request: Request) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    report = repo.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@router.get("/backlog-validation-reports/{report_id}/download")
def download_validation_report(report_id: str, request: Request, format: str = Query(default="json", pattern="^(json|csv)$")) -> Response:
    _, service, repo, _ = _svc(request)
    report = repo.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    payload = report["report"]
    if format == "csv":
        rows = service.report_download_rows(payload)
        output = io.StringIO()
        writer = csv.writer(output)
        for row in rows:
            writer.writerow([_safe_csv_cell(cell) for cell in row])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.csv"'},
        )
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{report_id}.json"'},
    )


@router.get("/backlog-validation-reports/{report_id}/coverage")
def get_validation_coverage(report_id: str, request: Request) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    stored = repo.get_report(report_id)
    if not stored:
        raise HTTPException(status_code=404, detail="report not found")
    report = stored.get("report") or {}
    basis = report.get("validation_basis") or "canonical_problems"
    matrix = repo.db.query(
        "SELECT * FROM backlog_coverage_matrix WHERE report_id=? ORDER BY priority_rank", (report_id,)
    )
    candidates = repo.db.query(
        "SELECT * FROM backlog_problem_candidates WHERE report_id=? ORDER BY backlog_id, rank", (report_id,)
    )
    for row in candidates:
        row["reasons"] = _json_value(row.pop("reasons_json", None), {})
    if basis == "factor_prioritisation":
        factor_coverage = report.get("factor_coverage") or []
        summary = {
            "covered_factors": sum(1 for row in factor_coverage if row.get("covered_by_count")),
            "uncovered_factors": sum(1 for row in factor_coverage if not row.get("covered_by_count")),
            "total_factors": len(factor_coverage),
            "total": len(matrix),
        }
        note = (
            "Coverage is factor-prioritisation coverage. High-priority factors with no backlog "
            "coverage remain explicit gaps; organisational priority is a human decision."
        )
    else:
        factor_coverage = []
        summary = {
            "covered": sum(1 for row in matrix if row["coverage_type"] in {"full", "partial"}),
            "uncovered": sum(1 for row in matrix if row["coverage_type"] == "uncovered"),
            "needs_review": sum(1 for row in matrix if row["coverage_type"] == "needs_review"),
            "total": len(matrix),
        }
        note = "Coverage is customer-evidence coverage; organisational priority remains a human decision."
    return {
        "report_id": report_id,
        "validation_basis": basis,
        "summary": summary,
        "matrix": matrix,
        "candidates": candidates,
        "factor_coverage": factor_coverage,
        "note": note,
    }


@router.post("/backlog-validation-reports/{report_id}/review", response_model=MessageResponse)
def review_validation_report(report_id: str, body: ReportReviewRequest, request: Request) -> MessageResponse:
    _, _, repo, _ = _svc(request)
    if not repo.get_report(report_id):
        raise HTTPException(status_code=404, detail="report not found")
    repo.review_report(report_id, body.reviewer, body.decision, body.note, body.backlog_id)
    return MessageResponse(message="Product-owner review recorded")


def _json_value(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


@router.get("/priorities")
def list_priorities(request: Request, run_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    if run_id is None:
        latest = repo.latest_completed_feedback_run()
        run_id = latest["run_id"] if latest else None
    if not run_id:
        return {"run_id": None, "items": [], "methodology_version": None}
    rows = repo.db.query(
        "SELECT * FROM problem_priority_snapshots WHERE run_id=? ORDER BY rank LIMIT ?", (run_id, limit)
    )
    items = []
    for row in rows:
        row["escalation_reasons"] = _json_value(row.pop("escalation_reasons_json", None), [])
        row["missing_metrics"] = _json_value(row.pop("missing_metrics_json", None), [])
        row["supporting_evidence"] = _json_value(row.pop("supporting_evidence_json", None), {})
        items.append(row)
    return {
        "run_id": run_id,
        "methodology_version": items[0]["methodology_version"] if items else None,
        "items": items,
        "note": "Priority is a customer-evidence prioritisation, not an organisational approval decision.",
    }


@router.get("/problems/{problem_id}/priority")
def get_problem_priority(problem_id: str, request: Request) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    rows = repo.db.query(
        "SELECT * FROM problem_priority_snapshots WHERE problem_id=? ORDER BY calculated_at DESC LIMIT 1",
        (problem_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="priority snapshot not found")
    row = rows[0]
    row["escalation_reasons"] = _json_value(row.pop("escalation_reasons_json", None), [])
    row["missing_metrics"] = _json_value(row.pop("missing_metrics_json", None), [])
    row["supporting_evidence"] = _json_value(row.pop("supporting_evidence_json", None), {})
    return row


@router.get("/problem-map")
def get_problem_map(request: Request, run_id: str | None = None) -> dict[str, Any]:
    pipeline, _, _, _ = _svc(request)
    return pipeline.mds.payload(run_id)


@router.post("/problem-map/recompute", response_model=None)
def recompute_problem_map(request: Request, run_id: str | None = None) -> dict[str, Any]:
    pipeline, _, _, _ = _svc(request)
    return pipeline.mds.recompute(run_id)


@router.get("/problem-map/{problem_id}")
def get_problem_map_theme(problem_id: str, request: Request) -> dict[str, Any]:
    pipeline, _, repo, _ = _svc(request)
    problem = repo.get_problem(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="problem not found")
    payload = pipeline.mds.payload(problem["run_id"])
    theme = next((item for item in payload.get("themes", []) if item["problem_id"] == problem_id), None)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme map point not found")
    return {
        "run_id": payload["run_id"],
        "status": payload["status"],
        "theme": theme,
        "problem": problem,
        "note": "MDS coordinates are semantic only; business attributes are separate.",
    }


@router.get("/problems/{problem_id}/measurement")
def get_problem_measurement(problem_id: str, request: Request) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    latest = repo.db.query_one(
        "SELECT run_id FROM problem_measurement_snapshots WHERE problem_id=? ORDER BY calculated_at DESC LIMIT 1",
        (problem_id,),
    )
    if not latest:
        raise HTTPException(status_code=404, detail="measurement not found")
    run_id = latest["run_id"]
    snapshots = repo.db.query(
        "SELECT * FROM problem_measurement_snapshots WHERE problem_id=? AND run_id=? ORDER BY metric_name",
        (problem_id, run_id),
    )
    for row in snapshots:
        row["dimensions"] = _json_value(row.pop("dimensions_json", None), {})
        row["metadata"] = _json_value(row.pop("metadata_json", None), {})
    daily = repo.db.query(
        "SELECT day, metric_name, metric_value, unit, status FROM problem_metrics_daily "
        "WHERE problem_id=? AND run_id=? ORDER BY day",
        (problem_id, run_id),
    )
    return {"problem_id": problem_id, "run_id": run_id, "snapshots": snapshots, "daily": daily}


@router.get("/data-quality")
def data_quality(request: Request, run_id: str | None = None) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    if run_id is None:
        latest = repo.latest_completed_feedback_run()
        run_id = latest["run_id"] if latest else None
    if not run_id:
        return {"run_id": None, "checks": []}
    rows = repo.db.query("SELECT * FROM data_quality_reports WHERE run_id=? ORDER BY id", (run_id,))
    for row in rows:
        row["detail"] = _json_value(row.pop("detail_json", None), {})
    return {"run_id": run_id, "checks": rows}


@router.get("/duplicates")
def duplicate_report(request: Request, run_id: str | None = None) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    if run_id is None:
        latest = repo.latest_completed_feedback_run()
        run_id = latest["run_id"] if latest else None
    if not run_id:
        return {"run_id": None, "items": [], "policy": "linked_not_discarded"}
    rows = repo.db.query(
        "SELECT * FROM feedback_duplicate_candidates WHERE run_id=? ORDER BY duplicate_type, detected_at", (run_id,)
    )
    for row in rows:
        row["metadata"] = _json_value(row.pop("metadata_json", None), {})
    return {"run_id": run_id, "items": rows, "policy": "linked_not_discarded"}


@router.get("/diagnostics")
def diagnostics(request: Request, run_id: str | None = None) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    if run_id is None:
        latest = repo.latest_completed_feedback_run()
        run_id = latest["run_id"] if latest else None
    if not run_id:
        return {"run_id": None, "items": []}
    rows = repo.db.query(
        "SELECT feedback_id, technical_root_cause, COUNT(*) AS occurrences FROM extracted_insights "
        "WHERE run_id=? GROUP BY feedback_id, technical_root_cause",
        (run_id,),
    )
    return {
        "run_id": run_id,
        "items": rows,
        "note": "Technical root cause is 'unknown' unless grounded evidence exists; the pipeline never infers it from sentiment.",
    }


@router.get("/problem-relationships")
def problem_relationships(request: Request, run_id: str | None = None) -> list[dict[str, Any]]:
    _, _, repo, _ = _svc(request)
    if run_id is None:
        latest = repo.latest_completed_feedback_run()
        run_id = latest["run_id"] if latest else None
    if not run_id:
        return []
    return repo.db.query("SELECT * FROM problem_relationships WHERE run_id=? ORDER BY created_at", (run_id,))


@router.get("/admin/overview")
def admin_overview(request: Request) -> dict[str, Any]:
    _, _, repo, _ = _svc(request)
    return repo.admin_overview()
