"""Deterministic statistical serialization for the problem portfolio.

The serialization is the only input to the narrative model. It is intentionally
built from persisted measurements and model outputs, never from narrative text,
and it keeps missing values explicit rather than converting them to zero.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from ...db import loads
from ...repository import Repository

MEASUREMENT_METRICS: tuple[str, ...] = (
    "evidence_volume",
    "distinct_customers",
    "negative_share",
    "repeat_complaint_count",
    "source_diversity",
    "volume_growth_pct",
    "negative_share_change",
    "assessment_velocity_delta",
    "customer_growth_pct",
    "volume_growth_abs",
)

UNAVAILABLE_ATTRIBUTES: tuple[dict[str, str], ...] = (
    {"field": "severity_score", "reason": "Not persisted in the canonical problem or measurement schema."},
    {"field": "frustration_score", "reason": "Emotion labels are evidence-level only; no problem score is persisted."},
    {"field": "trust_score", "reason": "Not persisted in the current data model."},
    {"field": "churn_risk_score", "reason": "Not persisted; churn must not be inferred from sentiment."},
    {"field": "customer_lifetime_value", "reason": "Not persisted in the current data model."},
    {"field": "revenue_at_risk", "reason": "Not persisted in the current data model."},
    {"field": "regulatory_risk_score", "reason": "Risk terms exist as evidence indicators, not verified scores."},
    {"field": "security_risk_score", "reason": "Risk terms exist as evidence indicators, not verified scores."},
    {"field": "financial_risk_score", "reason": "Not persisted in the current data model."},
    {"field": "complaint_cost", "reason": "Not persisted in the current data model."},
    {"field": "resolution_time", "reason": "Not persisted in the current data model."},
    {"field": "nps", "reason": "Not persisted in the current data model."},
    {"field": "csat", "reason": "Not persisted in the current data model."},
)

INTERPRETATION_CONSTRAINTS: tuple[str, ...] = (
    "FAMD coefficients describe association in latent-dimension space, not causal effects.",
    "relative_squared_coordinate_share_pct is a descriptive squared-coordinate decomposition, not a causal share.",
    "Missing measurements remain missing; they are never zero or evidence of absence.",
    "Draft or provisional factor names must be labelled as provisional and requiring review.",
    "Use only the approved business factor names supplied in factor_nomenclature.",
)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, digits: int = 6) -> float | None:
    number = _finite(value)
    return None if number is None else round(number, digits)


def _metric_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": _round(row.get("metric_value")),
        "unit": row.get("unit"),
        "status": row.get("status") or "NO_DATA",
        "calculation_method": row.get("calculation_method"),
        "window_start": row.get("measurement_window_start"),
        "window_end": row.get("measurement_window_end"),
        "input_record_count": row.get("input_record_count"),
        "source_availability": row.get("source_availability"),
        "quality_indicator": _round(row.get("quality_indicator")),
        "methodology_version": row.get("methodology_version"),
    }


def _priority_payload(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "priority_score": _round(row.get("priority_score")),
        "rank": row.get("rank"),
        "escalation_status": row.get("escalation_status"),
        "customer_impact_score": _round(row.get("customer_impact_score")),
        "business_risk_score": _round(row.get("business_risk_score")),
        "operational_impact_score": _round(row.get("operational_impact_score")),
        "trend_score": _round(row.get("trend_score")),
        "strategic_score": _round(row.get("strategic_score")),
        "escalation_reasons": loads(row.get("escalation_reasons_json"), []),
        "missing_metrics": loads(row.get("missing_metrics_json"), []),
        "methodology_version": row.get("methodology_version"),
        "window_start": row.get("measurement_window_start"),
        "window_end": row.get("measurement_window_end"),
    }


def _factor_id(dimension: dict[str, Any]) -> str:
    number = dimension.get("dimension_number")
    return f"F{number}" if number is not None else str(dimension.get("dimension_id") or "")


def _top_variables(definition: dict[str, Any], contributions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variables = definition.get("top_variables") or [
        item
        for item in contributions
        if not item.get("category_level")
    ]
    return [
        {
            "variable_name": item.get("variable_name"),
            "label": item.get("variable_name"),
            "contribution": _round(item.get("contribution")),
            "coordinate": _round(item.get("coordinate")),
            "direction_summary": item.get("direction_summary"),
            "rank": item.get("rank"),
        }
        for item in variables[:10]
    ]


def _top_categories(contributions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "variable_name": item.get("variable_name"),
            "category_level": item.get("category_level"),
            "contribution": _round(item.get("contribution")),
            "rank": item.get("rank"),
        }
        for item in contributions
        if item.get("category_level")
    ][:10]


def _journey_names(repo: Repository, feedback_run: dict[str, Any]) -> dict[str, str]:
    version = feedback_run.get("taxonomy_version")
    if not version:
        return {}
    return {
        row["node_id"]: row["display_name"]
        for row in repo.db.query(
            "SELECT node_id, display_name FROM taxonomy_nodes WHERE version=?",
            (version,),
        )
    }


def _measurement_index(repo: Repository, feedback_run_id: str) -> dict[str, dict[str, dict[str, Any]]]:
    rows = repo.db.query(
        "SELECT * FROM problem_measurement_snapshots WHERE run_id=? ORDER BY calculated_at",
        (feedback_run_id,),
    )
    index: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        index[row["problem_id"]][row["metric_name"]] = row
    return index


def _priority_index(repo: Repository, feedback_run_id: str) -> dict[str, dict[str, Any]]:
    rows = repo.db.query(
        "SELECT * FROM problem_priority_snapshots WHERE run_id=? ORDER BY calculated_at",
        (feedback_run_id,),
    )
    return {row["problem_id"]: row for row in rows}


def build_portfolio_serialization(
    repo: Repository,
    feedback_run_id: str,
    dimension_run_id: str,
    *,
    max_problems: int = 1000,
    serialization_version: str = "problem-portfolio-1.0.0",
    require_approved_factors: bool = True,
) -> dict[str, Any]:
    """Build one stable, versioned portfolio serialization."""

    feedback_run = repo.get_run(feedback_run_id)
    if not feedback_run:
        raise ValueError(f"Feedback run {feedback_run_id} was not found.")
    dimension_run = repo.get_dimension_run(dimension_run_id)
    if not dimension_run:
        raise ValueError(f"Dimension run {dimension_run_id} was not found.")
    if dimension_run.get("feedback_run_id") != feedback_run_id:
        raise ValueError("Dimension run does not belong to the requested feedback run.")

    definitions = dimension_run.get("definitions") or []
    eligible = [
        item
        for item in definitions
        if not require_approved_factors or item.get("review_status") in {"APPROVED", "PUBLISHED"}
    ]
    if not eligible:
        raise ValueError("No approved factor definitions are available for narrative serialization.")

    factor_by_dimension: dict[str, dict[str, Any]] = {}
    nomenclature: list[dict[str, Any]] = []
    for definition in eligible:
        factor_id = _factor_id(definition)
        contributions = repo.get_dimension_contributions(dimension_run_id, definition["dimension_id"])
        approved = definition.get("review_status") in {"APPROVED", "PUBLISHED"}
        source = str(definition.get("nomenclature_source") or "")
        if approved and definition.get("analyst_name"):
            business_name = definition["analyst_name"]
        elif source == "LLM" and (definition.get("proposed_label") or definition.get("analyst_name")):
            business_name = definition.get("proposed_label") or definition.get("analyst_name")
        else:
            business_name = definition.get("analyst_name") or definition.get("proposed_label")
        if not business_name:
            raise ValueError(
                f"Factor {factor_id} has no business name. Generate and approve factor nomenclature first."
            )
        if approved:
            nomenclature_status = "APPROVED"
        elif source == "LLM":
            nomenclature_status = "PROVISIONAL"
        else:
            nomenclature_status = "UNREVIEWED"
        item = {
            "factor_id": factor_id,
            "dimension_id": definition["dimension_id"],
            "dimension_number": definition.get("dimension_number"),
            "business_name": business_name,
            "short_name": definition.get("short_name"),
            "description": definition.get("description"),
            "formal_definition": definition.get("description"),
            "business_interpretation": definition.get("business_interpretation"),
            "banking_domain": definition.get("banking_domain"),
            "journey_scope": definition.get("journey_scope"),
            "core_customer_experience": definition.get("core_customer_experience"),
            "distinguishing_characteristics": definition.get("distinguishing_characteristics"),
            "supporting_variables": definition.get("supporting_variables") or [],
            "supporting_categories": definition.get("supporting_categories") or [],
            "review_status": definition.get("review_status") or "DRAFT",
            "nomenclature_status": nomenclature_status,
            "provisional": not approved,
            "source": source or "dimension_definition",
            "prompt_version": definition.get("prompt_version"),
            "model_name": definition.get("model_name"),
            "taxonomy_version": definition.get("taxonomy_version"),
            "confidence": definition.get("confidence"),
            "confidence_explanation": definition.get("confidence_explanation"),
            "aliases": [
                value
                for value in (definition.get("proposed_label"), definition.get("analyst_name"))
                if value
            ],
            "top_variables": _top_variables(definition, contributions),
        }
        factor_by_dimension[definition["dimension_id"]] = item
        nomenclature.append(item)
    nomenclature.sort(key=lambda item: (item.get("dimension_number") or 9999, item["factor_id"]))

    dimensions = (dimension_run.get("diagnostics") or {}).get("dimensions") or []
    dimension_summary = {item["dimension_id"]: item for item in dimensions}
    factor_profiles: list[dict[str, Any]] = []
    all_scores = repo.db.query(
        "SELECT * FROM problem_dimension_scores WHERE run_id=? ORDER BY canonical_problem_id, dimension_id",
        (dimension_run_id,),
    )
    scores_by_problem: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scores_by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for score in all_scores:
        scores_by_problem[score["canonical_problem_id"]].append(score)
        scores_by_dimension[score["dimension_id"]].append(score)

    for factor in nomenclature:
        dimension_id = factor["dimension_id"]
        contributions = repo.get_dimension_contributions(dimension_run_id, dimension_id)
        dimension_scores = scores_by_dimension.get(dimension_id, [])
        nonzero = [item for item in dimension_scores if _finite(item.get("coordinate")) not in (None, 0.0)]
        ranked = sorted(
            dimension_scores,
            key=lambda item: abs(_finite(item.get("coordinate")) or 0.0),
            reverse=True,
        )
        summary = dimension_summary.get(dimension_id, {})
        factor_profiles.append(
            {
                "factor_id": factor["factor_id"],
                "dimension_id": dimension_id,
                "dimension_number": factor.get("dimension_number"),
                "business_name": factor["business_name"],
                "provisional": factor["provisional"],
                "eigenvalue": _round(summary.get("eigenvalue")),
                "explained_variance": _round(summary.get("explained_variance")),
                "cumulative_variance": _round(summary.get("cumulative_variance")),
                "problem_count": len(nonzero),
                "problem_share_pct": (
                    round(len(nonzero) / len(scores_by_problem) * 100.0, 6) if scores_by_problem else None
                ),
                "mean_abs_coefficient": (
                    round(sum(abs(_finite(item.get("coordinate")) or 0.0) for item in dimension_scores) / len(dimension_scores), 6)
                    if dimension_scores
                    else None
                ),
                "max_abs_coefficient": (
                    round(max(abs(_finite(item.get("coordinate")) or 0.0) for item in dimension_scores), 6)
                    if dimension_scores
                    else None
                ),
                "top_variables": _top_variables({"top_variables": []}, contributions),
                "top_categories": _top_categories(contributions),
                "representative_problem_ids": [item["canonical_problem_id"] for item in ranked[:5]],
            }
        )
    factor_profiles.sort(key=lambda item: (item.get("dimension_number") or 9999, item["factor_id"]))

    equations = {
        row["canonical_problem_id"]: row
        for row in repo.db.query(
            "SELECT * FROM problem_dimension_equations WHERE run_id=?",
            (dimension_run_id,),
        )
    }
    measurements = _measurement_index(repo, feedback_run_id)
    priorities = _priority_index(repo, feedback_run_id)
    coverage = repo.latest_coverage_for_feedback_run(feedback_run_id)
    journeys = _journey_names(repo, feedback_run)

    problem_rows = repo.db.query(
        "SELECT * FROM customer_problems WHERE run_id=? ORDER BY problem_id LIMIT ?",
        (feedback_run_id, max_problems),
    )
    total_problems = repo.db.scalar("SELECT COUNT(*) FROM customer_problems WHERE run_id=?", (feedback_run_id,)) or 0

    problems: list[dict[str, Any]] = []
    for row in problem_rows:
        problem_id = row["problem_id"]
        problem_measurements = measurements.get(problem_id, {})
        selected_measurements = {
            name: _metric_payload(problem_measurements[name])
            for name in MEASUREMENT_METRICS
            if name in problem_measurements
        }
        problem_scores = sorted(
            scores_by_problem.get(problem_id, []),
            key=lambda item: (
                factor_by_dimension.get(item["dimension_id"], {}).get("dimension_number") or 9999,
                item["dimension_id"],
            ),
        )
        factors = []
        for score in problem_scores:
            factor = factor_by_dimension.get(score["dimension_id"])
            if not factor:
                continue
            factors.append(
                {
                    "factor_id": factor["factor_id"],
                    "business_name": factor["business_name"],
                    "review_status": factor["review_status"],
                    "provisional": factor["provisional"],
                    "coefficient": _round(score.get("coordinate")),
                    "relative_squared_coordinate_share_pct": _round(
                        score.get("relative_squared_coordinate_share_pct")
                    ),
                    "coordinate_rank": score.get("coordinate_rank"),
                }
            )
        dominant = None
        if factors:
            dominant = max(factors, key=lambda item: abs(item.get("coefficient") or 0.0))
        equation = equations.get(problem_id)
        priority = priorities.get(problem_id)
        coverage_row = coverage.get(problem_id, {})
        module = (row.get("journey_node_id") or "").split(".")[0] or None
        problems.append(
            {
                "problem_id": problem_id,
                "title": row.get("title"),
                "problem_statement": row.get("problem_statement"),
                "canonical_description": row.get("canonical_description"),
                "journey": {
                    "node_id": row.get("journey_node_id"),
                    "name": journeys.get(row.get("journey_node_id")),
                    "module": module,
                },
                "lifecycle_status": row.get("lifecycle_status"),
                "human_review_status": row.get("human_review_status"),
                "validation_status": row.get("validation_status"),
                "evidence_count": row.get("evidence_count"),
                "distinct_customers": row.get("distinct_customers"),
                "negative_count": row.get("negative_count"),
                "measurements": selected_measurements,
                "priority": _priority_payload(priority),
                "factors": factors,
                "dominant_factor": dominant,
                "equation": (
                    {
                        "equation_text": equation.get("equation_text"),
                        "number_of_dimensions": equation.get("number_of_dimensions"),
                        "coefficients": loads(equation.get("coefficient_representation_json"), []),
                    }
                    if equation
                    else None
                ),
                "coverage": {
                    "status": coverage_row.get("coverage_status", "unknown"),
                    "relationship": coverage_row.get("coverage_relationship"),
                    "report_id": coverage_row.get("coverage_report_id"),
                },
            }
        )
    problems.sort(
        key=lambda item: (
            (item.get("priority") or {}).get("rank") is None,
            (item.get("priority") or {}).get("rank") or 0,
            item["problem_id"],
        )
    )

    priority_status = Counter(
        (item.get("priority") or {}).get("escalation_status") or "unscored" for item in problems
    )
    coverage_status = Counter(item["coverage"]["status"] for item in problems)
    module_counts = Counter(item["journey"]["module"] or "unmapped" for item in problems)
    missing_measurements = Counter()
    for problem in problems:
        for name in MEASUREMENT_METRICS:
            metric = problem["measurements"].get(name)
            if not metric or metric["status"] not in {"OK", "PARTIAL"}:
                missing_measurements[name] += 1

    provisional = [item["business_name"] for item in nomenclature if item["provisional"]]
    warnings: list[str] = []
    if total_problems > len(problem_rows):
        warnings.append(f"Serialization truncated to {len(problem_rows)} of {total_problems} problems.")
    if provisional:
        warnings.append("Some factor names are provisional and require review before business use.")
    if missing_measurements:
        warnings.append("Some measurements are missing or partial; missing values are not zero.")
    if dimension_run.get("status") not in {"APPROVED", "PUBLISHED"}:
        warnings.append("The factor run is not approved; factor names must be treated as provisional.")

    serialization = {
        "schema_version": serialization_version,
        "generated_at": feedback_run.get("finished_at") or feedback_run.get("created_at"),
        "source": {
            "feedback_run_id": feedback_run_id,
            "dimension_run_id": dimension_run_id,
            "dimension_run_status": dimension_run.get("status"),
            "famd_methodology_version": dimension_run.get("method_version"),
            "feature_schema_version": dimension_run.get("feature_schema_version"),
            "counts": {
                "problems_in_run": total_problems,
                "problems_serialized": len(problems),
                "factors": len(nomenclature),
                "factor_scores": len(all_scores),
            },
        },
        "availability": {
            "available": [
                "canonical problems",
                "priority snapshots",
                "measurement snapshots",
                "FAMD factor coefficients",
                "factor nomenclature",
                "backlog coverage where a validation report exists",
            ],
            "unavailable": list(UNAVAILABLE_ATTRIBUTES),
            "missing_value_policy": "Missing measurements remain null with their persisted status; they are not zero.",
        },
        "factor_nomenclature": nomenclature,
        "factor_profiles": factor_profiles,
        "portfolio_summary": {
            "priority_escalation_counts": dict(sorted(priority_status.items())),
            "coverage_counts": dict(sorted(coverage_status.items())),
            "journey_module_counts": dict(sorted(module_counts.items())),
            "missing_measurement_counts": dict(sorted(missing_measurements.items())),
            "provisional_factor_names": provisional,
        },
        "problems": problems,
        "data_quality": {
            "warnings": warnings,
            "unavailable_attributes": list(UNAVAILABLE_ATTRIBUTES),
            "measurement_metrics": list(MEASUREMENT_METRICS),
        },
        "interpretation_constraints": list(INTERPRETATION_CONSTRAINTS),
    }
    return serialization


def build_narrative_context(
    serialization: dict[str, Any],
    *,
    max_problems: int = 30,
) -> dict[str, Any]:
    """Return a deterministic, token-bounded narrative context.

    The full serialization is retained and hashed separately. The narrative
    prompt receives the complete factor catalogue plus the highest-priority
    problem details and a compact index of every problem, which keeps grounding
    explicit without sending multi-megabyte payloads to the model.
    """

    problems = serialization.get("problems") or []
    ordered = sorted(
        problems,
        key=lambda item: (
            ((item.get("priority") or {}).get("rank") is None),
            (item.get("priority") or {}).get("rank") or 10**9,
            item.get("problem_id") or "",
        ),
    )
    included = []
    for problem in ordered[: max(1, max_problems)]:
        included.append(
            {
                "problem_id": problem.get("problem_id"),
                "title": problem.get("title"),
                "problem_statement": problem.get("problem_statement"),
                "journey": problem.get("journey"),
                "evidence_count": problem.get("evidence_count"),
                "distinct_customers": problem.get("distinct_customers"),
                "negative_count": problem.get("negative_count"),
                "measurements": problem.get("measurements"),
                "priority": problem.get("priority"),
                "factors": problem.get("factors"),
                "dominant_factor": problem.get("dominant_factor"),
                "coverage": problem.get("coverage"),
            }
        )

    problem_index = [
        {
            "problem_id": problem.get("problem_id"),
            "title": problem.get("title"),
            "priority_rank": (problem.get("priority") or {}).get("rank"),
            "escalation_status": (problem.get("priority") or {}).get("escalation_status"),
        }
        for problem in problems
    ]

    factor_profiles = []
    for profile in serialization.get("factor_profiles") or []:
        factor_profiles.append(
            {
                **profile,
                "top_variables": (profile.get("top_variables") or [])[:10],
                "top_categories": (profile.get("top_categories") or [])[:10],
                "representative_problem_ids": (profile.get("representative_problem_ids") or [])[:10],
            }
        )

    return {
        "context_scope": {
            "full_serialization_retained": True,
            "problems_in_run": (serialization.get("source") or {}).get("counts", {}).get("problems_in_run"),
            "problems_detailed": len(included),
            "problem_index_size": len(problem_index),
            "selection": "highest priority-ranked problems; full problem index included",
        },
        "source": serialization.get("source"),
        "availability": serialization.get("availability"),
        "factor_nomenclature": serialization.get("factor_nomenclature"),
        "factor_profiles": factor_profiles,
        "portfolio_summary": serialization.get("portfolio_summary"),
        "problems": included,
        "problem_index": problem_index,
        "data_quality": serialization.get("data_quality"),
        "interpretation_constraints": serialization.get("interpretation_constraints"),
    }
