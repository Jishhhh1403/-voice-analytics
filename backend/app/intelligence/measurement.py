"""Measurement engine: explicit windows, units, status and provenance.

No metric is ever returned without a status. When a source has no coverage the
status is ``NO_DATA`` / ``INSUFFICIENT_DATA`` rather than zero, so consumers can
distinguish a true zero from a missing signal.

Every core metric is calculated for four explicit windows:

- lifetime
- the configured measurement window (90 days by default)
- the current trend window (30 days by default)
- the previous trend window (30 days by default)

Canonical metric names (for example ``evidence_volume``) are aliases of the
configured measurement window. Window-suffixed names are also persisted so a
consumer never has to infer a window from metadata alone.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .contracts import CleanFeedback, ExtractedInsight, ProblemDraft

CORE_METRICS = (
    "evidence_volume",
    "distinct_customers",
    "negative_share",
    "repeat_complaint_count",
    "source_diversity",
)


@dataclass
class MeasurementResult:
    metrics: list[dict[str, Any]] = field(default_factory=list)
    daily: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    baseline_start: datetime | None = None
    current_start: datetime | None = None


@dataclass(frozen=True)
class _Window:
    key: str
    suffix: str
    start: datetime | None
    end: datetime
    days: int | None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _metric(
    problem_id: str,
    name: str,
    value: float | None,
    unit: str,
    status: str,
    *,
    window_start: datetime,
    window_end: datetime,
    input_count: int,
    sources: str = "available",
    quality: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "problem_id": problem_id,
        "metric_name": name,
        "metric_value": None if value is None else round(float(value), 4),
        "unit": unit,
        "status": status,
        "calculation_method": "deterministic_window_aggregation",
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "input_record_count": input_count,
        "source_availability": sources,
        "quality_indicator": quality,
        "metadata": metadata or {},
    }


def _window_specs(now: datetime, window_days: int, baseline_days: int, current_days: int) -> list[_Window]:
    current_start = now - timedelta(days=current_days)
    return [
        _Window("lifetime", "_lifetime", None, now, None),
        _Window(f"{window_days}d", f"_{window_days}d", now - timedelta(days=window_days), now, window_days),
        _Window(f"current_{current_days}d", f"_{current_days}d", current_start, now, current_days),
        _Window(
            f"previous_{baseline_days}d",
            f"_previous_{baseline_days}d",
            current_start - timedelta(days=baseline_days),
            current_start,
            baseline_days,
        ),
    ]


def _coverage(window: _Window, data_start: datetime | None, data_end: datetime | None) -> str:
    if window.start is None:
        return "full" if data_start is not None else "none"
    if data_start is None or data_end is None:
        return "none"
    if data_end < window.start or data_start >= window.end:
        return "outside"
    if data_start > window.start:
        return "partial"
    return "full"


def _availability(coverage: str) -> str:
    return {"none": "none", "outside": "none", "partial": "partial", "full": "available"}.get(coverage, "available")


def _window_status(coverage: str) -> str:
    if coverage in {"none", "outside"}:
        return "NO_DATA"
    if coverage == "partial":
        return "PARTIAL"
    return "OK"


def _in_window(value: datetime, window: _Window) -> bool:
    if window.start is None:
        return True
    return window.start <= value < window.end


def _selected(entries: list[tuple[ExtractedInsight, CleanFeedback, datetime | None]], window: _Window) -> list[tuple[ExtractedInsight, CleanFeedback, datetime | None]]:
    if window.start is None:
        return entries
    return [entry for entry in entries if entry[2] is not None and _in_window(entry[2], window)]


def _core_metrics(
    problem_id: str,
    selected: list[tuple[ExtractedInsight, CleanFeedback, datetime | None]],
    *,
    window: _Window,
    window_start: datetime,
    window_end: datetime,
    base_status: str,
    coverage: str,
    data_start: datetime | None,
    data_end: datetime | None,
    dated_records: int,
    duplicate_links: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    total = len(selected)
    customers = {record.synthetic_customer_ref for _, record, _ in selected if record.synthetic_customer_ref}
    missing_customers = sum(1 for _, record, _ in selected if not record.synthetic_customer_ref)
    negative = sum(1 for insight, _, _ in selected if insight.sentiment in {"negative", "mixed"})
    source_types = {record.source_type for _, record, _ in selected}
    record_ids = {record.feedback_id for _, record, _ in selected}
    repeat_by_feedback: Counter[str] = Counter()
    for link in duplicate_links or []:
        if link.get("duplicate_type") == "repeat" and link.get("feedback_id"):
            repeat_by_feedback[str(link["feedback_id"])] += 1
    repeat_total = sum(repeat_by_feedback.get(feedback_id, 0) for feedback_id in record_ids)

    metadata = {
        "window_type": window.key,
        "window_days": window.days,
        "window_coverage": coverage,
        "data_start": data_start.isoformat() if data_start else None,
        "data_end": data_end.isoformat() if data_end else None,
        "dated_records_in_window": dated_records if window.start else total - sum(1 for _, _, when in selected if when is None),
        "records_in_window": total,
        "undated_records_in_window": sum(1 for _, _, when in selected if when is None),
        "missing_customer_refs": missing_customers,
    }
    quality = (len([entry for entry in selected if entry[2] is not None]) / total) if total else None
    sources = _availability(coverage)

    metrics: list[dict[str, Any]] = []
    volume_status = base_status
    metrics.append(
        _metric(
            problem_id,
            "evidence_volume",
            total if base_status != "NO_DATA" else None,
            "records",
            volume_status,
            window_start=window_start,
            window_end=window_end,
            input_count=total,
            sources=sources,
            quality=quality,
            metadata=metadata,
        )
    )

    if base_status == "NO_DATA":
        customer_value, customer_status = None, "NO_DATA"
    elif not customers:
        customer_value, customer_status = None, "INSUFFICIENT_DATA"
    else:
        customer_value, customer_status = len(customers), base_status
    metrics.append(
        _metric(
            problem_id,
            "distinct_customers",
            customer_value,
            "customers",
            customer_status,
            window_start=window_start,
            window_end=window_end,
            input_count=total,
            sources=sources,
            quality=quality,
            metadata=metadata,
        )
    )

    if base_status == "NO_DATA":
        negative_value, negative_status = None, "NO_DATA"
    elif total == 0:
        negative_value, negative_status = None, "INSUFFICIENT_DATA"
    else:
        negative_value, negative_status = negative / total, base_status
    metrics.append(
        _metric(
            problem_id,
            "negative_share",
            negative_value,
            "ratio",
            negative_status,
            window_start=window_start,
            window_end=window_end,
            input_count=total,
            sources=sources,
            quality=quality,
            metadata={**metadata, "negative_records": negative},
        )
    )

    if base_status == "NO_DATA":
        repeat_value, repeat_status = None, "NO_DATA"
    elif duplicate_links is None:
        repeat_value, repeat_status = None, "INSUFFICIENT_DATA"
    else:
        repeat_value, repeat_status = repeat_total, base_status
    metrics.append(
        _metric(
            problem_id,
            "repeat_complaint_count",
            repeat_value,
            "links",
            repeat_status,
            window_start=window_start,
            window_end=window_end,
            input_count=total,
            sources=sources,
            quality=quality,
            metadata={**metadata, "repeat_links_available": duplicate_links is not None},
        )
    )

    diversity_value = len(source_types) if base_status != "NO_DATA" else None
    metrics.append(
        _metric(
            problem_id,
            "source_diversity",
            diversity_value,
            "source_types",
            base_status,
            window_start=window_start,
            window_end=window_end,
            input_count=total,
            sources=sources,
            quality=quality,
            metadata={**metadata, "source_types": sorted(source_types)},
        )
    )
    return metrics


def _growth_metric(
    problem_id: str,
    name: str,
    value: float | None,
    unit: str,
    status: str,
    *,
    window_start: datetime,
    window_end: datetime,
    input_count: int,
    current: float | None,
    previous: float | None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _metric(
        problem_id,
        name,
        value,
        unit,
        status,
        window_start=window_start,
        window_end=window_end,
        input_count=input_count,
        sources="available" if status in {"OK", "INSUFFICIENT_DATA"} else "none",
        metadata={"current_window_value": current, "previous_window_value": previous, **(metadata or {})},
    )


def _trend_status(current: str, previous: str) -> str:
    if current == "NO_DATA" and previous == "NO_DATA":
        return "NO_DATA"
    if current != "OK" or previous != "OK":
        return "INSUFFICIENT_DATA"
    return "OK"


def measure_problems(
    problems: Iterable[ProblemDraft],
    evidence: dict[str, list[tuple[ExtractedInsight, CleanFeedback]]],
    window_days: int = 90,
    baseline_days: int = 30,
    current_days: int = 30,
    duplicate_links: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> MeasurementResult:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    windows = _window_specs(now, window_days, baseline_days, current_days)
    measurement_window = windows[1]
    current_window = windows[2]
    previous_window = windows[3]
    baseline_start = previous_window.start or current_window.start or now
    result = MeasurementResult(
        window_start=measurement_window.start,
        window_end=measurement_window.end,
        baseline_start=baseline_start,
        current_start=current_window.start,
    )

    daily_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for problem in problems:
        members = evidence.get(problem.problem_id, [])
        entries = [(insight, record, _parse(record.submitted_at)) for insight, record in members]
        dated_entries = [entry for entry in entries if entry[2] is not None]
        data_start = min((entry[2] for entry in dated_entries if entry[2] is not None), default=None)
        data_end = max((entry[2] for entry in dated_entries if entry[2] is not None), default=None)

        for insight, _record, when in entries:
            if when is None:
                continue
            day = when.date().isoformat()
            daily_counts[(problem.problem_id, day)]["feedback_count"] += 1
            if insight.sentiment in {"negative", "mixed"}:
                daily_counts[(problem.problem_id, day)]["negative_count"] += 1

        by_suffix: dict[str, list[dict[str, Any]]] = {}
        summaries: dict[str, dict[str, Any]] = {}
        for window in windows:
            selected = _selected(entries, window)
            coverage = _coverage(window, data_start, data_end)
            base_status = "OK" if window.start is None and entries else _window_status(coverage)
            window_start = window.start or data_start or now
            metrics = _core_metrics(
                problem.problem_id,
                selected,
                window=window,
                window_start=window_start,
                window_end=window.end,
                base_status=base_status,
                coverage=coverage,
                data_start=data_start,
                data_end=data_end,
                dated_records=len([entry for entry in selected if entry[2] is not None]),
                duplicate_links=duplicate_links,
            )
            for metric in metrics:
                metric["metric_name"] = f"{metric['metric_name']}{window.suffix}"
            by_suffix[window.suffix] = metrics
            summaries[window.key] = {
                "status": base_status,
                "metrics": {item["metric_name"].removesuffix(window.suffix): item for item in metrics},
                "selected": selected,
            }

        snapshots = [metric for metrics in by_suffix.values() for metric in metrics]
        # Keep canonical names as aliases of the configured measurement window.
        for metric in by_suffix[measurement_window.suffix]:
            alias = dict(metric)
            alias["metric_name"] = metric["metric_name"].removesuffix(measurement_window.suffix)
            alias["metadata"] = {**metric["metadata"], "alias_of": metric["metric_name"]}
            snapshots.append(alias)

        current = summaries[current_window.key]
        previous = summaries[previous_window.key]
        current_metrics = current["metrics"]
        previous_metrics = previous["metrics"]
        growth_window_start = previous_window.start or current_window.start or now
        input_count = len(current["selected"]) + len(previous["selected"])
        trend_status = _trend_status(current["status"], previous["status"])

        volume_current = current_metrics["evidence_volume"]["metric_value"]
        volume_previous = previous_metrics["evidence_volume"]["metric_value"]
        volume_abs = (
            float(volume_current) - float(volume_previous)
            if trend_status == "OK" and volume_current is not None and volume_previous is not None
            else None
        )
        volume_pct_status = trend_status
        volume_pct = None
        if trend_status == "OK" and volume_previous not in {None, 0} and volume_current is not None:
            volume_pct = (float(volume_current) - float(volume_previous)) / float(volume_previous)
        elif trend_status == "OK":
            volume_pct_status = "INSUFFICIENT_DATA"
        snapshots.append(
            _growth_metric(
                problem.problem_id,
                "volume_growth_abs",
                volume_abs,
                "records",
                trend_status,
                window_start=growth_window_start,
                window_end=now,
                input_count=input_count,
                current=volume_current,
                previous=volume_previous,
                metadata={"window_type": "volume_growth", "baseline_days": baseline_days, "current_days": current_days},
            )
        )
        snapshots.append(
            _growth_metric(
                problem.problem_id,
                "volume_growth_pct",
                volume_pct,
                "ratio",
                volume_pct_status,
                window_start=growth_window_start,
                window_end=now,
                input_count=input_count,
                current=volume_current,
                previous=volume_previous,
                metadata={"window_type": "volume_growth", "baseline_days": baseline_days, "current_days": current_days},
            )
        )
        snapshots.append(
            _growth_metric(
                problem.problem_id,
                "assessment_velocity_delta",
                volume_abs,
                "records",
                trend_status,
                window_start=growth_window_start,
                window_end=now,
                input_count=input_count,
                current=volume_current,
                previous=volume_previous,
                metadata={
                    "window_type": "volume_growth",
                    "baseline_days": baseline_days,
                    "current_days": current_days,
                    "alias_of": "volume_growth_abs",
                },
            )
        )

        customers_current = current_metrics["distinct_customers"]["metric_value"]
        customers_previous = previous_metrics["distinct_customers"]["metric_value"]
        customer_abs = (
            float(customers_current) - float(customers_previous)
            if trend_status == "OK" and customers_current is not None and customers_previous is not None
            else None
        )
        customer_pct_status = trend_status
        customer_pct = None
        if trend_status == "OK" and customers_previous not in {None, 0} and customers_current is not None:
            customer_pct = (float(customers_current) - float(customers_previous)) / float(customers_previous)
        elif trend_status == "OK":
            customer_pct_status = "INSUFFICIENT_DATA"
        snapshots.append(
            _growth_metric(
                problem.problem_id,
                "customer_growth_abs",
                customer_abs,
                "customers",
                trend_status,
                window_start=growth_window_start,
                window_end=now,
                input_count=input_count,
                current=customers_current,
                previous=customers_previous,
                metadata={"window_type": "customer_growth"},
            )
        )
        snapshots.append(
            _growth_metric(
                problem.problem_id,
                "customer_growth_pct",
                customer_pct,
                "ratio",
                customer_pct_status,
                window_start=growth_window_start,
                window_end=now,
                input_count=input_count,
                current=customers_current,
                previous=customers_previous,
                metadata={"window_type": "customer_growth"},
            )
        )

        negative_current = current_metrics["negative_share"]["metric_value"]
        negative_previous = previous_metrics["negative_share"]["metric_value"]
        negative_change_status = trend_status
        negative_change = None
        if trend_status == "OK" and negative_current is not None and negative_previous is not None:
            negative_change = float(negative_current) - float(negative_previous)
        elif trend_status == "OK":
            negative_change_status = "INSUFFICIENT_DATA"
        snapshots.append(
            _growth_metric(
                problem.problem_id,
                "negative_share_change",
                negative_change,
                "ratio",
                negative_change_status,
                window_start=growth_window_start,
                window_end=now,
                input_count=input_count,
                current=negative_current,
                previous=negative_previous,
                metadata={"window_type": "negative_share_change"},
            )
        )

        result.snapshots.extend(snapshots)

    result.metrics = result.snapshots
    for (problem_id, day), counts in sorted(daily_counts.items()):
        for metric_name, value in counts.items():
            result.daily.append(
                {
                    "problem_id": problem_id,
                    "day": day,
                    "metric_name": metric_name,
                    "metric_value": float(value),
                    "unit": "records",
                    "status": "OK",
                }
            )
    return result


def measurement_inputs(result: MeasurementResult) -> dict[str, dict[str, Any]]:
    """Index canonical snapshots by problem for the prioritisation engine."""
    indexed: dict[str, dict[str, Any]] = defaultdict(dict)
    for snapshot in result.snapshots:
        indexed[snapshot["problem_id"]][snapshot["metric_name"]] = snapshot
    return dict(indexed)
