from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta

import networkx as nx

from .context import WhitespaceContext
from .models import LensSignal, WhitespaceDataset
from .utils import mean, minmax_scores, percentile, top_values


def _normalize(signals: list[LensSignal], raw_key: str = "raw_score") -> list[LensSignal]:
    if not signals:
        return []
    scores = minmax_scores([float(signal.metadata.get(raw_key, 0.0)) for signal in signals])
    return [
        LensSignal(
            lens_name=signal.lens_name,
            journey_node_id=signal.journey_node_id,
            intent=signal.intent,
            aspect=signal.aspect,
            normalized_score=score,
            supporting_feedback_ids=signal.supporting_feedback_ids,
            metadata={**signal.metadata, "raw_score": float(signal.metadata.get(raw_key, 0.0))},
        )
        for signal, score in zip(signals, scores, strict=True)
    ]


def detect_cross_journey_bridges(dataset: WhitespaceDataset, context: WhitespaceContext) -> list[LensSignal]:
    graph = nx.Graph()
    aspect_feedbacks: dict[str, set[str]] = defaultdict(set)
    aspect_journeys: dict[str, set[str]] = defaultdict(set)
    aspect_efforts: dict[str, list[float]] = defaultdict(list)
    aspect_intents: dict[str, list[str]] = defaultdict(list)
    edge_counts: Counter[tuple[str, str]] = Counter()
    for record in dataset.insights:
        if not record.aspect:
            continue
        aspect = record.aspect
        aspect_feedbacks[aspect].add(record.feedback_id)
        aspect_efforts[aspect].append(record.effort_score)
        if record.intent:
            aspect_intents[aspect].append(record.intent)
        if not record.journey_node_id:
            continue
        journey = record.journey_node_id
        aspect_journeys[aspect].add(journey)
        journey_node = f"journey:{journey}"
        aspect_node = f"aspect:{aspect}"
        graph.add_node(journey_node, bipartite=0)
        graph.add_node(aspect_node, bipartite=1)
        edge_counts[(journey_node, aspect_node)] += 1
    for (journey_node, aspect_node), count in edge_counts.items():
        graph.add_edge(journey_node, aspect_node, weight=count)
    aspect_nodes = [f"aspect:{aspect}" for aspect in aspect_feedbacks if aspect in aspect_journeys]
    if not aspect_nodes:
        return []
    centrality = nx.betweenness_centrality(graph, k=None, normalized=True, weight=None)
    threshold = percentile([centrality[node] for node in aspect_nodes], 85)
    signals: list[LensSignal] = []
    for aspect in sorted(aspect_feedbacks):
        node = f"aspect:{aspect}"
        if node not in centrality:
            continue
        score = centrality[node]
        journeys = {
            journey
            for journey in aspect_journeys.get(aspect, set())
            if not context.is_pair_covered(journey, None, aspect, 0.60)
        }
        feedback_ids = tuple(sorted(aspect_feedbacks[aspect]))
        if score < threshold or len(journeys) < 3 or len(feedback_ids) < 10:
            continue
        effort = mean(aspect_efforts.get(aspect, []))
        raw_score = score * len(journeys) * (effort / 5.0)
        dominant_journey = top_values(sorted(journeys), 1)
        dominant_intent = top_values(aspect_intents.get(aspect, []), 1)
        signals.append(
            LensSignal(
                lens_name="GRAPH_BRIDGE",
                journey_node_id=dominant_journey[0] if dominant_journey else None,
                intent=dominant_intent[0] if dominant_intent else None,
                aspect=aspect,
                normalized_score=0.0,
                supporting_feedback_ids=feedback_ids,
                metadata={
                    "raw_score": raw_score,
                    "centrality": score,
                    "uncovered_journey_count": len(journeys),
                    "uncovered_journeys": tuple(sorted(journeys)),
                    "feedback_count": len(feedback_ids),
                    "mean_effort_score": effort,
                },
            )
        )
    return _normalize(signals)


def detect_temporal_friction_chains(dataset: WhitespaceDataset, context: WhitespaceContext) -> list[LensSignal]:
    by_customer: dict[str, list[tuple[int, object]]] = defaultdict(list)
    for index, record in enumerate(dataset.insights):
        if record.timestamp is not None:
            by_customer[record.customer_id_hash].append((index, record.timestamp))
    counts: Counter[tuple[str, str]] = Counter()
    out_counts: Counter[str] = Counter()
    in_counts: Counter[str] = Counter()
    transitions: dict[tuple[str, str], set[int]] = defaultdict(set)
    downstream_intents: dict[tuple[str, str], list[str]] = defaultdict(list)
    downstream_aspects: dict[tuple[str, str], list[str]] = defaultdict(list)
    downstream_journeys: dict[tuple[str, str], list[str]] = defaultdict(list)
    total_transitions = 0
    for items in by_customer.values():
        items.sort(key=lambda item: (item[1], item[0]))
        for (first_index, first_time), (second_index, second_time) in zip(items, items[1:], strict=False):
            delta = second_time - first_time
            if delta < timedelta(0) or delta > timedelta(days=7):
                continue
            first, second = dataset.insights[first_index], dataset.insights[second_index]
            if not first.symptom or not second.symptom or first.symptom == second.symptom:
                continue
            key = (first.symptom, second.symptom)
            counts[key] += 1
            out_counts[first.symptom] += 1
            in_counts[second.symptom] += 1
            transitions[key].update((first_index, second_index))
            if second.intent:
                downstream_intents[key].append(second.intent)
            if second.aspect:
                downstream_aspects[key].append(second.aspect)
            if second.journey_node_id:
                downstream_journeys[key].append(second.journey_node_id)
            total_transitions += 1
    if not counts or total_transitions == 0:
        return []
    signals: list[LensSignal] = []
    for (source, target), count in sorted(counts.items()):
        if count < 5 or context.is_symptom_covered(target):
            continue
        denominator = out_counts[source] * in_counts[target]
        if denominator == 0:
            continue
        lift = count * total_transitions / denominator
        if lift < 2.0:
            continue
        indexes = sorted(transitions[(source, target)])
        feedback_ids = tuple(dict.fromkeys(dataset.insights[index].feedback_id for index in indexes))
        raw_score = math.log1p(count) * lift
        signals.append(
            LensSignal(
                lens_name="GRAPH_TEMPORAL",
                journey_node_id=top_values(downstream_journeys[(source, target)], 1)[0]
                if downstream_journeys[(source, target)]
                else None,
                intent=top_values(downstream_intents[(source, target)], 1)[0]
                if downstream_intents[(source, target)]
                else None,
                aspect=top_values(downstream_aspects[(source, target)], 1)[0]
                if downstream_aspects[(source, target)]
                else None,
                normalized_score=0.0,
                supporting_feedback_ids=feedback_ids,
                metadata={
                    "raw_score": raw_score,
                    "source_symptom": source,
                    "target_symptom": target,
                    "transition_count": count,
                    "lift": lift,
                    "total_transitions": total_transitions,
                },
            )
        )
    return _normalize(signals)


def analyze_graph(dataset: WhitespaceDataset, context: WhitespaceContext) -> list[LensSignal]:
    return detect_cross_journey_bridges(dataset, context) + detect_temporal_friction_chains(dataset, context)
