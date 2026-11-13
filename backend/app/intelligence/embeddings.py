from __future__ import annotations

import json
from collections.abc import Sequence

import numpy as np

from ..config import Settings


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
        matrix = self.vectorizer.fit_transform(corpus)
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


def _env(name: str) -> str:
    import os

    return os.environ.get(name, "")


def cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    if vectors.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    return np.clip(vectors @ vectors.T, -1.0, 1.0)


def vector_to_json(vector: np.ndarray) -> str:
    return json.dumps([round(float(value), 5) for value in vector], separators=(",", ":"))
