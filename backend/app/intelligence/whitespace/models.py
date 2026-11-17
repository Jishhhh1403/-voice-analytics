from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class InsightRecord:
    feedback_id: str
    customer_id_hash: str
    timestamp: datetime | None
    channel: str
    journey_node_id: str | None
    intent: str | None
    aspect: str | None
    symptom: str | None
    emotion: str | None
    effort_score: float
    is_open_set: bool


@dataclass(frozen=True)
class CanonicalProblemRecord:
    problem_id: str
    journey_node_id: str | None
    top_intents: tuple[str, ...]
    top_aspects: tuple[str, ...]
    priority_score: float
    mean_effort_score: float
    mds_x: float | None
    mds_y: float | None
    supporting_feedback_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BacklogProfileRecord:
    backlog_id: str
    title: str
    journey_node_id: str | None
    profiled_intents: tuple[str, ...]
    profiled_aspects: tuple[str, ...]


@dataclass(frozen=True)
class CoveragePair:
    problem_id: str
    backlog_id: str
    alignment_score: float


@dataclass(frozen=True)
class WhitespaceDataset:
    run_id: str
    report_id: str | None
    upload_id: str | None
    insights: tuple[InsightRecord, ...]
    canonical_problems: tuple[CanonicalProblemRecord, ...]
    backlog_profiles: tuple[BacklogProfileRecord, ...]
    coverage: tuple[CoveragePair, ...]


@dataclass(frozen=True)
class LensSignal:
    lens_name: str
    journey_node_id: str | None
    intent: str | None
    aspect: str | None
    normalized_score: float
    supporting_feedback_ids: tuple[str, ...]
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def parent_family(self) -> str:
        if self.lens_name.startswith("GRAPH_"):
            return "GRAPH"
        if self.lens_name == "SPATIAL_VOID":
            return "SPATIAL"
        return "COMBINATORIAL"


@dataclass(frozen=True)
class LensAssociation:
    problem_id: str
    lens_name: str
    association_score: float
    signal_score: float
    journey_node_id: str | None
    intent: str | None
    aspect: str | None
    shared_feedback_count: int


@dataclass(frozen=True)
class VerifiedWhitespace:
    whitespace_id: str
    journey_node_id: str | None
    primary_intent: str | None
    primary_aspect: str | None
    lenses_triggered: tuple[str, ...]
    graph_score: float
    spatial_score: float
    combinatorial_score: float
    backlog_coverage_score: float
    whitespace_score: float
    supporting_feedback_ids: tuple[str, ...]
    motif_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WhitespaceDiscoveryResult:
    run_id: str
    report_id: str | None
    upload_id: str | None
    lens_signals: tuple[LensSignal, ...]
    verified_whitespaces: tuple[VerifiedWhitespace, ...]
    merged_whitespaces: tuple[VerifiedWhitespace, ...]
    diagnostics: dict[str, object] = field(default_factory=dict)
