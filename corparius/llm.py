"""LLM layer. A HybridRouter runs local by default (Ollama) and escalates hard
tasks to a remote model when explicitly enabled. A deterministic MockProvider
lets the whole system run offline, with no models and no network.

Remote capacity is provider-agnostic. Besides Anthropic ("cloud:") and the
Claude Code CLI ("claudecode:", subscription auth, no API credits), any entry
in OPENAI_COMPAT_PROVIDERS can serve a tier or a fallback step; they all speak
the OpenAI chat-completions dialect. A provider is enabled by its API key in
the environment; a missing key simply removes it from the pool. When a remote
call fails, the router walks the CORP_LLM_FALLBACK chain in order, and local
Ollama always ends the chain.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from abc import ABC, abstractmethod

import requests

from . import cfg
from .models import Difficulty, LLMResult, Usage
from .safety import hash_embed

log = logging.getLogger("corparius.llm")


class ProviderError(Exception):
    """Raised by non-HTTP providers so the fallback chain can catch failures."""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _flatten(messages: list[dict]) -> str:
    return "\n".join(m.get("content", "") for m in messages)


# The harness's marker and a hint-line parser, kept here so the mock can answer
# structured prompts offline without importing corparius.structured (which imports
# models, which is fine, but this keeps the mock dependency-free and fast).
_STRUCT_MARKER = "<<corp-json-schema>>"
_HINT_LINE = re.compile(r'"([^"]+)":\s*(.+?)(?:,|\s*$)')


def _mock_json(prompt: str, model: str) -> str:
    """Build a valid object for the shape the harness rendered into the prompt.
    Strings echo the model tag so output stays deterministic and identifiable;
    lists, numbers and booleans get typed placeholders."""
    shape = prompt.rsplit("{", 1)[-1]
    out: dict = {}
    for key, decl in _HINT_LINE.findall(shape):
        decl = decl.strip()
        if decl.startswith("["):
            out[key] = [f"mock-{key}"]
        elif decl.startswith("true"):
            out[key] = True
        elif decl.startswith("number"):
            out[key] = 1
        elif "|" in decl and "(" not in decl:
            out[key] = decl.split("|")[0].strip()
        else:
            out[key] = f"[mock:{model}] {key}"
    return json.dumps(out or {"result": f"[mock:{model}]"})


# Free-tier remote providers, all OpenAI chat-completions compatible.
#   base: default endpoint (no trailing slash).
#   key_env: environment variable holding the API key. The provider joins the
#            pool only when the key is set, unless key_optional is true.
#   base_env: overrides base when the endpoint depends on the account
#             (Cloudflare) or is self-chosen (custom: OmniRoute, LiteLLM,
#             vLLM, LM Studio, any OpenAI-compatible gateway).
# Free-tier limits are documented in docs/llm-providers.md; the per-provider
# signup page is carried here too so the console can link straight to it from the
# row where the key is pasted, instead of sending the operator to read a table.
#   signup:        the exact page that creates/holds the API key (https).
#   no_card:       true only where signup needs no payment card (kept factual to
#                  the doc: an over-promised badge is worse than none).
#   recommended:   the "start here" picks - no card, fast, generous, no data
#                  caveat. Rendered first, so 14 providers do not read as a wall.
#   default_model: a sane model to route the normal tier to when the operator
#                  accepts the one-click activation after a key tests green. Only
#                  set where the model name is known-good (see the doc example).
OPENAI_COMPAT_PROVIDERS: dict[str, dict] = {
    "groq": {
        "base": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "signup": "https://console.groq.com/keys",
        "no_card": True,
        "recommended": True,
        "default_model": "llama-3.3-70b-versatile",
    },
    "cerebras": {
        "base": "https://api.cerebras.ai/v1",
        "key_env": "CEREBRAS_API_KEY",
        "signup": "https://cloud.cerebras.ai",
        "no_card": True,
        "recommended": True,
        "default_model": "gpt-oss-120b",
    },
    "openrouter": {
        "base": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "signup": "https://openrouter.ai/keys",
        "default_model": "deepseek/deepseek-r1-0528:free",
    },
    "mistral": {
        "base": "https://api.mistral.ai/v1",
        "key_env": "MISTRAL_API_KEY",
        "signup": "https://console.mistral.ai/api-keys",
        "default_model": "mistral-small-latest",
    },
    "gemini": {
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "signup": "https://aistudio.google.com/app/apikey",
    },
    "nvidia": {
        "base": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_API_KEY",
        "signup": "https://build.nvidia.com/settings/api-keys",
    },
    "github": {
        "base": "https://models.github.ai/inference",
        "key_env": "GITHUB_TOKEN",
        "signup": "https://github.com/settings/tokens",
        "no_card": True,
    },
    "cohere": {
        "base": "https://api.cohere.ai/compatibility/v1",
        "key_env": "CO_API_KEY",
        "signup": "https://dashboard.cohere.com/api-keys",
    },
    "huggingface": {
        "base": "https://router.huggingface.co/v1",
        "key_env": "HF_TOKEN",
        "signup": "https://huggingface.co/settings/tokens",
    },
    "ovh": {
        "base": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        "key_env": "OVH_AI_ENDPOINTS_ACCESS_TOKEN",
        "key_optional": True,
        "signup": "https://endpoints.ai.cloud.ovh.net",
        "no_card": True,
        "default_model": "gpt-oss-120b",
    },
    "zhipu": {
        "base": "https://open.bigmodel.cn/api/paas/v4",
        "key_env": "ZHIPU_API_KEY",
        "signup": "https://open.bigmodel.cn/usercenter/apikeys",
    },
    "siliconflow": {
        "base": "https://api.siliconflow.cn/v1",
        "key_env": "SILICONFLOW_API_KEY",
        "signup": "https://cloud.siliconflow.cn/account/ak",
    },
    "cloudflare": {
        "base": "",
        "base_env": "CF_AI_BASE_URL",
        "key_env": "CLOUDFLARE_API_TOKEN",
        "signup": "https://dash.cloudflare.com/profile/api-tokens",
    },
    "custom": {
        "base": "",
        "base_env": "CORP_CUSTOM_LLM_URL",
        "key_env": "CORP_CUSTOM_LLM_KEY",
        "key_optional": True,
    },
}


def _split(model_str: str) -> tuple[str, str]:
    """Split a tier model into (target, name). "cloud:x" -> ("cloud", "x") and
    "groq:x" -> ("groq", "x") for any registered provider. A bare name or an
    unknown prefix (Ollama tags like "gemma4:e4b") defaults to local."""
    prefix, sep, rest = model_str.partition(":")
    if sep and (prefix in ("cloud", "local", "claudecode") or prefix in OPENAI_COMPAT_PROVIDERS):
        return prefix, rest
    return "local", model_str


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, messages: list[dict], model: str, max_tokens: int = 512) -> LLMResult: ...

    def embed(self, text: str) -> list[float]:
        # Default: local, dependency-free embedding. Providers may override.
        return hash_embed(text)


class MockProvider(LLMProvider):
    """Deterministic, offline. Echoes a trimmed view of the prompt so drafted
    content is stable and the pipeline runs with no dependencies.

    When the structured harness is driving (its marker is in the prompt), the
    mock emits a valid JSON object for the requested shape, so offline mode
    exercises the real structured path instead of always hitting the fallback.
    """

    name = "mock"

    def generate(self, messages: list[dict], model: str, max_tokens: int = 512) -> LLMResult:
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        prompt = _flatten(messages)
        text = (
            _mock_json(prompt, model)
            if _STRUCT_MARKER in prompt
            else f"[mock:{model}] {last_user.strip()[:180]}"
        )
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
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
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
    """Cloud escalation for hard tasks. Called over plain HTTP; no SDK required."""

    name = "anthropic"

    def __init__(self, api_key: str, timeout: int = 120):
        self.api_key = api_key
        self.timeout = timeout

    def generate(self, messages: list[dict], model: str, max_tokens: int = 512) -> LLMResult:
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        turns = [m for m in messages if m.get("role") in ("user", "assistant")]
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            data=json.dumps(
                {"model": model, "max_tokens": max_tokens, "system": system, "messages": turns}
            ),
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(block.get("text", "") for block in data.get("content", []))
        u = data.get("usage", {})
        usage = Usage(u.get("input_tokens", 0), u.get("output_tokens", 0))
        return LLMResult(text=text, usage=usage, model=model, provider=self.name)


class OpenAICompatProvider(LLMProvider):
    """Any endpoint speaking the OpenAI chat-completions dialect: the free
    tiers in OPENAI_COMPAT_PROVIDERS or a self-hosted gateway. One class,
    many providers."""

    def __init__(self, name: str, base_url: str, api_key: str = "", timeout: int = 120):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def generate(self, messages: list[dict], model: str, max_tokens: int = 512) -> LLMResult:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        u = data.get("usage") or {}
        usage = Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        return LLMResult(text=text, usage=usage, model=model, provider=self.name)


class ClaudeCodeProvider(LLMProvider):
    """Anthropic models through the local Claude Code CLI in headless mode
    ("claude -p"). Uses whatever auth the CLI holds, including a Claude
    subscription login, so no API credits are required. Needs the CLI
    installed and logged in; subscription rate limits apply. max_tokens is
    not supported by the CLI and is ignored."""

    name = "claudecode"

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def generate(self, messages: list[dict], model: str, max_tokens: int = 512) -> LLMResult:
        from . import claudecli

        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        prompt = _flatten([m for m in messages if m.get("role") != "system"])
        # The resolved path, not "claude": on Windows the CLI is a .cmd that
        # subprocess cannot launch by bare name. See claudecli.resolve.
        exe = claudecli.resolve() or "claude"
        cmd = [exe, "-p", prompt, "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        if system:
            cmd += ["--append-system-prompt", system]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderError(f"claude CLI unavailable: {exc}") from exc
        if proc.returncode != 0:
            raise ProviderError(f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:300]}")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderError("claude CLI returned non-JSON output") from exc
        u = data.get("usage") or {}
        usage = Usage(u.get("input_tokens", 0), u.get("output_tokens", 0))
        return LLMResult(text=data.get("result", ""), usage=usage, model=model, provider=self.name)


def _remote_providers() -> dict[str, LLMProvider]:
    """Instantiate every registered provider whose key (and endpoint) is set."""
    remotes: dict[str, LLMProvider] = {}
    for name, spec in OPENAI_COMPAT_PROVIDERS.items():
        base = cfg.get(spec.get("base_env", ""), "").strip() or spec["base"]
        key = cfg.get(spec["key_env"], "").strip()
        if base and (key or spec.get("key_optional")):
            remotes[name] = OpenAICompatProvider(name, base, key)
    return remotes


class HybridRouter:
    """Local first, remote on escalation. If mock mode is on, everything is
    served by the MockProvider. Otherwise EASY tasks stay on Ollama and HARD
    tasks go to a remote provider when enabled. A failing remote call walks
    the CORP_LLM_FALLBACK chain, then falls back to local.
    """

    def __init__(self, settings):
        self.settings = settings
        if settings.llm_mock:
            self.local: LLMProvider = MockProvider()
            self.cloud: LLMProvider | None = None
            self.remotes: dict[str, LLMProvider] = {}
        else:
            self.local = OllamaProvider(
                settings.ollama_url,
                settings.embed_model,
                timeout=getattr(settings, "ollama_timeout", 420),
            )
            self.cloud = (
                AnthropicProvider(settings.anthropic_api_key)
                if settings.cloud_enabled and settings.anthropic_api_key
                else None
            )
            self.remotes = _remote_providers() if settings.cloud_enabled else {}
            if settings.cloud_enabled and settings.claude_code_enabled:
                self.remotes["claudecode"] = ClaudeCodeProvider()

    def _tier_model(self, difficulty: Difficulty) -> str:
        return {
            Difficulty.TRIVIAL: self.settings.trivial_model,
            Difficulty.EASY: self.settings.normal_model,
            Difficulty.HARD: self.settings.hard_model,
        }.get(difficulty, self.settings.normal_model)

    def _remote(self, target: str) -> LLMProvider | None:
        return self.cloud if target == "cloud" else self.remotes.get(target)

    def _chain(self, target: str, name: str) -> list[tuple[str, str]]:
        """The requested provider, then each CORP_LLM_FALLBACK step. A local
        step ends the chain; the final local fallback always applies anyway."""
        steps = [(target, name)]
        for entry in self.settings.llm_fallback:
            t, n = _split(entry)
            if t == "local":
                break
            if (t, n) not in steps:
                steps.append((t, n))
        return steps

    def generate(
        self,
        messages: list[dict],
        difficulty: Difficulty = Difficulty.EASY,
        model: str | None = None,
        max_tokens: int = 512,
    ) -> LLMResult:
        target, name = _split(model or self._tier_model(difficulty))
        # Mock mode: one deterministic provider; keep the label so you can see
        # which model each agent would have used.
        if self.settings.llm_mock:
            return self.local.generate(messages, name, max_tokens)
        if target != "local":
            for step_target, step_name in self._chain(target, name):
                provider = self._remote(step_target)
                if provider is None:
                    continue
                try:
                    return provider.generate(messages, step_name, max_tokens)
                except (requests.RequestException, ProviderError) as exc:
                    log.warning(
                        "%s call failed (%s), trying next step: %s", step_target, step_name, exc
                    )
            log.warning(
                "all remote steps failed or unavailable, falling back to local %s",
                self.settings.local_model,
            )
        # Local target, or every remote step was exhausted. One retry covers
        # Ollama cold starts, where the first call can time out while the
        # model is still loading into memory.
        local_name = name if target == "local" else self.settings.local_model
        try:
            return self.local.generate(messages, local_name, max_tokens)
        except requests.RequestException as exc:
            log.warning("local %s failed (%s), retrying once", local_name, exc)
            return self.local.generate(messages, local_name, max_tokens)

    def embed(self, text: str) -> list[float]:
        return self.local.embed(text)
