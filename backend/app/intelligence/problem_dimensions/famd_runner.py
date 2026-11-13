"""FAMD fitting and structured extraction via the ``prince`` library."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .feature_builder import FeatureSpec
from .preprocessing import PreparedFrame


@dataclass
class FAMDResult:
    status: str
    error: str | None
    library: str
    library_version: str | None
    n_components: int
    eigenvalues: list[float] = field(default_factory=list)
    percentage_of_variance: list[float] = field(default_factory=list)
    cumulative_percentage_of_variance: list[float] = field(default_factory=list)
    total_inertia: float | None = None
    dimensions: list[dict[str, Any]] = field(default_factory=list)
    problem_scores: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _to_float(value: Any) -> float:
    return float(np.asarray(value).reshape(-1)[0])


def _category_lookup(model: Any) -> dict[str, tuple[str, str]]:
    lookup: dict[str, tuple[str, str]] = {}
    one_hot = list(getattr(model, "one_hot_columns_", []) or [])
    offset = 0
    for variable in list(getattr(model, "cat_cols_", []) or []):
        categories = list((getattr(model, "categories_", {}) or {}).get(variable, []))
        for category in categories:
            if offset < len(one_hot):
                lookup[str(one_hot[offset])] = (str(variable), str(category))
            offset += 1
    return lookup


def _component_value(table: Any, row_label: Any, component: int) -> float | None:
    if table is None:
        return None
    try:
        return float(table.loc[row_label].iloc[component])
    except Exception:
        pass
    try:
        return float(table.iloc[component].loc[row_label])
    except Exception:
        return None


def run_famd(
    prepared: PreparedFrame,
    specs: list[FeatureSpec],
    max_components: int,
    random_state: int = 42,
    max_contributions: int = 25,
) -> FAMDResult:
    frame = prepared.frame
    if frame.empty or frame.shape[0] < 3 or frame.shape[1] < 2:
        return FAMDResult(
            status="INSUFFICIENT_DATA",
            error="FAMD needs at least three problems and two active features.",
            library="prince",
            library_version=None,
            n_components=0,
        )

    try:
        import prince
    except Exception as exc:  # pragma: no cover - exercised only when dependency is absent
        return FAMDResult(
            status="LIBRARY_UNAVAILABLE",
            error=f"prince is not importable: {exc}",
            library="prince",
            library_version=None,
            n_components=0,
        )

    n_components = max(1, min(int(max_components), int(frame.shape[0]) - 1, int(frame.shape[1])))
    try:
        model = prince.FAMD(n_components=n_components, random_state=random_state)
        model.fit(frame)
        row_coordinates = model.row_coordinates(frame)
        row_contributions = getattr(model, "row_contributions_", None)
    except Exception as exc:
        return FAMDResult(
            status="FIT_ERROR",
            error=f"FAMD fit failed: {exc}",
            library="prince",
            library_version=getattr(prince, "__version__", None),
            n_components=0,
        )

    eigenvalues = np.asarray(getattr(model, "eigenvalues_", []), dtype=float)
    percentages = np.asarray(getattr(model, "percentage_of_variance_", []), dtype=float)
    cumulative = np.asarray(getattr(model, "cumulative_percentage_of_variance_", []), dtype=float)
    total_inertia = getattr(model, "total_inertia_", None)
    total_inertia = None if total_inertia is None else float(total_inertia)

    variable_contributions = getattr(model, "variable_contributions_", None)
    variable_coordinates = getattr(model, "variable_coordinates_", None)
    column_contributions = getattr(model, "column_contributions_", None)
    category_lookup = _category_lookup(model)
    variable_names = [str(column) for column in frame.columns]

    dimensions: list[dict[str, Any]] = []
    for component in range(len(eigenvalues) if len(eigenvalues) else n_components):
        dimension_id = f"D{component + 1}"
        variables: list[dict[str, Any]] = []
        for variable in variable_names:
            contribution = _component_value(variable_contributions, variable, component)
            coordinate = _component_value(variable_coordinates, variable, component)
            if contribution is None and coordinate is None:
                continue
            contribution = 0.0 if contribution is None else contribution
            coordinate = 0.0 if coordinate is None else coordinate
            variables.append(
                {
                    "variable_name": variable,
                    "category_level": None,
                    "contribution": contribution,
                    "coordinate": coordinate,
                    "direction_summary": "+" if coordinate >= 0 else "-",
                }
            )
        variables.sort(key=lambda item: abs(item["contribution"]), reverse=True)
        for rank, item in enumerate(variables, start=1):
            item["rank"] = rank

        categories: list[dict[str, Any]] = []
        if column_contributions is not None:
            for column in column_contributions.index:
                column_name = str(column)
                if column_name not in category_lookup:
                    continue
                contribution = _component_value(column_contributions, column, component)
                if contribution is None:
                    continue
                variable, level = category_lookup[column_name]
                coordinate = None
                categories.append(
                    {
                        "variable_name": variable,
                        "category_level": level,
                        "contribution": contribution,
                        "coordinate": coordinate,
                        "direction_summary": None,
                    }
                )
            categories.sort(key=lambda item: item["contribution"], reverse=True)
            for rank, item in enumerate(categories, start=1):
                item["rank"] = rank

        dimensions.append(
            {
                "dimension_id": dimension_id,
                "dimension_number": component + 1,
                "factor_id": f"F{component + 1}",
                "component_index": component,
                "eigenvalue": float(eigenvalues[component]) if component < len(eigenvalues) else None,
                "explained_variance": float(percentages[component]) if component < len(percentages) else None,
                "cumulative_variance": float(cumulative[component]) if component < len(cumulative) else None,
                "variable_contributions": variables,
                "category_contributions": categories[:max_contributions],
                "top_variables": variables[:8],
                "top_categories": categories[:max_contributions],
            }
        )

    problem_scores: list[dict[str, Any]] = []
    for row_position, index in enumerate(frame.index):
        problem_id = prepared.metadata.get("problem_ids", [])[row_position] if row_position < len(prepared.metadata.get("problem_ids", [])) else str(index)
        for component, dimension in enumerate(dimensions):
            try:
                coordinate = float(row_coordinates.loc[index].iloc[component])
            except Exception:
                coordinate = 0.0
            contribution = _component_value(row_contributions, index, component)
            problem_scores.append(
                {
                    "problem_id": problem_id,
                    "dimension_id": dimension["dimension_id"],
                    "coordinate": coordinate,
                    "contribution_metadata": {
                        "row_contribution": contribution,
                        "component_index": component,
                    },
                    "score_status": "OK",
                }
            )

    return FAMDResult(
        status="OK",
        error=None,
        library="prince",
        library_version=getattr(prince, "__version__", None),
        n_components=len(dimensions),
        eigenvalues=[float(value) for value in eigenvalues],
        percentage_of_variance=[float(value) for value in percentages],
        cumulative_percentage_of_variance=[float(value) for value in cumulative],
        total_inertia=total_inertia,
        dimensions=dimensions,
        problem_scores=problem_scores,
        diagnostics={
            "n_problems": int(frame.shape[0]),
            "n_features": int(frame.shape[1]),
            "n_categorical": len([spec for spec in specs if spec.kind == "categorical"]),
            "n_numeric": len([spec for spec in specs if spec.kind == "numeric"]),
            "requested_components": n_components,
            "fitted_components": len(dimensions),
            "total_inertia": total_inertia,
            "eigenvalues": [float(value) for value in eigenvalues],
            "percentage_of_variance": [float(value) for value in percentages],
            "cumulative_percentage_of_variance": [float(value) for value in cumulative],
            "variable_names": variable_names,
            "one_hot_columns": list(getattr(model, "one_hot_columns_", []) or []),
            "selector_note": "The number of retained dimensions is a modelling decision that requires analyst review.",
        },
    )


def _component_coordinate_map(dimension: dict[str, Any]) -> dict[str, float]:
    return {
        str(item["variable_name"]): float(item.get("coordinate") or 0.0)
        for item in dimension.get("variable_contributions", [])
    }


def _abs_cosine(first: dict[str, float], second: dict[str, float]) -> float:
    keys = sorted(set(first) & set(second))
    if not keys:
        return 0.0
    left = np.asarray([first[key] for key in keys], dtype=float)
    right = np.asarray([second[key] for key in keys], dtype=float)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator == 0:
        return 0.0
    return float(abs(np.dot(left, right) / denominator))


def bootstrap_stability(
    prepared: PreparedFrame,
    specs: list[FeatureSpec],
    original: FAMDResult,
    iterations: int,
    random_state: int = 42,
) -> dict[str, Any]:
    if iterations <= 0:
        return {
            "status": "NOT_RUN",
            "iterations": 0,
            "note": "Bootstrap stability is optional and disabled by configuration.",
        }
    if original.status != "OK" or not original.dimensions or prepared.frame.empty:
        return {"status": "NOT_RUN", "iterations": iterations, "note": "No fitted dimensions to resample."}

    rng = np.random.default_rng(random_state)
    row_count = len(prepared.frame)
    original_maps = [_component_coordinate_map(dimension) for dimension in original.dimensions]
    scores: list[list[float]] = [[] for _ in original.dimensions]
    successes = 0
    for _ in range(iterations):
        indices = rng.integers(0, row_count, size=row_count)
        sample = prepared.frame.iloc[indices].reset_index(drop=True)
        sampled = PreparedFrame(frame=sample, metadata={**prepared.metadata, "problem_ids": [str(index) for index in sample.index]})
        result = run_famd(
            sampled,
            specs,
            max_components=len(original.dimensions),
            random_state=random_state,
            max_contributions=len(specs),
        )
        if result.status != "OK":
            continue
        successes += 1
        for component, dimension in enumerate(result.dimensions):
            if component >= len(original_maps):
                break
            scores[component].append(_abs_cosine(original_maps[component], _component_coordinate_map(dimension)))

    components = []
    for component, values in enumerate(scores):
        if not values:
            components.append(
                {
                    "dimension_id": original.dimensions[component]["dimension_id"],
                    "mean_abs_cosine": None,
                    "min_abs_cosine": None,
                    "iterations": 0,
                }
            )
            continue
        components.append(
            {
                "dimension_id": original.dimensions[component]["dimension_id"],
                "mean_abs_cosine": float(np.mean(values)),
                "min_abs_cosine": float(np.min(values)),
                "iterations": len(values),
            }
        )
    return {
        "status": "RUN" if successes else "FAILED",
        "iterations": iterations,
        "successful_iterations": successes,
        "components": components,
        "note": (
            "Bootstrap stability compares variable-coordinate subspaces across resamples. "
            "High absolute cosine similarity suggests a repeatable pattern; it is not causal evidence."
        ),
    }
