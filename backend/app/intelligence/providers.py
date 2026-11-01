from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from ..config import Settings
from .contracts import CleanFeedback, ExtractedInsight
from .extractor import extract_insights
from .text import normalize_text

PROMPT_VERSION = "extraction-1.0"

PROMPT = """You are an evidence-first banking customer-feedback analyst.
Extract sentence-level insights from the supplied redacted customer feedback.

Rules:
- One feedback may contain multiple independent insights.
- intent = customer's goal. aspect = banking feature being discussed. problem = reported obstacle.
- symptom = what happened. Do not infer root cause, blame, or facts not present in the text.
- sentiment is aspect-level and must be one of: positive, negative, neutral, mixed.
- reported_outcome must be one of: completed, failed, blocked, abandoned, workaround_used, unknown.
- customer_effort must be one of: low, medium, high, unknown.
- evidence_span MUST be an exact substring copied from the redacted feedback text.
- If a clause is positive and has no problem, set reported_problem to null and is_problem false.
- Never invent evidence. Prefer precision over recall.
Return strict JSON: {"results":[{"feedback_id":string,"insights":[{...}]}]}
Insight fields: sentence_index(int), customer_intent(string|null), aspect(string|null),
reported_problem(string|null), reported_symptom(string|null), sentiment(string), emotion(string),
customer_effort(string), reported_outcome(string), evidence_span(string), is_problem(boolean).
"""


class ExtractionProvider(Protocol):
    model_id: str

    def extract_batch(self, records: list[CleanFeedback]) -> dict[str, list[ExtractedInsight]]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(feedback_id: str, evidence: str, index: int) -> str:
    return "IN-" + hashlib.sha1(f"{feedback_id}|{evidence}|{index}".encode("utf-8")).hexdigest()[:16]


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
                    aspect=item.get("aspect"),
                    journey_node_id=None,
                    reported_problem=item.get("reported_problem"),
                    reported_symptom=item.get("reported_symptom"),
                    symptom_category=None,
                    sentiment=item.get("sentiment", "neutral"),
                    emotion=item.get("emotion") or "none",
                    customer_effort=item.get("customer_effort", "unknown"),
                    reported_outcome=item.get("reported_outcome", "unknown"),
                    evidence_span=evidence,
                    language=record.language,
                    model_id=self.model_id,
                    prompt_version=PROMPT_VERSION,
                    extraction_timestamp=_now(),
                    extraction_method="llm",
                    confidence=0.7,
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
