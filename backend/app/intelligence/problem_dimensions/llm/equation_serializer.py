"""Versioned factor-equation serialization for LLM interpretation."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from ....repository import Repository

EQUATION_SERIALIZATION_VERSION = "factor-equation-serialization-1.0.0"
COEFFICIENT_INTERPRETATION = (
    "Signed FAMD row coordinates describe a canonical problem's position in latent-dimension "
    "space. They are descriptive associations, not regression coefficients, causal effects or "
    "percentage impacts. A negative coefficient is the opposite direction along a dimension, "
    "not negative customer impact."
)
_TRANSACTION_STATE_TOKENS = (
    "pending",
    "processing",
    "failed",
    "success",
    "successful",
    "reversed",
    "refunded",
    "debited",
    "credited",
    "declined",
    "queued",
    "settled",
)


class FactorEquationSerializer:
    """Build one complete equation record per canonical problem."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def _affected_dimension_ids(self, run_id: str) -> list[str]:
        rows = self.repo.db.query(
            "SELECT DISTINCT dimension_id FROM problem_dimension_scores WHERE run_id=?",
            (run_id,),
        )
        return sorted(row["dimension_id"] for row in rows)

    def _dimension_metadata(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        diagnostics = run.get("diagnostics") or {}
        dimensions = diagnostics.get("dimensions") or []
        if dimensions:
            return sorted(
                dimensions,
                key=lambda item: (item.get("dimension_number") or 9999, item.get("dimension_id") or ""),
            )
        return [
            {
                "dimension_id": item["dimension_id"],
                "dimension_number": item.get("dimension_number"),
                "factor_id": f"F{item.get('dimension_number')}",
            }
            for item in sorted(
                run.get("definitions") or [],
                key=lambda item: (item.get("dimension_number") or 9999, item.get("dimension_id") or ""),
            )
        ]

    def _dimension_evidence(
        self, contributions: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in contributions:
            by_dimension[item["dimension_id"]].append(item)
        evidence: dict[str, dict[str, Any]] = {}
        for dimension_id, items in by_dimension.items():
            variables = [item for item in items if not item.get("category_level")]
            categories = [item for item in items if item.get("category_level")]
            variables.sort(key=lambda item: abs(float(item.get("contribution") or 0.0)), reverse=True)
            categories.sort(key=lambda item: abs(float(item.get("contribution") or 0.0)), reverse=True)
            evidence[dimension_id] = {
                "top_variables": [
                    {
                        "variable_name": item.get("variable_name"),
                        "contribution": item.get("contribution"),
                        "coordinate": item.get("coordinate"),
                        "direction_summary": item.get("direction_summary"),
                        "rank": item.get("rank"),
                    }
                    for item in variables[:10]
                ],
                "top_categories": [
                    {
                        "variable_name": item.get("variable_name"),
                        "category_level": item.get("category_level"),
                        "contribution": item.get("contribution"),
                        "rank": item.get("rank"),
                    }
                    for item in categories[:10]
                ],
            }
        return evidence

    def _transaction_state(self, problem: dict[str, Any]) -> str | None:
        symptoms = problem.get("symptoms") or []
        labels: list[str] = []
        for symptom in symptoms:
            if isinstance(symptom, dict):
                labels.extend(str(value) for value in symptom.values() if value)
            else:
                labels.append(str(symptom))
        text = " ".join(
            [
                str(problem.get("title") or ""),
                str(problem.get("problem_statement") or ""),
                str(problem.get("canonical_description") or ""),
                " ".join(labels),
            ]
        ).casefold()
        matches = [token for token in _TRANSACTION_STATE_TOKENS if token in text]
        return ", ".join(matches) if matches else None

    def serialize(self, run_id: str) -> dict[str, Any]:
        run = self.repo.get_dimension_run(run_id)
        if not run:
            raise KeyError(run_id)
        feedback_run_id = run.get("feedback_run_id")
        dimensions = self._dimension_metadata(run)
        dimension_ids = [item["dimension_id"] for item in dimensions] or self._affected_dimension_ids(run_id)
        factor_by_dimension = {
            item["dimension_id"]: item.get("factor_id") or f"F{index + 1}"
            for index, item in enumerate(dimensions)
        }
        for index, dimension_id in enumerate(dimension_ids):
            factor_by_dimension.setdefault(dimension_id, f"F{index + 1}")

        scores = self.repo.get_all_problem_scores(run_id)
        by_problem: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for score in scores:
            by_problem[score["canonical_problem_id"]].append(score)
        equations = {
            row["canonical_problem_id"]: row
            for row in self.repo.db.query(
                "SELECT * FROM problem_dimension_equations WHERE run_id=?",
                (run_id,),
            )
        }
        problems = {item["problem_id"]: item for item in self.repo.get_run_problems(feedback_run_id)}
        mappings = self.repo.get_problem_journey_mappings(sorted(problems))
        contributions = self.repo.get_dimension_contributions(run_id)
        dimension_evidence = self._dimension_evidence(contributions)
        diagnostics = run.get("diagnostics") or {}
        preprocessing = diagnostics.get("preprocessing") or {}
        missingness = {
            "missing_counts": preprocessing.get("missing_counts") or {},
            "imputed_counts": preprocessing.get("imputed_counts") or {},
            "dropped_constant_features": preprocessing.get("dropped_constant_features") or [],
            "feature_quality": run.get("feature_quality") or [],
        }

        records: list[dict[str, Any]] = []
        dimension_order = {dimension_id: index for index, dimension_id in enumerate(dimension_ids)}
        for problem_id in sorted(by_problem):
            problem = problems.get(problem_id, {})
            problem_scores = sorted(
                by_problem[problem_id],
                key=lambda item: (
                    dimension_order.get(item["dimension_id"], 9999),
                    item["dimension_id"],
                ),
            )
            equation = equations.get(problem_id) or {}
            coefficient_representation = equation.get("coefficient_representation_json")
            if isinstance(coefficient_representation, str):
                try:
                    coefficient_representation = json.loads(coefficient_representation)
                except ValueError:
                    coefficient_representation = []
            if not coefficient_representation:
                coefficient_representation = [
                    {
                        "dimension_id": item["dimension_id"],
                        "factor_id": factor_by_dimension.get(item["dimension_id"]),
                        "coefficient": item.get("coordinate"),
                        "relative_squared_coordinate_share_pct": item.get(
                            "relative_squared_coordinate_share_pct"
                        ),
                        "coordinate_rank": item.get("coordinate_rank"),
                    }
                    for item in problem_scores
                ]
            equation_text = equation.get("equation_text")
            if not equation_text:
                parts = []
                for coefficient in coefficient_representation:
                    value = float(coefficient.get("coefficient") or 0.0)
                    sign = "+" if value >= 0 else "-"
                    parts.append(f"{sign} {abs(value):.6f}*{coefficient.get('factor_id')}")
                equation_text = f"{problem_id} = " + " ".join(parts)
            mapping = mappings.get(problem_id, {})
            journey = {
                "node_id": problem.get("journey_node_id"),
                "module_id": mapping.get("module_id"),
                "feature_id": mapping.get("feature_id"),
                "journey_stage_id": mapping.get("journey_stage_id"),
                "mapping_confidence": mapping.get("mapping_confidence"),
            }
            records.append(
                {
                    "canonical_problem_id": problem_id,
                    "title": problem.get("title") or problem_id,
                    "problem_statement": problem.get("problem_statement"),
                    "canonical_description": problem.get("canonical_description"),
                    "journey": journey,
                    "aspect": problem.get("aspect"),
                    "customer_intent": problem.get("customer_intent"),
                    "symptom_category": problem.get("symptom_category"),
                    "symptoms": problem.get("symptoms") or [],
                    "transaction_state": self._transaction_state(problem),
                    "equation_text": equation_text,
                    "coefficients": coefficient_representation,
                    "dimension_evidence": dimension_evidence,
                    "missingness": missingness,
                    "data_quality_status": (
                        "PARTIAL" if missingness["missing_counts"] else "OK"
                    ),
                }
            )
        return {
            "schema_version": EQUATION_SERIALIZATION_VERSION,
            "analysis_run_id": run_id,
            "feedback_run_id": feedback_run_id,
            "model_version": diagnostics.get("method_library_version")
            or run.get("method_library_version")
            or run.get("method_version"),
            "retained_dimension_ids": dimension_ids,
            "factor_by_dimension": factor_by_dimension,
            "coefficient_interpretation": COEFFICIENT_INTERPRETATION,
            "problems": records,
        }
