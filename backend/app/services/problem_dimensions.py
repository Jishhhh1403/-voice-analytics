"""Orchestration for exploratory problem-dimension analysis runs."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from ..intelligence.problem_dimensions.coefficients import build_equations, calculate_relative_shares
from ..intelligence.problem_dimensions.data_quality import has_critical_failure, run_quality_checks
from ..intelligence.problem_dimensions.diagnostics import build_memberships, build_trends
from ..intelligence.problem_dimensions.efa_runner import run_efa
from ..intelligence.problem_dimensions.famd_runner import bootstrap_stability, run_famd
from ..intelligence.problem_dimensions.feature_builder import FEATURE_SPECS, build_feature_rows, resolve_feature_specs
from ..intelligence.problem_dimensions.interpretation import initial_definitions
from ..intelligence.problem_dimensions.preprocessing import prepare_frame
from ..intelligence.problem_dimensions.publisher import validate_publishable
from ..repository import Repository, now_iso

logger = logging.getLogger("bci.problem_dimensions")


class ProblemDimensionService:
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo
        self._threads: dict[str, threading.Thread] = {}

    def _resolve_feedback_run(self, feedback_run_id: str | None) -> dict[str, Any]:
        if feedback_run_id:
            run = self.repo.get_run(feedback_run_id)
            if not run:
                raise ValueError(f"Feedback run {feedback_run_id} was not found.")
        else:
            run = self.repo.latest_completed_feedback_run()
            if not run:
                raise ValueError("No completed feedback run is available for dimension analysis.")
        if run.get("run_type") != "feedback" or run.get("status") != "completed":
            raise ValueError(f"Feedback run {run['run_id']} is not a completed feedback run.")
        return run

    def start(
        self,
        feedback_run_id: str | None = None,
        max_components: int | None = None,
        force_rerun: bool = False,
        run_in_thread: bool = True,
    ) -> str:
        if not self.settings.enable_problem_dimensions:
            raise ValueError("Problem dimension analysis is disabled.")
        feedback_run = self._resolve_feedback_run(feedback_run_id)
        feedback_run_id = feedback_run["run_id"]
        method = self.settings.problem_dimension_method
        schema_version = self.settings.problem_dimension_feature_schema_version
        if not force_rerun:
            existing = self.repo.find_reusable_dimension_run(feedback_run_id, schema_version, method)
            if existing:
                return existing["run_id"]

        requested = int(max_components or self.settings.problem_dimension_max_components)
        requested = max(1, min(requested, self.settings.problem_dimension_max_components))
        run_id = f"DIM-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.repo.create_dimension_run(
            {
                "run_id": run_id,
                "method": method,
                "method_version": self.settings.problem_dimension_methodology_version,
                "method_library_version": None,
                "input_snapshot_id": None,
                "feedback_run_id": feedback_run_id,
                "feature_schema_version": schema_version,
                "parameters_json": None,
                "selected_features_json": None,
                "excluded_features_json": None,
                "configuration_json": None,
                "status": "QUEUED",
                "stage": "QUEUED",
                "diagnostics_json": None,
                "feature_quality_json": None,
                "feature_dictionary_json": None,
                "code_version": self.settings.code_version,
                "created_at": now_iso(),
                "started_at": None,
                "completed_at": None,
                "error": None,
            }
        )
        self.repo.update_dimension_run(
            run_id,
            parameters={
                "requested_components": requested,
                "max_components": self.settings.problem_dimension_max_components,
                "publish_components": self.settings.problem_dimension_publish_components,
                "random_state": self.settings.problem_dimension_random_state,
                "measurement_window_days": self.settings.measurement_window_days,
                "method": method,
                "feature_schema_version": schema_version,
                "review_required": self.settings.problem_dimension_require_review,
            },
        )
        if run_in_thread:
            thread = threading.Thread(target=self.execute, args=(run_id,), daemon=True, name=f"dimensions-{run_id}")
            self._threads[run_id] = thread
            thread.start()
        else:
            self.execute(run_id)
        return run_id

    def _fail(self, run_id: str, stage: str, error: str, **extra: Any) -> None:
        self.repo.update_dimension_run(
            run_id,
            status="FAILED",
            stage=stage,
            error=error,
            completed_at=now_iso(),
            **extra,
        )
        logger.warning("dimension run failed", extra={"run_id": run_id, "stage": stage, "error": error})

    def execute(self, run_id: str) -> None:
        run = self.repo.get_dimension_run(run_id)
        if not run:
            return
        feedback_run_id = run["feedback_run_id"]
        self.repo.update_dimension_run(
            run_id, status="BUILDING_FEATURES", started_at=now_iso(), stage="BUILDING_FEATURES"
        )
        try:
            selected_specs = resolve_feature_specs(
                self.settings.problem_dimension_active_features,
                self.settings.problem_dimension_supplementary_features,
                self.settings.problem_dimension_excluded_features,
            )
            build = build_feature_rows(
                self.repo.db,
                feedback_run_id,
                self.settings.problem_dimension_feature_schema_version,
                window_days=self.settings.measurement_window_days,
                feature_specs=selected_specs,
            )
            snapshot_id = f"SNAP-{uuid.uuid4().hex[:16]}"
            self.repo.save_feature_snapshot(snapshot_id, build)
            selected_names = {spec.name for spec in build.specs}
            configured_excluded = sorted(
                {
                    item.strip()
                    for item in (self.settings.problem_dimension_excluded_features or "").split(",")
                    if item.strip()
                }
                | {spec.name for spec in FEATURE_SPECS if spec.name not in selected_names}
            )
            self.repo.update_dimension_run(
                run_id,
                status="VALIDATING_DATA",
                input_snapshot_id=snapshot_id,
                stage="VALIDATING_DATA",
                feature_dictionary=build.feature_dictionary,
                selected_features=[{"name": spec.name, "kind": spec.kind, "role": spec.role} for spec in build.specs],
                excluded_features=configured_excluded,
                configuration={
                    "active_features": self.settings.problem_dimension_active_features,
                    "supplementary_features": self.settings.problem_dimension_supplementary_features,
                    "excluded_features": self.settings.problem_dimension_excluded_features,
                    "include_missing_indicators": self.settings.problem_dimension_include_missing_indicators,
                    "coordinate_type": "FAMD row coordinate (signed)",
                    "coefficient_interpretation": "association, not a causal effect",
                },
            )

            checks = run_quality_checks(
                build.rows,
                build.specs,
                min_problems=self.settings.problem_dimension_min_problems,
                min_category_count=self.settings.problem_dimension_min_category_count,
            )
            if has_critical_failure(checks):
                failed = [check for check in checks if check["severity"] == "CRITICAL" and check["status"] == "FAIL"]
                self._fail(
                    run_id,
                    "VALIDATING_DATA",
                    "Feature quality gates failed: " + "; ".join(check["message"] for check in failed),
                    feature_quality=checks,
                )
                return

            prepared = prepare_frame(
                build.rows,
                build.specs,
                include_missing_indicators=self.settings.problem_dimension_include_missing_indicators,
            )
            all_excluded = sorted(
                set(configured_excluded) | set(prepared.metadata.get("dropped_constant_features", []))
            )
            self.repo.update_dimension_run(
                run_id,
                status="FITTING_FAMD",
                stage="FITTING_FAMD",
                excluded_features=all_excluded,
            )
            result = run_famd(
                prepared,
                build.specs,
                max_components=int(run.get("parameters", {}).get("requested_components", 10)),
                random_state=self.settings.problem_dimension_random_state,
                max_contributions=self.settings.problem_dimension_max_contributions,
            )
            if result.status != "OK":
                self._fail(run_id, "FITTING_FAMD", result.error or result.status, feature_quality=checks)
                return

            stability = bootstrap_stability(
                prepared,
                build.specs,
                result,
                iterations=self.settings.problem_dimension_bootstrap_iterations,
                random_state=self.settings.problem_dimension_random_state,
            )
            efa = None
            if self.settings.enable_problem_dimension_efa:
                efa = run_efa(
                    prepared,
                    build.specs,
                    max_factors=min(
                        self.settings.problem_dimension_publish_components,
                        max(1, len(prepared.metadata.get("numeric_features", [])) - 1),
                    ),
                    random_state=self.settings.problem_dimension_random_state,
                )
            self.repo.update_dimension_run(
                run_id,
                status="VALIDATING_RESULTS",
                method_library_version=f"{result.library}-{result.library_version or 'unknown'}",
                stage="VALIDATING_RESULTS",
            )
            retained = max(
                1,
                min(
                    self.settings.problem_dimension_publish_components,
                    len(result.dimensions),
                ),
            )
            retained_dimensions = result.dimensions[:retained]
            retained_ids = {item["dimension_id"] for item in retained_dimensions}
            trimmed = replace(
                result,
                dimensions=retained_dimensions,
                problem_scores=[
                    score for score in result.problem_scores if score["dimension_id"] in retained_ids
                ],
            )
            trimmed = replace(
                trimmed,
                problem_scores=calculate_relative_shares(trimmed.problem_scores, retained_dimensions),
            )
            equations = build_equations(trimmed.problem_scores, retained_dimensions)
            model_version = f"{trimmed.library}-{trimmed.library_version or 'unknown'}"
            definitions = initial_definitions(trimmed, model_version=model_version)
            memberships = build_memberships(trimmed)
            trends = build_trends(
                memberships,
                build.rows,
                retained_dimensions,
                f"{self.settings.measurement_window_days}d",
            )
            contributions: list[dict[str, Any]] = []
            for dimension in retained_dimensions:
                for item in dimension["variable_contributions"]:
                    contributions.append({"dimension_id": dimension["dimension_id"], **item})
                for item in dimension["category_contributions"]:
                    contributions.append({"dimension_id": dimension["dimension_id"], **item})

            auto_publish = not self.settings.problem_dimension_require_review
            if auto_publish:
                for definition in definitions:
                    definition["review_status"] = "APPROVED"

            self.repo.save_dimension_results(
                run_id,
                definitions=definitions,
                contributions=contributions,
                scores=trimmed.problem_scores,
                memberships=memberships,
                trends=trends,
                equations=equations,
            )
            diagnostics = {
                **trimmed.diagnostics,
                "feedback_run_id": feedback_run_id,
                "feature_snapshot_id": snapshot_id,
                "as_of_date": build.as_of_date,
                "window_start": build.window_start,
                "window_end": build.window_end,
                "feature_build_notes": build.notes,
                "preprocessing": prepared.metadata,
                "preprocessing_warnings": prepared.warnings,
                "quality_summary": {
                    "checks": len(checks),
                    "pass": sum(1 for check in checks if check["status"] == "PASS"),
                    "warn": sum(1 for check in checks if check["status"] == "WARN"),
                    "fail": sum(1 for check in checks if check["status"] == "FAIL"),
                },
                "retained_components": retained,
                "selected_features": [
                    {"name": spec.name, "kind": spec.kind, "role": spec.role} for spec in build.specs
                ],
                "excluded_features": all_excluded,
                "coefficient_type": "FAMD row coordinate (signed)",
                "equations": len(equations),
                "dimensions": [
                    {
                        "dimension_id": item["dimension_id"],
                        "dimension_number": item.get("dimension_number"),
                        "factor_id": item.get("factor_id"),
                        "eigenvalue": item["eigenvalue"],
                        "explained_variance": item["explained_variance"],
                        "cumulative_variance": item["cumulative_variance"],
                    }
                    for item in retained_dimensions
                ],
                "membership_rows": len(memberships),
                "trend_rows": len(trends),
                "stability": stability,
                "efa": efa.to_dict() if efa else {"status": "DISABLED"},
                "interpretation_warning": (
                    "Dimensions are exploratory statistical patterns. Names and descriptions require analyst review "
                    "and must not be presented as proven root causes."
                ),
            }
            self.repo.update_dimension_run(
                run_id,
                status="PENDING_REVIEW",
                stage="PENDING_REVIEW",
                completed_at=now_iso(),
                feature_quality=checks,
                diagnostics=diagnostics,
                excluded_features=all_excluded,
                error=None,
            )
            if auto_publish:
                self.repo.publish_dimension_run(
                    run_id,
                    "system:auto",
                    "Auto-published because PROBLEM_DIMENSION_REQUIRE_REVIEW is disabled.",
                )
        except Exception as exc:
            logger.exception("dimension analysis failed", extra={"run_id": run_id})
            self._fail(run_id, "FAILED", str(exc))

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repo.list_dimension_runs(limit)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.repo.get_dimension_run(run_id)
        if not run:
            raise KeyError(run_id)
        return run

    def latest_published(self) -> dict[str, Any] | None:
        return self.repo.latest_dimension_publication()

    def latest_published_run(self) -> dict[str, Any] | None:
        latest = self.latest_published()
        return latest["run"] if latest else None

    def review(
        self,
        run_id: str,
        dimension_id: str,
        reviewer: str,
        decision: str,
        name: str | None = None,
        description: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] not in {"PENDING_REVIEW", "APPROVED"}:
            raise ValueError(f"Run {run_id} is not open for review (status {run['status']}).")
        definition = self.repo.review_dimension(
            run_id, dimension_id, reviewer, decision, name, description, note
        )
        if not definition:
            raise KeyError(dimension_id)
        definitions = self.repo.get_dimension_definitions(run_id)
        if decision == "reject":
            self.repo.update_dimension_run(run_id, status="REJECTED", stage="REJECTED")
        elif definitions and all(item["review_status"] == "APPROVED" for item in definitions):
            self.repo.update_dimension_run(run_id, status="APPROVED", stage="APPROVED")
        else:
            self.repo.update_dimension_run(run_id, status="PENDING_REVIEW", stage="PENDING_REVIEW")
        return self.get_run(run_id)

    def publish(self, run_id: str, published_by: str, note: str = "") -> dict[str, Any]:
        run = self.get_run(run_id)
        definitions = self.repo.get_dimension_definitions(run_id)
        validate_publishable(run, definitions)
        publication_id = self.repo.publish_dimension_run(run_id, published_by, note)
        published = self.get_run(run_id)
        published["publication_id"] = publication_id
        return published

    def dimension_payload(self, dimension_id: str, run_id: str | None = None) -> dict[str, Any]:
        run = self.get_run(run_id) if run_id else self.latest_published_run()
        if not run:
            raise KeyError("no published dimension run")
        definition = next(
            (item for item in run.get("definitions", []) if item["dimension_id"] == dimension_id),
            None,
        )
        if not definition:
            raise KeyError(dimension_id)
        contributions = self.repo.get_dimension_contributions(run["run_id"], dimension_id)
        scores = self.repo.get_dimension_scores(run["run_id"], dimension_id)
        problems = self.repo.db.query(
            "SELECT p.problem_id, p.title, p.aspect, p.symptom_category, p.journey_node_id FROM customer_problems p "
            "WHERE p.problem_id IN (SELECT canonical_problem_id FROM problem_dimension_scores "
            "WHERE run_id=? AND dimension_id=? ORDER BY ABS(coordinate) DESC LIMIT 25)",
            (run["run_id"], dimension_id),
        )
        score_map = {item["canonical_problem_id"]: item for item in scores}
        for problem in problems:
            score = score_map.get(problem["problem_id"], {})
            problem["coordinate"] = score.get("coordinate")
        problems.sort(key=lambda item: abs(item.get("coordinate") or 0), reverse=True)
        return {
            "run_id": run["run_id"],
            "run_status": run["status"],
            "definition": definition,
            "top_problems": problems,
            "contributions": contributions,
            "trends": self.repo.get_dimension_trends(run["run_id"], dimension_id),
        }

    def problem_payload(self, problem_id: str, run_id: str | None = None) -> dict[str, Any]:
        run = self.get_run(run_id) if run_id else self.latest_published_run()
        if not run:
            raise KeyError("no published dimension run")
        problem = self.repo.db.query_one(
            "SELECT problem_id, title, aspect, symptom_category, journey_node_id FROM customer_problems WHERE problem_id=?",
            (problem_id,),
        )
        if not problem:
            raise KeyError(problem_id)
        scores = self.repo.get_problem_dimension_scores(run["run_id"], problem_id)
        ordered = sorted(scores, key=lambda item: abs(float(item["coordinate"] or 0)), reverse=True)
        profile = self.repo.get_problem_dimension_profile(run["run_id"], problem_id) or {}
        return {
            "run_id": run["run_id"],
            "run_status": run["status"],
            "problem": problem,
            "dominant_dimension": ordered[0] if ordered else None,
            "equation": profile.get("equation"),
            "scores": scores,
            "ambiguous": any(bool(item.get("is_ambiguous")) for item in scores),
        }

    def coefficient_matrix(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        dimensions = [
            {
                "dimension_id": item["dimension_id"],
                "dimension_number": item.get("dimension_number"),
                "factor_id": f"F{item.get('dimension_number') or index + 1}",
                "factor_name": item.get("analyst_name"),
                "proposed_label": item.get("proposed_label"),
                "review_status": item.get("review_status"),
            }
            for index, item in enumerate(run.get("definitions", []))
        ]
        coefficients = self.repo.get_dimension_coefficient_matrix(run_id)
        return {
            "run_id": run["run_id"],
            "run_status": run["status"],
            "dimensions": dimensions,
            "coefficients": coefficients,
            "selected_features": run.get("selected_features", []),
            "excluded_features": run.get("excluded_features", []),
            "coefficient_type": "FAMD row coordinate (signed)",
            "share_definition": (
                "relative_squared_coordinate_share_pct = s_ij^2 / sum_j(s_ij^2) * 100; "
                "null when all coordinates for the problem are zero"
            ),
            "interpretation_warning": (
                "Coefficients describe association in latent-dimension space. They are not causal effects, "
                "regression betas, or approved business impact estimates."
            ),
        }

    def variables_payload(self, run_id: str, dimension_id: str | None = None) -> dict[str, Any]:
        run = self.get_run(run_id)
        return {
            "run_id": run["run_id"],
            "run_status": run["status"],
            "dimension_id": dimension_id,
            "variables": self.repo.get_dimension_variables(run_id, dimension_id),
        }

    def problem_profile(self, run_id: str, problem_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        profile = self.repo.get_problem_dimension_profile(run_id, problem_id)
        if not profile:
            raise KeyError(problem_id)
        problem = self.repo.db.query_one(
            "SELECT problem_id, title, aspect, symptom_category, journey_node_id FROM customer_problems WHERE problem_id=?",
            (problem_id,),
        )
        profile["run_status"] = run["status"]
        profile["problem"] = problem
        return profile
