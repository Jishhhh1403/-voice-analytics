from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import Settings
from . import lexicon
from .canonicalisation import CanonicalisationService
from .cluster_assignment import assign_clusters
from .contracts import CleanFeedback, ExtractedInsight, ProblemDraft
from .embeddings import build_weighted_embedder, cosine_similarity_matrix, vector_to_json
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
        words = insight.reported_symptom.lower().replace("customer", "").split()
        return "-".join(words[:4]) or (insight.symptom_category or "general")
    return insight.symptom_category or "general"


def _signature(insight: ExtractedInsight) -> str:
    node = insight.journey_node_id or "unmapped"
    symptom = _symptom_key(insight)
    return f"{node}|{symptom}|{insight.insight_id}"


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


def _components(insight: ExtractedInsight, record: CleanFeedback, taxonomy: Taxonomy) -> dict[str, str]:
    node = taxonomy.by_id.get(insight.journey_node_id or "")
    node_text = " ".join(
        filter(
            None,
            [
                node.display_name if node else (insight.journey_node_id or ""),
                taxonomy.path_label(node.node_id) if node else "",
                " ".join(node.synonyms) if node else "",
                node.description if node else "",
            ],
        )
    )
    symptom_text = " ".join(
        filter(
            None,
            [
                insight.reported_symptom or "",
                insight.symptom_category or "",
                insight.aspect or "",
                insight.customer_intent or "",
            ],
        )
    )
    feedback_text = record.feedback_text_redacted or record.feedback_text_original or insight.evidence_span
    return {"journey_node": node_text, "symptom": symptom_text, "feedback": feedback_text}


def _neighbors(
    insights: list[ExtractedInsight],
    vectors: np.ndarray,
    indexes: list[int],
    medoid_position: int,
    limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    member_vectors = vectors[indexes]
    medoid_vector = member_vectors[medoid_position]
    similarities = member_vectors @ medoid_vector
    order = np.argsort(-similarities)[: max(1, limit)]
    neighbors = [
        {
            "problem_id": insights[indexes[position]].insight_id,
            "text": insights[indexes[position]].reported_problem or "",
            "similarity": round(float(similarities[position]), 4),
        }
        for position in order
    ]
    return medoid_position, neighbors


def _cluster(
    taxonomy: Taxonomy,
    settings: Settings,
    insights: list[ExtractedInsight],
    feedback: dict[str, CleanFeedback],
) -> ClusterOutput:
    problem_insights = [item for item in insights if item.is_problem and item.reported_problem]
    if not problem_insights:
        return ClusterOutput()

    components = [
        _components(item, feedback[item.feedback_id], taxonomy)
        if item.feedback_id in feedback
        else {"journey_node": item.journey_node_id or "", "symptom": item.reported_symptom or "", "feedback": item.evidence_span}
        for item in problem_insights
    ]
    embedder, vectors = build_weighted_embedder(settings, components)
    for insight, vector in zip(problem_insights, vectors, strict=False):
        insight.embedding_json = vector_to_json(vector)

    assignment = assign_clusters(vectors, settings)

    semantic_nodes = [node for node in taxonomy.nodes if node.node_type in {"feature", "module"}]
    semantic_vectors = None
    if semantic_nodes:
        try:
            node_texts = [
                f"{node.display_name} {' '.join(node.synonyms)} {node.description or ''}".strip()
                for node in semantic_nodes
            ]
            semantic_vectors = (
                embedder.transform_texts(node_texts)
                if hasattr(embedder, "transform_texts")
                else embedder.transform(node_texts)
            )
        except Exception:
            semantic_vectors = None

    grouped: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(assignment.labels):
        grouped[int(label)].append(index)

    ordered_groups = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    canonical_service = CanonicalisationService(settings)
    medoid_positions: dict[int, int] = {}
    neighbor_map: dict[int, list[dict[str, Any]]] = {}
    neighbor_groups: list[list[dict[str, Any]]] = []
    for label, indexes in ordered_groups:
        member_vectors = vectors[indexes]
        similarity = cosine_similarity_matrix(member_vectors)
        medoid_position = int(np.argmax(similarity.mean(axis=1))) if len(indexes) > 1 else 0
        medoid_position, neighbors = _neighbors(
            problem_insights,
            vectors,
            indexes,
            medoid_position,
            settings.canonicalisation_max_neighbors,
        )
        medoid_positions[label] = medoid_position
        neighbor_map[label] = neighbors
        neighbor_groups.append(neighbors)
    canonical_results = canonical_service.define_batch(neighbor_groups)

    output = ClusterOutput()
    for (label, indexes), canonical in zip(ordered_groups, canonical_results, strict=False):
        members = [problem_insights[index] for index in indexes]
        member_vectors = vectors[indexes]
        medoid_position = medoid_positions[label]
        neighbors = neighbor_map[label]
        representative = members[medoid_position]
        node_id = representative.journey_node_id
        aspect_counter = Counter(item.aspect for item in members if item.aspect)
        symptom_counter = Counter(_symptom_key(item) for item in members)
        intent_counter = Counter(item.customer_intent for item in members if item.customer_intent)
        dominant_aspect = aspect_counter.most_common(1)[0][0] if aspect_counter else None
        signature = _signature(representative)
        problem_id = _id("CP-", signature + canonical.title)
        cluster_id = _id("CL-", signature)

        submitted = [
            feedback[item.feedback_id].submitted_at
            for item in members
            if item.feedback_id in feedback and feedback[item.feedback_id].submitted_at
        ]
        customers = {
            feedback[item.feedback_id].synthetic_customer_ref
            for item in members
            if item.feedback_id in feedback and feedback[item.feedback_id].synthetic_customer_ref
        }
        sources = Counter(feedback[item.feedback_id].source_type for item in members if item.feedback_id in feedback)
        negative_count = sum(1 for item in members if item.sentiment in ("negative", "mixed"))
        first_seen = min(submitted) if submitted else None
        last_seen = max(submitted) if submitted else None

        original_statement = representative.reported_problem or canonical.problem_statement
        discovery_confidence = min(
            0.95,
            0.35
            + 0.12 * min(4, len(members))
            + 0.08 * min(3, len(customers))
            + (0.05 if len(sources) > 1 else 0.0),
        )

        problem = ProblemDraft(
            problem_id=problem_id,
            signature=signature,
            title=canonical.title,
            problem_statement=canonical.problem_statement[:400],
            canonical_description=canonical.description[:200],
            customer_intent=intent_counter.most_common(1)[0][0] if intent_counter else None,
            aspect=dominant_aspect,
            symptom_category=representative.symptom_category,
            journey_node_id=node_id,
            symptoms=sorted(
                {
                    _symptom_label(key, [item for item in members if _symptom_key(item) == key])
                    for key in symptom_counter
                }
            ),
            evidence_count=len(members),
            distinct_customers=len(customers),
            negative_count=negative_count,
            first_seen=first_seen,
            last_seen=last_seen,
            cluster_id=cluster_id,
            lifecycle_status="candidate",
            validation_status="candidate",
            human_review_status="unreviewed",
            discovery_confidence=round(discovery_confidence, 3),
            embedding_ref=f"embedding:{embedder.model_name}:{signature}",
            model_metadata={
                "embedding_model": embedder.model_name,
                "grouping": assignment.algorithm,
                "canonicalisation_provider": canonical.provider,
                "canonicalisation_model": canonical.model or "",
                "canonicalisation_fallback": str(canonical.fallback),
                "canonicalisation_prompt_version": canonical.prompt_version,
                "canonicalisation_neighbors": str(len(neighbors)),
                "component_weights": json.dumps(embedder.weights) if hasattr(embedder, "weights") else "",
            },
        )
        output.problems.append(problem)
        output.evidence[problem_id] = [(item, feedback[item.feedback_id]) for item in members if item.feedback_id in feedback]

        description = (
            f"{len(members)} evidence mention(s) across {len(sources)} source type(s). "
            f"Canonical definition from {len(neighbors)} nearest problem statement(s): \"{canonical.title[:180]}\". "
            f"Representative redacted evidence: \"{original_statement[:160]}\"."
        )
        output.clusters.append(
            {
                "cluster_id": cluster_id,
                "label": canonical.title,
                "description": description,
                "algorithm": assignment.algorithm + "+llm-canonicalisation",
                "params_json": json.dumps(assignment.params, sort_keys=True),
                "model_version": embedder.model_name,
                "member_count": len(members),
                "medoid_insight_id": representative.insight_id,
                "canonicalisation": {
                    "provider": canonical.provider,
                    "model": canonical.model,
                    "fallback": canonical.fallback,
                    "rationale": canonical.rationale,
                    "source_problem_ids": canonical.source_problem_ids,
                    "neighbor_count": len(neighbors),
                },
            }
        )

        node = taxonomy.by_id.get(node_id or "")
        match_text = f"{canonical.title} {canonical.problem_statement}"
        normalized = 0.0
        semantic_score = 0.0
        if node is None:
            candidate, raw_score = taxonomy.best_node(match_text)
            normalized = min(0.99, raw_score / 4.0)
            if candidate and normalized >= settings.taxonomy_accept_threshold:
                node = candidate
            elif semantic_vectors is not None and len(semantic_vectors) and len(member_vectors):
                similarities = semantic_vectors @ member_vectors[medoid_position]
                best_index = int(np.argmax(similarities))
                semantic_score = float(similarities[best_index])
                if semantic_score >= settings.taxonomy_semantic_threshold:
                    node = semantic_nodes[best_index]
                    normalized = max(normalized, min(0.99, semantic_score))
        if node:
            if semantic_score:
                normalized = max(normalized, min(0.99, semantic_score))
            else:
                _, raw_score = taxonomy.best_node(match_text, allowed={node.node_id})
                normalized = min(0.99, max(0.72, raw_score / 4.0))
            output.mappings.append(
                {
                    "mapping_id": _id("MP-", problem_id + node.node_id),
                    "problem_id": problem_id,
                    "node_id": node.node_id,
                    "mapping_type": "primary",
                    "confidence": round(normalized, 3),
                    "rationale": (
                        f"Aspect '{dominant_aspect}' maps declaratively to taxonomy node "
                        f"'{taxonomy.path_label(node.node_id)}'."
                    ),
                    "status": "candidate"
                    if normalized >= settings.taxonomy_accept_threshold
                    else "pending_review",
                    "taxonomy_version": taxonomy.version,
                }
            )
        else:
            parent = taxonomy.module_for(
                next((a.node_hint for a in lexicon.ASPECTS if a.key == dominant_aspect), None)
            )
            output.proposals.append(
                {
                    "proposal_id": _id("TP-", problem_id),
                    "problem_id": problem_id,
                    "suggested_name": canonical.title,
                    "parent_candidate": parent.node_id if parent else None,
                    "description": f"Potential new category for: {canonical.title}. Grounded in customer evidence.",
                    "example_evidence": (original_statement or "")[:300],
                    "confidence": round(normalized, 3),
                    "reason": (
                        "The canonical problem is near the open-set boundary and needs human taxonomy review."
                        if normalized >= settings.taxonomy_open_set_threshold
                        else "The canonical problem could not be confidently mapped to an existing taxonomy node."
                    ),
                }
            )

    return output
