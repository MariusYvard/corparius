"""The HybridRouter must run offline in mock mode and pick the right tier model."""

import requests

from app.config import Settings
from app.llm import OPENAI_COMPAT_PROVIDERS, HybridRouter, LLMProvider, _split
from app.models import Difficulty, LLMResult, Usage


def _mock_settings() -> Settings:
    s = Settings()
    s.llm_mock = True
    return s


def test_split_reads_provider_prefix():
    assert _split("cloud:claude-x") == ("cloud", "claude-x")
    assert _split("local:gemma4:e4b") == ("local", "gemma4:e4b")
    assert _split("qwen2.5:7b-instruct") == ("local", "qwen2.5:7b-instruct")


def test_mock_router_runs_offline():
    r = HybridRouter(_mock_settings())
    res = r.generate([{"role": "user", "content": "hi"}], difficulty=Difficulty.TRIVIAL)
    assert res.provider == "mock"
    assert res.usage.total > 0


def test_trivial_tier_uses_tiny_local_model():
    r = HybridRouter(_mock_settings())
    res = r.generate([{"role": "user", "content": "x"}], difficulty=Difficulty.TRIVIAL)
    assert "gemma4:e4b" in res.text  # label carries the resolved model


def test_hard_tier_uses_top_model():
    r = HybridRouter(_mock_settings())
    res = r.generate([{"role": "user", "content": "x"}], difficulty=Difficulty.HARD)
    assert "claude-3-5-sonnet" in res.text


def test_pinned_model_overrides_tier():
    r = HybridRouter(_mock_settings())
    res = r.generate(
        [{"role": "user", "content": "x"}],
        difficulty=Difficulty.EASY,
        model="local:qwen2.5-coder:14b",
    )
    assert "qwen2.5-coder:14b" in res.text


def test_split_reads_free_provider_prefix():
    assert _split("groq:llama-3.3-70b-versatile") == ("groq", "llama-3.3-70b-versatile")
    assert _split("openrouter:deepseek/deepseek-r1-0528:free") == (
        "openrouter",
        "deepseek/deepseek-r1-0528:free",
    )
    assert _split("claudecode:sonnet") == ("claudecode", "sonnet")
    # Unknown prefixes are Ollama tags, not providers.
    assert _split("gemma4:e4b") == ("local", "gemma4:e4b")


def test_provider_registry_is_well_formed():
    for name, spec in OPENAI_COMPAT_PROVIDERS.items():
        assert spec.get("key_env"), name
        assert spec.get("base") or spec.get("base_env"), name
        assert not spec.get("base", "").endswith("/"), name


class _Down(LLMProvider):
    name = "down"

    def generate(self, messages, model, max_tokens=512):
        raise requests.exceptions.ConnectionError("down")


class _Up(LLMProvider):
    name = "up"

    def generate(self, messages, model, max_tokens=512):
        return LLMResult(text=f"up:{model}", usage=Usage(1, 1), model=model, provider=self.name)


def _live_settings() -> Settings:
    s = Settings()
    s.llm_mock = False
    s.cloud_enabled = True
    return s


def test_failed_remote_walks_fallback_chain():
    s = _live_settings()
    s.llm_fallback = ["cerebras:backup-model"]
    r = HybridRouter(s)
    r.remotes = {"groq": _Down(), "cerebras": _Up()}
    res = r.generate([{"role": "user", "content": "x"}], model="groq:main-model")
    assert (res.provider, res.model) == ("up", "backup-model")


def test_exhausted_chain_falls_back_to_local():
    s = _live_settings()
    r = HybridRouter(s)
    r.remotes = {"groq": _Down()}
    r.local = _Up()
    res = r.generate([{"role": "user", "content": "x"}], model="groq:main-model")
    assert res.provider == "up"
    assert res.model == s.local_model


def test_unavailable_provider_skips_to_local():
    # Key not set: the provider is absent from the pool, no crash.
    s = _live_settings()
    r = HybridRouter(s)
    r.remotes = {}
    r.local = _Up()
    res = r.generate([{"role": "user", "content": "x"}], model="groq:main-model")
    assert res.model == s.local_model


def test_local_target_retries_once_on_failure():
    class _FlakyLocal(LLMProvider):
        name = "flaky"
        calls = 0

        def generate(self, messages, model, max_tokens=512):
            type(self).calls += 1
            if type(self).calls == 1:
                raise requests.exceptions.ConnectTimeout("cold load")
            return LLMResult(text="warm", usage=Usage(1, 1), model=model, provider=self.name)

    s = _live_settings()
    r = HybridRouter(s)
    r.local = _FlakyLocal()
    res = r.generate([{"role": "user", "content": "x"}], model="local:gemma4:e4b")
    assert res.text == "warm" and _FlakyLocal.calls == 2


def test_ollama_timeout_is_configurable():
    s = _live_settings()
    s.ollama_timeout = 900
    r = HybridRouter(s)
    assert r.local.timeout == 900
