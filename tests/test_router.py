"""The HybridRouter must run offline in mock mode and pick the right tier model."""
from app.config import Settings
from app.llm import HybridRouter, _split
from app.models import Difficulty


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
    assert "gemma4:e4b" in res.text   # label carries the resolved model


def test_hard_tier_uses_top_model():
    r = HybridRouter(_mock_settings())
    res = r.generate([{"role": "user", "content": "x"}], difficulty=Difficulty.HARD)
    assert "claude-3-5-sonnet" in res.text


def test_pinned_model_overrides_tier():
    r = HybridRouter(_mock_settings())
    res = r.generate([{"role": "user", "content": "x"}],
                     difficulty=Difficulty.EASY, model="local:qwen2.5-coder:14b")
    assert "qwen2.5-coder:14b" in res.text
