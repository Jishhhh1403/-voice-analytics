"""Build a typed, versioned canonical-problem feature matrix.

The builder reads persisted backend fields only. UI display values, raw
feedback text, identifiers, MDS coordinates and priority scores are never
active features.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from ...db import Database


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    label: str
    kind: str
    source: str
    description: str
    transform: str = "none"
    missing_policy: str = ""
    role: str = "active"


@dataclass
class FeatureRow:
    problem_id: str
    values: dict[str, Any]
    raw_values: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    denominators: dict[str, float | None] = field(default_factory=dict)
    sources: dict[str, str | None] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class FeatureBuildResult:
    feedback_run_id: str
    as_of_date: str
    window_start: str | None
    window_end: str | None
    feature_schema_version: str
    rows: list[FeatureRow]
    specs: list[FeatureSpec] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def feature_dictionary(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "label": spec.label,
                "type": spec.kind,
                "source": spec.source,
                "description": spec.description,
                "transform": spec.transform,
                "role": spec.role,
                "missing_policy": spec.missing_policy
                or (
                    "Preserved as missing in the snapshot; filled with an explicit __MISSING__ "
                    "level for model fitting only."
                    if spec.kind == "categorical"
                    else "Preserved as missing in the snapshot; median-imputed for model fitting only."
                ),
            }
            for spec in self.specs
        ]


FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        "journey_module",
        "Journey module",
        "categorical",
        "customer_problems.journey_node_id / problem_journey_mappings.module_id",
        "Top-level banking journey module.",
    ),
    FeatureSpec(
        "journey_feature",
        "Journey feature",
        "categorical",
        "problem_journey_mappings.feature_id / journey_node_id",
        "Most specific mapped journey feature or stage.",
    ),
    FeatureSpec(
        "journey_stage",
        "Journey stage",
        "categorical",
        "problem_journey_mappings.journey_stage_id",
        "Mapped journey stage where available; unavailable stages remain missing.",
    ),
    FeatureSpec(
        "aspect",
        "Problem aspect",
        "categorical",
        "customer_problems.aspect",
        "Canonical problem aspect.",
    ),
    FeatureSpec(
        "symptom_category",
        "Symptom category",
        "categorical",
        "customer_problems.symptom_category",
        "Canonical symptom family.",
    ),
    FeatureSpec(
        "customer_intent",
        "Customer intent",
        "categorical",
        "customer_problems.customer_intent",
        "Intent associated with the canonical problem.",
    ),
    FeatureSpec(
        "evidence_volume",
        "Evidence volume (log)",
        "numeric",
        "problem_measurement_snapshots.evidence_volume",
        "Windowed linked evidence count, log1p transformed.",
        "log1p",
    ),
    FeatureSpec(
        "distinct_customers",
        "Distinct customers (log)",
        "numeric",
        "problem_measurement_snapshots.distinct_customers",
        "Windowed distinct customers, log1p transformed.",
        "log1p",
    ),
    FeatureSpec(
        "negative_share",
        "Negative share",
        "numeric",
        "problem_measurement_snapshots.negative_share",
        "Share of windowed evidence with negative or mixed sentiment.",
    ),
    FeatureSpec(
        "repeat_complaint_rate",
        "Repeat complaint rate",
        "numeric",
        "problem_measurement_snapshots.repeat_complaint_count / evidence_volume",
        "Repeat complaint links divided by windowed evidence volume.",
    ),
    FeatureSpec(
        "source_diversity",
        "Source diversity",
        "numeric",
        "problem_measurement_snapshots.source_diversity",
        "Number of distinct feedback source types in the measurement window.",
    ),
    FeatureSpec(
        "high_effort_share",
        "High-effort share",
        "numeric",
        "problem_evidence + extracted_insights.customer_effort",
        "Share of windowed evidence where customer effort is high.",
    ),
    FeatureSpec(
        "outcome_failure_share",
        "Task failure share",
        "numeric",
        "problem_evidence + extracted_insights.reported_outcome",
        "Share of windowed evidence with failed, blocked or abandoned outcome.",
    ),
    FeatureSpec(
        "negative_emotion_share",
        "Negative emotion share",
        "numeric",
        "problem_evidence + extracted_insights.emotion",
        "Share of windowed evidence with frustration, confusion, anxiety or disappointment.",
    ),
    FeatureSpec(
        "volume_growth_pct",
        "Volume growth",
        "numeric",
        "problem_measurement_snapshots.volume_growth_pct",
        "Window-over-window evidence growth, winsorized.",
        "winsorize",
    ),
    FeatureSpec(
        "negative_share_change",
        "Negative share change",
        "numeric",
        "problem_measurement_snapshots.negative_share_change",
        "Change in negative share versus the previous window, winsorized.",
        "winsorize",
    ),
    FeatureSpec(
        "assessment_velocity_delta",
        "Assessment velocity change",
        "numeric",
        "problem_measurement_snapshots.assessment_velocity_delta",
        "Change in problem assessment velocity versus the previous window, winsorized.",
        "winsorize",
    ),
    FeatureSpec(
        "customer_growth_pct",
        "Customer growth",
        "numeric",
        "problem_measurement_snapshots.customer_growth_pct",
        "Window-over-window distinct-customer growth, winsorized.",
        "winsorize",
    ),
    FeatureSpec(
        "volume_growth_abs",
        "Evidence volume growth (absolute)",
        "numeric",
        "problem_measurement_snapshots.volume_growth_abs",
        "Absolute window-over-window evidence growth, winsorized.",
        "winsorize",
    ),
    FeatureSpec(
        "evidence_confidence",
        "Evidence confidence",
        "numeric",
        "customer_problems.discovery_confidence",
        "Discovery confidence of the canonical problem. Treated as supplementary by default because it is a measurement-quality signal, not customer impact.",
        role="supplementary",
    ),
)

FORBIDDEN_FEATURES = {
    "problem_id",
    "canonical_problem_id",
    "title",
    "problem_statement",
    "canonical_description",
    "feedback_text",
    "feedback_text_redacted",
    "mds_x",
    "mds_y",
    "x",
    "y",
    "priority_score",
    "customer_impact_score",
    "business_risk_score",
    "operational_impact_score",
    "trend_score",
    "strategic_score",
}

METRIC_FALLBACKS = {
    "evidence_volume": ("evidence_volume", "evidence_volume_90d"),
    "distinct_customers": ("distinct_customers", "distinct_customers_90d"),
    "negative_share": ("negative_share", "negative_share_90d"),
    "repeat_complaint_count": ("repeat_complaint_count", "repeat_complaint_count_90d"),
    "source_diversity": ("source_diversity", "source_diversity_90d"),
    "volume_growth_pct": ("volume_growth_pct",),
    "negative_share_change": ("negative_share_change",),
    "assessment_velocity_delta": ("assessment_velocity_delta",),
    "customer_growth_pct": ("customer_growth_pct",),
    "volume_growth_abs": ("volume_growth_abs",),
}

_FAILED_OUTCOMES = {"failed", "blocked", "abandoned"}
_NEGATIVE_EMOTIONS = {"frustration", "confusion", "anxiety", "disappointment"}


def _feature_names(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def resolve_feature_specs(
    active_features: str | None = None,
    supplementary_features: str | None = None,
    excluded_features: str | None = None,
) -> list[FeatureSpec]:
    """Resolve configured feature roles without hardcoding them in the pipeline.

    An empty ``active_features`` uses the built-in active defaults. Explicit
    feature names not in the catalogue are ignored so old configuration files
    cannot silently add unsupported columns.
    """

    known = {spec.name for spec in FEATURE_SPECS}
    active = _feature_names(active_features) or [spec.name for spec in FEATURE_SPECS if spec.role == "active"]
    supplementary = _feature_names(supplementary_features) or [
        spec.name for spec in FEATURE_SPECS if spec.role == "supplementary"
    ]
    excluded = set(_feature_names(excluded_features))
    active_set = {name for name in active if name in known}
    supplementary_set = {name for name in supplementary if name in known}
    resolved: list[FeatureSpec] = []
    for spec in FEATURE_SPECS:
        if spec.name in excluded:
            continue
        if spec.name in active_set:
            resolved.append(replace(spec, role="active"))
        elif spec.name in supplementary_set:
            resolved.append(replace(spec, role="supplementary"))
    return resolved


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _clean_category(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _metric(metrics: dict[str, dict[str, Any]], names: tuple[str, ...]) -> dict[str, Any] | None:
    for name in names:
        row = metrics.get(name)
        if row and row.get("status") in {"OK", "PARTIAL"} and row.get("metric_value") is not None:
            return row
    return None


def _metric_value(metrics: dict[str, dict[str, Any]], names: tuple[str, ...]) -> tuple[float | None, str | None, dict[str, Any] | None]:
    row = _metric(metrics, names)
    if row is None:
        return None, None, None
    return float(row["metric_value"]), row.get("snapshot_id"), row


def _in_window(value: str | None, start: datetime | None, end: datetime | None) -> bool:
    parsed = _parse_datetime(value)
    if parsed is None:
        return False
    if start is not None and parsed < start:
        return False
    return not (end is not None and parsed >= end)


def _window_bounds(metrics: dict[str, dict[str, Any]]) -> tuple[datetime | None, datetime | None, str | None]:
    for names in METRIC_FALLBACKS.values():
        row = _metric(metrics, names)
        if not row:
            continue
        start = _parse_datetime(row.get("measurement_window_start"))
        end = _parse_datetime(row.get("measurement_window_end"))
        if start or end:
            return start, end, row.get("measurement_window_end") or row.get("measurement_window_start")
    return None, None, None


def _safe_rate(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return max(0.0, min(1.0, numerator / denominator))


def build_feature_rows(
    db: Database,
    feedback_run_id: str,
    feature_schema_version: str,
    window_days: int = 90,
    feature_specs: list[FeatureSpec] | None = None,
) -> FeatureBuildResult:
    specs = list(feature_specs or FEATURE_SPECS)
    problem_rows = db.query(
        "SELECT problem_id, journey_node_id, aspect, symptom_category, customer_intent, discovery_confidence "
        "FROM customer_problems WHERE run_id=? ORDER BY problem_id",
        (feedback_run_id,),
    )
    mapping_rows = db.query(
        "SELECT problem_id, module_id, feature_id, journey_stage_id, mapping_confidence "
        "FROM problem_journey_mappings WHERE problem_id IN "
        "(SELECT problem_id FROM customer_problems WHERE run_id=?) "
        "ORDER BY mapping_confidence DESC",
        (feedback_run_id,),
    )
    mappings: dict[str, dict[str, Any]] = {}
    for row in mapping_rows:
        mappings.setdefault(row["problem_id"], row)

    measurement_rows = db.query(
        "SELECT problem_id, metric_name, metric_value, status, snapshot_id, "
        "measurement_window_start, measurement_window_end, input_record_count, metadata_json "
        "FROM problem_measurement_snapshots WHERE run_id=?",
        (feedback_run_id,),
    )
    measurements: dict[str, dict[str, dict[str, Any]]] = {}
    for row in measurement_rows:
        measurements.setdefault(row["problem_id"], {})[row["metric_name"]] = row

    evidence_rows = db.query(
        "SELECT pe.problem_id, pe.submitted_at, ei.customer_effort, ei.reported_outcome, ei.emotion "
        "FROM problem_evidence pe LEFT JOIN extracted_insights ei ON ei.insight_id=pe.insight_id "
        "WHERE pe.run_id=?",
        (feedback_run_id,),
    )
    evidence_by_problem: dict[str, list[dict[str, Any]]] = {}
    for row in evidence_rows:
        evidence_by_problem.setdefault(row["problem_id"], []).append(row)

    run = db.query_one("SELECT finished_at, created_at FROM pipeline_runs WHERE run_id=?", (feedback_run_id,))
    as_of_date = (run or {}).get("finished_at") or (run or {}).get("created_at") or datetime.now(UTC).isoformat()

    rows: list[FeatureRow] = []
    notes: list[str] = []
    global_window_start: datetime | None = None
    global_window_end: datetime | None = None
    for problem in problem_rows:
        problem_id = problem["problem_id"]
        metrics = measurements.get(problem_id, {})
        mapping = mappings.get(problem_id, {})
        window_start, window_end, window_label = _window_bounds(metrics)
        if not window_label and run:
            window_end = _parse_datetime((run or {}).get("finished_at"))
            window_label = (run or {}).get("finished_at")
        if window_start is not None:
            global_window_start = window_start if global_window_start is None else min(global_window_start, window_start)
        if window_end is not None:
            global_window_end = window_end if global_window_end is None else max(global_window_end, window_end)

        raw: dict[str, Any] = {}
        values: dict[str, Any] = {}
        missing: list[str] = []
        sources: dict[str, str | None] = {}
        denominators: dict[str, float | None] = {}
        flags: list[str] = []

        module_id = mapping.get("module_id")
        feature_id = mapping.get("feature_id")
        journey_node_id = problem.get("journey_node_id")
        raw["journey_module"] = module_id or (str(journey_node_id).split(".")[0] if journey_node_id else None)
        raw["journey_feature"] = feature_id or journey_node_id
        raw["journey_stage"] = mapping.get("journey_stage_id")
        raw["aspect"] = problem.get("aspect")
        raw["symptom_category"] = problem.get("symptom_category")
        raw["customer_intent"] = problem.get("customer_intent")

        volume, volume_source, volume_row = _metric_value(metrics, METRIC_FALLBACKS["evidence_volume"])
        customers, customer_source, customer_row = _metric_value(metrics, METRIC_FALLBACKS["distinct_customers"])
        negative, negative_source, negative_row = _metric_value(metrics, METRIC_FALLBACKS["negative_share"])
        repeat, repeat_source, repeat_row = _metric_value(metrics, METRIC_FALLBACKS["repeat_complaint_count"])
        diversity, diversity_source, diversity_row = _metric_value(metrics, METRIC_FALLBACKS["source_diversity"])
        growth, growth_source, _ = _metric_value(metrics, METRIC_FALLBACKS["volume_growth_pct"])
        negative_change, negative_change_source, _ = _metric_value(metrics, METRIC_FALLBACKS["negative_share_change"])
        velocity, velocity_source, _ = _metric_value(metrics, METRIC_FALLBACKS["assessment_velocity_delta"])
        customer_growth, customer_growth_source, _ = _metric_value(metrics, METRIC_FALLBACKS["customer_growth_pct"])
        volume_growth_abs, volume_growth_abs_source, _ = _metric_value(metrics, METRIC_FALLBACKS["volume_growth_abs"])

        raw.update(
            {
                "evidence_volume": volume,
                "distinct_customers": customers,
                "negative_share": negative,
                "repeat_complaint_rate": _safe_rate(repeat, volume),
                "source_diversity": diversity,
                "volume_growth_pct": growth,
                "negative_share_change": negative_change,
                "assessment_velocity_delta": velocity,
                "customer_growth_pct": customer_growth,
                "volume_growth_abs": volume_growth_abs,
                "evidence_confidence": problem.get("discovery_confidence"),
            }
        )
        sources.update(
            {
                "evidence_volume": volume_source,
                "distinct_customers": customer_source,
                "negative_share": negative_source,
                "repeat_complaint_rate": repeat_source or volume_source,
                "source_diversity": diversity_source,
                "volume_growth_pct": growth_source,
                "negative_share_change": negative_change_source,
                "assessment_velocity_delta": velocity_source,
                "customer_growth_pct": customer_growth_source,
                "volume_growth_abs": volume_growth_abs_source,
                "evidence_confidence": "customer_problems.discovery_confidence",
            }
        )
        denominators["repeat_complaint_rate"] = volume

        evidence = evidence_by_problem.get(problem_id, [])
        selected = [
            item
            for item in evidence
            if window_start is None and window_end is None or _in_window(item.get("submitted_at"), window_start, window_end)
        ]
        evidence_total = len(selected)
        high_effort = sum(1 for item in selected if item.get("customer_effort") == "high")
        failures = sum(1 for item in selected if item.get("reported_outcome") in _FAILED_OUTCOMES)
        negative_emotions = sum(1 for item in selected if item.get("emotion") in _NEGATIVE_EMOTIONS)
        raw["high_effort_share"] = _safe_rate(high_effort, evidence_total)
        raw["outcome_failure_share"] = _safe_rate(failures, evidence_total)
        raw["negative_emotion_share"] = _safe_rate(negative_emotions, evidence_total)
        denominators.update(
            {
                "high_effort_share": evidence_total,
                "outcome_failure_share": evidence_total,
                "negative_emotion_share": evidence_total,
            }
        )
        sources.update(
            {
                "high_effort_share": f"problem_evidence:{evidence_total}",
                "outcome_failure_share": f"problem_evidence:{evidence_total}",
                "negative_emotion_share": f"problem_evidence:{evidence_total}",
            }
        )

        for spec in specs:
            value = raw.get(spec.name)
            if spec.kind == "categorical":
                value = _clean_category(value)
            if value is None:
                missing.append(spec.name)
                flags.append(f"missing:{spec.name}")
            values[spec.name] = value

        for metric_row, name in (
            (volume_row, "evidence_volume"),
            (customer_row, "distinct_customers"),
            (negative_row, "negative_share"),
            (repeat_row, "repeat_complaint_rate"),
            (diversity_row, "source_diversity"),
        ):
            if metric_row and metric_row.get("status") == "PARTIAL":
                flags.append(f"partial_window:{name}")

        rows.append(
            FeatureRow(
                problem_id=problem_id,
                values=values,
                raw_values=raw,
                missing=missing,
                denominators=denominators,
                sources=sources,
                quality_flags=sorted(set(flags)),
            )
        )

    if not rows:
        notes.append("No canonical problems were found for the selected feedback run.")
    if not any(row.values.get("evidence_volume") is not None for row in rows):
        notes.append("Windowed measurement snapshots are unavailable; verify the feedback run measurement stage.")
    notes.append(
        f"Rates use the configured {window_days}-day measurement window where persisted snapshots are available; "
        "missing values remain missing and are never converted to zero."
    )
    return FeatureBuildResult(
        feedback_run_id=feedback_run_id,
        as_of_date=as_of_date,
        window_start=global_window_start.isoformat() if global_window_start else None,
        window_end=global_window_end.isoformat() if global_window_end else None,
        feature_schema_version=feature_schema_version,
        rows=rows,
        specs=specs,
        notes=notes,
    )
