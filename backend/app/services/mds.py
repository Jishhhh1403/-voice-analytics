"""Service layer for the MDS theme map."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..config import Settings
from ..db import loads
from ..intelligence.mds import ThemeInput, compute_theme_map
from ..repository import Repository

_COVERAGE_KEYS = ("full", "partial", "related", "needs_review", "uncovered", "out_of_scope")


class MdsService:
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo

    # ------------------------------------------------------------- persistence
    def recompute(self, run_id: str | None = None, embedding_model: str | None = None) -> dict[str, Any]:
        resolved = self.repo.resolve_run_id(run_id)
        if not resolved:
            return self._empty(None, "NO_RUN")
        themes, truncated = self._load_themes(resolved)
        result = compute_theme_map(self.settings, themes, embedding_model)
        if truncated:
            result.notes.append(
                f"Only the {self.settings.mds_max_themes} highest-evidence themes were mapped."
            )
        self.repo.replace_mds_result(resolved, result)
        return self.payload(resolved)

    def payload(self, run_id: str | None = None) -> dict[str, Any]:
        resolved = self.repo.resolve_run_id(run_id)
        if not resolved:
            return self._empty(None, "NO_RUN")
        if not self.settings.enable_mds:
            return self._empty(resolved, "DISABLED")

        mds = self.repo.latest_mds(resolved)
        if mds is None:
            return self.recompute(resolved)
        if mds["status"] != "OK":
            return self._empty(resolved, mds["status"], mds)

        points = {row["problem_id"]: row for row in self.repo.mds_points(mds["mds_id"])}
        problems = {
            row["problem_id"]: row
            for row in self.repo.db.query(
                "SELECT problem_id, title, problem_statement, canonical_description, journey_node_id, "
                "lifecycle_status, human_review_status, validation_status, evidence_count, distinct_customers, "
                "negative_count FROM customer_problems WHERE run_id=?",
                (resolved,),
            )
        }
        journeys = self._journey_names(resolved)
        measurements = self._measurements(resolved)
        priorities = {
            row["problem_id"]: row
            for row in self.repo.db.query(
                "SELECT * FROM problem_priority_snapshots WHERE run_id=?", (resolved,)
            )
        }
        coverage = self.repo.latest_coverage_for_feedback_run(resolved)
        neighbors: dict[str, list[dict[str, Any]]] = {}
        for row in self.repo.mds_neighbors(mds["mds_id"]):
            neighbor_problem = problems.get(row["neighbor_problem_id"], {})
            neighbors.setdefault(row["problem_id"], []).append(
                {
                    "problem_id": row["neighbor_problem_id"],
                    "title": neighbor_problem.get("title"),
                    "rank": row["rank"],
                    "cosine_similarity": row["cosine_similarity"],
                    "cosine_distance": row["cosine_distance"],
                }
            )

        themes: list[dict[str, Any]] = []
        for problem_id, point in points.items():
            problem = problems.get(problem_id, {})
            metrics = measurements.get(problem_id, {})
            priority = priorities.get(problem_id, {})
            theme_coverage = coverage.get(problem_id, {})
            theme = {
                "problem_id": problem_id,
                "title": problem.get("title"),
                "problem_statement": problem.get("problem_statement"),
                "canonical_description": problem.get("canonical_description"),
                "journey_node_id": problem.get("journey_node_id"),
                "journey_name": journeys.get(problem.get("journey_node_id")),
                "lifecycle_status": problem.get("lifecycle_status"),
                "human_review_status": problem.get("human_review_status"),
                "validation_status": problem.get("validation_status"),
                "x": point["x"],
                "y": point["y"],
                "display_x": point["display_x"],
                "display_y": point["display_y"],
                "vector_source": point.get("vector_source"),
                "evidence_volume": self._metric(metrics, "evidence_volume")[0],
                "evidence_volume_status": self._metric(metrics, "evidence_volume")[1],
                "distinct_customers": self._metric(metrics, "distinct_customers")[0],
                "distinct_customers_status": self._metric(metrics, "distinct_customers")[1],
                "negative_share": self._metric(metrics, "negative_share")[0],
                "negative_share_status": self._metric(metrics, "negative_share")[1],
                "repeat_complaint_count": self._metric(metrics, "repeat_complaint_count")[0],
                "source_diversity": self._metric(metrics, "source_diversity")[0],
                "volume_growth_pct": self._metric(metrics, "volume_growth_pct")[0],
                "volume_growth_pct_status": self._metric(metrics, "volume_growth_pct")[1],
                "volume_growth_abs": self._metric(metrics, "volume_growth_abs")[0],
                "priority_score": priority.get("priority_score"),
                "priority_rank": priority.get("rank"),
                "escalation_status": priority.get("escalation_status"),
                "customer_impact_score": priority.get("customer_impact_score"),
                "business_risk_score": priority.get("business_risk_score"),
                "operational_impact_score": priority.get("operational_impact_score"),
                "trend_score": priority.get("trend_score"),
                "strategic_score": priority.get("strategic_score"),
                "coverage_status": theme_coverage.get("coverage_status", "unknown"),
                "coverage_relationship": theme_coverage.get("coverage_relationship"),
                "coverage_report_id": theme_coverage.get("coverage_report_id"),
                "neighbors": neighbors.get(problem_id, []),
            }
            themes.append(theme)

        themes.sort(
            key=lambda item: (
                item["priority_rank"] is None,
                item["priority_rank"] or 0,
                -(item["evidence_volume"] or 0),
                item["title"] or "",
            )
        )
        coverage_summary = {
            key: sum(1 for theme in themes if theme["coverage_status"] == key) for key in _COVERAGE_KEYS
        }
        coverage_summary["unknown"] = sum(1 for theme in themes if theme["coverage_status"] == "unknown")

        return {
            "run_id": resolved,
            "status": "OK",
            "methodology_version": mds["methodology_version"],
            "embedding_model": mds.get("embedding_model"),
            "distance_metric": mds.get("distance_metric", "cosine"),
            "n_themes": mds.get("n_themes", len(themes)),
            "stress": mds.get("stress"),
            "normalized_stress": mds.get("normalized_stress"),
            "stress_status": mds.get("stress_status"),
            "params": mds.get("params", {}),
            "axes": {
                "x": "MDS dimension 1 (semantic, arbitrary orientation)",
                "y": "MDS dimension 2 (semantic, arbitrary orientation)",
            },
            "severity_basis": "negative_share",
            "color_mode_default": "negative_share",
            "coverage_summary": coverage_summary,
            "themes": themes,
            "notes": [
                "MDS positions show semantic similarity only; they are not severity, priority or causality.",
                "Bubble size represents evidence volume and colour represents negative evidence share by default.",
                "Axes may rotate or reflect between runs; compare similarity, not absolute coordinates.",
            ],
        }

    # ---------------------------------------------------------------- loading
    def _load_themes(self, run_id: str) -> tuple[list[ThemeInput], bool]:
        limit = max(1, self.settings.mds_max_themes)
        rows = self.repo.db.query(
            "SELECT problem_id, title, problem_statement, canonical_description, journey_node_id, "
            "symptoms_json, evidence_count FROM customer_problems WHERE run_id=? "
            "ORDER BY evidence_count DESC, problem_id LIMIT ?",
            (run_id, limit + 1),
        )
        truncated = len(rows) > limit
        rows = rows[:limit]
        journeys = self._journey_names(run_id)

        member_vectors: dict[str, list[np.ndarray]] = {}
        vector_rows = self.repo.db.query(
            "SELECT pe.problem_id, ei.embedding_json FROM problem_evidence pe "
            "JOIN extracted_insights ei ON ei.insight_id=pe.insight_id "
            "WHERE pe.run_id=? AND ei.embedding_json IS NOT NULL",
            (run_id,),
        )
        for row in vector_rows:
            values = loads(row.get("embedding_json"), None)
            if not isinstance(values, list) or not values:
                continue
            vector = np.asarray(values, dtype=np.float32)
            if vector.ndim == 1 and vector.size:
                member_vectors.setdefault(row["problem_id"], []).append(vector)

        themes = [
            ThemeInput(
                problem_id=row["problem_id"],
                title=row.get("title") or row["problem_id"],
                problem_statement=row.get("problem_statement") or "",
                canonical_description=row.get("canonical_description"),
                symptoms=loads(row.get("symptoms_json"), []),
                journey_node_id=row.get("journey_node_id"),
                journey_name=journeys.get(row.get("journey_node_id")),
                member_vectors=member_vectors.get(row["problem_id"], []),
            )
            for row in rows
        ]
        return themes, truncated

    def _journey_names(self, run_id: str) -> dict[str, str]:
        run = self.repo.db.query_one("SELECT taxonomy_version FROM pipeline_runs WHERE run_id=?", (run_id,))
        version = run.get("taxonomy_version") if run else None
        if not version:
            return {}
        return {
            row["node_id"]: row["display_name"]
            for row in self.repo.db.query(
                "SELECT node_id, display_name FROM taxonomy_nodes WHERE version=?", (version,)
            )
        }

    def _measurements(self, run_id: str) -> dict[str, dict[str, dict[str, Any]]]:
        rows = self.repo.db.query(
            "SELECT problem_id, metric_name, metric_value, status FROM problem_measurement_snapshots "
            "WHERE run_id=?",
            (run_id,),
        )
        measurements: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            measurements.setdefault(row["problem_id"], {})[row["metric_name"]] = row
        return measurements

    @staticmethod
    def _metric(metrics: dict[str, dict[str, Any]], name: str) -> tuple[float | None, str]:
        row = metrics.get(name)
        if not row:
            return None, "NO_DATA"
        return row.get("metric_value"), row.get("status") or "NO_DATA"

    def _empty(self, run_id: str | None, status: str, mds: dict[str, Any] | None = None) -> dict[str, Any]:
        mds = mds or {}
        return {
            "run_id": run_id,
            "status": status,
            "methodology_version": mds.get("methodology_version", self.settings.mds_methodology_version),
            "embedding_model": mds.get("embedding_model"),
            "distance_metric": mds.get("distance_metric", "cosine"),
            "n_themes": mds.get("n_themes", 0),
            "stress": mds.get("stress"),
            "normalized_stress": mds.get("normalized_stress"),
            "stress_status": mds.get("stress_status"),
            "params": mds.get("params", {}),
            "axes": {},
            "severity_basis": "negative_share",
            "color_mode_default": "negative_share",
            "coverage_summary": {key: 0 for key in (*_COVERAGE_KEYS, "unknown")},
            "themes": [],
            "notes": ["No theme map is available for this run."],
        }
