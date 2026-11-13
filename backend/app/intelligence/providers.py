from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from ..config import Settings
from .contracts import CleanFeedback, ExtractedInsight
from .extractor import extract_insights
from .text import normalize_text

PROMPT_VERSION = "extraction-2.0"

PROMPT = """You are an evidence-first banking customer-feedback analyst.
Extract sentence-level insights from the supplied redacted customer feedback.

Rules:
- One feedback may contain multiple independent insights. Return every independent issue.
- intent = the customer's goal. aspect = the banking feature or journey step. problem = the reported obstacle.
- symptom = what the customer observed. Never infer technical root cause, blame, churn risk, or facts not in the text.
- A reported problem must be traceable to an exact evidence span. If the evidence is ambiguous, return no insight.
- sentiment is aspect-level and must be one of: positive, negative, neutral, mixed.
- reported_outcome must be one of: completed, failed, blocked, abandoned, workaround_used, unknown.
- customer_effort must be one of: low, medium, high, unknown. Use unknown when not stated.
- Preserve the customer's language. Do not translate. Do not rewrite the evidence span.
- If a clause is positive and has no problem, set reported_problem to null and is_problem false.
- Missing data must be reported as unknown/null, never guessed or filled with a default.
- Never invent evidence. Prefer precision over recall.
Return strict JSON: {"results":[{"feedback_id":string,"insights":[{...}]}]}
Insight fields: sentence_index(int), customer_intent(string|null), intents(string[]), aspect(string|null),
aspects(string[]), reported_problem(string|null), reported_symptom(string|null), sentiment(string), emotion(string),
customer_effort(string), reported_outcome(string), evidence_span(string), is_problem(boolean),
field_confidence(object mapping field name to 0-1 confidence).
"""


class ExtractionProvider(Protocol):
    model_id: str

    def extract_batch(self, records: list[CleanFeedback]) -> dict[str, list[ExtractedInsight]]: ...


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(feedback_id: str, evidence: str, index: int) -> str:
    return "IN-" + hashlib.sha1(f"{feedback_id}|{evidence}|{index}".encode()).hexdigest()[:16]


def _safe_choice(value: Any, allowed: set[str], default: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in allowed else default


class RuleProvider:
    def __init__(self) -> None:
        self.model_id = "rules-v1"

    def extract_batch(self, records: list[CleanFeedback]) -> dict[str, list[ExtractedInsight]]:
        return {record.feedback_id: extract_insights(record, self.model_id) for record in records}


class LLMProvider:
    """Provider adapter for Gemini REST or an OpenAI-compatible endpoint (Ollama/vLLM)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.kind = "gemini" if settings.gemini_api_key else "openai_compatible"
        self.model_id = settings.llm_model if self.kind == "gemini" else settings.openai_model
        self.fallback = RuleProvider()

    def _call(self, records: list[CleanFeedback]) -> dict[str, Any]:
        payload_records = [
            {
                "feedback_id": record.feedback_id,
                "title": record.feedback_title,
                "text": record.feedback_text_redacted,
                "source_type": record.source_type,
                "platform": record.platform,
            }
            for record in records
        ]
        prompt = PROMPT + "\nFeedback records:\n" + json.dumps(payload_records, ensure_ascii=False)
        if self.kind == "gemini":
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.settings.llm_model}:generateContent"
            )
            response = httpx.post(
                url,
                params={"key": self.settings.gemini_api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
                },
                timeout=self.settings.llm_timeout_seconds,
            )
        else:
            response = httpx.post(
                self.settings.openai_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key or 'local'}"},
                json={
                    "model": self.settings.openai_model,
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=self.settings.llm_timeout_seconds,
            )
        response.raise_for_status()
        data = response.json()
        if self.kind == "gemini":
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            text = data["choices"][0]["message"]["content"]
        return json.loads(text)

    def _convert(self, record: CleanFeedback, payload: dict[str, Any]) -> list[ExtractedInsight]:
        insights: list[ExtractedInsight] = []
        for index, item in enumerate(payload.get("insights") or []):
            evidence = normalize_text(str(item.get("evidence_span") or ""))
            if not evidence or evidence not in record.feedback_text_redacted:
                continue
            sentence_index = int(item.get("sentence_index") or index)
            insights.append(
                ExtractedInsight(
                    insight_id=_id(record.feedback_id, evidence, sentence_index),
                    feedback_id=record.feedback_id,
                    sentence_index=sentence_index,
                    customer_intent=item.get("customer_intent"),
                    intents=[str(value) for value in (item.get("intents") or []) if value],
                    aspect=item.get("aspect"),
                    aspects=[str(value) for value in (item.get("aspects") or []) if value],
                    journey_node_id=None,
                    reported_problem=item.get("reported_problem"),
                    reported_symptom=item.get("reported_symptom"),
                    symptom_category=None,
                    sentiment=_safe_choice(item.get("sentiment"), {"positive", "negative", "neutral", "mixed"}, "neutral"),
                    emotion=item.get("emotion") or "none",
                    customer_effort=_safe_choice(
                        item.get("customer_effort"), {"low", "medium", "high", "unknown"}, "unknown"
                    ),
                    reported_outcome=_safe_choice(
                        item.get("reported_outcome"),
                        {"completed", "failed", "blocked", "abandoned", "workaround_used", "unknown"},
                        "unknown",
                    ),
                    evidence_span=evidence,
                    evidence_verified=True,
                    technical_root_cause="unknown",
                    language=record.language,
                    model_id=self.model_id,
                    prompt_version=PROMPT_VERSION,
                    extraction_timestamp=_now(),
                    extraction_method="llm",
                    confidence=0.7,
                    field_confidence={
                        str(key): float(value)
                        for key, value in (item.get("field_confidence") or {}).items()
                        if isinstance(key, str) and isinstance(value, int | float)
                    },
                    is_problem=bool(item.get("is_problem")),
                )
            )
        return insights

    def extract_batch(self, records: list[CleanFeedback]) -> dict[str, list[ExtractedInsight]]:
        try:
            data = self._call(records)
        except Exception:
            # Bounded retry is handled by the caller; fall back to deterministic rules
            # rather than dropping records.
            return self.fallback.extract_batch(records)
        by_id = {record.feedback_id: record for record in records}
        result: dict[str, list[ExtractedInsight]] = {}
        for item in data.get("results") or []:
            feedback_id = item.get("feedback_id")
            record = by_id.get(feedback_id)
            if not record:
                continue
            result[feedback_id] = self._convert(record, item)
        for record in records:
            result.setdefault(record.feedback_id, self.fallback.extract_batch([record])[record.feedback_id])
        return result


def build_provider(settings: Settings) -> ExtractionProvider:
    provider = settings.extraction_provider.lower()
    if provider in ("gemini", "openai_compatible", "llm", "auto"):
        if provider == "auto" and not (settings.gemini_api_key or settings.openai_api_key):
            return RuleProvider()
        return LLMProvider(settings)
    return RuleProvider()
