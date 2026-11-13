"""Draft, human-reviewable dimension interpretations.

The suggested label is derived only from the fitted FAMD contributions. It is a
provisional description of a statistical pattern, not an approved business
concept and not a causal root cause.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .famd_runner import FAMDResult

_FEATURE_PHRASES = {
    "journey_module": "journey module",
    "journey_feature": "journey feature",
    "journey_stage": "journey stage",
    "aspect": "problem aspect",
    "symptom_category": "symptom family",
    "customer_intent": "customer intent",
    "evidence_volume": "evidence volume",
    "distinct_customers": "customer reach",
    "negative_share": "negative sentiment",
    "repeat_complaint_rate": "repeat complaints",
    "source_diversity": "source diversity",
    "high_effort_share": "customer effort",
    "outcome_failure_share": "task failure",
    "negative_emotion_share": "negative emotion",
    "volume_growth_pct": "volume growth",
    "negative_share_change": "sentiment deterioration",
    "assessment_velocity_delta": "assessment velocity",
    "customer_growth_pct": "customer growth",
    "volume_growth_abs": "absolute volume growth",
    "evidence_confidence": "evidence confidence",
}

_CATEGORY_VARIABLES = {"journey_module", "journey_feature", "journey_stage", "aspect", "symptom_category", "customer_intent"}


def _humanize(value: str | None) -> str:
    if not value:
        return ""
    if str(value) == "__MISSING__":
        return "unmapped"
    return str(value).replace("_", " ").replace(".", " · ").strip()


def _phrase(item: dict[str, Any]) -> str:
    variable = str(item.get("variable_name") or "")
    category = item.get("category_level")
    if variable in _CATEGORY_VARIABLES and category:
        return _humanize(str(category))
    return _FEATURE_PHRASES.get(variable, _humanize(variable))


def _unique_phrases(items: list[dict[str, Any]], limit: int = 3) -> list[str]:
    phrases: list[str] = []
    for item in items:
        phrase = _phrase(item)
        if phrase and phrase.lower() not in {value.lower() for value in phrases}:
            phrases.append(phrase)
        if len(phrases) >= limit:
            break
    return phrases


def _proposed_label(variable_phrases: list[str], category_phrases: list[str]) -> str:
    phrases = [item for item in category_phrases if item]
    phrases.extend(
        item
        for item in variable_phrases
        if item and item.lower() not in {value.lower() for value in phrases}
    )
    if not phrases:
        return "Unlabelled statistical dimension"
    label = " · ".join(phrases[:3])
    return label[:1].upper() + label[1:]


def initial_definitions(result: FAMDResult, model_version: str | None = None) -> list[dict[str, Any]]:
    scores_by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for score in result.problem_scores:
        scores_by_dimension[score["dimension_id"]].append(score)

    definitions: list[dict[str, Any]] = []
    for dimension in result.dimensions:
        dimension_id = dimension["dimension_id"]
        top_variables = dimension.get("top_variables", [])[:6]
        top_categories = dimension.get("top_categories", [])[:6]
        representative = sorted(
            scores_by_dimension.get(dimension_id, []),
            key=lambda item: abs(float(item["coordinate"])),
            reverse=True,
        )[:10]
        variable_phrases = _unique_phrases(top_variables)
        category_phrases = _unique_phrases(top_categories)
        proposed_label = _proposed_label(variable_phrases, category_phrases)
        variable_text = ", ".join(
            f"{_humanize(item['variable_name'])} ({item['direction_summary']})" for item in top_variables
        ) or "no dominant variable"
        category_text = ", ".join(
            f"{_humanize(item['variable_name'])}={_humanize(item.get('category_level'))}"
            for item in top_categories
        )
        description = (
            f"Provisional dimension associated with {variable_text}. "
            "The label is a statistical summary for analyst review, not a proven root cause."
        )
        if category_text:
            description += f" Strong category levels: {category_text}."
        definitions.append(
            {
                "dimension_id": dimension_id,
                "dimension_number": int(dimension.get("dimension_number") or dimension_id.removeprefix("D") or 0),
                "analyst_name": proposed_label,
                "proposed_label": proposed_label,
                "description": description,
                "business_interpretation": description,
                "interpretation_status": "DRAFT",
                "model_version": model_version,
                "top_variables": top_variables,
                "representative_problem_ids": [item["problem_id"] for item in representative],
                "review_status": "DRAFT",
            }
        )
    return definitions
