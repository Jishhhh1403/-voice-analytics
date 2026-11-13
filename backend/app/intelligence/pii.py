"""PII redaction with an optional Presidio layer.

The regex implementation in ``text.py`` remains the deterministic baseline and
fallback. Presidio is used only when explicitly configured and installed; this
keeps local runs reproducible and avoids a hard dependency on spaCy models.

Banking-specific recognisers are registered for account numbers, card numbers,
Aadhaar, phone numbers, email addresses, IFSC codes and UPI identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .text import normalize_text
from .text import redact_pii as regex_redact_pii

BANKING_PATTERNS: dict[str, str] = {
    "IN_IFSC": r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    "IN_UPI": r"\b[\w.-]{2,}@[a-zA-Z]{2,}\b",
    "IN_AADHAAR": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
    "IN_ACCOUNT": r"\b(?:a/c|account|acct|acc)\s*(?:no\.?|number)?\s*[:#-]?\s*\d{6,18}\b",
}


@dataclass
class RedactionResult:
    text: str
    labels: list[str] = field(default_factory=list)
    provider_used: str = "regex"
    recognizer_details: dict[str, int] = field(default_factory=dict)


def _presidio_recognizers() -> list[Any]:
    from presidio_analyzer import Pattern, PatternRecognizer  # type: ignore

    recognizers: list[Any] = []
    for name, pattern in BANKING_PATTERNS.items():
        confidence = 0.6 if name in {"IN_UPI", "IN_ACCOUNT"} else 0.8
        recognizers.append(
            PatternRecognizer(
                supported_entity=name,
                patterns=[Pattern(name=name.lower(), regex=pattern, score=confidence)],
            )
        )
    return recognizers


class PresidioRedactor:
    """Lazily-initialised Presidio adapter. Fails closed to regex."""

    def __init__(self, language: str = "en") -> None:
        from presidio_analyzer import AnalyzerEngine  # type: ignore

        self.language = language
        self.analyzer = AnalyzerEngine()
        for recognizer in _presidio_recognizers():
            self.analyzer.registry.add_recognizer(recognizer)

    def redact(self, text: str) -> RedactionResult:
        normalized = normalize_text(text)
        results = self.analyzer.analyze(text=normalized, language=self.language)
        # Replace from right to left so character offsets stay valid.
        redacted = normalized
        labels: list[str] = []
        counts: dict[str, int] = {}
        for result in sorted(results, key=lambda item: item.start, reverse=True):
            label = str(result.entity_type).upper()
            redacted = redacted[: result.start] + f"[{label}]" + redacted[result.end :]
            labels.append(label)
            counts[label] = counts.get(label, 0) + 1
        # Presidio may miss long bare digit runs; apply the deterministic guard.
        redacted, regex_labels = regex_redact_pii(redacted)
        for label in regex_labels:
            labels.append(label)
            counts[label] = counts.get(label, 0) + 1
        return RedactionResult(
            text=normalize_text(redacted),
            labels=sorted(set(labels)),
            provider_used="presidio",
            recognizer_details=counts,
        )


def redact_pii_enhanced(text: str, provider: str = "regex", language: str = "en") -> RedactionResult:
    """Redact PII using the configured provider with a deterministic fallback.

    ``provider`` accepts ``regex``, ``presidio`` or ``hybrid``. Any Presidio
    failure (missing dependency, unsupported language, model error) silently
    falls back to the regex baseline and is reported in the result metadata.
    """

    mode = (provider or "regex").lower()
    if mode in {"presidio", "hybrid"}:
        try:
            return PresidioRedactor(language).redact(text)
        except Exception:
            pass
    redacted, labels = regex_redact_pii(text)
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return RedactionResult(text=redacted, labels=labels, provider_used="regex", recognizer_details=counts)


__all__ = ["RedactionResult", "redact_pii_enhanced", "BANKING_PATTERNS", "re"]
