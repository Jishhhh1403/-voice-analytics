from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import Settings


@dataclass
class ClusterAssignment:
    labels: list[int]
    algorithm: str
    params: dict[str, Any] = field(default_factory=dict)


def _hdbscan_labels(vectors: np.ndarray, settings: Settings) -> list[int] | None:
    if settings.clustering_provider.lower().replace("-", "_") != "hdbscan":
        return None
    try:
        import hdbscan  # type: ignore

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=max(2, settings.min_cluster_size),
            min_samples=max(1, settings.min_samples),
            cluster_selection_method=settings.cluster_selection_method,
            metric="euclidean",
            allow_single_cluster=True,
        )
        return [int(label) for label in clusterer.fit_predict(vectors)]
    except Exception:
        return None


def _agglomerative_labels(vectors: np.ndarray, settings: Settings) -> list[int]:
    from sklearn.cluster import AgglomerativeClustering

    if len(vectors) <= 1:
        return [0] * len(vectors)
    threshold = max(0.05, 1.0 - settings.clustering_similarity_threshold)
    clusterer = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        metric="euclidean",
        linkage="average",
    )
    return [int(label) for label in clusterer.fit_predict(vectors)]


def _split_large_clusters(vectors: np.ndarray, labels: list[int], max_size: int) -> list[int]:
    from sklearn.cluster import AgglomerativeClustering

    result = list(labels)
    next_label = max(result, default=-1) + 1
    queue = [label for label in sorted(set(result)) if label >= 0]
    while queue:
        label = queue.pop(0)
        indexes = np.asarray([index for index, value in enumerate(result) if value == label], dtype=int)
        if len(indexes) <= max_size:
            continue
        n_parts = math.ceil(len(indexes) / max_size)
        try:
            parts = AgglomerativeClustering(
                n_clusters=n_parts,
                metric="euclidean",
                linkage="average",
            ).fit_predict(vectors[indexes])
        except Exception:
            parts = np.arange(len(indexes)) // max_size
        for part in sorted(set(int(value) for value in parts)):
            part_indexes = indexes[np.asarray([value == part for value in parts])]
            for index in part_indexes:
                result[int(index)] = next_label
            if len(part_indexes) > max_size:
                queue.append(next_label)
            next_label += 1
    return result


def _split_noise(vectors: np.ndarray, labels: list[int]) -> list[int]:
    result = list(labels)
    next_label = max(result, default=-1) + 1
    for index, label in enumerate(result):
        if label == -1:
            result[index] = next_label
            next_label += 1
    return result


def assign_clusters(vectors: np.ndarray, settings: Settings) -> ClusterAssignment:
    params: dict[str, Any] = {
        "min_cluster_size": settings.min_cluster_size,
        "min_samples": settings.min_samples,
        "cluster_selection_method": settings.cluster_selection_method,
        "max_cluster_size": max(1, settings.max_cluster_size),
    }
    labels = _hdbscan_labels(vectors, settings)
    algorithm = "hdbscan"
    if labels is None:
        labels = _agglomerative_labels(vectors, settings)
        algorithm = "agglomerative-cosine-fallback"
        params["distance_threshold"] = max(0.05, 1.0 - settings.clustering_similarity_threshold)
    labels = _split_noise(vectors, labels)
    labels = _split_large_clusters(vectors, labels, max(1, settings.max_cluster_size))
    return ClusterAssignment(labels=labels, algorithm=algorithm, params=params)
