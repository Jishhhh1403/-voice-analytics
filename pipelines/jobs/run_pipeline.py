from __future__ import annotations

import argparse
import json
import sys

from app.config import get_settings
from app.db import Database
from app.repository import Repository
from app.services.pipeline import FeedbackPipelineService
from app.storage import build_object_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the feedback pipeline synchronously (local or Cloud Run Job)."
    )
    parser.add_argument("--input-uri", default=None, help="gs://, local:// or filesystem CSV path")
    parser.add_argument("--generation", default=None, help="Immutable object generation to read")
    parser.add_argument("--force", action="store_true", help="Ignore an existing completed run")
    parser.add_argument("--stage", default="all", help="Requested stage label (PoV runs the full pipeline)")
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.ensure_dirs()
    repo = Repository(Database(settings.db_path))
    pipeline = FeedbackPipelineService(settings, repo, build_object_store(settings))

    try:
        uri = pipeline.ensure_default_source() if not args.input_uri else args.input_uri
        stat = pipeline.store.stat(uri, args.generation)
        run_id = pipeline.start(
            uri,
            args.generation or stat.generation,
            settings.tenant_id,
            force_rerun=args.force,
            run_in_thread=False,
        )
        pipeline.execute(run_id, uri, args.generation or stat.generation)
        run = repo.get_run(run_id)
        print(json.dumps({"run_id": run_id, "stage": args.stage, "status": run["status"], "summary": run["summary"]}))
        return 0 if run["status"] == "completed" else 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "failed", "stage": args.stage, "error": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
