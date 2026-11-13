from __future__ import annotations

import numpy as np

from app.config import Settings
from app.intelligence.mds import ThemeInput, compute_theme_map, cosine_distance_matrix


def _settings(**overrides) -> Settings:
    return Settings(embedding_provider="local", mds_max_iter=100, **overrides)


def test_cosine_distance_is_symmetric_and_zero_on_diagonal():
    vectors = np.asarray([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)

    distances = cosine_distance_matrix(vectors)

    assert distances.shape == (3, 3)
    assert np.allclose(np.diag(distances), 0.0)
    assert np.allclose(distances, distances.T)
    assert distances[0, 1] == 1.0


def test_mds_maps_theme_centroids_and_nearest_neighbours():
    themes = [
        ThemeInput("CP-1", "Transfer pending", member_vectors=[np.asarray([1.0, 0.0, 0.0])]),
        ThemeInput("CP-2", "Transfer delayed", member_vectors=[np.asarray([0.95, 0.05, 0.0])]),
        ThemeInput("CP-3", "Statement download", member_vectors=[np.asarray([0.0, 1.0, 0.0])]),
    ]

    result = compute_theme_map(_settings(), themes)

    assert result.status == "OK"
    assert result.embedding_model == "member-centroid"
    assert len(result.points) == 3
    assert result.points[0]["vector_source"] == "member_centroid"
    assert result.neighbors
    first = [row for row in result.neighbors if row["problem_id"] == "CP-1"][0]
    assert first["neighbor_problem_id"] == "CP-2"
    assert first["cosine_similarity"] > 0.9


def test_mds_handles_single_theme_and_insufficient_themes():
    single = compute_theme_map(_settings(), [ThemeInput("CP-1", "Only theme")])

    assert single.status == "INSUFFICIENT_THEMES"
    assert single.points == []


def test_mds_places_two_themes_symmetrically():
    themes = [
        ThemeInput("CP-1", "Transfer pending", member_vectors=[np.asarray([1.0, 0.0])]),
        ThemeInput("CP-2", "Statement download", member_vectors=[np.asarray([0.0, 1.0])]),
    ]

    result = compute_theme_map(_settings(), themes)

    assert result.status == "OK"
    assert result.points[0]["x"] == -0.5
    assert result.points[1]["x"] == 0.5
    assert result.points[0]["y"] == 0.0
