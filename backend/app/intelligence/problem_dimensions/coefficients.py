"""Signed canonical-problem coefficients, equations and relative shares.

FAMD row coordinates are the primary coefficients. They describe a problem's
position in latent-dimension space. They are not regression effects, causal
effects or percentages of a problem caused by a factor.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _ordered_dimensions(dimensions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        dimensions,
        key=lambda item: (
            int(item.get("dimension_number") or 0),
            int(item.get("component_index") or 0),
            str(item.get("dimension_id") or ""),
        ),
    )


def calculate_relative_shares(
    scores: list[dict[str, Any]],
    dimensions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add relative squared-coordinate shares and within-problem ranks.

    ``W_ij = s_ij^2 / sum_j(s_ij^2) * 100`` for non-zero coordinate vectors.
    The share is a descriptive decomposition of squared coordinate magnitude,
    not a causal contribution or a percentage of customer impact.
    """

    ordered = _ordered_dimensions(dimensions)
    dimension_order = {item["dimension_id"]: index for index, item in enumerate(ordered)}
    by_problem: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for score in scores:
        by_problem[str(score["problem_id"])].append(score)

    enriched: list[dict[str, Any]] = []
    for problem_id, problem_scores in by_problem.items():
        ordered_scores = sorted(
            problem_scores,
            key=lambda item: dimension_order.get(item["dimension_id"], 10**6),
        )
        squared = {item["dimension_id"]: float(item["coordinate"]) ** 2 for item in ordered_scores}
        denominator = sum(squared.values())
        ranked = sorted(ordered_scores, key=lambda item: abs(float(item["coordinate"])), reverse=True)
        rank_by_dimension = {item["dimension_id"]: index + 1 for index, item in enumerate(ranked)}
        for item in ordered_scores:
            share = (squared[item["dimension_id"]] / denominator * 100.0) if denominator > 0 else None
            enriched.append(
                {
                    **item,
                    "problem_id": problem_id,
                    "relative_squared_coordinate_share_pct": None if share is None else round(share, 6),
                    "coordinate_rank": rank_by_dimension.get(item["dimension_id"]),
                }
            )
    return enriched


def _format_equation(problem_id: str, coefficients: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in coefficients:
        coefficient = float(item["coefficient"])
        sign = "+" if coefficient >= 0 else "-"
        parts.append(f"{sign} {abs(coefficient):.6f}*{item['factor_id']}")
    return f"{problem_id} = " + " ".join(parts)


def build_equations(
    scores: list[dict[str, Any]],
    dimensions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build one human-readable equation and structured vector per problem."""

    ordered = _ordered_dimensions(dimensions)
    by_problem: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for score in scores:
        by_problem[str(score["problem_id"])].append(score)

    equations: list[dict[str, Any]] = []
    for problem_id, problem_scores in sorted(by_problem.items()):
        score_by_dimension = {item["dimension_id"]: item for item in problem_scores}
        coefficients: list[dict[str, Any]] = []
        for dimension in ordered:
            score = score_by_dimension.get(dimension["dimension_id"])
            if score is None:
                continue
            coefficients.append(
                {
                    "dimension_id": dimension["dimension_id"],
                    "dimension_number": dimension.get("dimension_number"),
                    "factor_id": dimension.get("factor_id") or dimension["dimension_id"].replace("D", "F", 1),
                    "coefficient": float(score["coordinate"]),
                    "relative_squared_coordinate_share_pct": score.get(
                        "relative_squared_coordinate_share_pct"
                    ),
                    "coordinate_rank": score.get("coordinate_rank"),
                }
            )
        equations.append(
            {
                "problem_id": problem_id,
                "equation_text": _format_equation(problem_id, coefficients),
                "number_of_dimensions": len(coefficients),
                "coefficient_representation": coefficients,
            }
        )
    return equations
