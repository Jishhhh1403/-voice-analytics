"""Configurable language detection.

The pipeline never translates or overwrites customer text. Detection returns
metadata only: an ISO-639-1 code, a confidence and whether the language is in
the configured supported set. The local heuristic is deterministic and requires
no model download; ``langdetect`` and ``fasttext`` are optional providers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SUPPORTED_LANGUAGES = {"en", "hi", "hinglish", "ta", "te", "bn", "mr", "unknown"}

_STOPWORDS: dict[str, set[str]] = {
    "en": {
        "the", "and", "is", "not", "my", "to", "of", "in", "on", "for", "with",
        "app", "bank", "cannot", "failed", "transfer", "payment", "account",
    },
    "hi": {"hai", "nahi", "mera", "meri", "aur", "ka", "ki", "ko", "me", "par", "nahin"},
}

_NON_LATIN = {
    "hi": re.compile(r"[\u0900-\u097F]"),
    "ta": re.compile(r"[\u0B80-\u0BFF]"),
    "te": re.compile(r"[\u0C00-\u0C7F]"),
    "bn": re.compile(r"[\u0980-\u09FF]"),
    "mr": re.compile(r"[\u0900-\u097F]"),
}


@dataclass
class LanguageResult:
    language: str
    confidence: float
    supported: bool
    provider: str


def _heuristic(text: str) -> LanguageResult:
    lowered = (text or "").lower()
    tokens = re.findall(r"[a-z']+", lowered)
    if not tokens:
        return LanguageResult("unknown", 0.0, False, "heuristic")
    for language, pattern in _NON_LATIN.items():
        if pattern.search(text or ""):
            return LanguageResult(language, 0.75, True, "heuristic")
    best_language = "en"
    best_score = 0.0
    for language, stopwords in _STOPWORDS.items():
        hits = sum(1 for token in tokens if token in stopwords)
        score = hits / max(1, len(tokens))
        if score > best_score:
            best_language, best_score = language, score
    # Latin-script Hindi often mixes English app vocabulary (Hinglish).
    hinglish_markers = {"hai", "nahi", "nahin", "kaam", "ho", "raha", "karo", "karta"}
    if sum(1 for token in tokens if token in hinglish_markers) >= 2:
        return LanguageResult("hinglish", max(0.4, min(0.85, best_score + 0.2)), True, "heuristic")
    confidence = min(0.95, 0.35 + best_score * 2)
    return LanguageResult(best_language, round(confidence, 3), best_language in SUPPORTED_LANGUAGES, "heuristic")


def _langdetect(text: str) -> LanguageResult:
    from langdetect import DetectorFactory, detect_langs  # type: ignore

    DetectorFactory.seed = 0
    results = detect_langs(text or "")
    if not results:
        return _heuristic(text)
    top = results[0]
    language = str(top.lang)
    return LanguageResult(language, round(float(top.prob), 3), language in SUPPORTED_LANGUAGES, "langdetect")


def _fasttext(text: str) -> LanguageResult:
    # The caller is responsible for providing a local model via FASTTEXT_MODEL.
    import os

    import fasttext  # type: ignore

    model_path = os.environ.get("FASTTEXT_MODEL", "")
    if not model_path:
        raise RuntimeError("FASTTEXT_MODEL is not configured")
    model = fasttext.load_model(model_path)
    labels, probabilities = model.predict((text or "").replace("\n", " "), k=1)
    language = labels[0].replace("__label__", "")
    return LanguageResult(language, round(float(probabilities[0]), 3), language in SUPPORTED_LANGUAGES, "fasttext")


def detect_language(text: str, provider: str = "heuristic", fallback_language: str = "en") -> LanguageResult:
    mode = (provider or "heuristic").lower()
    try:
        if mode == "langdetect":
            return _langdetect(text)
        if mode == "fasttext":
            return _fasttext(text)
    except Exception:
        pass
    result = _heuristic(text)
    if result.language == "unknown" and fallback_language:
        return LanguageResult(fallback_language, 0.0, fallback_language in SUPPORTED_LANGUAGES, "fallback")
    return result
