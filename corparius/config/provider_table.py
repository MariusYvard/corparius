"""Which remote LLM providers exist, and how a tier model names one. Rank 1.

This is a registry, not a client. It says a provider exists, what environment variable
holds its key, where its endpoint is and where an operator signs up — and nothing about how
to call one. That distinction is the point: it lived in `llm.py`, so **reading a setting
loaded the HTTP stack and the process spawner**. `settings_spec.py` imported `llm` on one
line out of 1 380, to read this dict, and paid `requests`, `subprocess` and `ssl` for it.

`split_target` comes with it, and belongs here rather than in the kernel: deciding whether
`groq:` is a provider prefix or part of an Ollama tag requires knowing which providers are
registered, and the registry is registered *here*. It was `llm._split`, a private name
reached from eleven modules — one of which, `agents.py`, imported `llm` for nothing else.

The dict is mutated in place at runtime: a provider plugin adds a row (see
`plugins.register_llm_provider`). Callers therefore hold the object, never a copy, and
rebinding this name would silently strand every one of them.
"""

from __future__ import annotations

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


def split_target(model_str: str) -> tuple[str, str]:
    """Split a tier model into (target, name). "cloud:x" -> ("cloud", "x") and
    "groq:x" -> ("groq", "x") for any registered provider. A bare name or an
    unknown prefix (Ollama tags like "gemma4:e4b") defaults to local."""
    prefix, sep, rest = model_str.partition(":")
    if sep and (prefix in ("cloud", "local", "claudecode") or prefix in OPENAI_COMPAT_PROVIDERS):
        return prefix, rest
    return "local", model_str
