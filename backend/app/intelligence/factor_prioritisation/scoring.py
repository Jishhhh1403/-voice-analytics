"""Deterministic component scorers for factor evidence prioritisation.

Every score is a normalised 0-100 value. Missing evidence is never silently
converted to zero: the component is returned with an UNKNOWN status and the
calculator decides whether a provisional score is allowed.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from statistics import mean, median
from typing import Any

from .data import FactorEvidenceInput

MEMBERSHIP_TYPES = {"high_score", "associated"}


def _round(value: float | None) -> float | None:
    return round(float(value), 4) if value is not None else None


def _score_status(score: float | None) -> str:
    return "OK" if score is not None else "UNKNOWN"


def score_prevalence(
    factor: FactorEvidenceInput,
    *,
    rule_version: str,
    membership_min_score: float,
) -> dict[str, Any]:
    total = factor.problems_analysed
    membership_ids = {
        str(item["canonical_problem_id"])
        for item in factor.memberships
        if str(item.get("membership_type")) in MEMBERSHIP_TYPES
    }
    source = "dimension_problem_membership"
    status = "OK"
    if not factor.memberships:
        membership_ids = {
            str(item["canonical_problem_id"])
            for item in factor.scores
            if abs(float(item.get("coordinate") or 0.0)) >= membership_min_score
        }
        source = "problem_dimension_scores (legacy fallback)"
        status = "PROVISIONAL"

    has_evidence = bool(factor.memberships or factor.scores)
    score = (len(membership_ids) / total * 100.0) if total > 0 and has_evidence else None
    explanation = (
        f"{len(membership_ids)} of {total} canonical problems are members of {factor.factor_id} "
        f"using the persisted FAMD membership rule (types high_score/associated)."
        if total > 0 and has_evidence
        else "No canonical problem population or factor score evidence is available."
    )
    if source.endswith("(legacy fallback)"):
        explanation = (
            f"{len(membership_ids)} of {total} canonical problems fall at or beyond the "
            f"legacy coordinate threshold |coordinate| >= {membership_min_score:.2f}; persisted "
            "membership rows were unavailable, so this component is provisional."
        )
    return {
        "component_name": "prevalence",
        "component_label": "Factor prevalence",
        "component_score": _round(score),
        "assessment_status": status if total > 0 and has_evidence else "UNKNOWN",
        "calculation_method": "membership coverage: N_f / N * 100",
        "rule_version": rule_version,
        "source_table": source,
        "explanation": explanation,
        "raw_value": {
            "problem_count": len(membership_ids),
            "total_problem_count": total,
            "membership_rows": len(factor.memberships),
            "membership_min_score": membership_min_score,
            "membership_types": sorted(MEMBERSHIP_TYPES),
        },
        "evidence_reference": {
            "problem_ids": sorted(membership_ids)[:50],
            "denominator": "diagnostics.n_problems",
        },
    }


def score_statistical_importance(factor: FactorEvidenceInput) -> dict[str, Any]:
    eigenvalue = factor.eigenvalue
    total_inertia = factor.total_inertia
    if eigenvalue is None:
        return {
            "component_name": "statistical_importance",
            "component_label": "Statistical importance",
            "component_score": None,
            "assessment_status": "UNKNOWN",
            "calculation_method": "eigenvalue / total inertia * 100",
            "rule_version": "famd-eigenvalue-1.0.0",
            "source_table": "dimension_analysis_runs.diagnostics_json",
            "explanation": f"{factor.factor_id} has no persisted eigenvalue, so its statistical importance cannot be calculated.",
            "raw_value": {"eigenvalue": None, "total_inertia": _round(total_inertia)},
            "evidence_reference": {"dimension_id": factor.dimension_id},
        }
    if total_inertia is None or total_inertia <= 0:
        score = factor.explained_variance
        return {
            "component_name": "statistical_importance",
            "component_label": "Statistical importance",
            "component_score": _round(score),
            "assessment_status": _score_status(score),
            "calculation_method": "reported FAMD explained variance (total inertia unavailable)",
            "rule_version": "famd-eigenvalue-1.0.0",
            "source_table": "dimension_analysis_runs.diagnostics_json",
            "explanation": (
                f"{factor.factor_id} uses the reported FAMD explained variance because total inertia "
                "is unavailable; both describe the same variance share but the denominator could not be re-checked."
            ),
            "raw_value": {
                "eigenvalue": _round(eigenvalue),
                "total_inertia": None,
                "reported_explained_variance": _round(factor.explained_variance),
            },
            "evidence_reference": {"dimension_id": factor.dimension_id},
        }

    score = eigenvalue / total_inertia * 100.0
    reported = factor.explained_variance
    reconciliation = (
        f" Reported FAMD explained variance is {reported:.4f}%."
        if reported is not None
        else ""
    )
    return {
        "component_name": "statistical_importance",
        "component_label": "Statistical importance",
        "component_score": _round(score),
        "assessment_status": "OK",
        "calculation_method": "eigenvalue / total inertia * 100",
        "rule_version": "famd-eigenvalue-1.0.0",
        "source_table": "dimension_analysis_runs.diagnostics_json",
        "explanation": (
            f"{factor.factor_id} has eigenvalue {eigenvalue:.4f} of total inertia {total_inertia:.4f}, "
            f"so it explains {score:.2f}% of FAMD variation.{reconciliation} This is a statistical "
            "variance share, not customer severity or business risk."
        ),
        "raw_value": {
            "eigenvalue": _round(eigenvalue),
            "total_inertia": _round(total_inertia),
            "reported_explained_variance": _round(reported),
            "cumulative_variance": _round(factor.cumulative_variance),
        },
        "evidence_reference": {"dimension_id": factor.dimension_id, "famd_run_id": None},
    }


def _row_contribution(score: dict[str, Any]) -> float | None:
    metadata = score.get("contribution_metadata") or {}
    value = metadata.get("row_contribution")
    return float(value) if value is not None else None


def score_representation(
    factor: FactorEvidenceInput,
    *,
    rule_version: str,
    multiplier: float,
) -> dict[str, Any]:
    scores = factor.scores
    total = factor.problems_analysed or len(scores)
    contributions = [value for value in (_row_contribution(item) for item in scores) if value is not None]
    positive_count = sum(1 for item in scores if float(item.get("coordinate") or 0.0) > 0)
    negative_count = sum(1 for item in scores if float(item.get("coordinate") or 0.0) < 0)
    missing_count = max(0, total - len(scores))

    if total <= 0:
        return {
            "component_name": "representation_strength",
            "component_label": "Problem representation strength",
            "component_score": None,
            "assessment_status": "UNKNOWN",
            "calculation_method": "represented problems / total problems * 100",
            "rule_version": rule_version,
            "source_table": "problem_dimension_scores.contribribution_metadata_json",
            "explanation": "No canonical problem population is available for representation scoring.",
            "raw_value": {},
            "evidence_reference": {},
        }

    if contributions:
        threshold = multiplier * (100.0 / total)
        represented = [
            item for item in scores if (_row_contribution(item) or 0.0) >= threshold
        ]
        represented_ids = {str(item["canonical_problem_id"]) for item in represented}
        score = len(represented_ids) / total * 100.0
        distribution = sorted(contributions)
        q1 = distribution[int(0.25 * (len(distribution) - 1))]
        q3 = distribution[int(0.75 * (len(distribution) - 1))]
        positive_represented = sum(
            1 for item in represented if float(item.get("coordinate") or 0.0) > 0
        )
        negative_represented = sum(
            1 for item in represented if float(item.get("coordinate") or 0.0) < 0
        )
        return {
            "component_name": "representation_strength",
            "component_label": "Problem representation strength",
            "component_score": _round(score),
            "assessment_status": "OK",
            "calculation_method": (
                "represented problems / total problems * 100; representation rule = "
                f"row_contribution >= {multiplier:.2f} x mean contribution"
            ),
            "rule_version": rule_version,
            "source_table": "problem_dimension_scores.contribution_metadata_json",
            "explanation": (
                f"{len(represented_ids)} of {total} canonical problems have a FAMD row contribution "
                f"at or above the expected mean contribution threshold of {threshold:.4f}% "
                f"({multiplier:.2f} x 100/{total}). This measures representation coverage, not causal impact."
            ),
            "raw_value": {
                "represented_problem_count": len(represented_ids),
                "total_problem_count": total,
                "row_contribution_threshold": _round(threshold),
                "mean_row_contribution": _round(mean(contributions)),
                "median_row_contribution": _round(median(contributions)),
                "max_row_contribution": _round(max(contributions)),
                "q1_row_contribution": _round(q1),
                "q3_row_contribution": _round(q3),
                "positive_problem_count": positive_count,
                "negative_problem_count": negative_count,
                "positive_represented_problem_count": positive_represented,
                "negative_represented_problem_count": negative_represented,
                "missing_problem_score_count": missing_count,
            },
            "evidence_reference": {
                "represented_problem_ids": sorted(represented_ids)[:50],
                "dimension_id": factor.dimension_id,
            },
            "_represented_ids": sorted(represented_ids),
        }

    membership_ids = {
        str(item["canonical_problem_id"])
        for item in factor.memberships
        if str(item.get("membership_type")) in MEMBERSHIP_TYPES
    }
    if membership_ids:
        score = len(membership_ids) / total * 100.0
        return {
            "component_name": "representation_strength",
            "component_label": "Problem representation strength",
            "component_score": _round(score),
            "assessment_status": "PROVISIONAL",
            "calculation_method": "membership coverage fallback (row contributions unavailable)",
            "rule_version": rule_version,
            "source_table": "dimension_problem_membership",
            "explanation": (
                "FAMD row contributions were not persisted for this factor, so representation uses "
                f"the validated membership set: {len(membership_ids)} of {total} canonical problems. "
                "The component is provisional because it is not based on row contribution."
            ),
            "raw_value": {
                "represented_problem_count": len(membership_ids),
                "total_problem_count": total,
                "row_contribution_threshold": None,
                "mean_row_contribution": None,
                "median_row_contribution": None,
                "max_row_contribution": None,
                "positive_problem_count": positive_count,
                "negative_problem_count": negative_count,
                "missing_problem_score_count": missing_count,
            },
            "evidence_reference": {
                "represented_problem_ids": sorted(membership_ids)[:50],
                "dimension_id": factor.dimension_id,
            },
            "_represented_ids": sorted(membership_ids),
        }

    return {
        "component_name": "representation_strength",
        "component_label": "Problem representation strength",
        "component_score": None,
        "assessment_status": "UNKNOWN",
        "calculation_method": "represented problems / total problems * 100",
        "rule_version": rule_version,
        "source_table": "problem_dimension_scores",
        "explanation": "No row contributions or validated memberships are available for this factor.",
        "raw_value": {
            "represented_problem_count": 0,
            "total_problem_count": total,
            "positive_problem_count": positive_count,
            "negative_problem_count": negative_count,
            "missing_problem_score_count": missing_count,
        },
        "evidence_reference": {"dimension_id": factor.dimension_id},
    }


def _normalised_entropy(values: list[str]) -> tuple[float, int, str | None, float]:
    counts = Counter(value for value in values if value)
    total = sum(counts.values())
    if total == 0:
        return 0.0, 0, None, 0.0
    dominant, dominant_count = counts.most_common(1)[0]
    if len(counts) == 1:
        return 1.0, 1, dominant, 100.0
    entropy = -sum((count / total) * math.log(count / total, 2) for count in counts.values())
    normalised = entropy / math.log(len(counts), 2)
    concentration = max(0.0, min(1.0, 1.0 - normalised))
    return concentration, len(counts), dominant, dominant_count / total * 100.0


def _semantic_dimension(
    name: str,
    label: str,
    problem_ids: list[str],
    problems: dict[str, dict[str, Any]],
    extractor: Callable[[dict[str, Any]], str | None],
) -> dict[str, Any]:
    values = [extractor(problems.get(problem_id, {})) for problem_id in problem_ids]
    observed = [value for value in values if value]
    concentration, distinct, dominant, dominant_share = _normalised_entropy(observed)
    if not observed:
        return {
            "label": label,
            "score": None,
            "status": "UNKNOWN",
            "problem_count": 0,
            "distinct_levels": 0,
            "dominant_level": None,
            "dominant_share_pct": None,
            "explanation": f"No {label.lower()} evidence is available for the represented problems.",
            "top_levels": [],
        }
    score = concentration * 100.0
    return {
        "label": label,
        "score": _round(score),
        "status": "OK",
        "problem_count": len(observed),
        "distinct_levels": distinct,
        "dominant_level": dominant,
        "dominant_share_pct": _round(dominant_share),
        "explanation": (
            f"{len(observed)} represented problems span {distinct} {label.lower()} level(s); "
            f"the dominant level is '{dominant}' ({dominant_share:.1f}% of problems). "
            f"Normalised concentration is {score:.1f}/100 (higher means a more coherent theme)."
        ),
        "top_levels": [
            {"level": level, "count": count, "share_pct": _round(count / len(observed) * 100.0)}
            for level, count in Counter(observed).most_common(5)
        ],
    }


def _journey_value(problem: dict[str, Any]) -> str | None:
    mapping = problem.get("journey_mapping") or {}
    return mapping.get("module_id") or problem.get("journey_node_id")


def _process_value(problem: dict[str, Any]) -> str | None:
    mapping = problem.get("journey_mapping") or {}
    return mapping.get("journey_stage_id") or mapping.get("feature_id") or problem.get("journey_node_id")


def score_semantic_coherence(
    factor: FactorEvidenceInput,
    *,
    rule_version: str,
    represented_ids: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if represented_ids:
        problem_ids = represented_ids
    else:
        problem_ids = sorted(
            {
                str(item["canonical_problem_id"])
                for item in factor.memberships
                if str(item.get("membership_type")) in MEMBERSHIP_TYPES
            }
        )
    if not problem_ids:
        problem_ids = [
            str(item["canonical_problem_id"])
            for item in factor.scores
            if abs(float(item.get("coordinate") or 0.0)) > 0
        ]

    subdimensions = {
        "journey_coherence": _semantic_dimension(
            "journey_coherence", "Journey coherence", problem_ids, factor.problems, _journey_value
        ),
        "aspect_coherence": _semantic_dimension(
            "aspect_coherence", "Aspect coherence", problem_ids, factor.problems, lambda p: p.get("aspect")
        ),
        "intent_coherence": _semantic_dimension(
            "intent_coherence", "Intent coherence", problem_ids, factor.problems, lambda p: p.get("customer_intent")
        ),
        "symptom_coherence": _semantic_dimension(
            "symptom_coherence", "Symptom coherence", problem_ids, factor.problems, lambda p: p.get("symptom_category")
        ),
        "banking_process_coherence": _semantic_dimension(
            "banking_process_coherence",
            "Banking-process coherence",
            problem_ids,
            factor.problems,
            _process_value,
        ),
    }
    assessable = [item for item in subdimensions.values() if item["score"] is not None]
    coverage = len(assessable) / len(subdimensions) * 100.0
    score = mean(float(item["score"]) for item in assessable) if assessable else None
    status = "OK" if score is not None and coverage == 100.0 else ("PARTIAL" if score is not None else "UNKNOWN")

    coordinate_by_problem = {
        str(score_row.get("canonical_problem_id")): abs(float(score_row.get("coordinate") or 0.0))
        for score_row in factor.scores
    }
    supporting = sorted(
        problem_ids,
        key=lambda problem_id: -coordinate_by_problem.get(problem_id, 0.0),
    )[:20]
    evaluation = {
        "subdimensions": subdimensions,
        "coverage_pct": _round(coverage),
        "assessed_dimensions": len(assessable),
        "total_dimensions": len(subdimensions),
        "rule": "normalised concentration (1 - normalised Shannon entropy) across represented problem attributes",
        "supporting_problem_ids": supporting,
        "contradictory_problem_ids": [
            str(item) for item in (factor.definition.get("contradictory_problem_ids") or [])
        ],
        "nomenclature": {
            "factor_name": factor.factor_name,
            "short_name": factor.nomenclature.get("short_name"),
            "description": factor.factor_description,
            "source": factor.nomenclature.get("source"),
            "serialization_id": factor.nomenclature.get("serialization_id"),
            "model_name": factor.nomenclature.get("model_name"),
            "prompt_version": factor.nomenclature.get("prompt_version"),
        },
    }
    explanation = (
        f"Semantic coherence averages {len(assessable)} assessable attribute-concentration dimensions "
        f"for {len(problem_ids)} represented problems. Coverage is {coverage:.0f}%. "
        "This is a deterministic description of evidence coherence, not an LLM judgement or a business-impact estimate."
    )
    component = {
        "component_name": "semantic_coherence",
        "component_label": "Semantic coherence",
        "component_score": _round(score),
        "assessment_status": status,
        "calculation_method": "mean of assessable journey/aspect/intent/symptom/process concentration scores",
        "rule_version": rule_version,
        "source_table": "customer_problems + problem_journey_mappings",
        "explanation": explanation,
        "raw_value": evaluation,
        "evidence_reference": {
            "supporting_problem_ids": supporting,
            "contradictory_problem_ids": evaluation["contradictory_problem_ids"],
        },
    }
    return component, evaluation
