"""Post-fit diagnostics that stay separate from the latent dimensions themselves."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

from .famd_runner import FAMDResult
from .feature_builder import FeatureRow


def _adaptive_threshold(values: list[float], minimum: float) -> float:
    if not values:
        return minimum
    return max(minimum, float(np.quantile(np.abs(values), 0.75)))


def build_memberships(
    result: FAMDResult,
    min_score: float = 1.0,
    margin_ratio: float = 0.25,
) -> list[dict[str, Any]]:
    by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_problem: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for score in result.problem_scores:
        by_dimension[score["dimension_id"]].append(score)
        by_problem[score["problem_id"]].append(score)

    thresholds = {
        dimension: _adaptive_threshold([float(item["coordinate"]) for item in scores], min_score)
        for dimension, scores in by_dimension.items()
    }

    memberships: list[dict[str, Any]] = []
    for problem_id, scores in by_problem.items():
        ordered = sorted(scores, key=lambda item: abs(float(item["coordinate"])), reverse=True)
        top = ordered[0] if ordered else None
        second = ordered[1] if len(ordered) > 1 else None
        top_abs = abs(float(top["coordinate"])) if top else 0.0
        second_abs = abs(float(second["coordinate"])) if second else 0.0
        margin = top_abs - second_abs
        ambiguous = bool(top and (margin < max(0.5, margin_ratio * top_abs)))

        for score in scores:
            coordinate_abs = abs(float(score["coordinate"]))
            threshold = thresholds[score["dimension_id"]]
            if coordinate_abs < min_score:
                continue
            membership_type = "high_score" if coordinate_abs >= threshold else "associated"
            memberships.append(
                {
                    "problem_id": problem_id,
                    "dimension_id": score["dimension_id"],
                    "membership_type": membership_type,
                    "score": float(score["coordinate"]),
                    "margin": margin,
                    "is_ambiguous": ambiguous,
                }
            )
    return memberships


def _mean(values: list[float | None]) -> float | None:
    observed = [float(value) for value in values if value is not None]
    return float(np.mean(observed)) if observed else None


def _sum(values: list[float | None]) -> float | None:
    observed = [float(value) for value in values if value is not None]
    return float(np.sum(observed)) if observed else None


def build_trends(
    memberships: list[dict[str, Any]],
    rows: list[FeatureRow],
    dimensions: list[dict[str, Any]],
    time_window: str,
) -> list[dict[str, Any]]:
    rows_by_problem = {row.problem_id: row for row in rows}
    members_by_dimension: dict[str, list[str]] = defaultdict(list)
    for membership in memberships:
        if membership["membership_type"] in {"high_score", "associated"}:
            members_by_dimension[membership["dimension_id"]].append(membership["problem_id"])

    trends: list[dict[str, Any]] = []
    for dimension in dimensions:
        dimension_id = dimension["dimension_id"]
        problem_ids = sorted(set(members_by_dimension.get(dimension_id, [])))
        member_rows = [rows_by_problem[problem_id] for problem_id in problem_ids if problem_id in rows_by_problem]
        metrics: list[tuple[str, float | None, float | None]] = [
            ("problem_count", float(len(member_rows)) if member_rows else None, float(len(rows))),
            (
                "evidence_volume_sum",
                _sum([row.raw_values.get("evidence_volume") for row in member_rows]),
                None,
            ),
            (
                "distinct_customers_sum",
                _sum([row.raw_values.get("distinct_customers") for row in member_rows]),
                None,
            ),
            (
                "evidence_per_problem_mean",
                _mean([row.raw_values.get("evidence_volume") for row in member_rows]),
                None,
            ),
            (
                "negative_share_mean",
                _mean([row.raw_values.get("negative_share") for row in member_rows]),
                None,
            ),
            (
                "high_effort_share_mean",
                _mean([row.raw_values.get("high_effort_share") for row in member_rows]),
                None,
            ),
            (
                "outcome_failure_share_mean",
                _mean([row.raw_values.get("outcome_failure_share") for row in member_rows]),
                None,
            ),
            (
                "negative_emotion_share_mean",
                _mean([row.raw_values.get("negative_emotion_share") for row in member_rows]),
                None,
            ),
        ]
        for metric_name, value, denominator in metrics:
            status = "OK" if value is not None else "INSUFFICIENT_DATA"
            trends.append(
                {
                    "dimension_id": dimension_id,
                    "time_window": time_window,
                    "metric_name": metric_name,
                    "metric_value": value,
                    "denominator": denominator,
                    "status": status,
                }
            )
    return trends


def stability_summary(result: FAMDResult) -> dict[str, Any]:
    cumulative = result.cumulative_percentage_of_variance
    first = float(cumulative[0]) if cumulative else None
    first_three = float(cumulative[min(2, len(cumulative) - 1)]) if cumulative else None
    return {
        "status": "NOT_RUN",
        "note": "Bootstrap stability is optional and disabled by configuration. Review contributions before publication.",
        "first_component_variance": first,
        "first_three_components_variance": first_three,
    }
