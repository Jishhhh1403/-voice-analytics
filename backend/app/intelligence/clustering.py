from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import numpy as np

from ..config import Settings
from . import lexicon
from .contracts import CleanFeedback, ExtractedInsight, ProblemDraft
from .embeddings import build_embedder, cosine_similarity_matrix, vector_to_json
from .taxonomy import Taxonomy


@dataclass
class ClusterOutput:
    problems: list[ProblemDraft] = field(default_factory=list)
    evidence: dict[str, list[tuple[ExtractedInsight, CleanFeedback]]] = field(default_factory=dict)
    clusters: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    mappings: list[dict[str, Any]] = field(default_factory=list)


def _id(prefix: str, value: str, length: int = 14) -> str:
    return prefix + hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def _symptom_key(insight: ExtractedInsight) -> str:
    if insight.reported_symptom and insight.reported_symptom != "reported issue":
        # Use category + first two words of the symptom label as a stable failure-mode key.
        words = insight.reported_symptom.lower().replace("customer", "").split()
        return "-".join(words[:4]) or (insight.symptom_category or "general")
    return insight.symptom_category or "general"


def _signature(insight: ExtractedInsight) -> str:
    node = insight.journey_node_id or "unmapped"
    symptom = _symptom_key(insight)
    if symptom == "general":
        return f"{node}|general|{insight.customer_intent or 'unknown'}"
    return f"{node}|{symptom}"


def _aspect_label(aspect_key: str | None) -> str:
    for aspect in lexicon.ASPECTS:
        if aspect.key == aspect_key:
            return aspect.label
    return "Customer experience"


def _symptom_label(symptom_key: str, insights: list[ExtractedInsight]) -> str:
    for insight in insights:
        if insight.reported_symptom and insight.reported_symptom != "reported issue":
            return insight.reported_symptom
    return "Reported issue"


def _cluster(taxonomy: Taxonomy, settings: Settings, insights: list[ExtractedInsight], feedback: dict[str, CleanFeedback]) -> ClusterOutput:
    problem_insights = [item for item in insights if item.is_problem and item.reported_problem]
    if not problem_insights:
        return ClusterOutput()

    texts = [item.reported_problem or "" for item in problem_insights]
    embedder, vectors = build_embedder(settings, texts)
    for insight, vector in zip(problem_insights, vectors):
        insight.embedding_json = vector_to_json(vector)

    # 1. Deterministic base groups preserve distinct failure modes.
    groups: dict[str, list[int]] = defaultdict(list)
    for index, insight in enumerate(problem_insights):
        groups[_signature(insight)].append(index)

    # 2. Merge only highly similar groups that share a journey node and compatible symptom scope.
    keys = list(groups.keys())
    parent = {key: key for key in keys}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    centroids: dict[str, np.ndarray] = {}
    meta: dict[str, tuple[str, str]] = {}
    for key, indexes in groups.items():
        centroids[key] = vectors[indexes].mean(axis=0)
        node, symptom, *_ = key.split("|") + ["general"]
        meta[key] = (node, symptom)

    threshold = settings.clustering_similarity_threshold
    for i, left in enumerate(keys):
        for right in keys[i + 1 :]:
            left_node, left_symptom = meta[left]
            right_node, right_symptom = meta[right]
            if left_node != right_node or left_node == "unmapped":
                continue
            if left_symptom != right_symptom:
                continue
            similarity = float(np.dot(centroids[left], centroids[right]))
            if similarity >= min(0.9, threshold + 0.18):
                union(left, right)

    merged: dict[str, list[int]] = defaultdict(list)
    for key, indexes in groups.items():
        merged[find(key)].extend(indexes)

    output = ClusterOutput()
    for signature, indexes in sorted(merged.items(), key=lambda item: (-len(item[1]), item[0])):
        members = [problem_insights[index] for index in indexes]
        member_vectors = vectors[indexes]
        similarity = cosine_similarity_matrix(member_vectors)
        # Medoid is the most representative, naturally grounded statement.
        medoid_index = int(np.argmax(similarity.mean(axis=1))) if len(members) > 1 else 0
        representative = members[medoid_index]
        node_id = representative.journey_node_id
        aspect_counter = Counter(item.aspect for item in members if item.aspect)
        symptom_counter = Counter(_symptom_key(item) for item in members)
        intent_counter = Counter(item.customer_intent for item in members if item.customer_intent)
        dominant_aspect = aspect_counter.most_common(1)[0][0] if aspect_counter else None
        symptom_key = symptom_counter.most_common(1)[0][0] if symptom_counter else "general"
        symptom_label = _symptom_label(symptom_key, members)
        aspect_label = _aspect_label(dominant_aspect)
        title = f"{aspect_label}: {symptom_label}"[:150]
        if symptom_key == "general":
            intent = intent_counter.most_common(1)[0][0] if intent_counter else "issue"
            title = f"{aspect_label}: {intent.replace('_', ' ')}"[:150]
        problem_id = _id("CP-", signature)
        cluster_id = _id("CL-", signature)

        submitted = [feedback[item.feedback_id].submitted_at for item in members if item.feedback_id in feedback and feedback[item.feedback_id].submitted_at]
        customers = {
            feedback[item.feedback_id].synthetic_customer_ref
            for item in members
            if item.feedback_id in feedback and feedback[item.feedback_id].synthetic_customer_ref
        }
        sources = Counter(feedback[item.feedback_id].source_type for item in members if item.feedback_id in feedback)
        negative_count = sum(1 for item in members if item.sentiment in ("negative", "mixed"))
        first_seen = min(submitted) if submitted else None
        last_seen = max(submitted) if submitted else None

        original_statement = representative.reported_problem or title
        statement = original_statement
        if len(members) > 1:
            statement = f"{original_statement} Similar reports: {len(members) - 1}."

        problem = ProblemDraft(
            problem_id=problem_id,
            signature=signature,
            title=title,
            problem_statement=statement[:400],
            customer_intent=intent_counter.most_common(1)[0][0] if intent_counter else None,
            aspect=dominant_aspect,
            symptom_category=representative.symptom_category,
            journey_node_id=node_id,
            evidence_count=len(members),
            distinct_customers=len(customers),
            negative_count=negative_count,
            first_seen=first_seen,
            last_seen=last_seen,
            cluster_id=cluster_id,
            lifecycle_status="candidate",
        )
        output.problems.append(problem)
        output.evidence[problem_id] = [(item, feedback[item.feedback_id]) for item in members if item.feedback_id in feedback]

        description = (
            f"{len(members)} evidence mention(s) across {len(sources)} source type(s). "
            f"Representative redacted evidence: \"{original_statement[:220]}\"."
        )
        output.clusters.append(
            {
                "cluster_id": cluster_id,
                "label": title,
                "description": description,
                "algorithm": "signature+tfidf-medoid",
                "params_json": '{"grouping":"journey_node+symptom_key","merge_threshold":'
                + str(settings.clustering_similarity_threshold)
                + "}",
                "model_version": embedder.model_name,
                "member_count": len(members),
            }
        )

        node = taxonomy.by_id.get(node_id or "")
        if node:
            output.mappings.append(
                {
                    "mapping_id": _id("MP-", problem_id + node.node_id),
                    "problem_id": problem_id,
                    "node_id": node.node_id,
                    "mapping_type": "primary",
                    "confidence": 0.92 if dominant_aspect else 0.72,
                    "rationale": (
                        f"Aspect '{dominant_aspect}' maps declaratively to taxonomy node "
                        f"'{taxonomy.path_label(node.node_id)}'."
                    ),
                    "status": "candidate",
                    "taxonomy_version": taxonomy.version,
                }
            )
        else:
            parent = taxonomy.module_for(
                (next((a.node_hint for a in lexicon.ASPECTS if a.key == dominant_aspect), None))
            )
            output.proposals.append(
                {
                    "proposal_id": _id("TP-", problem_id),
                    "problem_id": problem_id,
                    "suggested_name": title,
                    "parent_candidate": parent.node_id if parent else None,
                    "description": f"Potential new category for: {title}. Grounded in customer evidence.",
                    "example_evidence": (original_statement or "")[:300],
                    "reason": "The problem statement could not be confidently mapped to an existing taxonomy node.",
                }
            )

    return output
