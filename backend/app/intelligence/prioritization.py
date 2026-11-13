"""Problem prioritisation engine.

The score is a transparent weighted sum of five components. Every component is
returned alongside the total, and missing inputs are reported explicitly. MDS
is never used as a severity measure and churn is never inferred from sentiment.

Risk terms are *indicators*, not verified incidents. The score keeps the
indicator score separate from verification state and never claims that a risk
was confirmed without an explicit verification source.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..config import Settings
from .contracts import CleanFeedback, ExtractedInsight, ProblemDraft

RISK_TERMS = {
    "unauthorized": 1.0,
    "fraud": 1.0,
    "money deducted": 1.0,
    "debited": 0.9,
    "security": 0.9,
    "locked": 0.7,
    "blocked": 0.7,
    "kyc": 0.7,
    "regulatory": 0.8,
    "duplicate payment": 0.8,
    "payment failed": 0.7,
    "failed transfer": 0.7,
}

MODULE_STRATEGIC_WEIGHT = {
    "payments": 0.95,
    "accounts": 0.85,
    "onboarding": 0.85,
    "cards": 0.8,
    "authentication": 0.9,
    "loans": 0.8,
    "deposits": 0.7,
    "support": 0.7,
    "notifications": 0.6,
    "navigation": 0.55,
}

CORE_MEASUREMENT_METRICS = (
    "evidence_volume",
    "distinct_customers",
    "negative_share",
    "repeat_complaint_count",
    "source_diversity",
)


@dataclass
class PriorityResult:
    scores: list[dict[str, Any]]
    weights: dict[str, float]
    missing: dict[str, list[str]]


def _log_scale(value: float, cap: float) -> float:
    if cap <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(max(0.0, value)) / math.log1p(cap)))


def _evidence_text(members: list[tuple[ExtractedInsight, CleanFeedback]]) -> str:
    return " ".join(
        filter(
            None,
            [
                " ".join(item.reported_problem or "" for item, _ in members),
                " ".join(item.reported_symptom or "" for item, _ in members),
                " ".join(record.feedback_text_redacted for _, record in members),
            ],
        )
    ).lower()


def _module_for(node_id: str | None) -> str | None:
    return node_id.split(".")[0] if node_id else None


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else value


def _metric_value(metrics: dict[str, Any], name: str) -> tuple[float | None, str]:
    metric = metrics.get(name) or {}
    status = str(metric.get("status") or "NO_DATA")
    value = metric.get("metric_value")
    if status in {"OK", "PARTIAL"} and value is not None:
        return float(value), status
    return None, status


def _risk_indicators(text: str) -> list[dict[str, Any]]:
    return [
        {"term": term, "weight": weight}
        for term, weight in sorted(RISK_TERMS.items(), key=lambda item: (-item[1], item[0]))
        if term in text
    ]


def _window_metadata(metrics: dict[str, Any], name: str = "evidence_volume") -> dict[str, Any]:
    metric = metrics.get(name) or {}
    return {
        "window_start": metric.get("window_start"),
        "window_end": metric.get("window_end"),
        "window_status": metric.get("status"),
        "window_coverage": (metric.get("metadata") or {}).get("window_coverage"),
    }


def prioritise_problems(
    settings: Settings,
    problems: Iterable[ProblemDraft],
    evidence: dict[str, list[tuple[ExtractedInsight, CleanFeedback]]],
    measurements: dict[str, dict[str, Any]],
    duplicate_links: list[dict[str, Any]] | None = None,
    measurement_window_start: datetime | str | None = None,
    measurement_window_end: datetime | str | None = None,
) -> PriorityResult:
    weights = {
        "customer_impact": settings.priority_weight_customer_impact,
        "business_risk": settings.priority_weight_business_risk,
        "operational_impact": settings.priority_weight_operational_impact,
        "trend": settings.priority_weight_trend,
        "strategic": settings.priority_weight_strategic,
    }
    weight_total = sum(weights.values()) or 1.0
    weights = {name: value / weight_total for name, value in weights.items()}

    rows: list[dict[str, Any]] = []
    missing: dict[str, list[str]] = {}
    for problem in problems:
        members = evidence.get(problem.problem_id, [])
        metrics = measurements.get(problem.problem_id, {})
        missing_metrics: list[str] = []
        measurement_status = {
            name: str((metrics.get(name) or {}).get("status") or "NO_DATA") for name in CORE_MEASUREMENT_METRICS
        }

        volume, _ = _metric_value(metrics, "evidence_volume")
        customers_value, _ = _metric_value(metrics, "distinct_customers")
        negative_share, _ = _metric_value(metrics, "negative_share")
        repeat, _ = _metric_value(metrics, "repeat_complaint_count")
        source_count, _ = _metric_value(metrics, "source_diversity")

        for name, value in (
            ("evidence_volume", volume),
            ("distinct_customers", customers_value),
            ("negative_share", negative_share),
            ("repeat_complaint_count", repeat),
            ("source_diversity", source_count),
        ):
            if value is None:
                missing_metrics.append(name)

        customer_impact = 0.0
        if customers_value is not None:
            customer_impact += 0.55 * _log_scale(customers_value, 200)
        if negative_share is not None:
            customer_impact += 0.30 * negative_share
        if repeat is not None:
            customer_impact += 0.15 * min(1.0, repeat / max(1.0, volume or 1.0))

        text = _evidence_text(members)
        indicators = _risk_indicators(text)
        risk_hits = sum(float(item["weight"]) for item in indicators)
        business_risk = min(1.0, risk_hits / 3.0 + (0.35 * negative_share if negative_share is not None else 0.0))
        verified_risk = {
            "status": "NOT_VERIFIED",
            "verified_by": None,
            "source": None,
            "verified_score": None,
        }

        operational_impact = 0.0
        if volume is not None:
            operational_impact += 0.6 * _log_scale(volume, 500)
        if source_count is not None:
            operational_impact += 0.2 * _log_scale(source_count, 5)
        if customers_value is not None:
            operational_impact += 0.2 * (1.0 if customers_value >= 3 else 0.0)

        trend_value, _ = _metric_value(metrics, "volume_growth_abs")
        if trend_value is None:
            trend_value, _ = _metric_value(metrics, "assessment_velocity_delta")
        if trend_value is None:
            missing_metrics.append("volume_growth_abs")
            trend_score = 0.0
        else:
            trend_score = max(0.0, min(1.0, 0.5 + trend_value / 40.0))

        module = _module_for(problem.journey_node_id)
        strategic = MODULE_STRATEGIC_WEIGHT.get(module or "", 0.5)
        if not module:
            missing_metrics.append("journey_node_id")

        components = {
            "customer_impact": round(min(1.0, customer_impact), 4),
            "business_risk": round(business_risk, 4),
            "operational_impact": round(min(1.0, operational_impact), 4),
            "trend": round(trend_score, 4),
            "strategic": round(strategic, 4),
        }
        priority_score = round(sum(weights[name] * components[name] for name in weights), 4)
        available_components = sum(
            1
            for name, value in (
                ("customer_impact", customers_value if customers_value is not None or negative_share is not None else None),
                ("business_risk", business_risk if indicators or negative_share is not None else None),
                ("operational_impact", volume if volume is not None else None),
                ("trend", trend_value),
                ("strategic", strategic if module else None),
            )
            if value is not None
        )
        data_completeness = round(available_components / len(weights), 4)

        escalation_reasons: list[str] = []
        if components["business_risk"] >= settings.priority_escalation_risk_threshold:
            escalation_reasons.append("business_risk_indicator_above_threshold")
        if components["trend"] >= 0.8 and components["customer_impact"] >= 0.5:
            escalation_reasons.append("rising_customer_impact")
        escalation = "ESCALATE" if escalation_reasons else ("WATCH" if priority_score >= 0.6 else "NORMAL")

        window = _window_metadata(metrics)
        rows.append(
            {
                "problem_id": problem.problem_id,
                "title": problem.title,
                "priority_score": priority_score,
                **{f"{name}_score": value for name, value in components.items()},
                "escalation_status": escalation,
                "escalation_reasons": escalation_reasons,
                "missing_metrics": sorted(set(missing_metrics)),
                "supporting_evidence": {
                    "evidence_count": volume,
                    "distinct_customers": customers_value,
                    "negative_share": negative_share,
                    "repeat_complaints": repeat,
                    "source_count": source_count,
                    "journey_node_id": problem.journey_node_id,
                    "measurement_status": measurement_status,
                    "measurement_windows": {
                        "evidence_volume": window,
                        "window_start": _iso(measurement_window_start) or window.get("window_start"),
                        "window_end": _iso(measurement_window_end) or window.get("window_end"),
                    },
                    "risk_indicators": indicators,
                    "risk_indicator_score": round(business_risk, 4),
                    "verified_risk": verified_risk,
                    "data_completeness": data_completeness,
                },
                "component_weights": weights,
                "methodology_version": settings.scoring_methodology_version,
                "measurement_window_start": _iso(measurement_window_start) or window.get("window_start"),
                "measurement_window_end": _iso(measurement_window_end) or window.get("window_end"),
            }
        )
        missing[problem.problem_id] = sorted(set(missing_metrics))

    rows.sort(
        key=lambda item: (
            item["priority_score"],
            item["supporting_evidence"].get("evidence_count") or 0,
            item["supporting_evidence"].get("data_completeness") or 0,
        ),
        reverse=True,
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return PriorityResult(scores=rows, weights=weights, missing=missing)
