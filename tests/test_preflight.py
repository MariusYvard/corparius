"""A catalogue lists models that exist. Only a call says you may use one.

`/models` returns names that answer 404 for your key — a paid tier you are not
on, a preview you were never granted, a region your account is not in. Routing
tiers off that list configures a model that fails on the first real turn, with a
company depending on it.

The classification is the whole design, and getting it wrong in the *other*
direction is worse than the catalogue: the free tiers this project is built
around go cold, rate-limit and return 503 while a model loads. Rejecting those
would throw away models that work perfectly a minute later. Verified live
against the owner's own providers before these were written — groq answered in
730 ms, `groq:gpt-4o` came back 404, and OVH returned `HTTP 500 TTL exceeded`,
which is exactly the cold-start case that must never count as a verdict.
"""

import types

import pytest
import requests

from corparius import preflight
from corparius.preflight import BLOCKED, CAPACITY, UNKNOWN, USABLE


class _Response:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = (
            payload if payload is not None else {"choices": [{"message": {"content": "ok"}}]}
        )
        self.text = text or "{}"

    def json(self):
        if self._payload is _BROKEN:
            raise ValueError("not json")
        return self._payload


_BROKEN = object()


@pytest.fixture
def keyed(monkeypatch):
    """A provider with a key set, so probing gets as far as the network."""
    from corparius import cfg

    monkeypatch.setattr(cfg, "get", lambda key, default="": "k" if key.endswith("_KEY") else "")
    return "groq"


def _answer(monkeypatch, response=None, raises=None):
    def fake_post(url, **kwargs):
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(requests, "post", fake_post)


# --------------------------------------------------------------------------
# What each answer means
# --------------------------------------------------------------------------


def test_a_real_answer_is_the_only_thing_that_proves_usable(monkeypatch, keyed):
    _answer(monkeypatch, _Response(200))
    result = preflight.probe(keyed, "m")
    assert result.state == USABLE
    assert result.reply == "ok"
    assert result.ok


def test_a_404_blocks_because_this_account_cannot_call_it(monkeypatch, keyed):
    """Verified live: `groq:gpt-4o` answers 404 with "does not exist or you do
    not have access to it" — a real model name, on a provider that has it, for
    an account that may not use it."""
    _answer(monkeypatch, _Response(404, text='{"error":{"message":"does not exist"}}'))
    result = preflight.probe(keyed, "gpt-4o")
    assert result.state == BLOCKED
    assert "gpt-4o" in result.detail
    assert not result.ok


@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 502, 503, 504])
def test_a_busy_or_cold_provider_is_capacity_never_a_verdict(monkeypatch, keyed, status):
    """The case that matters most. OVH really did return `HTTP 500 TTL exceeded`
    for a model that works: counting that as unusable would delete a working
    fallback from somebody's configuration."""
    _answer(monkeypatch, _Response(status, text="TTL exceeded"))
    result = preflight.probe(keyed, "m")
    assert result.state == CAPACITY, status
    assert result.ok, "capacity must not read as a failure"
    assert "not a verdict" in result.detail


def test_a_timeout_is_capacity_too(monkeypatch, keyed):
    _answer(monkeypatch, raises=requests.Timeout("slow"))
    result = preflight.probe(keyed, "m", timeout=3)
    assert result.state == CAPACITY and result.ok
    assert "3s" in result.detail


def test_an_unreachable_provider_is_capacity_not_a_missing_model(monkeypatch, keyed):
    _answer(monkeypatch, raises=requests.ConnectionError("boom"))
    result = preflight.probe(keyed, "m")
    assert result.state == CAPACITY and result.ok


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_key_blocks_but_says_it_is_the_key(monkeypatch, keyed, status):
    """Distinct from 404 on purpose: swapping the model would not help."""
    _answer(monkeypatch, _Response(status, text="invalid api key"))
    result = preflight.probe(keyed, "m")
    assert result.state == BLOCKED
    assert "key" in result.detail.lower()


def test_a_400_that_names_the_model_blocks_and_a_generic_one_does_not(monkeypatch, keyed):
    """Several gateways answer 400 rather than 404 for a model you may not use.
    The message names it; a 400 about something else must not be read as a
    verdict on the model."""
    _answer(monkeypatch, _Response(400, text='{"error":"unknown model banana-7b"}'))
    assert preflight.probe(keyed, "banana-7b").state == BLOCKED

    _answer(monkeypatch, _Response(400, text='{"error":"temperature must be <= 2"}'))
    assert preflight.probe(keyed, "banana-7b").state == UNKNOWN


def test_a_200_with_an_unreadable_body_is_not_claimed_as_proof(monkeypatch, keyed):
    _answer(monkeypatch, _Response(200, payload=_BROKEN))
    assert preflight.probe(keyed, "m").state == UNKNOWN


def test_a_null_content_does_not_become_the_word_none(monkeypatch, keyed):
    """openrouter's free tier really answers 200 with `content: null`. `str(None)`
    would put "None" in the report as if the model had said it."""
    _answer(monkeypatch, _Response(200, payload={"choices": [{"message": {"content": None}}]}))
    result = preflight.probe(keyed, "m")
    assert result.state == USABLE
    assert result.reply == ""


# --------------------------------------------------------------------------
# What it refuses to guess
# --------------------------------------------------------------------------


def test_no_key_proves_nothing_and_says_so(monkeypatch):
    from corparius import cfg

    monkeypatch.setattr(cfg, "get", lambda key, default="": "")
    result = preflight.probe("groq", "m")
    assert result.state == UNKNOWN and "no key" in result.detail
    assert result.status == 0, "it must not have called anything"


def test_an_unregistered_provider_is_not_a_verdict_on_a_model():
    assert preflight.probe("nowhere", "m").state == UNKNOWN


def test_the_probe_is_eight_tokens_not_a_conversation(monkeypatch, keyed):
    sent = {}

    def fake_post(url, json=None, **kwargs):
        sent.update(json or {})
        sent["url"] = url
        return _Response(200)

    monkeypatch.setattr(requests, "post", fake_post)
    preflight.probe(keyed, "m")
    assert sent["max_tokens"] == preflight.MAX_TOKENS <= 8
    assert len(sent["messages"]) == 1
    assert sent["url"].endswith("/chat/completions")


# --------------------------------------------------------------------------
# Which models get probed
# --------------------------------------------------------------------------


def _settings(**over):
    base = {
        "trivial_model": "groq:a",
        "normal_model": "groq:b",
        "hard_model": "cloud:claude",
        "llm_fallback": ["mistral:c", "ovh:d"],
        "llm_mock": False,
    }
    base.update(over)
    return types.SimpleNamespace(**base)


def test_every_configured_tier_is_probed_role_by_role():
    """Role by role, not provider by provider: two tiers may sit on the same
    provider with different models, one fine and one not."""
    plan = preflight.targets(_settings())
    assert ("trivial", "groq", "a") in plan
    assert ("normal", "groq", "b") in plan
    assert ("fallback", "mistral", "c") in plan
    assert ("fallback", "ovh", "d") in plan


def test_the_fallback_list_is_read_whether_it_is_a_list_or_a_string():
    """Settings hands this over as a list; the environment as a comma string.
    Treating it as a string gave `["['cerebras:gpt-oss-120b'", " 'mistral:...'"]`
    and silently probed none of the fallbacks — found by running it against a
    real configuration."""
    from_list = preflight.targets(_settings(llm_fallback=["mistral:c"]))
    from_str = preflight.targets(_settings(llm_fallback="mistral:c"))
    assert ("fallback", "mistral", "c") in from_list
    assert ("fallback", "mistral", "c") in from_str


def test_the_same_model_twice_is_one_call():
    """Each probe is real money on a real account."""
    plan = preflight.targets(_settings(trivial_model="groq:a", normal_model="groq:a"))
    assert [p for p in plan if p[1:] == ("groq", "a")] == [("trivial", "groq", "a")]


def test_what_it_cannot_prove_is_reported_not_dropped():
    """`claudecode:` goes through the local CLI and `local:` through Ollama;
    neither speaks this API. A preflight that covers three of six tiers and says
    "everything checks out" is worse than one that admits its reach."""
    s = _settings(hard_model="claudecode:opus", llm_fallback=["local:qwen", "mistral:c"])
    assert ("hard", "claudecode:opus") in preflight.skipped(s)
    assert ("fallback", "local:qwen") in preflight.skipped(s)
    assert all(t[1] != "claudecode" for t in preflight.targets(s))


def test_mock_mode_calls_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: called.append(1))
    report = preflight.run(_settings(llm_mock=True))
    assert report.probes == [] and not called


# --------------------------------------------------------------------------
# The cache the doctor reads
# --------------------------------------------------------------------------


def test_a_report_survives_a_round_trip(tmp_path):
    from corparius.store import Store

    store = Store(str(tmp_path))
    report = preflight.Report(
        ts=1.0,
        probes=[
            preflight.Probe("groq", "a", "normal", USABLE, "answered in 700 ms", 200, 700),
            preflight.Probe("ovh", "d", "fallback", CAPACITY, "HTTP 500", 500, 20),
        ],
    )
    preflight.save(store, report)
    back = preflight.load(store)
    assert [p.as_dict() for p in back.probes] == [p.as_dict() for p in report.probes]
    assert back.ts == 1.0
    assert len(back.blocking) == 0 and len(back.transient) == 1
    store.close()


def test_no_previous_run_is_an_empty_report_not_a_crash(tmp_path):
    from corparius.store import Store

    store = Store(str(tmp_path))
    assert preflight.load(store).probes == []
    store.set_setting("CORP_PREFLIGHT", "not json at all")
    assert preflight.load(store).probes == []
    store.close()


def test_the_doctor_reads_the_cache_and_never_calls_a_provider(tmp_path, monkeypatch):
    """A probe costs a real generation, and the doctor runs on every launcher
    start and is served over HTTP. Measuring here would be the polled-endpoint
    mistake with somebody's money attached."""
    from corparius.config import Settings
    from corparius.doctor import _check_preflight
    from corparius.store import Store

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "false")
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: pytest.fail("the doctor called a provider")
    )

    s = Settings()
    level, name, message = _check_preflight(s)[:3]
    assert (level, name) == ("ok", "preflight") and "never run" in message

    store = Store(str(tmp_path))
    preflight.save(
        store,
        preflight.Report(
            ts=1.0, probes=[preflight.Probe("groq", "a", "normal", BLOCKED, "HTTP 404", 404)]
        ),
    )
    store.close()
    level, _, message = _check_preflight(s)[:3]
    assert level == "warn" and "groq:a" in message


def test_a_cold_provider_does_not_make_the_doctor_complain(tmp_path, monkeypatch):
    from corparius.config import Settings
    from corparius.doctor import _check_preflight
    from corparius.store import Store

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "false")
    store = Store(str(tmp_path))
    preflight.save(
        store,
        preflight.Report(
            ts=1.0,
            probes=[
                preflight.Probe("groq", "a", "normal", USABLE, "ok", 200),
                preflight.Probe("ovh", "d", "fallback", CAPACITY, "HTTP 500", 500),
            ],
        ),
    )
    store.close()
    level, _, message = _check_preflight(Settings())[:3]
    assert level == "ok"
    assert "rate-limited or cold" in message and "not rejected" in message


# --------------------------------------------------------------------------
# What is remembered, per provider
# --------------------------------------------------------------------------


def test_a_verdict_is_remembered_per_provider_and_model(tmp_path):
    """The first version kept one report per run and overwrote it, so the same
    404s were rediscovered every time. Measured on NVIDIA with a real key: 10 of
    18 catalogue entries answered 404. That is worth keeping."""
    from corparius.store import Store

    store = Store(str(tmp_path))
    preflight.remember(
        store,
        [
            preflight.Probe("nvidia", "meta/llama-3.1-8b-instruct", state=USABLE, status=200),
            preflight.Probe("nvidia", "nvidia/nv-embed-v1", state=BLOCKED, status=404),
            preflight.Probe("groq", "llama-3.3-70b-versatile", state=USABLE, status=200),
        ],
    )
    assert preflight.known(store) == {
        "nvidia": ["meta/llama-3.1-8b-instruct"],
        "groq": ["llama-3.3-70b-versatile"],
    }
    assert preflight.known(store, "nvidia") == {"nvidia": ["meta/llama-3.1-8b-instruct"]}
    assert len(store.known_probes()) == 3
    store.close()


def test_a_later_run_updates_a_verdict_instead_of_adding_a_second(tmp_path):
    """A model that was cold last week and answers today must end up with
    today's verdict, not two rows disagreeing."""
    from corparius.store import Store

    store = Store(str(tmp_path))
    preflight.remember(store, [preflight.Probe("ovh", "m", state=CAPACITY, status=503)])
    preflight.remember(store, [preflight.Probe("ovh", "m", state=USABLE, status=200)])
    rows = store.known_probes("ovh")
    assert len(rows) == 1 and rows[0]["state"] == USABLE
    store.close()


def test_nothing_is_remembered_when_nothing_was_called(tmp_path):
    """No key means no knowledge. Writing "unknown" would let a later run treat
    an unasked question as an answered one."""
    from corparius.store import Store

    store = Store(str(tmp_path))
    preflight.remember(store, [preflight.Probe("groq", "m", state=UNKNOWN, detail="no key set")])
    assert store.known_probes() == []
    store.close()


def test_a_catalogue_sweep_spreads_across_the_list_rather_than_taking_the_front(monkeypatch):
    """Providers list alphabetically. The first twenty of "01-ai…" through
    "ai21labs…" are not a sample of a 102-model catalogue."""
    from corparius import llm

    catalogue = [f"m{i:03d}" for i in range(100)]
    monkeypatch.setattr(llm, "list_models", lambda name, timeout=8: catalogue)
    monkeypatch.setattr(
        preflight, "probe", lambda p, m, tier="", timeout=0: preflight.Probe(p, m, tier, USABLE)
    )
    got = [p.model for p in preflight.probe_catalogue("nvidia", limit=10)]
    assert len(got) == 10
    assert got[0] == "m000" and got[-1] != "m009", "it took the front of the list"
    assert len(set(got)) == 10


def test_a_provider_with_no_catalogue_is_not_a_crash(monkeypatch):
    from corparius import llm

    def boom(name, timeout=8):
        raise requests.ConnectionError("no")

    monkeypatch.setattr(llm, "list_models", boom)
    assert preflight.probe_catalogue("nvidia") == []


def test_the_model_picker_hides_what_is_proved_uncallable(tmp_path, monkeypatch):
    """The whole point of remembering. Offering a name known to 404 is worse
    than offering nothing."""
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    from corparius import llm, webui
    from corparius.store import Store

    store = Store(str(tmp_path))
    preflight.remember(
        store,
        [
            preflight.Probe("nvidia", "good", state=USABLE, status=200),
            preflight.Probe("nvidia", "bad", state=BLOCKED, status=404),
        ],
    )
    store.close()
    monkeypatch.setattr(llm, "list_models", lambda name, timeout=8: ["good", "bad", "untried"])

    state = webui.UiState(webui._fresh_settings(), tmp_path / ".env")
    ctx = types.SimpleNamespace(body={"name": "nvidia"}, state=state, lang="en")
    status, payload = webui._route_provider_models(ctx)
    state.close()

    assert status == 200 and payload["ok"]
    assert payload["proved"] == {"good": USABLE, "bad": BLOCKED}
    # `bad` is still listed; the page drops it, and the count says how many.
    assert "untried" in payload["models"], "an unprobed model is still offered"
