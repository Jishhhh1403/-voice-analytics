from __future__ import annotations

import json
import logging
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.dimension_routes import router as dimension_router
from .api.factor_routes import router as factor_router
from .api.mapping_routes import router as mapping_router
from .api.portfolio_routes import router as portfolio_router
from .api.prioritisation_routes import router as prioritisation_router
from .api.routes import router
from .config import Settings, get_settings
from .db import Database
from .repository import Repository
from .services.backlog import BacklogValidationService
from .services.factor_prioritisation import FactorPrioritisationService
from .services.mappings import MappingGraphService
from .services.pipeline import FeedbackPipelineService
from .services.problem_dimensions import ProblemDimensionService
from .services.problem_portfolio import ProblemPortfolioService
from .storage import build_object_store


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("run_id", "stage", "correlation_id", "report_id"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "urllib3", "uvicorn.access"):
        logging.getLogger(noisy).setLevel("WARNING")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    db = Database(settings.db_path)
    repo = Repository(db)
    store = build_object_store(settings)
    pipeline = FeedbackPipelineService(settings, repo, store)
    backlog = BacklogValidationService(settings, repo, store)
    problem_dimensions = ProblemDimensionService(settings, repo)
    problem_portfolio = ProblemPortfolioService(settings, repo)
    factor_prioritisation = FactorPrioritisationService(settings, repo)
    mappings = MappingGraphService(repo)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_seed_source and settings.object_store.lower() == "local":
            try:
                pipeline.ensure_default_source()
            except Exception:
                logging.getLogger("bci.startup").exception("could not seed sample feedback source")
        if settings.auto_run_sample and not repo.latest_completed_feedback_run():
            try:
                pipeline.start(None, None, None, force_rerun=False, run_in_thread=True)
                logging.getLogger("bci.startup").info("sample feedback pipeline started")
            except Exception:
                logging.getLogger("bci.startup").exception("could not start sample pipeline")
        yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.code_version,
        description=(
            "Evidence-first banking customer intelligence and backlog validation API. "
            "Local-first implementation with GCS/BigQuery-ready adapters."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.repo = repo
    app.state.store = store
    app.state.pipeline = pipeline
    app.state.backlog = backlog
    app.state.problem_dimensions = problem_dimensions
    app.state.problem_portfolio = problem_portfolio
    app.state.factor_prioritisation = factor_prioritisation
    app.state.mappings = mappings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.include_router(router, prefix=settings.api_prefix)
    app.include_router(dimension_router, prefix=settings.api_prefix)
    app.include_router(factor_router, prefix=settings.api_prefix)
    app.include_router(mapping_router, prefix=settings.api_prefix)
    app.include_router(portfolio_router, prefix=settings.api_prefix)
    app.include_router(prioritisation_router, prefix=settings.api_prefix)

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "name": settings.app_name,
            "version": settings.code_version,
            "docs": "/docs",
            "api": settings.api_prefix,
            "local_first": True,
        }

    return app


app = create_app()
