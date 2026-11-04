from __future__ import annotations

import argparse
import json
import sys
import uuid

from app.config import get_settings
from app.db import Database
from app.repository import Repository
from app.services.backlog import BacklogValidationService
from app.services.pipeline import FeedbackPipelineService
from app.storage import build_object_store


def _run_feedback(args: argparse.Namespace, settings, repo, pipeline) -> int:
    uri = pipeline.ensure_default_source() if not args.input_uri else args.input_uri
    stat = pipeline.store.stat(uri, args.generation)
    generation = args.generation or stat.generation
    run_id = pipeline.start(
        uri,
        generation,
        settings.tenant_id,
        force_rerun=args.force,
        run_in_thread=False,
    )
    existing = repo.get_run(run_id)
    if existing and existing["status"] == "completed" and not args.force:
        print(json.dumps({"run_id": run_id, "stage": args.stage, "status": "completed", "reused": True}))
        return 0
    pipeline.execute(run_id, uri, generation)
    run = repo.get_run(run_id)
    print(
        json.dumps(
            {
                "run_id": run_id,
                "stage": args.stage,
                "status": run["status"],
                "summary": run["summary"],
            }
        )
    )
    return 0 if run["status"] == "completed" else 1


def _run_backlog(args: argparse.Namespace, settings, repo, store) -> int:
    if not args.upload_id:
        print(json.dumps({"status": "failed", "error": "MISSING_UPLOAD_ID"}), file=sys.stderr)
        return 2
    service = BacklogValidationService(settings, repo, store)
    run_id = args.validation_run_id or "VRUN-" + uuid.uuid4().hex[:12]
    if not repo.get_validation_run(run_id):
        repo.create_validation_run(run_id, args.upload_id)
    service.execute(run_id, args.upload_id)
    run = repo.get_validation_run(run_id) or {}
    print(
        json.dumps(
            {
                "validation_run_id": run_id,
                "stage": args.stage,
                "status": run.get("status"),
                "report_id": run.get("report_id"),
            }
        )
    )
    return 0 if run.get("status") == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run feedback or backlog processing synchronously (local or Cloud Run Job).")
    parser.add_argument("--mode", choices=("feedback", "backlog"), default="feedback")
    parser.add_argument("--input-uri", default=None, help="gs://, local:// or filesystem CSV path")
    parser.add_argument("--generation", default=None, help="Immutable object generation to read")
    parser.add_argument("--force", action="store_true", help="Ignore an existing completed run")
    parser.add_argument("--stage", default="all", help="Requested stage label recorded by Workflows")
    parser.add_argument("--upload-id", default=None, help="Backlog upload id for --mode backlog")
    parser.add_argument("--validation-run-id", default=None, help="Existing validation run id for --mode backlog")
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.ensure_dirs()
    repo = Repository(Database(settings.db_path))
    store = build_object_store(settings)

    try:
        if args.mode == "backlog":
            return _run_backlog(args, settings, repo, store)
        pipeline = FeedbackPipelineService(settings, repo, store)
        return _run_feedback(args, settings, repo, pipeline)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(json.dumps({"status": "failed", "stage": args.stage, "error": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
