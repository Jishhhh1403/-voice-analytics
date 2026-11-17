from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import maximum_filter

from .context import WhitespaceContext
from .models import LensSignal, WhitespaceDataset
from .utils import kde_2d, minmax_scores, top_values

_GRID_SIZE = 100
_PAD_RATIO = 0.1
_VOID_RADIUS_RATIO = 0.25
_RESIDUAL_THRESHOLD = 0.25


def _finite_points(dataset: WhitespaceDataset) -> list[tuple[float, float]]:
    return [
        (float(problem.mds_x), float(problem.mds_y))
        for problem in dataset.canonical_problems
        if problem.mds_x is not None
        and problem.mds_y is not None
        and math.isfinite(float(problem.mds_x))
        and math.isfinite(float(problem.mds_y))
    ]


def _problem_attributes(problem: object) -> dict[str, object]:
    return {
        "journey_node_id": getattr(problem, "journey_node_id", None),
        "intents": set(getattr(problem, "top_intents", ())),
        "aspects": set(getattr(problem, "top_aspects", ())),
    }


def _attribute_distance(backlog: dict[str, object], problem: dict[str, object]) -> float:
    components: list[float] = []
    if backlog.get("journey_node_id") and problem.get("journey_node_id"):
        components.append(0.0 if backlog["journey_node_id"] == problem["journey_node_id"] else 1.0)
    for key in ("intents", "aspects"):
        left, right = backlog.get(key), problem.get(key)
        if isinstance(left, set) and isinstance(right, set) and left and right:
            components.append(0.0 if left & right else 1.0)
    return sum(components) / len(components) if components else 0.0


def project_backlog_to_mds(dataset: WhitespaceDataset) -> list[tuple[float, float]]:
    problems = [
        problem
        for problem in dataset.canonical_problems
        if problem.mds_x is not None
        and problem.mds_y is not None
        and math.isfinite(float(problem.mds_x))
        and math.isfinite(float(problem.mds_y))
    ]
    if len(problems) < 3 or not dataset.backlog_profiles:
        return []
    coordinates = [(float(problem.mds_x), float(problem.mds_y)) for problem in problems]
    problem_attributes = [_problem_attributes(problem) for problem in problems]
    projected: list[tuple[float, float]] = []
    for backlog in dataset.backlog_profiles:
        backlog_attributes = {
            "journey_node_id": backlog.journey_node_id,
            "intents": set(backlog.profiled_intents),
            "aspects": set(backlog.profiled_aspects),
        }
        distances = [
            (_attribute_distance(backlog_attributes, attributes), index)
            for index, attributes in enumerate(problem_attributes)
        ]
        nearest = sorted(distances, key=lambda item: (item[0], item[1]))[: min(5, len(distances))]
        weights = [1.0 / (distance + 1e-6) for distance, _ in nearest]
        total = sum(weights)
        if total <= 0:
            weights = [1.0 for _ in nearest]
            total = float(len(weights))
        x = sum(weight * coordinates[index][0] for weight, (_, index) in zip(weights, nearest, strict=True)) / total
        y = sum(weight * coordinates[index][1] for weight, (_, index) in zip(weights, nearest, strict=True)) / total
        projected.append((x, y))
    return projected


def detect_spatial_voids(dataset: WhitespaceDataset, context: WhitespaceContext) -> list[LensSignal]:
    points = _finite_points(dataset)
    if len(points) < 3:
        return []
    finite_problems = [
        problem
        for problem in dataset.canonical_problems
        if problem.mds_x is not None
        and problem.mds_y is not None
        and math.isfinite(float(problem.mds_x))
        and math.isfinite(float(problem.mds_y))
    ]
    xs = np.asarray([point[0] for point in points], dtype=float)
    ys = np.asarray([point[1] for point in points], dtype=float)
    x_span, y_span = float(xs.max() - xs.min()), float(ys.max() - ys.min())
    if x_span <= 0 or y_span <= 0:
        return []
    x_pad, y_pad = x_span * _PAD_RATIO, y_span * _PAD_RATIO
    bounds = (float(xs.min()) - x_pad, float(xs.max()) + x_pad, float(ys.min()) - y_pad, float(ys.max()) + y_pad)
    rng = np.random.default_rng(42)
    jitter_x = rng.uniform(-1e-5, 1e-5, len(points)) * x_span
    jitter_y = rng.uniform(-1e-5, 1e-5, len(points)) * y_span
    pain_weights = [
        max(0.0, float(problem.priority_score) * float(problem.mean_effort_score)) for problem in finite_problems
    ]
    pain = kde_2d(xs + jitter_x, ys + jitter_y, pain_weights, (_GRID_SIZE, _GRID_SIZE), bounds)
    backlog_points = project_backlog_to_mds(dataset)
    if len(backlog_points) >= 2:
        backlog = kde_2d(
            [point[0] for point in backlog_points],
            [point[1] for point in backlog_points],
            [1.0 for _ in backlog_points],
            (_GRID_SIZE, _GRID_SIZE),
            bounds,
        )
        residual = np.maximum(0.0, pain - 0.85 * backlog)
    else:
        residual = np.maximum(0.0, pain)
    peaks = maximum_filter(residual, size=5)
    mask = (residual >= peaks) & (residual > _RESIDUAL_THRESHOLD)
    y_indices, x_indices = np.nonzero(mask)
    candidates = sorted(
        ((float(residual[y, x]), int(x), int(y)) for x, y in zip(x_indices, y_indices, strict=True)),
        key=lambda item: (-item[0], item[2], item[1]),
    )
    x_bins = np.linspace(bounds[0], bounds[1], _GRID_SIZE)
    y_bins = np.linspace(bounds[2], bounds[3], _GRID_SIZE)
    void_radius = 0.25 * max(x_span, y_span)
    signals: list[LensSignal] = []
    for value, x_index, y_index in candidates[:25]:
        center_x = float(x_bins[x_index])
        center_y = float(y_bins[y_index])
        if any(math.hypot(center_x - bx, center_y - by) <= void_radius for bx, by in backlog_points):
            continue
        captured_indexes = [
            index
            for index, (px, py) in enumerate(points)
            if math.hypot(center_x - float(px), center_y - float(py)) <= void_radius
        ]
        feedback_ids = tuple(
            sorted(
                {
                    feedback_id
                    for index in captured_indexes
                    for feedback_id in finite_problems[index].supporting_feedback_ids
                }
            )
        )
        if len(feedback_ids) < 5:
            continue
        nearest_index = min(
            captured_indexes or range(len(points)),
            key=lambda index: math.hypot(center_x - float(points[index][0]), center_y - float(points[index][1])),
        )
        nearest = finite_problems[nearest_index]
        intents = [intent for index in captured_indexes for intent in finite_problems[index].top_intents]
        aspects = [aspect for index in captured_indexes for aspect in finite_problems[index].top_aspects]
        signals.append(
            LensSignal(
                lens_name="SPATIAL_VOID",
                journey_node_id=nearest.journey_node_id,
                intent=top_values(intents, 1)[0] if intents else None,
                aspect=top_values(aspects, 1)[0] if aspects else None,
                normalized_score=0.0,
                supporting_feedback_ids=feedback_ids,
                metadata={
                    "raw_score": value,
                    "x": center_x,
                    "y": center_y,
                    "radius": void_radius,
                    "captured_feedback_count": len(feedback_ids),
                    "captured_problem_count": len(captured_indexes),
                    "residual": value,
                    "backlog_projected_count": len(backlog_points),
                    "max_alignment": context.max_alignment(feedback_ids),
                },
            )
        )
    if not signals:
        return []
    scores = minmax_scores([float(signal.metadata["raw_score"]) for signal in signals])
    return [
        LensSignal(
            lens_name=signal.lens_name,
            journey_node_id=signal.journey_node_id,
            intent=signal.intent,
            aspect=signal.aspect,
            normalized_score=score,
            supporting_feedback_ids=signal.supporting_feedback_ids,
            metadata=signal.metadata,
        )
        for signal, score in zip(signals, scores, strict=True)
    ]


def analyze_spatial(dataset: WhitespaceDataset, context: WhitespaceContext) -> list[LensSignal]:
    return detect_spatial_voids(dataset, context)
