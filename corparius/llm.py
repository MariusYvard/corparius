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

import base64
import json
import logging
import os
import re
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from . import cfg
from .models import Difficulty, LLMResult, Usage
from .safety import hash_embed

log = logging.getLogger("corparius.llm")


class ProviderError(Exception):
    """Raised by non-HTTP providers so the fallback chain can catch failures."""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _argv_chars(cmd: list[str]) -> int:
    """Roughly what a command line costs, quoting included. Two characters per
    argument for quotes and one for the separating space — an over-estimate on
    purpose, because the failure it guards is a hard truncation."""
    return sum(len(a) + 3 for a in cmd)


def _flatten(messages: list[dict]) -> str:
    return "\n".join(m.get("content", "") for m in messages)


def _float(value) -> float:
    """A cost field that is missing, null or a string is worth 0.0 rather than a
    crashed turn. Providers send it as a JSON number or as a decimal string
    depending on the day, and a run must not die over which."""
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


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
        # Checked live: the previous default, deepseek/deepseek-r1-0528:free,
        # stopped being listed while its paid variant stayed. Any hardcoded
        # name rots the same way, which is why doctor now compares each tier
        # against the provider's own catalogue.
        "default_model": "openai/gpt-oss-20b:free",
    },
    "mistral": {
        "base": "https://api.mistral.ai/v1",
        "key_env": "MISTRAL_API_KEY",
        "signup": "https://console.mistral.ai/api-keys",
        "default_model": "mistral-small-latest",
    },
    "openai": {
        "base": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "signup": "https://platform.openai.com/api-keys",
        # No default_model on purpose. Per the note above, one is set only where
        # the name is known-good, and OpenAI renames and retires its models
        # faster than a literal in this file can track — the previous
        # openrouter default rotted exactly that way. The console reads the real
        # catalogue from /models once a key is present, which is what
        # list_models() is for.
    },
    "alibaba": {
        # Model Studio (Bailian / DashScope) speaks the OpenAI protocol. Two
        # regions, and they are separate accounts with separate keys rather than
        # mirrors — a key from one is refused by the other. International is the
        # default; set DASHSCOPE_BASE_URL to the Beijing endpoint
        # (https://dashscope.aliyuncs.com/compatible-mode/v1) for a China
        # account. Both verified live: each answers 401 unauthenticated, which
        # is a real endpoint refusing a missing key rather than a wrong URL.
        "base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "base_env": "DASHSCOPE_BASE_URL",
        "key_env": "DASHSCOPE_API_KEY",
        "signup": "https://modelstudio.console.alibabacloud.com/?tab=playground#/api-key",
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


# Preference for the general tiers: fast, generous models first; OpenRouter last
# for the normal tier because its default is a reasoning model (slower), but
# first choice for the hard tier for the same reason.
_ROUTING_ORDER = ["groq", "cerebras", "mistral", "ovh", "openrouter"]


def connected_providers() -> list[str]:
    """The OpenAI-compatible providers that actually have what they need to
    answer: a key, or a base URL for the ones that take none. The console and
    the CLI both decide routing from this, so it lives here rather than being
    computed twice and drifting."""
    return [
        name
        for name, spec in OPENAI_COMPAT_PROVIDERS.items()
        if cfg.get(spec["key_env"], "").strip()
        or (
            spec.get("key_optional")
            and (cfg.get(spec.get("base_env", ""), "").strip() or spec.get("base"))
        )
    ]


def recommended_routing(
    configured: list[str],
    local_trivial: str = "",
    hard: str = "",
    fallback_tail=(),
    proven: dict[str, dict[str, dict]] | None = None,
    catalogue: dict[str, dict] | None = None,
    scores: dict[str, float] | None = None,
) -> dict[str, str] | None:
    """A coherent tier configuration from the free providers actually connected,
    so no tier resolves to something the operator has not set up.

    Returns the environment variables to write, or None when nothing usable is
    connected. This closes the gap left by the defaults (trivial on a local model
    that may be absent, normal/hard on paid Anthropic): enabling one free key set
    only the normal tier and left the rest broken. Here every tier lands on a
    connected provider - a reasoning model on hard when OpenRouter is in the mix,
    fast general models elsewhere, local on trivial when Ollama is up - and the
    fallback chain lists the remaining providers (the router always ends on local
    after it).

    `hard` overrides the top tier — that is what lets a metered account (a Claude
    subscription, in practice) take the strategy and coder work while the free
    providers carry the rest.

    `local_trivial` is the local model to put on the trivial tier, or "" for
    none. It replaced an `ollama_ready` boolean, which asked the wrong question:
    a port answering says nothing about whether the machine can serve a tier.
    The caller measures (see corparius/hardware.py) and passes the answer.

    `fallback_tail` is the remote ladder walked once every free provider has
    failed, before the router drops to local. It is deliberately separate from
    `hard`: the chain is shared by *every* tier, so putting the top-tier model
    there would let a failed social post escalate to the most expensive model in
    the roster. Cheapest first — the everyday work degrades one rung at a time.

    `proven` is what a preflight actually measured, from
    `preflight.proven_map`. Without it this behaves exactly as before, on the
    `default_model` literals — which are strings frozen on the day they were
    written, and they rot: openrouter's pinned default stopped existing while
    its paid variant stayed, so "recommended" routing wrote a tier that 404s.
    With it, a default known to be blocked is never chosen, and the replacement
    is the fastest model that province actually answered on. Measuring 785
    models to populate a dropdown would have been a waste; this is what the
    measurement is for.
    """
    picks = [
        p
        for p in _ROUTING_ORDER
        if p in configured and OPENAI_COMPAT_PROVIDERS.get(p, {}).get("default_model")
    ]
    if not picks:
        return None

    def model(provider: str, tier: str = "normal") -> str:
        default = OPENAI_COMPAT_PROVIDERS[provider]["default_model"]
        known = (proven or {}).get(provider) or {}
        if not known or known.get(default, {}).get("state") != "blocked":
            # Nothing measured, or the default is fine. Never second-guess a
            # working default on the strength of a faster alternative: the
            # defaults are chosen for capability, not latency.
            return f"{provider}:{default}"
        from .preflight import rank

        usable = rank(known, tier=tier, catalogue=catalogue, scores=scores)
        if not usable:
            log.warning(
                "%s: the pinned default %s is not callable with this key, and nothing else "
                "on it has been proved. Leaving it; run `corparius preflight --provider %s`.",
                provider,
                default,
                provider,
            )
            return f"{provider}:{default}"
        # Best measured model on that provider — schema-capable first, then
        # reliable, then fast. See preflight.rank for why that order.
        best = usable[0]
        log.info("%s: %s is not callable; routing to %s, which answered", provider, default, best)
        return f"{provider}:{best}"

    normal_p = picks[0]
    hard_p = "openrouter" if "openrouter" in picks else normal_p
    # The chain is walked by every tier, so it is ranked as `normal`.
    chain = [model(p) for p in picks if p != normal_p]
    chain += [step for step in fallback_tail if step]
    return {
        "CORP_TRIVIAL_MODEL": (
            f"local:{local_trivial}" if local_trivial else model(normal_p, "trivial")
        ),
        "CORP_NORMAL_MODEL": model(normal_p, "normal"),
        "CORP_HARD_MODEL": hard or model(hard_p, "hard"),
        "CORP_LLM_FALLBACK": ",".join(chain),
    }


def list_models(name: str, timeout: int = 8) -> list[str]:
    """Model ids a provider advertises at its OpenAI-compatible /models endpoint,
    so the console can offer real names instead of asking the operator to know
    them. Returns [] when the provider is unconfigured or does not answer; the
    caller surfaces that rather than guessing."""
    spec = OPENAI_COMPAT_PROVIDERS.get(name)
    if not spec:
        return []
    base = (cfg.get(spec.get("base_env", ""), "").strip() or spec.get("base", "")).rstrip("/")
    if not base:
        return []
    key = cfg.get(spec["key_env"], "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = requests.get(base + "/models", headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json().get("data", [])
    return sorted({m.get("id", "") for m in data if m.get("id")})


# --- pictures -------------------------------------------------------------
#
# Carried as their own argument, never inside `messages`. Every provider in this
# module reads `content` as a string: `_flatten` joins them, the mock slices the
# last one, Anthropic concatenates the system ones. An OpenAI-style list of
# content blocks smuggled into a message would break four call paths at once and
# do it quietly. The dialects differ too much to share one message shape, so each
# provider spends the argument its own way and the ones that cannot say so.

# Per image, before base64 — which costs a third on top. Generous enough for a
# screenshot, small enough that a photograph out of a phone is refused rather
# than silently emptying a session budget in one call.
MAX_IMAGE_BYTES = 3 << 20
MAX_IMAGES = 2

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


@dataclass(frozen=True)
class Image:
    """One picture, read, with what a provider needs in order to describe it."""

    data: bytes
    media_type: str
    name: str = ""

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode()

    @property
    def data_uri(self) -> str:
        return f"data:{self.media_type};base64,{self.b64}"


def read_images(
    paths, max_bytes: int = MAX_IMAGE_BYTES, limit: int = MAX_IMAGES
) -> tuple[list[Image], list[str]]:
    """Load what can be sent, and name what cannot.

    Returns `(images, skipped)`. The second half is the point: "no silent
    truncation" applies to a dropped picture exactly as it applies to a truncated
    document, and a caller that gets only the first half cannot tell the operator
    what was left behind. Never raises — an unreadable file is a line of prose,
    not an exception in the middle of a turn.
    """
    images: list[Image] = []
    skipped: list[str] = []
    for path in list(paths or []):
        name = getattr(path, "name", str(path))
        if len(images) >= max(0, limit):
            skipped.append(f"{name}: past the {limit}-image limit for one call")
            continue
        media = _MEDIA_TYPES.get(str(getattr(path, "suffix", "")).lower())
        if media is None:
            skipped.append(f"{name}: not an image format a provider accepts")
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            skipped.append(f"{name}: {exc}")
            continue
        if size > max_bytes:
            skipped.append(f"{name}: {size} bytes, over the {max_bytes}-byte cap")
            continue
        try:
            images.append(Image(path.read_bytes(), media, name))
        except OSError as exc:
            skipped.append(f"{name}: {exc}")
    return images, skipped


class LLMProvider(ABC):
    name: str = "base"
    # Whether this provider knows how to carry a picture at all. False here means
    # `images` is ignored, and the caller is told rather than left to assume.
    accepts_images: bool = False

    @abstractmethod
    def generate(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int = 512,
        images: list[Image] | None = None,
    ) -> LLMResult: ...

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
    # It cannot see, but it must be able to say what it was handed, or no test
    # could prove an image ever reached a provider.
    accepts_images = True

    def __init__(self) -> None:
        self.last_images: list[Image] = []

    def generate(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int = 512,
        images: list[Image] | None = None,
    ) -> LLMResult:
        self.last_images = list(images or [])
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        prompt = _flatten(messages)
        text = (
            _mock_json(prompt, model)
            if _STRUCT_MARKER in prompt
            else f"[mock:{model}] {last_user.strip()[:180]}"
        )
        # Named in the output, so a mock run shows an image travelling instead of
        # only asserting it in a test.
        if self.last_images and _STRUCT_MARKER not in prompt:
            seen = ", ".join(i.name or i.media_type for i in self.last_images)
            text = f"{text} [saw {len(self.last_images)} image(s): {seen}]"
        usage = Usage(_estimate_tokens(_flatten(messages)), _estimate_tokens(text))
        return LLMResult(text=text, usage=usage, model=model, provider=self.name)


class OllamaProvider(LLMProvider):
    """Local inference against a self-hosted Ollama server."""

    name = "ollama"
    accepts_images = True

    def __init__(self, base_url: str, embed_model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.embed_model = embed_model
        self.timeout = timeout

    def generate(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int = 512,
        images: list[Image] | None = None,
    ) -> LLMResult:
        # Ollama's own dialect: base64 strings on the message, no data: prefix and
        # no content blocks. Attached to the last user turn, which is the one the
        # picture belongs to.
        turns: list[dict] = list(messages)
        if images:
            for index in range(len(turns) - 1, -1, -1):
                if turns[index].get("role") == "user":
                    turns[index] = {**turns[index], "images": [i.b64 for i in images]}
                    break
        r = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": model,
                "messages": turns,
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        text = data.get("message", {}).get("content", "")
        # Ollama times its own generation and reports it here. Reading it means a
        # real turn measures the machine as accurately as a dedicated probe does,
        # through the same parser — see corparius/hardware.parse_timings.
        from .hardware import parse_timings

        timed = parse_timings(data)
        usage = Usage(
            data.get("prompt_eval_count", 0),
            data.get("eval_count", 0),
            tokens_per_second=timed.get("tokens_per_second", 0.0),
            load_seconds=timed.get("load_seconds", 0.0),
        )
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
    accepts_images = True

    def __init__(self, api_key: str, timeout: int = 120):
        self.api_key = api_key
        self.timeout = timeout

    def generate(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int = 512,
        images: list[Image] | None = None,
    ) -> LLMResult:
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        turns = [m for m in messages if m.get("role") in ("user", "assistant")]
        if images:
            # Anthropic's own shape: a content list of blocks, the picture given as
            # base64 with its media type declared. Only built when there is an
            # image, so the plain path keeps sending a bare string and the `system`
            # join above stays correct.
            for index in range(len(turns) - 1, -1, -1):
                if turns[index].get("role") == "user":
                    turns[index] = {
                        "role": "user",
                        "content": [
                            *(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": i.media_type,
                                        "data": i.b64,
                                    },
                                }
                                for i in images
                            ),
                            {"type": "text", "text": turns[index].get("content", "")},
                        ],
                    }
                    break
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

    accepts_images = True

    def __init__(self, name: str, base_url: str, api_key: str = "", timeout: int = 120):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def generate(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int = 512,
        images: list[Image] | None = None,
    ) -> LLMResult:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        turns: list[dict] = list(messages)
        if images:
            # The OpenAI dialect: content becomes a list of typed parts and the
            # picture rides as a `data:` URI. Built only when there is an image, so
            # every text-only call keeps the string content that `_flatten` and the
            # rest of this module rely on.
            for index in range(len(turns) - 1, -1, -1):
                if turns[index].get("role") == "user":
                    turns[index] = {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": turns[index].get("content", "")},
                            *(
                                {"type": "image_url", "image_url": {"url": i.data_uri}}
                                for i in images
                            ),
                        ],
                    }
                    break
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json={"model": model, "messages": turns, "max_tokens": max_tokens},
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        u = data.get("usage") or {}
        # OpenRouter reports what the call actually cost, in the same usage block
        # every OpenAI-compatible provider fills in, on the endpoint already
        # being called. It was being read for tokens and thrown away for money,
        # which is the number an operator running a company actually budgets in.
        # The other providers do not send it and stay at 0.0 — "not reported",
        # not "free"; see Usage.cost.
        usage = Usage(
            u.get("prompt_tokens", 0), u.get("completion_tokens", 0), _float(u.get("cost"))
        )
        return LLMResult(text=text, usage=usage, model=model, provider=self.name)


class ClaudeCodeProvider(LLMProvider):
    """Anthropic models through the local Claude Code CLI in headless mode
    ("claude -p"). Uses whatever auth the CLI holds, including a Claude
    subscription login, so no API credits are required. Needs the CLI
    installed and logged in; subscription rate limits apply. max_tokens is
    not supported by the CLI and is ignored."""

    name = "claudecode"

    # The CLI takes text on stdin or argv. There is no shape here for a picture,
    # so `accepts_images` stays False and the router does not hand it one — rather
    # than this method taking an argument it would quietly drop.
    accepts_images = False

    # How much of a command line this platform will actually carry.
    #
    # On Windows the CLI npm installs is `claude.CMD`, so every call goes through
    # cmd.exe, which truncates the whole command line at 8191 characters.
    # Measured on the installed CLI (2.1.220): an 8000-character prompt reaches
    # the model, 8100 fails with `claude CLI exited 1: La ligne de commande est
    # trop longue`. That is not a corner case — a company with documents and
    # skills passes it on the design agent's very first turn, and the failure
    # looked like a provider outage, so the router fell through to a free model
    # that cannot produce JSON and the site was never rewritten. Nobody could
    # have read that story out of the log.
    #
    # The prompt now goes on stdin, which the CLI reads (`claude -p` with no
    # prompt argument): measured, a 25 268-character prompt returns rc 0. Only
    # the flags are left on argv, and this budget is what decides whether the
    # system prompt can stay there too.
    ARGV_BUDGET = 7800 if os.name == "nt" else 128_000

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def generate(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int = 512,
        images: list[Image] | None = None,
    ) -> LLMResult:
        from . import claudecli

        if images:
            log.info("claudecode takes no images; %d not sent this call", len(images))
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        prompt = _flatten([m for m in messages if m.get("role") != "system"])
        # The resolved path, not "claude": on Windows the CLI is a .cmd that
        # subprocess cannot launch by bare name. See claudecli.resolve.
        exe = claudecli.resolve() or "claude"
        cmd = [exe, "-p", "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        if system:
            # The system prompt belongs in --append-system-prompt, and stays there
            # while it fits. When it does not, it is folded into the prompt rather
            # than dropped: a call that silently loses the company's skills and
            # house rules would answer confidently in the wrong voice, which is
            # worse than a longer prompt.
            if (
                _argv_chars(cmd) + len(system) + len("--append-system-prompt") + 2
                <= self.ARGV_BUDGET
            ):
                cmd += ["--append-system-prompt", system]
            else:
                log.info(
                    "claudecode: system prompt is %d chars, past this platform's %d-char "
                    "command line; folding it into the prompt on stdin",
                    len(system),
                    self.ARGV_BUDGET,
                )
                prompt = f"{system}\n\n---\n\n{prompt}"
        try:
            proc = subprocess.run(
                cmd,
                # The prompt on stdin, not on argv: see ARGV_BUDGET. There is no
                # length limit worth naming here — 25k characters is measured.
                input=prompt,
                capture_output=True,
                text=True,
                # utf-8 explicitly: `text=True` alone decodes with the locale
                # encoding — cp1252 on Windows — and the CLI emits utf-8 JSON.
                # Measured on a real run: every accent in a hard-tier reply came
                # back mangled and stored that way, and the malformed bytes also
                # produced intermittent "claude CLI returned non-JSON output".
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
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


# A provider that just refused is not going to say yes to the next call a
# second later. The router already walked the fallback chain, but it walked it
# from the top every single time, so a rate-limited provider was re-tried on
# every turn of every agent and each attempt cost a full round trip before the
# chain even started. One real run logged twenty-odd `429 Too Many Requests`
# against the same model in four minutes, and every one of them was a wait the
# operator sat through.
#
# So: remember the refusal for a moment and skip straight past it. Short on
# purpose — free tiers recover in seconds, and a long cooldown would be its own
# outage.
_COOLDOWN_S = 45.0
_RATE_LIMIT_COOLDOWN_S = 90.0
_resting: dict[str, float] = {}


def _rest(provider: str, exc: Exception) -> None:
    """Stand a provider down briefly after it refuses."""
    text = str(exc)
    seconds = _RATE_LIMIT_COOLDOWN_S if ("429" in text or "Too Many" in text) else _COOLDOWN_S
    _resting[provider] = time.monotonic() + seconds


def _is_resting(provider: str) -> bool:
    until = _resting.get(provider, 0.0)
    if not until:
        return False
    if time.monotonic() >= until:
        # Expired: forget it rather than leaving a stale entry to be re-read.
        _resting.pop(provider, None)
        return False
    return True


def resting_providers() -> dict[str, int]:
    """{provider: seconds left}, for the console and the doctor. Never probes."""
    now = time.monotonic()
    return {p: int(until - now) for p, until in _resting.items() if until > now}


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

    def resolve_model(self, difficulty: Difficulty, model: str | None = None) -> str:
        """The `target:name` this call would actually use.

        Public because a caller that has to reason about the model — is it able to
        read a picture? — must ask the same question `generate` answers, and
        `spec.model` is None for nine of the ten roles: the tier decides. Reading
        the tier itself is how a caller ends up disagreeing with the router.
        """
        return model or self._tier_model(difficulty)

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
        images: list[Image] | None = None,
    ) -> LLMResult:
        target, name = _split(model or self._tier_model(difficulty))
        # Mock mode: one deterministic provider; keep the label so you can see
        # which model each agent would have used.
        if self.settings.llm_mock:
            return self.local.generate(
                messages, name, max_tokens, **self._carry(self.local, images)
            )
        if target != "local":
            chain = list(self._chain(target, name))
            # Anything that refused a moment ago goes to the back rather than
            # being dropped: if every provider is resting, a stale cooldown must
            # not be the reason nothing answers at all.
            # The requested target keeps its place at the head, resting or not.
            # Only the fallback steps get reordered.
            #
            # This mattered on a real run, measured: the design role was pinned to
            # `claudecode:opus`, the log said `[design] pinned to claudecode:opus`,
            # and the answer came back from `cerebras:gpt-oss-120b` — which cannot
            # produce JSON, so the tool reported "no model returned usable
            # structure" and did nothing. The pin was demoted because claudecode had
            # refused once earlier in the same run and was inside its 45-second
            # cooldown. A cooldown is a hint; a pinned model is an instruction, and
            # an instruction the router silently reorders is the same
            # declared-but-not-honoured shape this project keeps finding.
            #
            # The cost of trying a resting target first is one failed call, which
            # the chain below already handles. The cost of not trying it is the
            # operator's explicit choice never running.
            head, tail = chain[:1], chain[1:]
            ready = [s for s in tail if not _is_resting(s[0])]
            rested = [s for s in tail if _is_resting(s[0])]
            for step_target, step_name in head + ready + rested:
                provider = self._remote(step_target)
                if provider is None:
                    continue
                try:
                    result = provider.generate(
                        messages, step_name, max_tokens, **self._carry(provider, images)
                    )
                except (requests.RequestException, ProviderError) as exc:
                    _rest(step_target, exc)
                    log.warning(
                        "%s call failed (%s), trying next step: %s", step_target, step_name, exc
                    )
                    continue
                # It answered, so whatever we thought about it is out of date.
                _resting.pop(step_target, None)
                return result
            log.warning(
                "all remote steps failed or unavailable, falling back to local %s",
                self.settings.local_model,
            )
        # Local target, or every remote step was exhausted. One retry covers
        # Ollama cold starts, where the first call can time out while the
        # model is still loading into memory.
        local_name = name if target == "local" else self.settings.local_model
        carried = self._carry(self.local, images)
        try:
            return self.local.generate(messages, local_name, max_tokens, **carried)
        except requests.RequestException as exc:
            log.warning("local %s failed (%s), retrying once", local_name, exc)
            return self.local.generate(messages, local_name, max_tokens, **carried)

    @staticmethod
    def _carry(provider: LLMProvider, images: list[Image] | None) -> dict:
        """`{"images": [...]}` when this provider can carry them, `{}` otherwise.

        A keyword that is simply absent rather than a fourth positional argument,
        because a plugin may register its own provider (corparius/plugins.py)
        written against the three-argument signature that existed before images
        did. A fourth positional breaks that code on its first turn; an omitted
        keyword leaves it working untouched.

        Asked here rather than inside each `generate`, so a provider with no shape
        for a picture never receives one it would have to drop — and a dropped one
        is said, because an image silently missing from a prompt leaves a turn
        reasoning about something it cannot see.
        """
        if not images:
            return {}
        if not getattr(provider, "accepts_images", False):
            log.info("%s carries no images; %d not sent this call", provider.name, len(images))
            return {}
        return {"images": images}

    def embed(self, text: str) -> list[float]:
        return self.local.embed(text)
