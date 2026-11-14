"""Final deterministic priority score, coverage and explainability builder."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .data import FactorEvidenceInput, FactorPrioritisationDataset
from .scoring import (
    score_prevalence,
    score_representation,
    score_semantic_coherence,
    score_statistical_importance,
)


@dataclass(frozen=True)
class PrioritisationWeights:
    prevalence: float = 0.30
    statistical_importance: float = 0.25
    representation_strength: float = 0.25
    semantic_coherence: float = 0.20

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    def normalised(self) -> dict[str, float]:
        total = sum(self.as_dict().values())
        if total <= 0:
            raise ValueError("Prioritisation weights must sum to a positive value.")
        return {key: value / total for key, value in self.as_dict().items()}


@dataclass(frozen=True)
class PrioritisationRules:
    model_version: str
    weights: PrioritisationWeights
    representation_multiplier: float
    allow_provisional: bool
    minimum_problem_count: int
    membership_rule_version: str
    membership_min_score: float
    representation_rule_version: str
    semantic_rule_version: str
    metadata: dict[str, Any] = field(default_factory=dict)


COMPONENT_ORDER = (
    "prevalence",
    "statistical_importance",
    "representation_strength",
    "semantic_coherence",
)


def _round(value: float | None) -> float | None:
    return round(float(value), 4) if value is not None else None


class FactorPriorityCalculator:
    def __init__(self, rules: PrioritisationRules) -> None:
        self.rules = rules
        self.weights = rules.weights.normalised()

    def calculate(self, dataset: FactorPrioritisationDataset) -> dict[str, Any]:
        scores: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        assessments: list[dict[str, Any]] = []

        for factor in dataset.factors:
            components = self._components(factor)
            result, factor_evidence, assessment = self._factor_result(factor, components, dataset)
            scores.append(result)
            evidence.extend(factor_evidence)
            assessments.append(assessment)

        ranked = sorted(
            (item for item in scores if item["final_priority_score"] is not None),
            key=lambda item: (-item["final_priority_score"], item["factor_id"]),
        )
        for rank, item in enumerate(ranked, start=1):
            item["rank"] = rank
            item["explanation"]["rank"] = rank
            item["explanation"]["headline"] = self._headline(item, len(scores))

        summary = self._summary(dataset, scores)
        return {
            "scores": scores,
            "evidence": evidence,
            "semantic_assessments": assessments,
            "summary": summary,
        }

    def _components(self, factor: FactorEvidenceInput) -> dict[str, dict[str, Any]]:
        prevalence = score_prevalence(
            factor,
            rule_version=self.rules.membership_rule_version,
            membership_min_score=self.rules.membership_min_score,
        )
        statistical = score_statistical_importance(factor)
        representation = score_representation(
            factor,
            rule_version=self.rules.representation_rule_version,
            multiplier=self.rules.representation_multiplier,
        )
        represented_ids = representation.pop("_represented_ids", None)
        semantic, _evaluation = score_semantic_coherence(
            factor,
            rule_version=self.rules.semantic_rule_version,
            represented_ids=represented_ids,
        )
        return {
            "prevalence": prevalence,
            "statistical_importance": statistical,
            "representation_strength": representation,
            "semantic_coherence": semantic,
        }

    def _factor_result(
        self,
        factor: FactorEvidenceInput,
        components: dict[str, dict[str, Any]],
        dataset: FactorPrioritisationDataset,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        assessable = [
            name for name in COMPONENT_ORDER if components[name]["component_score"] is not None
        ]
        coverage = sum(self.weights[name] for name in assessable) * 100.0
        all_known = len(assessable) == len(COMPONENT_ORDER)
        nomenclature_status = str(factor.definition.get("review_status") or "DRAFT").upper()
        nomenclature_approved = nomenclature_status in {"APPROVED", "PUBLISHED"}

        eligible = (
            dataset.problems_analysed >= self.rules.minimum_problem_count
            and dataset.problems_analysed > 0
        )
        if not eligible:
            eligibility = "EXCLUDED"
        elif not assessable:
            eligibility = "INSUFFICIENT_EVIDENCE"
        elif all_known and nomenclature_approved:
            eligibility = "ELIGIBLE"
        else:
            eligibility = "PROVISIONAL"

        raw_score = None
        if assessable:
            raw_score = sum(
                self.weights[name] * float(components[name]["component_score"])
                for name in assessable
            ) / sum(self.weights[name] for name in assessable)

        score_status: str
        final_score = raw_score
        if eligibility == "EXCLUDED":
            score_status, final_score = "EXCLUDED", None
        elif eligibility == "INSUFFICIENT_EVIDENCE":
            score_status, final_score = "INSUFFICIENT_EVIDENCE", None
        elif eligibility == "PROVISIONAL":
            if self.rules.allow_provisional:
                score_status = "PROVISIONAL"
            else:
                score_status, final_score = "INSUFFICIENT_EVIDENCE", None
        else:
            score_status = "VALIDATED"

        factor_name = factor.factor_name
        weights = {
            name: self.weights[name]
            for name in COMPONENT_ORDER
        }
        component_payload = []
        evidence_rows: list[dict[str, Any]] = []
        for name in COMPONENT_ORDER:
            component = components[name]
            contribution = (
                self.weights[name] * float(component["component_score"])
                if component["component_score"] is not None
                else None
            )
            component_payload.append(
                {
                    "name": name,
                    "label": component["component_label"],
                    "weight": self.weights[name],
                    "score": component["component_score"],
                    "weighted_contribution": _round(contribution),
                    "assessment_status": component["assessment_status"],
                    "calculation_method": component["calculation_method"],
                    "rule_version": component["rule_version"],
                    "explanation": component["explanation"],
                    "raw_value": component["raw_value"],
                }
            )
            evidence_rows.append(
                {
                    "factor_id": factor.factor_id,
                    "component_name": name,
                    "component_label": component["component_label"],
                    "component_weight": self.weights[name],
                    "component_score": component["component_score"],
                    "weighted_contribution": _round(contribution),
                    "raw_value": component["raw_value"],
                    "normalised_value": component["component_score"],
                    "calculation_method": component["calculation_method"],
                    "rule_version": component["rule_version"],
                    "source_table": component["source_table"],
                    "assessment_status": component["assessment_status"],
                    "explanation": component["explanation"],
                    "evidence_reference": component["evidence_reference"],
                }
            )

        semantic_evaluation = components["semantic_coherence"]["raw_value"]
        explanation = {
            "factor_id": factor.factor_id,
            "dimension_id": factor.dimension_id,
            "factor_name": factor_name,
            "headline": "",
            "rank": None,
            "formula": " + ".join(
                f"{self.weights[name]:.2f} x {components[name]['component_label']}"
                for name in COMPONENT_ORDER
            ),
            "components": component_payload,
            "evidence_coverage_pct": _round(coverage),
            "assessed_components": assessable,
            "missing_components": [
                name for name in COMPONENT_ORDER if name not in assessable
            ],
            "nomenclature_status": nomenclature_status,
            "nomenclature_approved": nomenclature_approved,
            "why": self._why(
                components,
                final_score,
                coverage,
                nomenclature_approved=nomenclature_approved,
                nomenclature_status=nomenclature_status,
            ),
            "caveats": [
                "Priority ranks evidence strength for factor review; it is not a causal, revenue or "
                "customer-harm estimate.",
                "Signed FAMD coordinates are preserved. A direction is not treated as good or bad.",
                "Missing evidence is marked UNKNOWN and is not treated as a zero score.",
                "Semantic coherence is a deterministic concentration measure, not an LLM judgement.",
            ],
            "nomenclature": semantic_evaluation.get("nomenclature") or {},
            "validation_warnings": list(dataset.validation_warnings),
        }
        result = {
            "factor_id": factor.factor_id,
            "dimension_id": factor.dimension_id,
            "dimension_number": factor.dimension_number,
            "factor_name": factor_name,
            "prevalence_score": components["prevalence"]["component_score"],
            "statistical_importance_score": components["statistical_importance"]["component_score"],
            "representation_strength_score": components["representation_strength"]["component_score"],
            "semantic_coherence_score": components["semantic_coherence"]["component_score"],
            "final_priority_score": _round(final_score),
            "evidence_coverage": _round(coverage),
            "eligibility_status": eligibility,
            "score_status": score_status,
            "rank": None,
            "weights": weights,
            "explanation": explanation,
        }
        assessment = {
            "assessment_id": str(uuid.uuid4()),
            "factor_id": factor.factor_id,
            "famd_run_id": dataset.famd_run_id,
            "semantic_evaluation": semantic_evaluation,
            "supporting_problem_ids": semantic_evaluation.get("supporting_problem_ids") or [],
            "contradictory_problem_ids": semantic_evaluation.get("contradictory_problem_ids") or [],
            "assessment_status": components["semantic_coherence"]["assessment_status"],
            "coverage": coverage,
            "review_status": "UNREVIEWED",
        }
        return result, evidence_rows, assessment

    def _why(
        self,
        components: dict[str, dict[str, Any]],
        final_score: float | None,
        coverage: float,
        *,
        nomenclature_approved: bool,
        nomenclature_status: str,
    ) -> list[str]:
        if final_score is None:
            return [
                "No priority score was calculated because no component had usable evidence.",
                f"Evidence coverage is {coverage:.0f}%.",
            ]
        parts = sorted(
            (
                (self.weights[name] * float(component["component_score"]), name, component)
                for name, component in components.items()
                if component["component_score"] is not None
            ),
            reverse=True,
        )
        reasons = [
            f"{label} contributes {contribution:.2f} weighted points "
            f"(score {component['component_score']:.2f}/100 x weight {self.weights[name]:.2f})."
            for contribution, name, component in parts
            for label in [component["component_label"]]
        ]
        reasons.append(
            f"Final priority is {final_score:.2f}/100 from {coverage:.0f}% evidence coverage; "
            "partial coverage is renormalised over assessable components."
        )
        if not nomenclature_approved:
            reasons.append(
                f"Factor nomenclature status is {nomenclature_status}, so the score remains provisional "
                "until the factor name is approved."
            )
        return reasons

    def _headline(self, item: dict[str, Any], total: int) -> str:
        return (
            f"Rank {item['rank']} of {total} with priority {item['final_priority_score']:.2f}/100 "
            f"({item['score_status']}, {item['evidence_coverage']:.0f}% evidence coverage)."
        )

    def _summary(
        self,
        dataset: FactorPrioritisationDataset,
        scores: list[dict[str, Any]],
    ) -> dict[str, Any]:
        def count(status: str) -> int:
            return sum(1 for item in scores if item["score_status"] == status)

        eligible = sum(1 for item in scores if item["eligibility_status"] == "ELIGIBLE")
        provisional = sum(1 for item in scores if item["eligibility_status"] == "PROVISIONAL")
        insufficient = sum(
            1 for item in scores if item["eligibility_status"] == "INSUFFICIENT_EVIDENCE"
        )
        excluded = sum(1 for item in scores if item["eligibility_status"] == "EXCLUDED")
        ranked = [item for item in scores if item["final_priority_score"] is not None]
        top = min(ranked, key=lambda item: (item["rank"] or 9999, item["factor_id"]), default=None)
        return {
            "factor_count": len(scores),
            "scored_factor_count": len(ranked),
            "eligible_factor_count": eligible,
            "provisional_factor_count": provisional,
            "insufficient_evidence_factor_count": insufficient,
            "excluded_factor_count": excluded,
            "validated_score_count": count("VALIDATED"),
            "provisional_score_count": count("PROVISIONAL"),
            "insufficient_score_count": count("INSUFFICIENT_EVIDENCE"),
            "excluded_score_count": count("EXCLUDED"),
            "problems_analysed": dataset.problems_analysed,
            "top_factor_id": top["factor_id"] if top else None,
            "top_factor_name": top["factor_name"] if top else None,
            "top_priority_score": top["final_priority_score"] if top else None,
            "weights": self.weights,
            "model_version": self.rules.model_version,
            "validation_warnings": list(dataset.validation_warnings),
        }
