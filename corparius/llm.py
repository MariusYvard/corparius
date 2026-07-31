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

    def model(provider: str) -> str:
        default = OPENAI_COMPAT_PROVIDERS[provider]["default_model"]
        known = (proven or {}).get(provider) or {}
        if not known or known.get(default, {}).get("state") != "blocked":
            # Nothing measured, or the default is fine. Never second-guess a
            # working default on the strength of a faster alternative: the
            # defaults are chosen for capability, not latency.
            return f"{provider}:{default}"
        from .preflight import rank

        usable = rank(known)
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
    chain = [model(p) for p in picks if p != normal_p]
    chain += [step for step in fallback_tail if step]
    return {
        "CORP_TRIVIAL_MODEL": f"local:{local_trivial}" if local_trivial else model(normal_p),
        "CORP_NORMAL_MODEL": model(normal_p),
        "CORP_HARD_MODEL": hard or model(hard_p),
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
