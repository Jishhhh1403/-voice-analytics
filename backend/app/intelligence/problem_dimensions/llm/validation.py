"""Validation for LLM nomenclature and cross-dimension consistency."""

from __future__ import annotations

import re
from typing import Any

from .contracts import DimensionEvidenceAggregation, FactorNomenclatureProposal

_TECHNICAL_NAME = re.compile(r"\b(f\d+|d\d+|dim(?:ension)?\.?\s*\d+|factor\s*\d+)\b", re.IGNORECASE)
_CAUSAL_LANGUAGE = re.compile(
    r"\b(causes?|caused by|leads? to|results? in|drives?|because of|due to)\b", re.IGNORECASE
)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "for",
    "in",
    "on",
    "to",
    "with",
    "customer",
    "customers",
    "experience",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 2 and token not in _STOPWORDS
    }


class NomenclatureValidationService:
    """Validate model output without changing statistical assignments."""

    def validate_observation(self, raw: dict[str, Any]) -> dict[str, Any]:
        from .contracts import ProblemDimensionObservation

        try:
            observation = ProblemDimensionObservation.model_validate(raw)
        except Exception as exc:
            return {"status": "FAILED", "errors": [str(exc)], "warnings": []}
        errors = []
        warnings = []
        if _TECHNICAL_NAME.search(observation.problem_summary):
            warnings.append("Problem summary contains a technical factor identifier.")
        if _CAUSAL_LANGUAGE.search(observation.relevance_explanation):
            warnings.append("Relevance explanation contains causal language.")
        return {
            "status": "PASSED" if not errors else "FAILED",
            "errors": errors,
            "warnings": warnings,
        }

    def validate_proposal(
        self,
        proposal: dict[str, Any] | FactorNomenclatureProposal,
        *,
        dimension_id: str,
        factor_id: str,
        known_variables: set[str],
        known_categories: set[str],
        known_problem_ids: set[str],
    ) -> dict[str, Any]:
        try:
            parsed = (
                proposal
                if isinstance(proposal, FactorNomenclatureProposal)
                else FactorNomenclatureProposal.model_validate(proposal)
            )
        except Exception as exc:
            return {"status": "FAILED", "errors": [str(exc)], "warnings": []}
        errors: list[str] = []
        warnings: list[str] = []
        if parsed.factor_id != factor_id:
            errors.append(f"factor_id {parsed.factor_id} does not match {factor_id}.")
        if parsed.dimension_id != dimension_id:
            errors.append(f"dimension_id {parsed.dimension_id} does not match {dimension_id}.")
        if _TECHNICAL_NAME.search(parsed.proposed_name) or _TECHNICAL_NAME.search(parsed.short_name):
            errors.append("Proposed name contains a technical factor or dimension identifier.")
        if _CAUSAL_LANGUAGE.search(parsed.formal_definition):
            warnings.append("Formal definition contains causal language; review wording.")
        if _CAUSAL_LANGUAGE.search(parsed.business_interpretation):
            warnings.append("Business interpretation contains causal language; review wording.")
        unknown_variables = sorted(set(parsed.supporting_variables) - known_variables)
        if unknown_variables:
            errors.append("Unknown supporting variables: " + ", ".join(unknown_variables[:10]))
        unknown_categories = sorted(
            set(parsed.supporting_categories) - known_categories
        )
        if unknown_categories:
            warnings.append(
                "Supporting categories not found verbatim in contribution evidence: "
                + ", ".join(unknown_categories[:10])
            )
        unknown_representative = sorted(set(parsed.representative_problem_ids) - known_problem_ids)
        if unknown_representative:
            errors.append("Unknown representative problem IDs: " + ", ".join(unknown_representative[:10]))
        unknown_contradictory = sorted(set(parsed.contradictory_problem_ids) - known_problem_ids)
        if unknown_contradictory:
            errors.append("Unknown contradictory problem IDs: " + ", ".join(unknown_contradictory[:10]))
        if not parsed.representative_problem_ids and not parsed.contradictory_problem_ids:
            errors.append("Nomenclature provides no canonical problem evidence.")
        if len(parsed.proposed_name.split()) > 12:
            warnings.append("Proposed name is long; consider a shorter business label.")
        if parsed.nomenclature_status == "CONFIDENT" and parsed.confidence < 0.6:
            warnings.append("Nomenclature is marked confident but confidence is below 0.6.")
        return {
            "status": "PASSED" if not errors else "FAILED",
            "errors": errors,
            "warnings": warnings,
        }

    def validate_aggregation(self, aggregation: DimensionEvidenceAggregation) -> dict[str, Any]:
        errors = []
        warnings = []
        if not aggregation.evidence_references:
            errors.append("Aggregation has no canonical problem evidence references.")
        if aggregation.confidence < 0.3:
            warnings.append("Aggregation confidence is low; human review is required.")
        return {
            "status": "PASSED" if not errors else "FAILED",
            "errors": errors,
            "warnings": warnings,
        }

    def detect_overlaps(self, catalogue: list[dict[str, Any]]) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        for index, first in enumerate(catalogue):
            first_tokens = _tokens(str(first.get("proposed_name") or ""))
            for second in catalogue[index + 1 :]:
                second_tokens = _tokens(str(second.get("proposed_name") or ""))
                if not first_tokens or not second_tokens:
                    continue
                union = first_tokens | second_tokens
                intersection = first_tokens & second_tokens
                similarity = len(intersection) / len(union) if union else 0.0
                if similarity >= 0.5 or first_tokens == second_tokens:
                    findings.append(
                        {
                            "dimension_ids": [first.get("dimension_id"), second.get("dimension_id")],
                            "factor_ids": [first.get("factor_id"), second.get("factor_id")],
                            "names": [first.get("proposed_name"), second.get("proposed_name")],
                            "token_overlap": round(similarity, 4),
                            "problem": "Potential duplicate or overlapping nomenclature.",
                        }
                    )
        return {
            "status": "PASSED" if not findings else "REVIEW_REQUIRED",
            "findings": findings,
        }
