"""Adaptadores de proveedores LLM."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .errors import ProviderError, QuotaExceededError, RateLimitError
from .transport import http_post_json

QUOTA_MARKERS = (
    "insufficient_quota", "quota exceeded", "quota_exceeded", "out of quota",
    "exceeded your current quota", "resource_exhausted",
)
RATE_MARKERS = ("rate limit", "rate_limit", "too many requests", "exceeded rate")


def _markers_in(text: str, markers) -> bool:
    text = text.lower()
    return any(marker in text for marker in markers)


class Provider:
    """Base común de proveedores con cooldown y circuit breaker."""

    def __init__(self, name="", priority=100, models=None, cooldown_seconds=300,
                 circuit_seconds=600, failure_threshold=3, **kwargs):
        self.name = name
        self.priority = priority
        self.models = list(models or [])
        self.cooldown_seconds = float(cooldown_seconds)
        self.circuit_seconds = float(circuit_seconds)
        self.failure_threshold = int(failure_threshold)
        self.cooldown_until = 0.0
        self.circuit_open_until = 0.0
        self.consecutive_failures = 0

    def in_cooldown(self, now=None):
        return (time.time() if now is None else now) < self.cooldown_until

    def circuit_open(self, now=None):
        return (time.time() if now is None else now) < self.circuit_open_until

    def available(self, now=None):
        return not self.in_cooldown(now) and not self.circuit_open(now)

    def record_failure(self, now=None):
        now = time.time() if now is None else now
        self.consecutive_failures += 1
        self.cooldown_until = now + self.cooldown_seconds
        if self.consecutive_failures >= self.failure_threshold:
            self.circuit_open_until = now + self.circuit_seconds

    def record_success(self):
        self.consecutive_failures = 0
        self.cooldown_until = 0.0
        self.circuit_open_until = 0.0

    def complete(self, *args, **kwargs):
        raise NotImplementedError

    def _normalize(self, content, model, usage):
        return {
            "content": content,
            "model": model,
            "provider": self.name,
            "usage": {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            },
        }


class OpenAICompatibleProvider(Provider):
    """Proveedor para APIs compatibles con OpenAI Chat Completions."""

    def __init__(self, name, base_url, api_key, models=None, **kwargs):
        super().__init__(name=name, models=models, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def complete(self, messages, model=None, temperature=None, max_tokens=None, timeout=60):
        model = model or (self.models[0] if self.models else None)
        if not model:
            raise ProviderError(self.name, "no se indicó modelo")
        payload = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        status, body = http_post_json(
            self.base_url + "/chat/completions",
            {"Authorization": "Bearer " + self.api_key},
            payload,
            timeout=timeout,
        )
        if 200 <= status < 300:
            try:
                content = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                raise ProviderError(self.name, "respuesta sin choices")
            return self._normalize(content, model, body.get("usage") or {})

        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        message = err.get("message") or str(body)[:300]
        code = err.get("code") or ""
        text = f"{code} {message}"
        if _markers_in(text, QUOTA_MARKERS) or status == 402:
            raise QuotaExceededError(self.name, message or "cuota agotada", status)
        if status in (429, 503) or _markers_in(text, RATE_MARKERS):
            raise RateLimitError(self.name, message or "rate limit", status)
        raise ProviderError(self.name, message or f"HTTP {status}", status)


class GeminiProvider(Provider):
    """Adaptador para Google Gemini GenerateContent."""

    def __init__(self, name, base_url, api_key, models=None, **kwargs):
        super().__init__(name=name, models=models, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def complete(self, messages, model=None, temperature=None, max_tokens=None, timeout=60):
        model = model or (self.models[0] if self.models else None)
        if not model:
            raise ProviderError(self.name, "no se indicó modelo")
        contents = []
        for message in messages:
            role = message.get("role", "user")
            text = message.get("content", "") or ""
            if role == "system":
                text = "[Instrucciones del sistema]\n" + text
                role = "user"
            elif role not in ("user", "model"):
                role = "user"
            contents.append({"role": role, "parts": [{"text": text}]})
        payload = {"contents": contents}
        config = {}
        if temperature is not None:
            config["temperature"] = temperature
        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens
        if config:
            payload["generationConfig"] = config

        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
        status, body = http_post_json(url, {}, payload, timeout=timeout)
        if 200 <= status < 300:
            try:
                parts = body["candidates"][0]["content"]["parts"]
                content = "".join(part.get("text", "") for part in parts)
            except (KeyError, IndexError, TypeError):
                raise ProviderError(self.name, "respuesta sin candidates")
            usage = body.get("usageMetadata") or {}
            return self._normalize(content, model, {
                "prompt_tokens": usage.get("promptTokenCount") or 0,
                "completion_tokens": usage.get("candidatesTokenCount") or 0,
            })

        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        message = err.get("message") or str(body)[:300]
        status_text = err.get("status") or ""
        text = f"{status_text} {message}"
        if _markers_in(text, QUOTA_MARKERS):
            raise QuotaExceededError(self.name, message or "cuota agotada", status)
        if status in (429, 503) or _markers_in(text, RATE_MARKERS):
            raise RateLimitError(self.name, message or "rate limit", status)
        raise ProviderError(self.name, message or f"HTTP {status}", status)
