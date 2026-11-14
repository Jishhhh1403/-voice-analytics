"""Orchestration for deterministic factor evidence prioritisation."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from ..intelligence.factor_prioritisation import (
    FactorPrioritisationDataError,
    FactorPrioritisationDataService,
    FactorPriorityCalculator,
    PrioritisationRules,
    PrioritisationWeights,
)
from ..repository import Repository, now_iso

logger = logging.getLogger("bci.factor_prioritisation")

WEIGHT_KEYS = (
    "prevalence",
    "statistical_importance",
    "representation_strength",
    "semantic_coherence",
)


class FactorPrioritisationService:
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo
        self._threads: dict[str, threading.Thread] = {}

    def _default_weights(self) -> PrioritisationWeights:
        return PrioritisationWeights(
            prevalence=self.settings.factor_prioritisation_weight_prevalence,
            statistical_importance=self.settings.factor_prioritisation_weight_statistical,
            representation_strength=self.settings.factor_prioritisation_weight_representation,
            semantic_coherence=self.settings.factor_prioritisation_weight_semantic,
        )

    def _resolve_weights(self, overrides: dict[str, Any] | None) -> PrioritisationWeights:
        if not overrides:
            weights = self._default_weights()
        else:
            unknown = set(overrides) - set(WEIGHT_KEYS)
            if unknown:
                raise ValueError("Unknown prioritisation weight(s): " + ", ".join(sorted(unknown)))
            values = self._default_weights().as_dict()
            for key, value in overrides.items():
                try:
                    number = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Prioritisation weight {key} must be numeric.") from exc
                if number < 0:
                    raise ValueError(f"Prioritisation weight {key} must not be negative.")
                values[key] = number
            weights = PrioritisationWeights(**values)
        if sum(weights.as_dict().values()) <= 0:
            raise ValueError("At least one prioritisation weight must be greater than zero.")
        return weights

    def _resolve_dimension_run(
        self,
        famd_run_id: str | None,
        feedback_run_id: str | None,
    ) -> dict[str, Any]:
        if famd_run_id:
            run = self.repo.get_dimension_run(famd_run_id)
        else:
            run = self.repo.latest_prioritisable_dimension_run(feedback_run_id)
        if not run:
            raise ValueError(
                "No structurally complete factor run is available for prioritisation. "
                "Complete a factor analysis run first."
            )
        if feedback_run_id and run.get("feedback_run_id") != feedback_run_id:
            raise ValueError("Factor run does not belong to the requested feedback run.")
        if run.get("status") not in {"PENDING_REVIEW", "APPROVED", "PUBLISHED"}:
            raise ValueError(
                f"Factor run {run['run_id']} has status {run.get('status') or 'UNKNOWN'}; "
                "prioritisation requires a successfully completed factor run."
            )
        return run

    def _rules(self, weights: PrioritisationWeights) -> PrioritisationRules:
        return PrioritisationRules(
            model_version=self.settings.factor_prioritisation_model_version,
            weights=weights,
            representation_multiplier=self.settings.factor_prioritisation_representation_multiplier,
            allow_provisional=self.settings.factor_prioritisation_allow_provisional,
            minimum_problem_count=self.settings.factor_prioritisation_min_problem_count,
            membership_rule_version=self.settings.factor_prioritisation_membership_rule_version,
            membership_min_score=self.settings.factor_prioritisation_membership_min_score,
            representation_rule_version=self.settings.factor_prioritisation_representation_rule_version,
            semantic_rule_version=self.settings.factor_prioritisation_semantic_rule_version,
            metadata={"code_version": self.settings.code_version},
        )

    def start(
        self,
        famd_run_id: str | None = None,
        feedback_run_id: str | None = None,
        *,
        weights: dict[str, Any] | None = None,
        force_rerun: bool = False,
        run_in_thread: bool = True,
    ) -> str:
        if not self.settings.enable_factor_prioritisation:
            raise ValueError("Factor prioritisation is disabled.")
        run = self._resolve_dimension_run(famd_run_id, feedback_run_id)
        resolved_weights = self._resolve_weights(weights)
        weight_configuration = resolved_weights.normalised()
        weight_json = json.dumps(weight_configuration, sort_keys=True, separators=(",", ":"))
        if not force_rerun:
            existing = self.repo.find_reusable_factor_prioritisation_run(
                run["run_id"],
                self.settings.factor_prioritisation_model_version,
                weight_json,
            )
            if existing:
                return existing["prioritisation_run_id"]

        run_id = f"FPR-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        rules = self._rules(resolved_weights)
        self.repo.create_factor_prioritisation_run(
            {
                "prioritisation_run_id": run_id,
                "famd_run_id": run["run_id"],
                "feedback_run_id": run.get("feedback_run_id"),
                "feature_schema_version": run.get("feature_schema_version"),
                "scoring_model_version": rules.model_version,
                "weight_configuration_json": weight_json,
                "membership_rule_version": rules.membership_rule_version,
                "representation_rule_version": rules.representation_rule_version,
                "semantic_rule_version": rules.semantic_rule_version,
                "status": "QUEUED",
                "stage": "QUEUED",
                "total_factor_count": 0,
                "eligible_factor_count": 0,
                "provisional_factor_count": 0,
                "excluded_factor_count": 0,
                "summary_json": None,
                "error": None,
                "created_at": now_iso(),
                "started_at": None,
                "completed_at": None,
            }
        )
        if run_in_thread:
            thread = threading.Thread(
                target=self.execute,
                args=(run_id,),
                daemon=True,
                name=f"factor-prioritisation-{run_id}",
            )
            self._threads[run_id] = thread
            thread.start()
        else:
            self.execute(run_id)
        return run_id

    def _fail(self, run_id: str, stage: str, error: str) -> None:
        self.repo.update_factor_prioritisation_run(
            run_id,
            status="FAILED",
            stage=stage,
            error=error,
            completed_at=now_iso(),
        )
        logger.warning("factor prioritisation failed", extra={"run_id": run_id, "stage": stage, "error": error})

    def execute(self, run_id: str) -> None:
        run = self.repo.get_factor_prioritisation_run(run_id)
        if not run:
            return
        self.repo.update_factor_prioritisation_run(
            run_id,
            status="CALCULATING",
            stage="CALCULATING",
            started_at=now_iso(),
        )
        try:
            dataset = FactorPrioritisationDataService(self.repo).load(run["famd_run_id"])
            weights = self._resolve_weights(run.get("weight_configuration"))
            result = FactorPriorityCalculator(self._rules(weights)).calculate(dataset)
            self.repo.save_factor_prioritisation_results(
                run_id,
                scores=result["scores"],
                evidence=result["evidence"],
                semantic_assessments=result["semantic_assessments"],
            )
            summary = result["summary"]
            self.repo.update_factor_prioritisation_run(
                run_id,
                status="COMPLETED",
                stage="COMPLETED",
                total_factor_count=summary["factor_count"],
                eligible_factor_count=summary["eligible_factor_count"],
                provisional_factor_count=summary["provisional_factor_count"],
                excluded_factor_count=(
                    summary["excluded_factor_count"]
                    + summary["insufficient_evidence_factor_count"]
                ),
                summary=summary,
                completed_at=now_iso(),
            )
        except FactorPrioritisationDataError as exc:
            self._fail(run_id, "VALIDATING_DATA", str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("unexpected factor prioritisation error", extra={"run_id": run_id})
            self._fail(run_id, "CALCULATING", str(exc))

    def _apply_current_nomenclature(
        self,
        famd_run_id: str,
        scores: list[dict[str, Any]],
        assessments: list[dict[str, Any]] | None = None,
    ) -> None:
        nomenclature = {
            str(item["dimension_id"]): item
            for item in self.repo.latest_dimension_narrative_nomenclature(famd_run_id)
        }

        def payload(dimension_id: str) -> dict[str, Any]:
            item = nomenclature.get(dimension_id, {})
            name = str(item.get("factor_name") or "").strip() or None
            description = str(item.get("description") or "").strip() or None
            return {
                "factor_name": name,
                "short_name": item.get("short_name"),
                "description": description,
                "source": item.get("source"),
                "serialization_id": item.get("serialization_id"),
                "model_name": item.get("model_name"),
                "prompt_version": item.get("prompt_version"),
            }

        for score in scores:
            item = payload(str(score["dimension_id"]))
            score["factor_name"] = item["factor_name"]
            explanation = score.setdefault("explanation", {})
            explanation["factor_name"] = item["factor_name"]
            explanation["nomenclature"] = item

        by_factor = {item["factor_id"]: item for item in scores}
        for assessment in assessments or []:
            evaluation = assessment.get("semantic_evaluation")
            matching = by_factor.get(assessment.get("factor_id"))
            if not isinstance(evaluation, dict) or not matching:
                continue
            item = payload(str(matching["dimension_id"]))
            evaluation["nomenclature"] = {
                "factor_name": item["factor_name"],
                "description": item["description"],
            }

    def _refresh_summary_top_factor(self, run: dict[str, Any], scores: list[dict[str, Any]]) -> None:
        summary = run.get("summary")
        if not isinstance(summary, dict):
            return
        top = next((item for item in scores if item.get("final_priority_score") is not None), None)
        if top:
            summary["top_factor_id"] = top["factor_id"]
            summary["top_factor_name"] = top.get("factor_name")
            summary["top_priority_score"] = top.get("final_priority_score")

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_factor_prioritisation_run(run_id)
        if not run:
            return None
        scores = self.repo.get_factor_prioritisation_scores(run_id)
        assessments = self.repo.get_factor_semantic_assessments(run_id)
        self._apply_current_nomenclature(run["famd_run_id"], scores, assessments)
        self._refresh_summary_top_factor(run, scores)
        return {**run, "scores": scores, "semantic_assessments": assessments}

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repo.list_factor_prioritisation_runs(limit=limit)

    def get_factor(self, run_id: str, factor_id: str) -> dict[str, Any]:
        score = self.repo.get_factor_prioritisation_score(run_id, factor_id)
        if not score:
            raise KeyError(f"Factor {factor_id} was not found in prioritisation run {run_id}.")
        run = self.repo.get_factor_prioritisation_run(run_id)
        assessment = self.repo.get_factor_semantic_assessment(run_id, factor_id)
        if run:
            self._apply_current_nomenclature(
                run["famd_run_id"],
                [score],
                [assessment] if assessment else [],
            )
        return {
            "score": score,
            "evidence": self.repo.get_factor_prioritisation_evidence(run_id, factor_id),
            "semantic_assessment": assessment,
        }

    def get_scores(self, run_id: str) -> list[dict[str, Any]]:
        run = self.repo.get_factor_prioritisation_run(run_id)
        if not run:
            raise KeyError(f"Prioritisation run {run_id} was not found.")
        scores = self.repo.get_factor_prioritisation_scores(run_id)
        self._apply_current_nomenclature(run["famd_run_id"], scores)
        return scores

    def review_semantic(
        self,
        run_id: str,
        factor_id: str,
        *,
        reviewer: str,
        decision: str,
        note: str = "",
    ) -> dict[str, Any]:
        status = {
            "approve": "APPROVED",
            "reject": "REJECTED",
            "request_revision": "REVISION_REQUESTED",
        }[decision]
        self.repo.update_factor_semantic_review(
            run_id,
            factor_id,
            reviewer_id=reviewer,
            review_status=status,
            review_note=note,
        )
        assessment = self.repo.get_factor_semantic_assessment(run_id, factor_id)
        if not assessment:
            raise KeyError(f"Semantic assessment for factor {factor_id} was not found.")
        return assessment

    def latest_run(self) -> dict[str, Any] | None:
        run = self.repo.latest_factor_prioritisation_run()
        if not run:
            return None
        return self.get_run(run["prioritisation_run_id"])
