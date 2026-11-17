from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class StructuredResponse:
    payload: dict[str, Any]
    provider: str
    model: str


class StructuredLLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        provider: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.settings = settings
        requested = (provider or "auto").lower().replace("-", "_")
        if requested in {"gemini", "google"} and settings.gemini_api_key:
            self.kind = "gemini"
        elif requested in {"openai_compatible", "openai", "ollama", "vllm"} and settings.openai_api_key:
            self.kind = "openai_compatible"
        elif requested in {"auto", "llm", "structured_llm"}:
            if settings.gemini_api_key:
                self.kind = "gemini"
            elif settings.openai_api_key:
                self.kind = "openai_compatible"
            else:
                self.kind = "none"
        else:
            self.kind = "none"
        self.model = model or (
            (settings.gemini_model or settings.llm_model) if self.kind == "gemini" else settings.openai_model
        )
        self.timeout = timeout if timeout is not None else settings.llm_timeout_seconds
        self.temperature = temperature
        self.api_keys = (
            [key for key in (settings.gemini_api_key, settings.gemini_api_key_1, settings.gemini_api_key_2) if key]
            if self.kind == "gemini"
            else []
        )
        self.key_index = 0

    @property
    def available(self) -> bool:
        return self.kind != "none"

    def _request(self, prompt: str) -> dict[str, Any]:
        if self.kind == "gemini":
            return {
                "url": f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                "params": {
                    "key": self.api_keys[self.key_index]
                    if self.api_keys
                    else self.settings.gemini_api_key
                },
                "json": {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": self.temperature,
                    },
                },
            }
        return {
            "url": self.settings.openai_base_url.rstrip("/") + "/chat/completions",
            "headers": {"Authorization": f"Bearer {self.settings.openai_api_key}"},
            "json": {
                "model": self.model,
                "temperature": self.temperature,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
        }

    def generate_json(self, prompt: str) -> StructuredResponse:
        if not self.available:
            raise LLMUnavailable("no structured LLM provider is configured")
        original_model = self.model
        fallback_model = (
            self.settings.gemini_fallback_model
            if self.kind == "gemini"
            and self.settings.gemini_fallback_model
            and self.settings.gemini_fallback_model != original_model
            else None
        )
        using_fallback = False
        reverted_model = False
        for attempt in range(8):
            request = self._request(prompt)
            try:
                response = httpx.post(timeout=self.timeout, **request)
                response.raise_for_status()
                data = response.json()
                if self.kind == "gemini":
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    text = data["choices"][0]["message"]["content"]
                payload = json.loads(text)
                if not isinstance(payload, dict):
                    raise LLMUnavailable("structured LLM returned a non-object payload")
                return StructuredResponse(payload=payload, provider=self.kind, model=self.model)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                body = exc.response.text[:200]
                if status in {401, 429} and self.api_keys and self.key_index < len(self.api_keys) - 1:
                    self.key_index += 1
                    logger.warning("Gemini key rejected; rotated to API key %s", self.key_index + 1)
                    time.sleep(1)
                    continue
                if status in {401, 429} and self.api_keys and self.key_index == len(self.api_keys) - 1:
                    self.key_index = 0
                if fallback_model and status in {404, 503} and not using_fallback:
                    using_fallback = True
                    self.model = fallback_model
                    logger.warning("Gemini unavailable; switched to fallback model %s", fallback_model)
                    time.sleep(1)
                    continue
                if fallback_model and status in {404, 503} and using_fallback and not reverted_model:
                    reverted_model = True
                    using_fallback = False
                    self.model = original_model
                    logger.warning("Gemini fallback failed; reverted to %s", original_model)
                    time.sleep(1)
                    continue
                if status in {429, 500, 502, 503, 504} and attempt < 5:
                    delay = min(30, 2**attempt * 2)
                    time.sleep(delay + random.uniform(0, delay / 2))
                    continue
                raise LLMUnavailable(f"LLM HTTP {status}: {body}") from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < 5:
                    delay = min(30, 2**attempt * 2)
                    time.sleep(delay + random.uniform(0, delay / 2))
                    continue
                raise LLMUnavailable(f"LLM transport error: {type(exc).__name__}") from exc
            except LLMUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - callers fall back deterministically
                raise LLMUnavailable(f"structured LLM call failed: {type(exc).__name__}") from exc
        raise LLMUnavailable("structured LLM retries exhausted")
