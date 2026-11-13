"""Orchestration for problem portfolio serialization and narrative generation."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from ..intelligence.portfolio.narrative import NarrativeProvider, build_narrative_provider
from ..intelligence.portfolio.serialization import build_portfolio_serialization
from ..intelligence.portfolio.validation import validate_portfolio_narrative
from ..repository import Repository, now_iso

logger = logging.getLogger("bci.problem_portfolio")


class ProblemPortfolioService:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        narrative_provider: NarrativeProvider | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.narrative_provider = narrative_provider if narrative_provider is not None else build_narrative_provider(settings)
        self._threads: dict[str, threading.Thread] = {}

    def _resolve_feedback_run(self, feedback_run_id: str | None) -> dict[str, Any]:
        if feedback_run_id:
            run = self.repo.get_run(feedback_run_id)
            if not run:
                raise ValueError(f"Feedback run {feedback_run_id} was not found.")
        else:
            run = self.repo.latest_completed_feedback_run()
            if not run:
                raise ValueError("No completed feedback run is available for portfolio analysis.")
        if run.get("run_type") != "feedback" or run.get("status") != "completed":
            raise ValueError(f"Feedback run {run['run_id']} is not a completed feedback run.")
        return run

    def _resolve_dimension_run(self, feedback_run_id: str, dimension_run_id: str | None) -> dict[str, Any]:
        if dimension_run_id:
            run = self.repo.get_dimension_run(dimension_run_id)
            if not run:
                raise ValueError(f"Dimension run {dimension_run_id} was not found.")
            if run.get("feedback_run_id") != feedback_run_id:
                raise ValueError("Dimension run does not belong to the requested feedback run.")
        else:
            run = self.repo.latest_usable_dimension_run(feedback_run_id)
            if not run:
                raise ValueError(
                    "No approved or published factor run is available. Review and approve factor names first."
                )
            run = self.repo.get_dimension_run(run["run_id"])
        if not run:
            raise ValueError("Factor run could not be loaded.")
        if self.settings.portfolio_require_approved_factors and run.get("status") not in {"APPROVED", "PUBLISHED"}:
            raise ValueError(
                f"Factor run {run['run_id']} has status {run.get('status')}; approve all factor names before generating a narrative."
            )
        return run

    def start(
        self,
        feedback_run_id: str | None = None,
        dimension_run_id: str | None = None,
        *,
        force_rerun: bool = False,
        generate_narrative: bool = True,
        run_in_thread: bool = True,
    ) -> str:
        if not self.settings.enable_problem_portfolio:
            raise ValueError("Problem portfolio analysis is disabled.")
        feedback_run = self._resolve_feedback_run(feedback_run_id)
        resolved_feedback_run_id = feedback_run["run_id"]
        dimension_run = self._resolve_dimension_run(resolved_feedback_run_id, dimension_run_id)

        if not force_rerun:
            existing = self.repo.find_reusable_portfolio_run(
                resolved_feedback_run_id,
                dimension_run["run_id"],
                self.settings.portfolio_serialization_version,
            )
            if existing:
                return existing["run_id"]

        run_id = f"PPA-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.repo.create_portfolio_run(
            {
                "run_id": run_id,
                "feedback_run_id": resolved_feedback_run_id,
                "dimension_run_id": dimension_run["run_id"],
                "status": "QUEUED",
                "stage": "QUEUED",
                "serialization_version": self.settings.portfolio_serialization_version,
                "narrative_model": getattr(self.narrative_provider, "model_id", None),
                "prompt_version": self.settings.portfolio_narrative_prompt_version,
                "parameters_json": None,
                "summary_json": None,
                "error": None,
                "created_at": now_iso(),
                "started_at": None,
                "completed_at": None,
            }
        )
        self.repo.update_portfolio_run(
            run_id,
            parameters={
                "feedback_run_id": resolved_feedback_run_id,
                "dimension_run_id": dimension_run["run_id"],
                "serialization_version": self.settings.portfolio_serialization_version,
                "narrative_provider": self.settings.portfolio_narrative_provider,
                "narrative_model": getattr(self.narrative_provider, "model_id", None),
                "generate_narrative": generate_narrative,
                "require_approved_factors": self.settings.portfolio_require_approved_factors,
            },
        )
        if run_in_thread:
            thread = threading.Thread(target=self.execute, args=(run_id,), daemon=True, name=f"portfolio-{run_id}")
            self._threads[run_id] = thread
            thread.start()
        else:
            self.execute(run_id)
        return run_id

    def _fail(self, run_id: str, stage: str, error: str) -> None:
        self.repo.update_portfolio_run(
            run_id,
            status="FAILED",
            stage=stage,
            error=error,
            completed_at=now_iso(),
        )
        logger.warning("portfolio run failed", extra={"run_id": run_id, "stage": stage, "error": error})

    def execute(self, run_id: str) -> None:
        run = self.repo.get_portfolio_run(run_id)
        if not run:
            return
        self.repo.update_portfolio_run(
            run_id,
            status="BUILDING_SERIALIZATION",
            stage="BUILDING_SERIALIZATION",
            started_at=now_iso(),
        )
        try:
            serialization = build_portfolio_serialization(
                self.repo,
                run["feedback_run_id"],
                run["dimension_run_id"],
                max_problems=self.settings.portfolio_max_problems,
                serialization_version=self.settings.portfolio_serialization_version,
                require_approved_factors=self.settings.portfolio_require_approved_factors,
            )
            canonical = json.dumps(serialization, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            serialization_id = f"SER-{content_hash[:20]}-{run_id[-6:]}"
            self.repo.save_portfolio_serialization(
                serialization_id=serialization_id,
                run_id=run_id,
                schema_version=self.settings.portfolio_serialization_version,
                content_hash=content_hash,
                payload=serialization,
            )
            self.repo.save_factor_nomenclature(run_id, serialization.get("factor_nomenclature") or [])
            self.repo.save_factor_profiles(run_id, serialization.get("factor_profiles") or [])
            summary = {
                "serialization_id": serialization_id,
                "content_hash": content_hash,
                "n_problems": (serialization.get("source") or {}).get("counts", {}).get("problems_serialized"),
                "n_factors": (serialization.get("source") or {}).get("counts", {}).get("factors"),
                "data_quality_warnings": (serialization.get("data_quality") or {}).get("warnings") or [],
            }
            self.repo.update_portfolio_run(
                run_id,
                summary=summary,
                stage="SERIALIZED",
                status="SERIALIZED",
            )

            if not run.get("parameters", {}).get("generate_narrative", True):
                self.repo.update_portfolio_run(run_id, status="SERIALIZED", stage="SERIALIZED", completed_at=now_iso())
                return

            if self.narrative_provider is None:
                self._save_unavailable_narrative(run_id, serialization_id, "Narrative provider is not configured.")
                summary["narrative_status"] = "UNAVAILABLE"
                self.repo.update_portfolio_run(
                    run_id,
                    summary=summary,
                    status="SERIALIZED",
                    stage="SERIALIZED",
                    completed_at=now_iso(),
                )
                return

            self.repo.update_portfolio_run(run_id, status="GENERATING_NARRATIVE", stage="GENERATING_NARRATIVE")
            result = self._generate_and_validate(run_id, serialization_id, serialization)
            summary["narrative_status"] = result["narrative_status"]
            summary["validation_status"] = result["validation_status"]
            self.repo.update_portfolio_run(
                run_id,
                summary=summary,
                narrative_model=getattr(self.narrative_provider, "model_id", None),
                status="COMPLETED" if result["narrative_status"] in {"PASSED", "WARNING"} else "SERIALIZED",
                stage="COMPLETED" if result["narrative_status"] in {"PASSED", "WARNING"} else "SERIALIZED",
                completed_at=now_iso(),
                error=result.get("error"),
            )
        except Exception as exc:
            logger.exception("portfolio analysis failed", extra={"run_id": run_id})
            self._fail(run_id, "FAILED", str(exc))

    def _save_unavailable_narrative(self, run_id: str, serialization_id: str, error: str) -> None:
        narrative_id = f"NAR-{uuid.uuid4().hex[:16]}"
        self.repo.save_portfolio_narrative(
            narrative_id=narrative_id,
            run_id=run_id,
            serialization_id=serialization_id,
            provider=self.settings.portfolio_narrative_provider,
            model_id=getattr(self.narrative_provider, "model_id", None),
            prompt_version=self.settings.portfolio_narrative_prompt_version,
            status="UNAVAILABLE",
            narrative=None,
            generation_attempts=0,
            error=error,
        )

    def _generate_and_validate(
        self,
        run_id: str,
        serialization_id: str,
        serialization: dict[str, Any],
    ) -> dict[str, Any]:
        provider = self.narrative_provider
        if provider is None:
            raise RuntimeError("Narrative provider is not configured.")
        attempts = max(1, self.settings.portfolio_narrative_max_attempts)
        correction: str | None = None
        last_error: str | None = None
        for attempt in range(1, attempts + 1):
            try:
                narrative = provider.generate(serialization, correction=correction)
                narrative_payload = narrative.model_dump(mode="json")
                validation = validate_portfolio_narrative(narrative, serialization)
                narrative_id = f"NAR-{uuid.uuid4().hex[:16]}"
                self.repo.save_portfolio_narrative(
                    narrative_id=narrative_id,
                    run_id=run_id,
                    serialization_id=serialization_id,
                    provider=getattr(provider, "provider", self.settings.portfolio_narrative_provider),
                    model_id=getattr(provider, "model_id", None),
                    prompt_version=self.settings.portfolio_narrative_prompt_version,
                    status=validation["status"],
                    narrative=narrative_payload,
                    generation_attempts=attempt,
                    error=None,
                )
                self.repo.save_narrative_validation(
                    validation_id=f"VAL-{uuid.uuid4().hex[:16]}",
                    run_id=run_id,
                    narrative_id=narrative_id,
                    result=validation,
                )
                if validation["status"] in {"PASSED", "WARNING"}:
                    return {
                        "narrative_status": validation["status"],
                        "validation_status": validation["status"],
                    }
                correction = (
                    "Fix these validation errors:\n"
                    + "\n".join(f"- {item}" for item in validation.get("errors") or [])
                    + "\nValidation checks:\n"
                    + "\n".join(
                        f"- {item['name']}: {item['message']}"
                        for item in validation.get("checks") or []
                        if item.get("status") == "FAIL"
                    )
                )
                last_error = "Narrative failed deterministic validation."
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "narrative generation attempt failed",
                    extra={"run_id": run_id, "attempt": attempt, "error": last_error},
                )
        narrative_id = f"NAR-{uuid.uuid4().hex[:16]}"
        self.repo.save_portfolio_narrative(
            narrative_id=narrative_id,
            run_id=run_id,
            serialization_id=serialization_id,
            provider=getattr(provider, "provider", self.settings.portfolio_narrative_provider),
            model_id=getattr(provider, "model_id", None),
            prompt_version=self.settings.portfolio_narrative_prompt_version,
            status="FAILED",
            narrative=None,
            generation_attempts=attempts,
            error=last_error or "Narrative generation failed.",
        )
        return {"narrative_status": "FAILED", "validation_status": "FAILED", "error": last_error}

    def regenerate_narrative(self, run_id: str, *, force: bool = False) -> dict[str, Any]:
        run = self.get_run(run_id)
        if self.narrative_provider is None:
            raise ValueError("Narrative provider is not configured.")
        if not force and run.get("narrative"):
            return run
        serialization_row = self.repo.get_portfolio_serialization(run_id)
        if not serialization_row:
            raise ValueError("No serialization is available for this portfolio run.")
        self.repo.update_portfolio_run(run_id, status="GENERATING_NARRATIVE", stage="GENERATING_NARRATIVE", error=None)
        result = self._generate_and_validate(run_id, serialization_row["serialization_id"], serialization_row["payload"])
        summary = dict(run.get("summary") or {})
        summary["narrative_status"] = result["narrative_status"]
        summary["validation_status"] = result["validation_status"]
        self.repo.update_portfolio_run(
            run_id,
            summary=summary,
            status="COMPLETED" if result["narrative_status"] in {"PASSED", "WARNING"} else "SERIALIZED",
            stage="COMPLETED" if result["narrative_status"] in {"PASSED", "WARNING"} else "SERIALIZED",
            completed_at=now_iso(),
            error=result.get("error"),
        )
        return self.get_run(run_id)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repo.list_portfolio_runs(limit)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.repo.get_portfolio_run(run_id)
        if not run:
            raise KeyError(run_id)
        serialization = self.repo.get_portfolio_serialization(run_id)
        if serialization:
            run["serialization"] = {
                "serialization_id": serialization["serialization_id"],
                "schema_version": serialization["schema_version"],
                "content_hash": serialization["content_hash"],
                "created_at": serialization["created_at"],
            }
        run["narrative"] = self.repo.get_latest_portfolio_narrative(run_id)
        run["validation"] = self.repo.get_latest_narrative_validation(run_id)
        run["factor_nomenclature"] = self.repo.get_factor_nomenclature(run_id)
        run["factor_profiles"] = self.repo.get_factor_profiles(run_id)
        return run

    def serialization_payload(self, run_id: str) -> dict[str, Any]:
        row = self.repo.get_portfolio_serialization(run_id)
        if not row:
            raise KeyError(run_id)
        return row

    def narrative_payload(self, run_id: str) -> dict[str, Any]:
        row = self.repo.get_latest_portfolio_narrative(run_id)
        if not row:
            raise KeyError(run_id)
        return row

    def validation_payload(self, run_id: str) -> dict[str, Any]:
        row = self.repo.get_latest_narrative_validation(run_id)
        if not row:
            raise KeyError(run_id)
        return row

    def status(self) -> dict[str, Any]:
        runs = self.list_runs(limit=5)
        latest = runs[0] if runs else None
        return {
            "enabled": self.settings.enable_problem_portfolio,
            "provider": self.settings.portfolio_narrative_provider,
            "model": getattr(self.narrative_provider, "model_id", None),
            "provider_configured": self.narrative_provider is not None,
            "serialization_version": self.settings.portfolio_serialization_version,
            "prompt_version": self.settings.portfolio_narrative_prompt_version,
            "require_approved_factors": self.settings.portfolio_require_approved_factors,
            "latest_run_id": latest.get("run_id") if latest else None,
            "latest_run_status": latest.get("status") if latest else None,
            "latest_runs": runs,
        }
