"""The HybridRouter must run offline in mock mode and pick the right tier model."""

import pytest
import requests

from corparius.config.provider_table import OPENAI_COMPAT_PROVIDERS, split_target
from corparius.config.settings import Settings
from corparius.kernel.records import Difficulty, LLMResult, Usage
from corparius.providers import llm as llm_mod
from corparius.providers.llm import HybridRouter, LLMProvider


def _mock_settings() -> Settings:
    s = Settings()
    s.llm_mock = True
    return s


def test_split_reads_provider_prefix():
    assert split_target("cloud:claude-x") == ("cloud", "claude-x")
    assert split_target("local:gemma4:e4b") == ("local", "gemma4:e4b")
    assert split_target("qwen2.5:7b-instruct") == ("local", "qwen2.5:7b-instruct")


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
    assert split_target("groq:llama-3.3-70b-versatile") == ("groq", "llama-3.3-70b-versatile")
    assert split_target("openrouter:deepseek/deepseek-r1-0528:free") == (
        "openrouter",
        "deepseek/deepseek-r1-0528:free",
    )
    assert split_target("claudecode:sonnet") == ("claudecode", "sonnet")
    # Unknown prefixes are Ollama tags, not providers.
    assert split_target("gemma4:e4b") == ("local", "gemma4:e4b")


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


# --- a cooldown is a hint; the requested model is an instruction ---------------


def _asked_provider(monkeypatch, settings, model, resting=()):
    """Which provider actually got the call, given a chain and a set of resting ones."""
    import corparius.providers.llm as llm_mod

    asked: list[str] = []

    class Fake(LLMProvider):
        def __init__(self, name):
            self.name = name

        def generate(self, messages, model, max_tokens=512, images=None):
            asked.append(self.name)
            return LLMResult("ok", self.name, model, Usage(1, 1))

    monkeypatch.setattr(llm_mod, "_resting", {p: float("inf") for p in resting})
    monkeypatch.setattr(llm_mod, "_is_resting", lambda p: p in resting)
    router = HybridRouter(settings)
    monkeypatch.setattr(router, "_remote", lambda target: Fake(target))
    router.generate([{"role": "user", "content": "x"}], model=model)
    return asked


def _live_settings():
    s = Settings()
    s.llm_mock = False
    s.cloud_enabled = True
    s.llm_fallback = ["cerebras:gpt-oss-120b", "groq:llama-3.3-70b-versatile"]
    return s


def test_a_resting_target_is_still_tried_first(monkeypatch):
    """Measured on a real run: the design role was pinned to `claudecode:opus`, the
    log said so, and the answer came from `cerebras:gpt-oss-120b` — which cannot
    produce JSON, so the tool reported "no model returned usable structure" and did
    nothing. The pin had been demoted because claudecode refused once earlier in the
    same run and was inside its 45-second cooldown."""
    asked = _asked_provider(
        monkeypatch, _live_settings(), "claudecode:opus", resting=("claudecode",)
    )
    assert asked[0] == "claudecode", f"the pinned target was demoted: {asked}"


def test_fallback_steps_are_still_reordered_by_cooldown(monkeypatch):
    """The reordering keeps its purpose for the steps it was written for: a stale
    cooldown must not be the reason nothing answers at all."""
    s = _live_settings()

    import corparius.providers.llm as llm_mod

    asked: list[str] = []

    class Failing(LLMProvider):
        def __init__(self, name):
            self.name = name

        def generate(self, messages, model, max_tokens=512, images=None):
            asked.append(self.name)
            if self.name in ("claudecode", "cerebras"):
                raise llm_mod.ProviderError("nope")
            return LLMResult("ok", self.name, model, Usage(1, 1))

    monkeypatch.setattr(llm_mod, "_is_resting", lambda p: p == "cerebras")
    router = HybridRouter(s)
    monkeypatch.setattr(router, "_remote", lambda target: Failing(target))
    router.generate([{"role": "user", "content": "x"}], model="claudecode:opus")
    # claudecode first because it was asked for, then groq because cerebras is
    # resting — and cerebras is never reached at all, since groq answers. That
    # ordering is the whole point: `asked` says it exactly.
    assert asked == ["claudecode", "groq"], f"chain order wrong: {asked}"


def test_the_chain_order_is_otherwise_unchanged(monkeypatch):
    asked = _asked_provider(monkeypatch, _live_settings(), "claudecode:opus")
    assert asked == ["claudecode"], "a target that answers must end the chain"


def test_a_tier_default_is_still_demoted_by_its_cooldown(monkeypatch):
    """The other direction, and I got this wrong once. Putting a *tier* model at
    the head regardless of its cooldown brought back the exact failure the cooldown
    was written for: measured on a real run, twenty-odd `429 Too Many Requests`
    against one model in four minutes, each one a wait the operator sat through.

    Head-first is for a model somebody named, not for a default."""
    s = _live_settings()
    s.normal_model = "groq:llama-3.3-70b-versatile"
    asked = _asked_provider(monkeypatch, s, None, resting=("groq",))
    assert asked and asked[0] != "groq", f"the resting tier model was tried first: {asked}"


# --- whose fault it was ------------------------------------------------------------
#
# Taken from reading LiteLLM's router, which draws this line from the other end: it cools down on
# 429, 401, 408 and 5XX, exempts other 4XX outright, and never cools down an `APIConnectionError`.
# The reasoning transports even though almost nothing else in that file does — its ratio-based rule
# (50% failures over at least five requests) needs a request volume a company turn does not have,
# and its five-second default suits a pool of interchangeable deployments rather than a short chain
# of free tiers on per-minute limits.
#
# Measured here before the rule existed, and every one of these six was rested for 45 or 90 seconds:
#
#     429 the provider is limiting us      right
#     401 our key is wrong                 right
#     400 our request is malformed         wrong
#     the prompt exceeded the context      wrong, and expensively
#     a passing network blip               wrong
#     503 the provider is down             right


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (requests.HTTPError("429 Client Error: Too Many Requests"), "rate_limit"),
        (requests.HTTPError("Rate limit reached for model"), "rate_limit"),
        (requests.HTTPError("401 Client Error: Unauthorized"), "auth"),
        (requests.HTTPError("Invalid API key provided"), "auth"),
        (requests.HTTPError("400 Client Error: Bad Request"), "bad_request"),
        (llm_mod.ProviderError("maximum context length is 8192 tokens"), "context"),
        (requests.ConnectionError("Connection aborted"), "unreachable"),
        (requests.Timeout("Read timed out"), "timeout"),
        (requests.HTTPError("503 Server Error: Service Unavailable"), "unavailable"),
        (llm_mod.ProviderError("something nobody has seen"), "unknown"),
    ],
)
def test_every_refusal_is_given_a_cause(exc, expected):
    """The taxonomy, before any rule reads it. `"429" in str(exc)` at each place that cares is one
    classifier per caller, which is how two of them come to disagree."""
    assert llm_mod.cause_of(exc) == expected


def test_a_context_overflow_is_read_before_the_400_it_arrives_as():
    """Ordering that matters and would be invisible otherwise. A context overflow *is* a 400, and
    the two want opposite things from an operator: shorten what you are sending, versus fix how you
    are sending it."""
    both = requests.HTTPError("400 Bad Request: maximum context length is 8192 tokens")
    assert llm_mod.cause_of(both) == "context"


@pytest.mark.parametrize(
    "exc",
    [
        requests.HTTPError("429 Too Many Requests"),
        requests.HTTPError("401 Unauthorized"),
        requests.HTTPError("503 Service Unavailable"),
        requests.Timeout("Read timed out"),
    ],
)
def test_what_the_provider_owns_stands_it_down(exc):
    llm_mod._resting.clear()
    llm_mod._rest("groq", exc)
    assert llm_mod._is_resting("groq") is True


@pytest.mark.parametrize(
    "exc",
    [
        requests.HTTPError("400 Client Error: Bad Request"),
        llm_mod.ProviderError("maximum context length is 8192 tokens"),
        requests.ConnectionError("Connection aborted"),
    ],
)
def test_what_we_sent_never_stands_a_provider_down(exc):
    """The correction. A malformed request and a prompt too long are ours, and a network that is
    down is nobody's — resting a healthy service for any of the three takes capacity away for a
    minute and a half over a fault the provider had no part in."""
    llm_mod._resting.clear()
    llm_mod._rest("groq", exc)
    assert llm_mod._is_resting("groq") is False


def test_our_own_bug_can_no_longer_empty_the_whole_chain():
    """The expensive one, and the reason this was worth changing.

    A prompt that overflows the context fails at the first provider, is rested there, and is then
    sent **unchanged** to the next one, which fails identically and is rested too. Three steps later
    the chain is empty, everything falls through to a local Ollama that may not be installed, and
    the operator is told no model could be reached — which is the path this project already followed
    to a 500 in the CEO chat.
    """
    llm_mod._resting.clear()
    too_long = llm_mod.ProviderError("maximum context length is 8192 tokens")
    for provider in ("groq", "cerebras", "openrouter", "mistral"):
        llm_mod._rest(provider, too_long)
    assert llm_mod.resting_providers() == {}, "one bad prompt stood the whole chain down"


def test_a_rate_limit_rests_longer_than_an_outage():
    """Free tiers meter per minute, so the wait has to outlast the window that refused; a 503 is
    over when it is over. Different numbers because they are different facts."""
    llm_mod._resting.clear()
    llm_mod._rest("groq", requests.HTTPError("429 Too Many Requests"))
    llm_mod._rest("cerebras", requests.HTTPError("503 Service Unavailable"))
    left = llm_mod.resting_providers()
    assert left["groq"] > left["cerebras"]


def test_the_two_classes_of_cause_do_not_overlap():
    """Both ends of the thread. A cause in neither list would be silently treated as ours and never
    rest anything, which is the failure that looks like working."""
    assert not (set(llm_mod.THEIRS) & set(llm_mod.OURS))
    assert not (set(llm_mod.THEIRS) & set(llm_mod.NOBODY))
    named = set(llm_mod.THEIRS) | set(llm_mod.OURS) | set(llm_mod.NOBODY)
    seen = {
        llm_mod.cause_of(e)
        for e in (
            requests.HTTPError("429"),
            requests.HTTPError("401"),
            requests.HTTPError("400"),
            requests.HTTPError("503"),
            requests.Timeout("timed out"),
            requests.ConnectionError("x"),
            llm_mod.ProviderError("context length"),
            llm_mod.ProviderError("?"),
        )
    }
    assert seen <= named, f"causes nothing classifies: {sorted(seen - named)}"
