"""Hybrid retrieval for Module F/G candidate generation.

Dense embeddings and sparse TF-IDF scores are combined with configurable
weights. Retrieval is only a candidate-generation step: the backlog validator
still applies journey, intent and acceptance-criteria coverage checks before
deciding a relationship. An optional cross-encoder reranker is used when
configured and installed; otherwise the hybrid ranking is deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..config import Settings
from .embeddings import build_embedder


@dataclass
class RetrievalOutput:
    scores: np.ndarray
    model_name: str
    dense_weight: float
    sparse_weight: float
    reranked: bool = False
    dense_scores: np.ndarray | None = None
    sparse_scores: np.ndarray | None = None


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return matrix
    maxima = matrix.max(axis=1, keepdims=True)
    maxima[maxima == 0] = 1.0
    return matrix / maxima


class HybridRetriever:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dense_weight = settings.retrieval_dense_weight
        self.sparse_weight = settings.retrieval_sparse_weight
        self.embedder = None
        self.vectorizer = None
        self.problem_vectors = None
        self.sparse_matrix = None
        self.model_name = "unfitted"
        self._texts: list[str] = []

    def fit(self, problem_texts: Sequence[str]) -> HybridRetriever:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._texts = list(problem_texts)
        self.embedder, vectors = build_embedder(self.settings, problem_texts)
        self.problem_vectors = vectors
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True, stop_words="english")
        self.sparse_matrix = self.vectorizer.fit_transform([text or "empty" for text in problem_texts])
        self.model_name = self.embedder.model_name
        return self

    def score(self, query_texts: Sequence[str]) -> RetrievalOutput:
        from sklearn.metrics.pairwise import cosine_similarity

        if self.embedder is None or self.vectorizer is None:
            raise RuntimeError("HybridRetriever must be fitted before scoring")
        dense_queries = self.embedder.transform(query_texts)
        dense = np.clip(dense_queries @ self.problem_vectors.T, -1.0, 1.0)
        sparse_queries = self.vectorizer.transform([text or "empty" for text in query_texts])
        sparse = cosine_similarity(sparse_queries, self.sparse_matrix)
        dense_matrix = np.asarray(dense, dtype=np.float32)
        sparse_matrix = np.asarray(sparse, dtype=np.float32)
        combined = self.dense_weight * _normalise_rows(dense_matrix) + self.sparse_weight * _normalise_rows(
            sparse_matrix
        )
        reranked = False
        if (self.settings.reranker_provider or "none").lower() in {"cross_encoder", "cross-encoder"}:
            combined, reranked = self._rerank(query_texts, combined)
        return RetrievalOutput(
            scores=np.asarray(combined, dtype=np.float32),
            model_name=self.model_name,
            dense_weight=self.dense_weight,
            sparse_weight=self.sparse_weight,
            reranked=reranked,
            dense_scores=dense_matrix,
            sparse_scores=sparse_matrix,
        )

    def _rerank(self, query_texts: Sequence[str], scores: np.ndarray) -> tuple[np.ndarray, bool]:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore

            model = CrossEncoder(self.settings.cross_encoder_model)
        except Exception:
            return scores, False
        reranked = scores.copy()
        top_k = max(1, self.settings.retrieval_top_k)
        for row_index, query in enumerate(query_texts):
            candidates = np.argsort(scores[row_index])[::-1][:top_k]
            pairs = [(query, self._texts[index]) for index in candidates]
            try:
                relevance = model.predict(pairs)
            except Exception:
                return scores, False
            for candidate_index, value in zip(candidates, relevance, strict=False):
                # Blend the cross-encoder with the hybrid score; never discard the
                # deterministic signal entirely.
                reranked[row_index, candidate_index] = 0.6 * float(value) + 0.4 * float(scores[row_index, candidate_index])
        return reranked, True

    @property
    def problem_texts(self) -> Sequence[str]:
        return self._texts
