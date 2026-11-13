"""MDS theme map.

Canonical customer problems are treated as themes. Each theme gets one
representative embedding, pairwise cosine distances are computed, and metric
MDS projects the distance matrix into two dimensions.

Positions are semantic only. They are not severity, priority or causal
signals; business meaning is attached by the API/UI from measurement and
priority snapshots.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import Settings
from .embeddings import build_embedder, vector_to_json


@dataclass
class ThemeInput:
    problem_id: str
    title: str
    problem_statement: str = ""
    canonical_description: str | None = None
    symptoms: list[str] = field(default_factory=list)
    journey_node_id: str | None = None
    journey_name: str | None = None
    member_vectors: list[np.ndarray] = field(default_factory=list)

    def text(self) -> str:
        parts = [
            self.title,
            self.canonical_description or "",
            self.problem_statement,
            " ".join(self.symptoms),
            self.journey_name or "",
            self.journey_node_id or "",
        ]
        return " | ".join(part.strip() for part in parts if part and part.strip())


@dataclass
class MdsResult:
    status: str
    points: list[dict[str, Any]] = field(default_factory=list)
    neighbors: list[dict[str, Any]] = field(default_factory=list)
    theme_vectors: list[dict[str, Any]] = field(default_factory=list)
    stress: float | None = None
    normalized_stress: float | None = None
    stress_status: str | None = None
    embedding_model: str | None = None
    dimensions: int | None = None
    methodology_version: str = "mds-1.0.0"
    params: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def cosine_distance_matrix(vectors: np.ndarray) -> np.ndarray:
    """Return pairwise cosine distance (1 - cosine similarity)."""
    if vectors.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    normalized = _l2_normalize(np.asarray(vectors, dtype=np.float32))
    similarity = np.clip(normalized @ normalized.T, -1.0, 1.0)
    distance = np.clip(1.0 - similarity, 0.0, 2.0)
    np.fill_diagonal(distance, 0.0)
    distance = (distance + distance.T) / 2.0
    return distance.astype(np.float32)


def build_theme_vectors(
    settings: Settings,
    themes: Sequence[ThemeInput],
    embedding_model: str | None = None,
) -> tuple[np.ndarray, str, list[str]]:
    """Build one representative vector per theme.

    Member centroids are preferred when every theme has at least one member
    vector and all vectors share the same dimensionality. Otherwise all theme
    vectors are recomputed from theme text with a single embedder so vectors
    from different spaces are never mixed.
    """
    if not themes:
        return np.zeros((0, 0), dtype=np.float32), embedding_model or "none", []

    member_vectors = [theme.member_vectors for theme in themes]
    dimensions = {vector.shape[0] for vectors in member_vectors for vector in vectors}
    use_members = all(member_vectors) and len(dimensions) == 1
    if use_members:
        matrix = np.asarray(
            [np.mean(np.vstack(vectors), axis=0) for vectors in member_vectors],
            dtype=np.float32,
        )
        model_name = embedding_model or "member-centroid"
        sources = ["member_centroid" for _ in themes]
    else:
        embedder, matrix = build_embedder(settings, [theme.text() or "empty theme" for theme in themes])
        model_name = embedder.model_name
        sources = ["theme_text" for _ in themes]
    return _l2_normalize(np.asarray(matrix, dtype=np.float32)), model_name, sources


def _stress_status(normalized_stress: float | None) -> str | None:
    if normalized_stress is None:
        return None
    if normalized_stress <= 0.10:
        return "good"
    if normalized_stress <= 0.20:
        return "caution"
    return "poor"


def _mds_coordinates(
    distances: np.ndarray,
    settings: Settings,
) -> tuple[np.ndarray, float | None, float | None, str | None]:
    n_themes = distances.shape[0]
    if n_themes == 0:
        return np.zeros((0, 2), dtype=np.float32), None, None, None
    if n_themes == 1:
        return np.zeros((1, 2), dtype=np.float32), 0.0, 0.0, "good"
    if n_themes == 2:
        distance = float(distances[0, 1])
        coords = np.asarray([[-distance / 2.0, 0.0], [distance / 2.0, 0.0]], dtype=np.float32)
        return coords, 0.0, 0.0, "good"
    if np.allclose(distances, 0.0):
        return np.zeros((n_themes, 2), dtype=np.float32), 0.0, 0.0, "good"

    from sklearn.manifold import MDS

    model = MDS(
        n_components=2,
        metric=True,
        dissimilarity="precomputed",
        random_state=settings.mds_random_state,
        normalized_stress="auto",
        max_iter=settings.mds_max_iter,
        n_init=4,
    )
    coords = np.asarray(model.fit_transform(distances), dtype=np.float32)
    stress = float(model.stress_)
    denominator = float(np.sum(distances**2))
    normalized = float(stress / denominator) if denominator > 0 else None
    return coords, stress, normalized, _stress_status(normalized)


def _display_coordinates(coords: np.ndarray, scale: float) -> np.ndarray:
    if coords.size == 0:
        return coords
    centered = coords - coords.mean(axis=0, keepdims=True)
    magnitude = float(np.max(np.abs(centered))) if centered.size else 0.0
    if magnitude == 0:
        return centered
    return centered / magnitude * max(0.1, scale)


def _nearest_neighbors(
    themes: Sequence[ThemeInput],
    vectors: np.ndarray,
    limit: int,
) -> list[dict[str, Any]]:
    if len(themes) < 2 or vectors.size == 0:
        return []
    similarity = np.clip(_l2_normalize(vectors) @ _l2_normalize(vectors).T, -1.0, 1.0)
    rows: list[dict[str, Any]] = []
    for index, theme in enumerate(themes):
        order = [candidate for candidate in np.argsort(-similarity[index]) if candidate != index][:limit]
        for rank, candidate in enumerate(order, start=1):
            rows.append(
                {
                    "problem_id": theme.problem_id,
                    "neighbor_problem_id": themes[int(candidate)].problem_id,
                    "rank": rank,
                    "cosine_similarity": round(float(similarity[index, candidate]), 5),
                    "cosine_distance": round(float(max(0.0, 1.0 - similarity[index, candidate])), 5),
                }
            )
    return rows


def compute_theme_map(
    settings: Settings,
    themes: Sequence[ThemeInput],
    embedding_model: str | None = None,
) -> MdsResult:
    themes = list(themes)
    if len(themes) < settings.mds_min_themes:
        return MdsResult(
            status="INSUFFICIENT_THEMES",
            methodology_version=settings.mds_methodology_version,
            params={"min_themes": settings.mds_min_themes},
            notes=["At least two canonical problems are required to build a theme map."],
        )

    vectors, model_name, sources = build_theme_vectors(settings, themes, embedding_model)
    distances = cosine_distance_matrix(vectors)
    coords, stress, normalized_stress, stress_status = _mds_coordinates(distances, settings)
    display = _display_coordinates(coords, settings.mds_coordinate_scale)
    neighbors = _nearest_neighbors(themes, vectors, settings.mds_neighbors)

    points: list[dict[str, Any]] = []
    theme_vectors: list[dict[str, Any]] = []
    for index, theme in enumerate(themes):
        points.append(
            {
                "problem_id": theme.problem_id,
                "x": round(float(coords[index, 0]), 6),
                "y": round(float(coords[index, 1]), 6),
                "display_x": round(float(display[index, 0]), 6),
                "display_y": round(float(display[index, 1]), 6),
                "vector_source": sources[index],
            }
        )
        theme_vectors.append(
            {
                "problem_id": theme.problem_id,
                "model_name": model_name,
                "dimensions": int(vectors.shape[1]),
                "vector_json": vector_to_json(vectors[index]),
                "source": sources[index],
            }
        )

    return MdsResult(
        status="OK",
        points=points,
        neighbors=neighbors,
        theme_vectors=theme_vectors,
        stress=round(stress, 6) if stress is not None else None,
        normalized_stress=round(normalized_stress, 6) if normalized_stress is not None else None,
        stress_status=stress_status,
        embedding_model=model_name,
        dimensions=int(vectors.shape[1]) if vectors.size else None,
        methodology_version=settings.mds_methodology_version,
        params={
            "distance_metric": "cosine",
            "mds_metric": True,
            "random_state": settings.mds_random_state,
            "max_iter": settings.mds_max_iter,
            "neighbors": settings.mds_neighbors,
            "coordinate_scale": settings.mds_coordinate_scale,
        },
        notes=[
            "Positions represent semantic similarity only; axes have arbitrary orientation.",
            "Bubble size and colour carry business meaning, not the MDS coordinates.",
        ],
    )
