"""Assemble and validate the evidence used by factor prioritisation.

The service reads only persisted FAMD outputs. It never refits FAMD and never
changes canonical problem scores, factor memberships or factor definitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...repository import Repository


class FactorPrioritisationDataError(ValueError):
    """Raised when a factor run cannot supply valid prioritisation evidence."""


ALLOWED_RUN_STATUSES = {"PENDING_REVIEW", "APPROVED", "PUBLISHED"}


@dataclass
class FactorEvidenceInput:
    dimension_id: str
    factor_id: str
    dimension_number: int | None
    definition: dict[str, Any]
    scores: list[dict[str, Any]]
    memberships: list[dict[str, Any]]
    contributions: list[dict[str, Any]]
    problems: dict[str, dict[str, Any]]
    dimension_metadata: dict[str, Any]
    problems_analysed: int
    total_inertia: float | None
    eigenvalue: float | None
    explained_variance: float | None
    cumulative_variance: float | None
    nomenclature: dict[str, Any] = field(default_factory=dict)

    @property
    def factor_name(self) -> str | None:
        name = str(self.nomenclature.get("factor_name") or "").strip()
        return name or None

    @property
    def factor_description(self) -> str | None:
        description = str(self.nomenclature.get("description") or "").strip()
        return description or None


@dataclass
class FactorPrioritisationDataset:
    famd_run_id: str
    feedback_run_id: str | None
    feature_schema_version: str | None
    famd_run_status: str
    diagnostics: dict[str, Any]
    problems_analysed: int
    total_inertia: float | None
    factors: list[FactorEvidenceInput] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)


def _dimension_number(definition: dict[str, Any], index: int) -> int | None:
    value = definition.get("dimension_number")
    if value is not None:
        return int(value)
    dimension_id = str(definition.get("dimension_id") or "")
    suffix = dimension_id.removeprefix("D")
    return int(suffix) if suffix.isdigit() else index + 1


def _sum_eigenvalues(diagnostics: dict[str, Any]) -> float | None:
    values = [float(value) for value in diagnostics.get("eigenvalues") or [] if value is not None]
    return float(sum(values)) if values else None


def _dimension_metadata(diagnostics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("dimension_id")): item
        for item in diagnostics.get("dimensions") or []
        if item.get("dimension_id")
    }


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def build_factor_dataset(repo: Repository, famd_run_id: str) -> FactorPrioritisationDataset:
    run = repo.get_dimension_run(famd_run_id)
    if not run:
        raise FactorPrioritisationDataError(f"Factor run {famd_run_id} was not found.")

    status = str(run.get("status") or "")
    if status not in ALLOWED_RUN_STATUSES:
        raise FactorPrioritisationDataError(
            f"Factor run {famd_run_id} has status {status or 'UNKNOWN'}; "
            "only completed, reviewed or published runs can be prioritised."
        )

    diagnostics = run.get("diagnostics") or {}
    definitions = run.get("definitions") or []
    if not definitions:
        raise FactorPrioritisationDataError(f"Factor run {famd_run_id} has no retained factor definitions.")

    all_scores = repo.get_all_problem_scores(famd_run_id)
    if not all_scores:
        raise FactorPrioritisationDataError(f"Factor run {famd_run_id} has no problem-factor scores.")

    scores_by_dimension: dict[str, dict[str, dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for score in all_scores:
        dimension_id = str(score.get("dimension_id"))
        problem_id = str(score.get("canonical_problem_id"))
        key = (dimension_id, problem_id)
        if key in seen:
            continue
        seen.add(key)
        scores_by_dimension.setdefault(dimension_id, {})[problem_id] = score

    membership_rows = repo.db.query(
        "SELECT * FROM dimension_problem_membership WHERE run_id=? ORDER BY dimension_id, canonical_problem_id",
        (famd_run_id,),
    )
    memberships_by_dimension: dict[str, list[dict[str, Any]]] = {}
    for row in membership_rows:
        memberships_by_dimension.setdefault(str(row["dimension_id"]), []).append(row)

    problem_ids = sorted({str(score["canonical_problem_id"]) for score in all_scores})
    problem_rows: list[dict[str, Any]] = []
    mappings: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(problem_ids, 500):
        problem_rows.extend(
            repo.db.query(
                "SELECT problem_id, title, problem_statement, canonical_description, journey_node_id, aspect, "
                "symptom_category, customer_intent FROM customer_problems WHERE problem_id IN "
                f"({', '.join('?' for _ in chunk)})",
                chunk,
            )
        )
        mappings.update(repo.get_problem_journey_mappings(chunk))
    problems = {str(row["problem_id"]): row for row in problem_rows}
    for problem_id, mapping in mappings.items():
        problems.setdefault(problem_id, {})["journey_mapping"] = mapping

    narrative_by_dimension = {
        str(item["dimension_id"]): item
        for item in repo.latest_dimension_narrative_nomenclature(famd_run_id)
    }
    metadata = _dimension_metadata(diagnostics)
    problems_analysed = int(diagnostics.get("n_problems") or len(problem_ids))
    total_inertia = diagnostics.get("total_inertia")
    total_inertia = float(total_inertia) if total_inertia is not None else _sum_eigenvalues(diagnostics)

    factors: list[FactorEvidenceInput] = []
    warnings: list[str] = []
    definition_ids = {str(item["dimension_id"]) for item in definitions}
    for index, definition in enumerate(definitions):
        dimension_id = str(definition["dimension_id"])
        dimension_number = _dimension_number(definition, index)
        dimension_meta = metadata.get(dimension_id, {})
        eigenvalue = dimension_meta.get("eigenvalue")
        explained = dimension_meta.get("explained_variance")
        cumulative = dimension_meta.get("cumulative_variance")
        scores = sorted(
            scores_by_dimension.get(dimension_id, {}).values(),
            key=lambda item: str(item["canonical_problem_id"]),
        )
        if eigenvalue is None and not scores:
            warnings.append(f"{dimension_id} has neither an eigenvalue nor problem scores.")
        factors.append(
            FactorEvidenceInput(
                dimension_id=dimension_id,
                factor_id=f"F{dimension_number}",
                dimension_number=dimension_number,
                definition=definition,
                scores=scores,
                memberships=memberships_by_dimension.get(dimension_id, []),
                contributions=repo.get_dimension_contributions(famd_run_id, dimension_id),
                problems=problems,
                dimension_metadata=dimension_meta,
                problems_analysed=problems_analysed,
                total_inertia=total_inertia,
                eigenvalue=float(eigenvalue) if eigenvalue is not None else None,
                explained_variance=float(explained) if explained is not None else None,
                cumulative_variance=float(cumulative) if cumulative is not None else None,
                nomenclature=narrative_by_dimension.get(dimension_id, {}),
            )
        )

    missing_scores = sorted(definition_ids - set(scores_by_dimension))
    if missing_scores:
        warnings.append("No problem scores were found for retained factors: " + ", ".join(missing_scores))

    return FactorPrioritisationDataset(
        famd_run_id=famd_run_id,
        feedback_run_id=run.get("feedback_run_id"),
        feature_schema_version=run.get("feature_schema_version"),
        famd_run_status=status,
        diagnostics=diagnostics,
        problems_analysed=problems_analysed,
        total_inertia=total_inertia,
        factors=factors,
        validation_warnings=warnings,
    )


class FactorPrioritisationDataService:
    """Repository-backed entry point for prioritisation data assembly."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def load(self, famd_run_id: str) -> FactorPrioritisationDataset:
        return build_factor_dataset(self.repo, famd_run_id)
