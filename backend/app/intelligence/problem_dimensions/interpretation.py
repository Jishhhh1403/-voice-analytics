"""Technical FAMD dimension scaffolding.

Names and business interpretations are supplied by the LLM nomenclature stage.
The deterministic layer only records statistical facts needed for review.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .famd_runner import FAMDResult


def _humanize(value: str | None) -> str:
    if not value:
        return ""
    if str(value) == "__MISSING__":
        return "unmapped"
    return str(value).replace("_", " ").replace(".", " · ").strip()


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
        variable_text = ", ".join(
            f"{_humanize(item['variable_name'])} ({item['direction_summary']})" for item in top_variables
        ) or "no dominant variable"
        category_text = ", ".join(
            f"{_humanize(item['variable_name'])}={_humanize(item.get('category_level'))}"
            for item in top_categories
        )
        description = (
            f"Technical FAMD dimension with strongest contributions from {variable_text}. "
            "No business name has been assigned."
        )
        if category_text:
            description += f" Strong category levels: {category_text}."
        definitions.append(
            {
                "dimension_id": dimension_id,
                "dimension_number": int(dimension.get("dimension_number") or dimension_id.removeprefix("D") or 0),
                "analyst_name": "",
                "proposed_label": None,
                "description": description,
                "business_interpretation": None,
                "interpretation_status": "PENDING_LLM",
                "model_version": model_version,
                "top_variables": top_variables,
                "representative_problem_ids": [item["problem_id"] for item in representative],
                "review_status": "DRAFT",
            }
        )
    return definitions
