"""LLM layer. A HybridRouter runs local by default (Ollama) and escalates hard
tasks to a cloud model when explicitly enabled. A deterministic MockProvider
lets the whole system run offline, with no models and no network.
"""
from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod

import requests

from .models import LLMResult, Usage, Difficulty
from .safety import hash_embed

log = logging.getLogger("corparius.llm")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _flatten(messages: list[dict]) -> str:
    return "\n".join(m.get("content", "") for m in messages)


def _split(model_str: str) -> tuple[str, str]:
    """Split a tier model into (target, name). "cloud:x" -> ("cloud", "x");
    a bare name defaults to local. Real model names never start with these."""
    if model_str.startswith("cloud:"):
        return "cloud", model_str[len("cloud:"):]
    if model_str.startswith("local:"):
        return "local", model_str[len("local:"):]
    return "local", model_str


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, messages: list[dict], model: str, max_tokens: int = 512) -> LLMResult:
        ...

    def embed(self, text: str) -> list[float]:
        # Default: local, dependency-free embedding. Providers may override.
        return hash_embed(text)


class MockProvider(LLMProvider):
    """Deterministic, offline. Echoes a trimmed view of the prompt so drafted
    content is stable and the pipeline runs with no dependencies."""

    name = "mock"

    def generate(self, messages: list[dict], model: str, max_tokens: int = 512) -> LLMResult:
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        text = f"[mock:{model}] {last_user.strip()[:180]}"
        usage = Usage(_estimate_tokens(_flatten(messages)), _estimate_tokens(text))
        return LLMResult(text=text, usage=usage, model=model, provider=self.name)


class OllamaProvider(LLMProvider):
    """Local inference against a self-hosted Ollama server."""

    name = "ollama"

    def __init__(self, base_url: str, embed_model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.embed_model = embed_model
        self.timeout = timeout

    def generate(self, messages: list[dict], model: str, max_tokens: int = 512) -> LLMResult:
        r = requests.post(
            f"{self.base_url}/api/chat",
            json={"model": model, "messages": messages, "stream": False,
                  "options": {"num_predict": max_tokens}},
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        text = data.get("message", {}).get("content", "")
        usage = Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0))
        return LLMResult(text=text, usage=usage, model=model, provider=self.name)

    def embed(self, text: str) -> list[float]:
        try:
            r = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json().get("embedding") or hash_embed(text)
        except requests.RequestException:
            return hash_embed(text)


class AnthropicProvider(LLMProvider):
    """Cloud fallback for hard tasks. Called over plain HTTP; no SDK required."""

    name = "anthropic"

    def __init__(self, api_key: str, timeout: int = 120):
        self.api_key = api_key
        self.timeout = timeout

    def generate(self, messages: list[dict], model: str, max_tokens: int = 512) -> LLMResult:
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        turns = [m for m in messages if m.get("role") in ("user", "assistant")]
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({"model": model, "max_tokens": max_tokens,
                             "system": system, "messages": turns}),
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(block.get("text", "") for block in data.get("content", []))
        u = data.get("usage", {})
        usage = Usage(u.get("input_tokens", 0), u.get("output_tokens", 0))
        return LLMResult(text=text, usage=usage, model=model, provider=self.name)


class HybridRouter:
    """Local first, cloud on escalation. If mock mode is on, everything is served
    by the MockProvider. Otherwise EASY tasks stay on Ollama and HARD tasks go to
    the cloud when it is enabled, falling back to local if the cloud call fails.
    """

    def __init__(self, settings):
        self.settings = settings
        if settings.llm_mock:
            self.local: LLMProvider = MockProvider()
            self.cloud: LLMProvider | None = None
        else:
            self.local = OllamaProvider(settings.ollama_url, settings.embed_model)
            self.cloud = (
                AnthropicProvider(settings.anthropic_api_key)
                if settings.cloud_enabled and settings.anthropic_api_key
                else None
            )

    def _tier_model(self, difficulty: Difficulty) -> str:
        return {
            Difficulty.TRIVIAL: self.settings.trivial_model,
            Difficulty.EASY: self.settings.normal_model,
            Difficulty.HARD: self.settings.hard_model,
        }.get(difficulty, self.settings.normal_model)

    def generate(self, messages: list[dict], difficulty: Difficulty = Difficulty.EASY,
                 model: str | None = None, max_tokens: int = 512) -> LLMResult:
        target, name = _split(model or self._tier_model(difficulty))
        # Mock mode: one deterministic provider; keep the label so you can see
        # which model each agent would have used.
        if self.settings.llm_mock:
            return self.local.generate(messages, name, max_tokens)
        if target == "cloud" and self.cloud is not None:
            try:
                return self.cloud.generate(messages, name, max_tokens)
            except requests.RequestException as exc:
                log.warning("cloud call failed, falling back to local %s: %s",
                            self.settings.local_model, exc)
                return self.local.generate(messages, self.settings.local_model, max_tokens)
        # Local target, or cloud was requested but is unavailable.
        local_name = name if target == "local" else self.settings.local_model
        return self.local.generate(messages, local_name, max_tokens)

    def embed(self, text: str) -> list[float]:
        return self.local.embed(text)
