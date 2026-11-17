from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import numpy as np

from ..config import Settings


def _fit_tfidf(vectorizer, texts: Sequence[str]):
    from sklearn.feature_extraction.text import TfidfVectorizer

    try:
        vectorizer.fit(texts)
        return vectorizer
    except ValueError:
        params = vectorizer.get_params()
        params.update(max_df=1.0, stop_words=None)
        fallback = TfidfVectorizer(**params)
        try:
            fallback.fit(texts)
        except ValueError:
            fallback.fit(["empty"] * max(1, len(texts)))
        return fallback


class LocalTfidfEmbedder:
    """Offline embedding adapter using TF-IDF + LSA.

    This is intentionally dependency-light: it runs inside the local Docker
    Compose stack without downloading any model weights. Vectors are used only
    for candidate retrieval; final problem grouping and backlog validation add
    lexical, journey and symptom-scope checks.
    """

    def __init__(self, dimensions: int = 96) -> None:
        self.dimensions = dimensions
        self.model_name = f"tfidf-svd-{dimensions}-v1"
        self.vectorizer = None
        self.svd = None

    def fit_transform(self, texts: Sequence[str]) -> np.ndarray:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize

        corpus = [text or "empty" for text in texts]
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=1,
            max_df=0.95,
            sublinear_tf=True,
            stop_words="english",
            strip_accents="unicode",
        )
        self.vectorizer = _fit_tfidf(self.vectorizer, corpus)
        matrix = self.vectorizer.transform(corpus)
        n_samples, n_features = matrix.shape
        components = max(2, min(self.dimensions, n_features - 1, n_samples - 1))
        if n_features > 2 and n_samples > 2 and components >= 2:
            self.svd = TruncatedSVD(n_components=components, random_state=42)
            dense = self.svd.fit_transform(matrix)
        else:
            dense = matrix.toarray()
        return normalize(np.asarray(dense, dtype=np.float32))

    def transform(self, texts: Sequence[str]) -> np.ndarray:
        from sklearn.preprocessing import normalize

        if self.vectorizer is None:
            return self.fit_transform(texts)
        matrix = self.vectorizer.transform([text or "empty" for text in texts])
        dense = self.svd.transform(matrix) if self.svd is not None else matrix.toarray()
        return normalize(np.asarray(dense, dtype=np.float32))


class WeightedTfidfEmbedder:
    COMPONENTS = ("journey_node", "symptom", "feedback")

    def __init__(self, dimensions: int = 96, weights: dict[str, float] | None = None) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.dimensions = dimensions
        raw = weights or {}
        values = {name: max(0.0, float(raw.get(name, 0.0))) for name in self.COMPONENTS}
        total = sum(values.values()) or 1.0
        self.weights = {name: value / total for name, value in values.items()}
        self.model_name = "tfidf-weighted-" + "-".join(
            f"{name}{self.weights[name]:.2f}" for name in self.COMPONENTS
        ) + f"-svd-{dimensions}-v1"
        self.vectorizers = {
            name: TfidfVectorizer(
                ngram_range=(1, 2),
                min_df=1,
                max_df=0.95,
                sublinear_tf=True,
                stop_words="english",
                strip_accents="unicode",
            )
            for name in self.COMPONENTS
        }
        self.svd = None

    def _matrix(self, components: Sequence[dict[str, str]]) -> Any:
        from scipy import sparse

        blocks = []
        for name in self.COMPONENTS:
            texts = [str(item.get(name) or "") or "empty" for item in components]
            matrix = self.vectorizers[name].transform(texts)
            blocks.append(matrix * self.weights[name])
        matrix = sparse.hstack(blocks, format="csr")
        if matrix.shape[1] < 2:
            matrix = sparse.hstack([matrix, sparse.csr_matrix((matrix.shape[0], 2 - matrix.shape[1]))], format="csr")
        return matrix

    def _dense(self, matrix: Any, fit: bool) -> np.ndarray:
        from scipy import sparse
        from sklearn.preprocessing import normalize

        if fit:
            matrix = matrix.tocsr()
            fit_matrix = matrix
            if fit_matrix.shape[0] < 2:
                fit_matrix = sparse.vstack(
                    [fit_matrix, sparse.csr_matrix((1, fit_matrix.shape[1]))], format="csr"
                )
            if fit_matrix.nnz == 0:
                fit_matrix = np.eye(fit_matrix.shape[1], dtype=np.float32)
            n_components = min(
                self.dimensions,
                max(2, fit_matrix.shape[1] - 1),
                max(2, fit_matrix.shape[0] - 1),
            )
            from sklearn.decomposition import TruncatedSVD

            self.svd = TruncatedSVD(n_components=n_components, random_state=42)
            self.svd.fit(fit_matrix)
        dense = self.svd.transform(matrix) if self.svd is not None else matrix.toarray()
        return normalize(np.asarray(dense, dtype=np.float32))

    def fit_transform(self, components: Sequence[dict[str, str]]) -> np.ndarray:
        for name in self.COMPONENTS:
            texts = [str(item.get(name) or "") or "empty" for item in components]
            self.vectorizers[name] = _fit_tfidf(self.vectorizers[name], texts)
        return self._dense(self._matrix(components), fit=True)

    def transform(self, components: Sequence[dict[str, str]]) -> np.ndarray:
        return self._dense(self._matrix(components), fit=False)

    def transform_texts(self, texts: Sequence[str]) -> np.ndarray:
        rows = [{"journey_node": "", "symptom": "", "feedback": text or ""} for text in texts]
        return self.transform(rows)


class BGELargeEmbedder:
    def __init__(self, model_name: str, query_instruction: str = "", batch_size: int = 64) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model = SentenceTransformer(model_name)
        self.model_name = f"bge-{model_name}"
        self.query_instruction = query_instruction
        self.batch_size = max(1, batch_size)

    def fit_transform(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, self.query_instruction)

    def transform(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, "")

    def _encode(self, texts: Sequence[str], instruction: str) -> np.ndarray:
        prepared = [f"{instruction}{text or 'empty'}" for text in texts]
        vectors = self.model.encode(
            prepared,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return np.asarray(vectors, dtype=np.float32)


class GeminiEmbedder:
    def __init__(self, api_key: str, model: str = "text-embedding-004") -> None:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is required for Gemini embeddings")
        self.api_key = api_key
        self.model = model
        self.model_name = f"gemini-{model}"

    def fit_transform(self, texts: Sequence[str]) -> np.ndarray:
        import httpx
        from sklearn.preprocessing import normalize

        vectors: list[list[float]] = []
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"
        for start in range(0, len(texts), 100):
            batch = texts[start : start + 100]
            payload = {
                "requests": [
                    {"model": f"models/{self.model}", "content": {"parts": [{"text": text or "empty"}]}}
                    for text in batch
                ]
            }
            response = httpx.post(url, params={"key": self.api_key}, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            vectors.extend([item["values"] for item in data.get("embeddings", [])])
        return normalize(np.asarray(vectors, dtype=np.float32))

    def transform(self, texts: Sequence[str]) -> np.ndarray:
        return self.fit_transform(texts)




class SentenceTransformerEmbedder:
    """Dense embeddings via sentence-transformers when installed.

    Model weights are not bundled; deployments that choose this provider must
    make the model available locally or allow the library to download it.
    """

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model = SentenceTransformer(model_name)
        self.model_name = f"st-{model_name.split('/')[-1]}"

    def fit_transform(self, texts: Sequence[str]) -> np.ndarray:
        from sklearn.preprocessing import normalize

        vectors = self.model.encode([text or "empty" for text in texts], normalize_embeddings=False)
        return normalize(np.asarray(vectors, dtype=np.float32))

    def transform(self, texts: Sequence[str]) -> np.ndarray:
        return self.fit_transform(texts)


class VertexEmbedder:
    """Vertex AI text embeddings over the REST API using application default credentials."""

    def __init__(self, project: str, location: str, model: str) -> None:
        if not project:
            raise RuntimeError("BIGQUERY_PROJECT (or GOOGLE_CLOUD_PROJECT) is required for Vertex embeddings")
        self.project = project
        self.location = location
        self.model = model
        self.model_name = f"vertex-{model}"

    def _access_token(self) -> str:
        import google.auth  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore

        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(Request())
        return credentials.token

    def fit_transform(self, texts: Sequence[str]) -> np.ndarray:
        import httpx
        from sklearn.preprocessing import normalize

        url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project}"
            f"/locations/{self.location}/publishers/google/models/{self.model}:predict"
        )
        token = self._access_token()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 100):
            batch = texts[start : start + 100]
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"instances": [{"content": text or "empty"} for text in batch]},
                timeout=60,
            )
            response.raise_for_status()
            vectors.extend([item["embeddings"]["values"] for item in response.json().get("predictions", [])])
        return normalize(np.asarray(vectors, dtype=np.float32))

    def transform(self, texts: Sequence[str]) -> np.ndarray:
        return self.fit_transform(texts)


def build_embedder(settings: Settings, texts: Sequence[str]):
    provider = settings.embedding_provider.lower().replace("-", "_")
    try:
        if provider == "gemini" and settings.gemini_api_key:
            embedder = GeminiEmbedder(settings.gemini_api_key, settings.llm_model.replace("gemini", "text-embedding"))
            return embedder, embedder.fit_transform(texts)
        if provider in {"sentence_transformer", "sentence_transformers", "st"}:
            embedder = SentenceTransformerEmbedder(settings.sentence_transformer_model)
            return embedder, embedder.fit_transform(texts)
        if provider == "vertex":
            project = settings.bigquery_project or _env("GOOGLE_CLOUD_PROJECT")
            embedder = VertexEmbedder(project, settings.vertex_location, settings.vertex_embedding_model)
            return embedder, embedder.fit_transform(texts)
    except Exception:
        pass
    # Deterministic offline fallback; the pipeline never fails because an
    # optional embedding provider is unavailable.
    embedder = LocalTfidfEmbedder(settings.embedding_dimensions)
    return embedder, embedder.fit_transform(texts)


def _component_weights(settings: Settings) -> dict[str, float]:
    return {
        "journey_node": settings.tfidf_weight_journey_node,
        "symptom": settings.tfidf_weight_symptom,
        "feedback": settings.tfidf_weight_feedback,
    }


def weighted_text(components: dict[str, str], weights: dict[str, float]) -> str:
    parts: list[str] = []
    for name, weight in weights.items():
        text = str(components.get(name) or "").strip()
        if not text or weight <= 0:
            continue
        repeats = max(1, round(weight * 20))
        parts.append(" ".join([text] * repeats))
    return " ".join(parts) or "empty"


def build_weighted_embedder(settings: Settings, components: Sequence[dict[str, str]]):
    provider = settings.embedding_provider.lower().replace("-", "_")
    weights = _component_weights(settings)
    texts = [weighted_text(item, weights) for item in components]
    try:
        if provider == "gemini" and settings.gemini_api_key:
            embedder = GeminiEmbedder(settings.gemini_api_key, settings.llm_model.replace("gemini", "text-embedding"))
            return embedder, embedder.fit_transform(texts)
        if provider in {"sentence_transformer", "sentence_transformers", "st"}:
            embedder = SentenceTransformerEmbedder(settings.sentence_transformer_model)
            return embedder, embedder.fit_transform(texts)
        if provider == "vertex":
            project = settings.bigquery_project or _env("GOOGLE_CLOUD_PROJECT")
            embedder = VertexEmbedder(project, settings.vertex_location, settings.vertex_embedding_model)
            return embedder, embedder.fit_transform(texts)
    except Exception:
        pass
    embedder = WeightedTfidfEmbedder(settings.embedding_dimensions, weights)
    return embedder, embedder.fit_transform(components)


def build_coverage_embedder(
    settings: Settings,
    canonical_texts: Sequence[str],
    backlog_texts: Sequence[str],
):
    from sklearn.preprocessing import normalize

    try:
        embedder = BGELargeEmbedder(
            settings.bge_model_name,
            settings.bge_query_instruction,
            settings.embedding_batch_size,
        )
        canonical_vectors = embedder.fit_transform(canonical_texts)
        backlog_vectors = embedder.transform(backlog_texts)
        return embedder, canonical_vectors, backlog_vectors
    except Exception:
        embedder = LocalTfidfEmbedder(settings.embedding_dimensions)
        combined = [text or "empty" for text in list(canonical_texts) + list(backlog_texts)]
        vectors = embedder.fit_transform(combined)
        split = len(canonical_texts)
        return embedder, vectors[:split], normalize(np.asarray(vectors[split:], dtype=np.float32))


def _env(name: str) -> str:
    import os

    return os.environ.get(name, "")


def cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    if vectors.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    return np.clip(vectors @ vectors.T, -1.0, 1.0)


def vector_to_json(vector: np.ndarray) -> str:
    return json.dumps([round(float(value), 5) for value in vector], separators=(",", ":"))
