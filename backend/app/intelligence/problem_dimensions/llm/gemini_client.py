"""Structured LLM clients with bounded retries and auditable logging."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

import httpx

from ....config import Settings

logger = logging.getLogger("bci.factor_interpretation")


class StructuredLLMProvider(Protocol):
    provider: str
    model_id: str | None

    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        prompt_version: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class StructuredLLMError(RuntimeError):
    """Raised when a structured response cannot be produced."""


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(
        token in text
        for token in (
            "resource_exhausted",
            "quota",
            "rate limit",
            "rate_limit",
            "429",
            "too many requests",
        )
    )


def _parse_json_content(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise StructuredLLMError("Model response must be a JSON object.")
    return parsed


class GeminiStructuredProvider:
    provider = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_id = settings.problem_dimension_llm_model or settings.gemini_model or settings.llm_model

    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        prompt_version: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:  # pragma: no cover - dependency guard
            raise StructuredLLMError("google-genai is not installed.") from exc
        if not self.settings.gemini_api_key:
            raise StructuredLLMError("GEMINI_API_KEY is not configured.")

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=self.settings.problem_dimension_llm_temperature,
            max_output_tokens=self.settings.problem_dimension_llm_max_output_tokens,
        )
        attempts = max(1, self.settings.problem_dimension_llm_max_attempts)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                client = genai.Client(
                    api_key=self.settings.gemini_api_key,
                    http_options=types.HttpOptions(
                        timeout=max(1, self.settings.problem_dimension_llm_timeout_seconds) * 1000,
                    ),
                )
                response = client.models.generate_content(
                    model=self.model_id,
                    contents=prompt,
                    config=config,
                )
                latency_ms = round((time.monotonic() - started) * 1000, 2)
                usage = getattr(response, "usage_metadata", None)
                logger.info(
                    "factor interpretation LLM metrics model=%s prompt_version=%s attempt=%s "
                    "latency_ms=%s prompt_tokens=%s output_tokens=%s",
                    self.model_id,
                    prompt_version,
                    attempt,
                    latency_ms,
                    getattr(usage, "prompt_token_count", None),
                    getattr(usage, "candidates_token_count", None),
                )
                parsed = getattr(response, "parsed", None)
                if parsed is not None:
                    if hasattr(parsed, "model_dump"):
                        return parsed.model_dump()
                    return dict(parsed)
                text = getattr(response, "text", None)
                if not text:
                    raise StructuredLLMError("Gemini returned no structured response.")
                return _parse_json_content(text)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "factor interpretation LLM call failed model=%s prompt_version=%s attempt=%s error=%s",
                    self.model_id,
                    prompt_version,
                    attempt,
                    exc,
                )
                if _is_quota_error(exc):
                    break
                if attempt < attempts:
                    time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
        raise StructuredLLMError(f"Gemini structured generation failed: {last_error}") from last_error


class OpenAICompatibleStructuredProvider:
    """Structured client for Ollama, vLLM or any OpenAI-compatible endpoint."""

    provider = "openai_compatible"

    def __init__(
        self,
        settings: Settings,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = (base_url or settings.problem_dimension_llm_base_url or settings.openai_base_url).rstrip("/")
        self.model_id = model or settings.problem_dimension_llm_model or settings.openai_model
        self.api_key = api_key or settings.problem_dimension_llm_api_key or settings.openai_api_key or "local"

    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        prompt_version: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise StructuredLLMError("No OpenAI-compatible base URL is configured.")
        schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True)
        user_prompt = (
            f"{prompt}\n\nReturn only one JSON object matching this JSON schema exactly:\n{schema_text}"
        )
        attempts = max(1, self.settings.problem_dimension_llm_max_attempts)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                request_payload = {
                    "model": self.model_id,
                    "temperature": self.settings.problem_dimension_llm_temperature,
                    "max_tokens": self.settings.problem_dimension_llm_max_output_tokens,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_prompt},
                    ],
                }
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request_payload,
                    timeout=max(1, self.settings.problem_dimension_llm_timeout_seconds),
                )
                if response.status_code in {400, 404, 422} and "response_format" in request_payload:
                    request_payload.pop("response_format", None)
                    response = httpx.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=request_payload,
                        timeout=max(1, self.settings.problem_dimension_llm_timeout_seconds),
                    )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                latency_ms = round((time.monotonic() - started) * 1000, 2)
                logger.info(
                    "factor interpretation LLM metrics provider=%s model=%s prompt_version=%s "
                    "attempt=%s latency_ms=%s",
                    self.provider,
                    self.model_id,
                    prompt_version,
                    attempt,
                    latency_ms,
                )
                return _parse_json_content(content)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "factor interpretation LLM call failed provider=%s model=%s prompt_version=%s "
                    "attempt=%s error=%s",
                    self.provider,
                    self.model_id,
                    prompt_version,
                    attempt,
                    exc,
                )
                if _is_quota_error(exc):
                    break
                if attempt < attempts:
                    time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
        raise StructuredLLMError(f"OpenAI-compatible structured generation failed: {last_error}") from last_error


class FallbackStructuredProvider:
    """Try a primary provider, then a configured local/alternate provider."""

    def __init__(self, primary: StructuredLLMProvider, fallback: StructuredLLMProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.provider = f"{primary.provider}+{fallback.provider}"
        self.model_id = primary.model_id

    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        prompt_version: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return self.primary.generate(
                system_instruction=system_instruction,
                prompt=prompt,
                schema=schema,
                prompt_version=prompt_version,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning(
                "primary factor interpretation provider failed provider=%s error=%s; trying fallback=%s",
                self.primary.provider,
                exc,
                self.fallback.provider,
            )
        return self.fallback.generate(
            system_instruction=system_instruction,
            prompt=prompt,
            schema=schema,
            prompt_version=prompt_version,
            metadata=metadata,
        )


def _build_named_provider(settings: Settings, name: str) -> StructuredLLMProvider | None:
    provider = (name or "").strip().casefold().replace("-", "_")
    if provider in {"gemini", "google"}:
        if not settings.gemini_api_key:
            return None
        return GeminiStructuredProvider(settings)
    if provider in {"openai", "openai_compatible", "ollama", "local", "vllm"}:
        return OpenAICompatibleStructuredProvider(settings)
    return None


def build_structured_provider(settings: Settings) -> StructuredLLMProvider | None:
    if not settings.problem_dimension_llm_enabled:
        return None
    name = settings.problem_dimension_llm_provider
    if name.casefold() == "auto":
        name = "gemini" if settings.gemini_api_key else "openai_compatible"
    primary = _build_named_provider(settings, name)
    fallback = _build_named_provider(settings, settings.problem_dimension_llm_fallback_provider)
    if primary and fallback and primary.provider != fallback.provider:
        return FallbackStructuredProvider(primary, fallback)
    return primary or fallback
