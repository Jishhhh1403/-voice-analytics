from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.intelligence.whitespace.combinatorial_analyzer import analyze_combinatorial, detect_combinatorial_nmf
from app.intelligence.whitespace.context import WhitespaceContext
from app.intelligence.whitespace.graph_analyzer import analyze_graph
from app.intelligence.whitespace.models import (
    BacklogProfileRecord,
    CanonicalProblemRecord,
    CoveragePair,
    InsightRecord,
    LensSignal,
    WhitespaceDataset,
)
from app.intelligence.whitespace.spatial_analyzer import analyze_spatial
from app.intelligence.whitespace.triangulator import triangulate


def _insight(
    feedback_id: str,
    *,
    journey: str | None = "payments.status",
    intent: str | None = "track_transfer",
    aspect: str | None = "transfer_status",
    symptom: str | None = "status_unclear",
    effort: float = 5.0,
    customer: str | None = None,
    timestamp: datetime | None = None,
    channel: str = "in_app",
    emotion: str = "frustration",
) -> InsightRecord:
    return InsightRecord(
        feedback_id=feedback_id,
        customer_id_hash=customer or f"cust-{feedback_id}",
        timestamp=timestamp or datetime(2026, 1, 1, tzinfo=UTC),
        channel=channel,
        journey_node_id=journey,
        intent=intent,
        aspect=aspect,
        symptom=symptom,
        emotion=emotion,
        effort_score=effort,
        is_open_set=True,
    )


def _dataset(
    insights: list[InsightRecord],
    *,
    problems: list[CanonicalProblemRecord] | None = None,
    backlog: list[BacklogProfileRecord] | None = None,
    coverage: list[CoveragePair] | None = None,
) -> WhitespaceDataset:
    return WhitespaceDataset(
        run_id="RUN-TEST",
        report_id="RPT-TEST",
        upload_id="UP-TEST",
        insights=tuple(insights),
        canonical_problems=tuple(problems or []),
        backlog_profiles=tuple(backlog or []),
        coverage=tuple(coverage or []),
    )


def test_graph_bridge_requires_three_journeys_and_ten_feedbacks() -> None:
    insights = [
        _insight(
            f"FB-{index:03d}",
            journey=["payments.status", "cards.controls", "statements.download"][index % 3],
            aspect="refund_tracking",
            symptom="refund_not_visible",
        )
        for index in range(12)
    ]
    dataset = _dataset(insights)
    signals = analyze_graph(dataset, WhitespaceContext(dataset))
    bridges = [signal for signal in signals if signal.lens_name == "GRAPH_BRIDGE"]
    assert len(bridges) == 1
    assert bridges[0].aspect == "refund_tracking"
    assert bridges[0].normalized_score > 0
    assert len(bridges[0].supporting_feedback_ids) == 12
    assert bridges[0].metadata["uncovered_journey_count"] == 3


def test_temporal_chain_uses_lift_and_requires_uncovered_target() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    insights: list[InsightRecord] = []
    for index in range(5):
        customer = f"chain-{index}"
        insights.append(_insight(f"A-{index}", customer=customer, symptom="money_delayed", timestamp=base))
        insights.append(
            _insight(
                f"B-{index}",
                customer=customer,
                symptom="status_unclear",
                timestamp=base + timedelta(days=2),
            )
        )
        other = f"other-{index}"
        insights.append(_insight(f"C-{index}", customer=other, symptom="login_failed", timestamp=base))
        insights.append(
            _insight(
                f"D-{index}",
                customer=other,
                symptom="otp_expired",
                timestamp=base + timedelta(days=2),
            )
        )
    dataset = _dataset(insights)
    signals = analyze_graph(dataset, WhitespaceContext(dataset))
    temporal = [signal for signal in signals if signal.lens_name == "GRAPH_TEMPORAL"]
    target = next((signal for signal in temporal if signal.metadata["target_symptom"] == "status_unclear"), None)
    assert target is not None
    assert target.metadata["transition_count"] == 5
    assert float(target.metadata["lift"]) >= 2.0
    assert "B-0" in target.supporting_feedback_ids


def test_spatial_void_detection_includes_captured_provenance() -> None:
    coordinates = [(0.05, 0.05), (0.15, 0.05), (0.05, 0.15), (0.12, 0.12), (0.02, 0.12), (1.9, 1.9)]
    problems = [
        CanonicalProblemRecord(
            problem_id=f"CP-{index:03d}",
            journey_node_id="payments.status" if index < 5 else "auth.login",
            top_intents=("track_transfer",) if index < 5 else ("login",),
            top_aspects=("transfer_status",) if index < 5 else ("otp",),
            priority_score=0.9 if index < 5 else 0.1,
            mean_effort_score=5.0 if index < 5 else 2.0,
            mds_x=x,
            mds_y=y,
            supporting_feedback_ids=(f"FB-{index:03d}a", f"FB-{index:03d}b"),
        )
        for index, (x, y) in enumerate(coordinates)
    ]
    backlog = [
        BacklogProfileRecord("BL-1", "far backlog", "auth.login", ("login",), ("otp",)),
        BacklogProfileRecord("BL-2", "other backlog", "auth.login", ("login",), ("otp",)),
    ]
    dataset = _dataset([], problems=problems, backlog=backlog)
    signals = analyze_spatial(dataset, WhitespaceContext(dataset))
    assert signals
    void = signals[0]
    assert void.lens_name == "SPATIAL_VOID"
    assert len(void.supporting_feedback_ids) >= 5
    assert void.normalized_score > 0
    assert float(void.metadata["radius"]) > 0


def test_combinatorial_lattice_and_nmf_signals() -> None:
    insights = [
        _insight(
            f"FB-{index:03d}",
            journey="payments.status",
            intent="track_transfer",
            aspect="transfer_status",
            symptom=["money_delayed", "status_unclear", "refund_missing", "receipt_missing"][index % 4],
            emotion=["frustration", "anger", "confusion", "worry"][index % 4],
            channel=["in_app", "survey", "review"][index % 3],
        )
        for index in range(30)
    ]
    dataset = _dataset(insights)
    context = WhitespaceContext(dataset)
    lattice = [signal for signal in analyze_combinatorial(dataset, context) if signal.lens_name == "COMBINATORIAL_LATTICE"]
    assert lattice
    assert lattice[0].metadata["pair_type"] == "journey_intent"
    nmf = detect_combinatorial_nmf(dataset, context)
    assert nmf
    assert all(signal.lens_name == "COMBINATORIAL_NMF" for signal in nmf)
    assert all(signal.supporting_feedback_ids for signal in nmf)


def test_triangulator_requires_two_parent_families_and_applies_score() -> None:
    shared = ("FB-1", "FB-2", "FB-3", "FB-4", "FB-5")
    signals = [
        LensSignal("GRAPH_BRIDGE", "payments.status", "track_transfer", "transfer_status", 0.6, shared),
        LensSignal("SPATIAL_VOID", "payments.status", "track_transfer", "transfer_status", 0.4, shared),
    ]
    problem = CanonicalProblemRecord(
        problem_id="CP-1",
        journey_node_id="payments.status",
        top_intents=("track_transfer",),
        top_aspects=("transfer_status",),
        priority_score=0.8,
        mean_effort_score=4.0,
        mds_x=0.0,
        mds_y=0.0,
        supporting_feedback_ids=shared,
    )
    dataset = _dataset([], problems=[problem], coverage=[CoveragePair("CP-1", "BL-1", 0.8)])
    results = triangulate(signals, WhitespaceContext(dataset))
    assert len(results) == 1
    result = results[0]
    assert result.lenses_triggered == ("GRAPH_BRIDGE", "SPATIAL_VOID")
    assert result.backlog_coverage_score == 0.8
    assert abs(result.whitespace_score - 0.36) < 1e-9
    assert result.supporting_feedback_ids == shared


def test_triangulator_keeps_single_family_candidates() -> None:
    shared = ("FB-1", "FB-2", "FB-3", "FB-4", "FB-5")
    signals = [
        LensSignal("GRAPH_BRIDGE", "payments.status", "track_transfer", "transfer_status", 0.6, shared),
        LensSignal("GRAPH_TEMPORAL", "payments.status", "track_transfer", "transfer_status", 0.4, shared),
    ]
    results = triangulate(signals, WhitespaceContext(_dataset([])))
    assert len(results) == 1
    assert results[0].lenses_triggered == ("GRAPH_BRIDGE", "GRAPH_TEMPORAL")
    assert abs(results[0].whitespace_score - 0.36) < 1e-9


def test_lens_associations_rank_signals_against_canonical_problems() -> None:
    shared = ("FB-1", "FB-2", "FB-3", "FB-4", "FB-5")
    problem = CanonicalProblemRecord(
        problem_id="CP-1",
        journey_node_id="payments.status",
        top_intents=("track_transfer",),
        top_aspects=("transfer_status",),
        priority_score=0.8,
        mean_effort_score=4.0,
        mds_x=0.0,
        mds_y=0.0,
        supporting_feedback_ids=shared,
    )
    other = CanonicalProblemRecord(
        problem_id="CP-2",
        journey_node_id="cards.controls",
        top_intents=("freeze_card",),
        top_aspects=("card_control",),
        priority_score=0.3,
        mean_effort_score=2.0,
        mds_x=1.0,
        mds_y=1.0,
        supporting_feedback_ids=("FB-99",),
    )
    signals = [
        LensSignal("GRAPH_BRIDGE", "payments.status", "track_transfer", "transfer_status", 0.7, shared),
        LensSignal("COMBINATORIAL_LATTICE", "payments.status", "track_transfer", "transfer_status", 0.65, shared[:3]),
        LensSignal("COMBINATORIAL_LATTICE", "payments.status", "track_transfer", "transfer_status", 0.6, shared),
        LensSignal("SPATIAL_VOID", "payments.status", "track_transfer", "transfer_status", 0.95, shared),
    ]
    associations = WhitespaceContext(_dataset([], problems=[problem, other])).lens_associations(signals)
    assert set(associations) == {"CP-1"}
    assert associations["CP-1"].lens_name == "GRAPH_BRIDGE"
    assert associations["CP-1"].association_score > 0.5
    assert associations["CP-1"].shared_feedback_count == 5


def test_lens_associations_ignore_signals_below_internal_score_threshold() -> None:
    shared = ("FB-1", "FB-2", "FB-3", "FB-4", "FB-5")
    problem = CanonicalProblemRecord(
        problem_id="CP-1",
        journey_node_id="payments.status",
        top_intents=("track_transfer",),
        top_aspects=("transfer_status",),
        priority_score=0.8,
        mean_effort_score=4.0,
        mds_x=0.0,
        mds_y=0.0,
        supporting_feedback_ids=shared,
    )
    signals = [
        LensSignal("GRAPH_BRIDGE", "payments.status", "track_transfer", "transfer_status", 0.6, shared),
        LensSignal("COMBINATORIAL_LATTICE", "payments.status", "track_transfer", "transfer_status", 0.59, shared),
    ]
    context = WhitespaceContext(_dataset([], problems=[problem]))
    assert context.lens_associations(signals) == {}
    assert context.lens_associations(signals, minimum_signal_score=0.58)["CP-1"].lens_name == "GRAPH_BRIDGE"
