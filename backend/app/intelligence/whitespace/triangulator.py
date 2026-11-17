from __future__ import annotations

from collections import defaultdict

from .context import WhitespaceContext
from .models import LensSignal, VerifiedWhitespace
from .utils import deterministic_id, jaccard, top_values


def _should_merge(left: LensSignal, right: LensSignal) -> bool:
    if left.journey_node_id and left.intent and left.journey_node_id == right.journey_node_id and left.intent == right.intent:
        return True
    if left.aspect and left.aspect == right.aspect and jaccard(left.supporting_feedback_ids, right.supporting_feedback_ids) >= 0.20:
        return True
    return jaccard(left.supporting_feedback_ids, right.supporting_feedback_ids) >= 0.30


def triangulate(signals: list[LensSignal], context: WhitespaceContext) -> list[VerifiedWhitespace]:
    if not signals:
        return []
    ordered = sorted(signals, key=lambda signal: (signal.lens_name, signal.journey_node_id or "", signal.intent or "", signal.aspect or "", signal.supporting_feedback_ids))
    parents = list(range(len(ordered)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    for left in range(len(ordered)):
        for right in range(left + 1, len(ordered)):
            if _should_merge(ordered[left], ordered[right]):
                union(left, right)
    grouped: dict[int, list[LensSignal]] = defaultdict(list)
    for index, signal in enumerate(ordered):
        grouped[find(index)].append(signal)
    results: list[VerifiedWhitespace] = []
    for members in grouped.values():
        families = {member.parent_family for member in members}
        family_scores: dict[str, float] = {}
        for member in members:
            family_scores[member.parent_family] = max(family_scores.get(member.parent_family, 0.0), member.normalized_score)
        feedback_ids = tuple(sorted({feedback_id for member in members for feedback_id in member.supporting_feedback_ids}))
        if not feedback_ids:
            continue
        journeys = top_values([member.journey_node_id for member in members], 1)
        intents = top_values([member.intent for member in members], 1)
        aspects = top_values([member.aspect for member in members], 1)
        journey = journeys[0] if journeys else None
        intent = intents[0] if intents else None
        aspect = aspects[0] if aspects else None
        backlog_coverage = context.canonical_coverage(feedback_ids)
        graph_score = family_scores.get("GRAPH", 0.0)
        spatial_score = family_scores.get("SPATIAL", 0.0)
        combinatorial_score = family_scores.get("COMBINATORIAL", 0.0)
        score = 0.35 * graph_score + 0.30 * spatial_score + 0.20 * combinatorial_score + 0.15 * (1.0 - backlog_coverage)
        results.append(
            VerifiedWhitespace(
                whitespace_id=deterministic_id("WS", (journey or "", intent or "", aspect or "", *feedback_ids)),
                journey_node_id=journey,
                primary_intent=intent,
                primary_aspect=aspect,
                lenses_triggered=tuple(sorted({member.lens_name for member in members})),
                graph_score=graph_score,
                spatial_score=spatial_score,
                combinatorial_score=combinatorial_score,
                backlog_coverage_score=backlog_coverage,
                whitespace_score=score,
                supporting_feedback_ids=feedback_ids,
                motif_metadata={
                    "parent_families": tuple(sorted(families)),
                    "lens_count": len(members),
                    "feedback_count": len(feedback_ids),
                    "member_scores": sorted(
                        (
                            {"lens_name": member.lens_name, "score": member.normalized_score}
                            for member in members
                        ),
                        key=lambda item: (item["lens_name"], -float(item["score"])),
                    ),
                },
            )
        )
    return sorted(results, key=lambda item: (-item.whitespace_score, item.whitespace_id))
