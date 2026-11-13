"""Build one complete factor-level equation payload per retained FAMD dimension."""

from __future__ import annotations

from typing import Any

from ....repository import Repository

FACTOR_EQUATION_VERSION = "factor-equation-1.0.0"
COEFFICIENT_INTERPRETATION = (
    "Signed FAMD row coordinates describe problem position in latent-dimension space. "
    "They are descriptive associations, not regression coefficients, causal effects or "
    "percentage impacts. A negative coefficient is the opposite direction along the same "
    "dimension, not negative customer impact."
)


def _coefficient(problem: dict[str, Any], dimension_id: str) -> float:
    for item in problem.get("coefficients") or []:
        if item.get("dimension_id") == dimension_id:
            return float(item.get("coefficient") or 0.0)
    return 0.0


def _compact_problem(problem: dict[str, Any], dimension_id: str) -> dict[str, Any]:
    return {
        "canonical_problem_id": problem.get("canonical_problem_id"),
        "title": problem.get("title"),
        "problem_statement": problem.get("problem_statement"),
        "canonical_description": problem.get("canonical_description"),
        "journey": problem.get("journey"),
        "aspect": problem.get("aspect"),
        "customer_intent": problem.get("customer_intent"),
        "symptom_category": problem.get("symptom_category"),
        "transaction_state": problem.get("transaction_state"),
        "current_dimension_coefficient": _coefficient(problem, dimension_id),
        "equation_text": problem.get("equation_text"),
        "coefficients": problem.get("coefficients") or [],
    }


class FactorEquationBuilder:
    """Turn problem-level FAMD equations into factor-level naming evidence."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def build(
        self,
        contract: dict[str, Any],
        *,
        focus_problem_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        run = self.repo.get_dimension_run(contract["analysis_run_id"]) or {}
        diagnostics = run.get("diagnostics") or {}
        metadata = {
            item.get("dimension_id"): item
            for item in diagnostics.get("dimensions") or []
        }
        problems = contract.get("problems") or []
        focus_problem = None
        if focus_problem_id:
            focus_problem = next(
                (
                    problem
                    for problem in problems
                    if problem.get("canonical_problem_id") == focus_problem_id
                ),
                None,
            )
            if focus_problem is None:
                raise KeyError(focus_problem_id)
        equations: dict[str, dict[str, Any]] = {}
        for dimension_id in contract.get("retained_dimension_ids") or []:
            dimension_evidence = next(
                (
                    problem.get("dimension_evidence", {}).get(dimension_id)
                    for problem in problems
                    if problem.get("dimension_evidence", {}).get(dimension_id)
                ),
                {},
            )
            scored = [problem for problem in problems if _coefficient(problem, dimension_id) != 0.0]
            positive = sorted(
                [problem for problem in scored if _coefficient(problem, dimension_id) > 0],
                key=lambda item: (-_coefficient(item, dimension_id), item["canonical_problem_id"]),
            )
            negative = sorted(
                [problem for problem in scored if _coefficient(problem, dimension_id) < 0],
                key=lambda item: (_coefficient(item, dimension_id), item["canonical_problem_id"]),
            )
            representative = sorted(
                problems,
                key=lambda item: (-abs(_coefficient(item, dimension_id)), item["canonical_problem_id"]),
            )[:16]
            if focus_problem is not None:
                representative = (
                    [focus_problem]
                    + [
                        problem
                        for problem in representative
                        if problem.get("canonical_problem_id") != focus_problem_id
                    ]
                )[:16]
                focus_coefficient = _coefficient(focus_problem, dimension_id)
                if focus_coefficient > 0:
                    positive = [focus_problem] + [
                        problem
                        for problem in positive
                        if problem.get("canonical_problem_id") != focus_problem_id
                    ]
                elif focus_coefficient < 0:
                    negative = [focus_problem] + [
                        problem
                        for problem in negative
                        if problem.get("canonical_problem_id") != focus_problem_id
                    ]
            item = metadata.get(dimension_id) or {}
            factor_id = contract["factor_by_dimension"].get(dimension_id) or dimension_id.replace("D", "F", 1)
            equations[dimension_id] = {
                "schema_version": FACTOR_EQUATION_VERSION,
                "factor_id": factor_id,
                "dimension_id": dimension_id,
                "dimension_number": item.get("dimension_number"),
                "eigenvalue": item.get("eigenvalue"),
                "explained_variance": item.get("explained_variance"),
                "cumulative_variance": item.get("cumulative_variance"),
                "coefficient_interpretation": COEFFICIENT_INTERPRETATION,
                "problem_count": len(scored),
                "variable_contributions": dimension_evidence.get("top_variables") or [],
                "category_contributions": dimension_evidence.get("top_categories") or [],
                "representative_problem_equations": [
                    _compact_problem(problem, dimension_id) for problem in representative
                ],
                "positive_position_problem_equations": [
                    _compact_problem(problem, dimension_id) for problem in positive[:8]
                ],
                "negative_position_problem_equations": [
                    _compact_problem(problem, dimension_id) for problem in negative[:8]
                ],
                "representative_problem_ids": [
                    problem["canonical_problem_id"] for problem in representative
                ],
                "positive_problem_ids": [
                    problem["canonical_problem_id"] for problem in positive[:20]
                ],
                "negative_problem_ids": [
                    problem["canonical_problem_id"] for problem in negative[:20]
                ],
                "focused_problem_id": focus_problem_id,
                "focused_problem_equation": (
                    _compact_problem(focus_problem, dimension_id)
                    if focus_problem is not None
                    else None
                ),
                "missingness": problems[0].get("missingness") if problems else {},
            }
        return equations
