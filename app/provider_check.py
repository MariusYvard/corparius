"""Prove a provider works, rather than storing a key and hoping.

The 14 free tiers were already wired; what was missing was a way to tell a good
key from a typo without launching a whole company day. Every provider gets the
same Test the mail account and the Claude CLI got: one minimal real call, a
readable verdict, the fix named instead of the HTTP status.
"""
from __future__ import annotations

import requests

from . import cfg
from .llm import OPENAI_COMPAT_PROVIDERS, OpenAICompatProvider

# A cheap, widely-available model per provider for the probe, so the test does
# not fail merely because a default model name is wrong. Empty means "let the
# operator's configured tier decide" / provider default.
_PROBE_MODEL = {
    "groq": "llama-3.1-8b-instant",
    "cerebras": "llama3.1-8b",
    "openrouter": "meta-llama/llama-3.2-3b-instruct:free",
    "mistral": "mistral-small-latest",
    "gemini": "gemini-2.0-flash",
    "nvidia": "meta/llama-3.1-8b-instruct",
    "github": "gpt-4o-mini",
    "cohere": "command-r",
    "huggingface": "meta-llama/Llama-3.1-8B-Instruct",
    "ovh": "Meta-Llama-3_1-8B-Instruct",
    "zhipu": "glm-4-flash",
    "siliconflow": "Qwen/Qwen2.5-7B-Instruct",
    "cloudflare": "@cf/meta/llama-3.1-8b-instruct",
    "custom": "",
}


def _diagnose(status: int, provider: str, body: str) -> str:
    if status in (401, 403):
        return ("The provider rejected this key. Copy it again from your account; a "
                "fresh key with chat access is enough.")
    if status == 404:
        return ("Connected and authorised, but the probe model is unknown to this "
                "account. The key is likely fine; pick a model this provider serves in "
                "the routing tiers.")
    if status == 429:
        return "The key works, but you are rate-limited right now. Try again in a moment."
    if status >= 500:
        return f"The provider is having trouble ({status}). Not your key; try again later."
    return f"The provider answered {status}: {body[:160]}"


def check(name: str, timeout: int = 20) -> dict:
    """One minimal chat call against a configured provider."""
    spec = OPENAI_COMPAT_PROVIDERS.get(name)
    if spec is None:
        return {"ok": False, "configured": False, "detail": f"Unknown provider '{name}'."}
    base = cfg.get(spec.get("base_env", ""), "").strip() or spec["base"]
    key = cfg.get(spec["key_env"], "").strip()
    if not base:
        return {"ok": False, "configured": False,
                "detail": f"Set the endpoint ({spec['base_env']}) first."}
    if not key and not spec.get("key_optional"):
        return {"ok": False, "configured": False,
                "detail": f"No key set yet ({spec['key_env']})."}
    model = _PROBE_MODEL.get(name) or cfg.get("CORP_NORMAL_MODEL", "").split(":")[-1] or "gpt-4o-mini"
    provider = OpenAICompatProvider(name, base, key, timeout=timeout)
    try:
        result = provider.generate(
            [{"role": "user", "content": "Reply with the single word: ready"}],
            model, max_tokens=8)
    except requests.HTTPError as exc:
        resp = exc.response
        return {"ok": False, "configured": True,
                "detail": _diagnose(resp.status_code if resp is not None else 0, name,
                                    resp.text if resp is not None else str(exc))}
    except requests.RequestException as exc:
        return {"ok": False, "configured": True,
                "detail": f"Could not reach {name}: {exc}"}
    return {"ok": True, "configured": True,
            "detail": f"{name} answered as {result.model}. The key works."}
