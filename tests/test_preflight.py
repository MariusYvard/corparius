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

import time
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

    catalogue = [f"m{i:03d}" for i in range(100)]
    # `preflight` imports `list_models` at module level, so patching it on `llm`
    # alone leaves the real one in place — and this test then swept the live
    # NVIDIA catalogue over the network. Patch the name the code actually calls.
    monkeypatch.setattr(preflight, "list_models", lambda name, timeout=8: catalogue)
    monkeypatch.setattr(
        preflight, "probe", lambda p, m, tier="", timeout=0: preflight.Probe(p, m, tier, USABLE)
    )
    got = [p.model for p in preflight.probe_catalogue("nvidia", limit=10)]
    assert len(got) == 10
    assert got[0] == "m000" and got[-1] != "m009", "it took the front of the list"
    assert len(set(got)) == 10


def test_a_provider_with_no_catalogue_is_not_a_crash(monkeypatch):
    def boom(name, timeout=8):
        raise requests.ConnectionError("no")

    monkeypatch.setattr(preflight, "list_models", boom)
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


# --------------------------------------------------------------------------
# One pass over everything
# --------------------------------------------------------------------------


def _sweepable(monkeypatch, catalogues, answers=None):
    """A machine with keys for the named providers and these catalogues."""
    from corparius import cfg, llm

    monkeypatch.setattr(
        cfg, "get", lambda key, default="": "k" if key.endswith(("_KEY", "_TOKEN")) else ""
    )
    monkeypatch.setattr(llm, "list_models", lambda name, timeout=8: catalogues.get(name, []))
    monkeypatch.setattr(preflight, "list_models", lambda name, timeout=8: catalogues.get(name, []))
    seen = []

    def fake_probe(provider, model, tier="", timeout=0):
        seen.append((provider, model))
        state = (answers or {}).get(f"{provider}:{model}", USABLE)
        return preflight.Probe(provider, model, tier, state, "", 200 if state == USABLE else 404)

    monkeypatch.setattr(preflight, "probe", fake_probe)
    return seen


def test_the_estimate_prices_the_sweep_without_calling_anything(monkeypatch):
    """NVIDIA alone advertises 102 models; a real sweep of the owner's machine
    prices at 785 calls. Someone pressing "check everything" is spending their
    own money and their own rate limits, so they get the number first."""
    called = []
    monkeypatch.setattr(preflight, "probe", lambda *a, **k: called.append(1))
    _sweepable(monkeypatch, {"groq": ["a", "b"], "nvidia": ["x"]})
    monkeypatch.setattr(preflight, "probe", lambda *a, **k: called.append(1))

    est = preflight.estimate()
    assert est["total"] == sum(est["providers"].values())
    assert not called, "estimating must not call a single model"


def test_a_sweep_covers_every_configured_provider(tmp_path, monkeypatch):
    from corparius.store import Store

    seen = _sweepable(monkeypatch, {"groq": ["a", "b"], "nvidia": ["x", "y", "z"]})
    store = Store(str(tmp_path))
    result = preflight.sweep(store, timeout=1)
    store.close()
    assert result["probed"] == 5
    assert set(seen) >= {("groq", "a"), ("nvidia", "z")}


def test_each_verdict_is_stored_as_it_arrives_so_stopping_keeps_it(tmp_path, monkeypatch):
    """Verified live: a sweep stopped after 27 calls kept all 27. Losing an hour
    of real calls because someone closed a tab would be its own kind of waste."""
    from corparius.store import Store

    _sweepable(monkeypatch, {"groq": [f"m{i}" for i in range(10)]})
    store = Store(str(tmp_path))
    stop_after = 4
    preflight.sweep(store, timeout=1, should_stop=lambda: len(store.known_probes()) >= stop_after)
    kept = store.known_probes()
    store.close()
    assert 0 < len(kept) <= stop_after + 1, len(kept)
    assert all(r["state"] for r in kept)


def test_a_limit_samples_across_the_catalogue_rather_than_its_front(tmp_path, monkeypatch):
    from corparius.store import Store

    seen = _sweepable(monkeypatch, {"groq": [f"m{i:03d}" for i in range(60)]})
    store = Store(str(tmp_path))
    preflight.sweep(store, limit=6, timeout=1)
    store.close()
    models = [m for _, m in seen]
    assert len(models) == 6
    assert models[-1] != "m005", "it took the front of the list"


def test_a_provider_with_no_catalogue_does_not_stop_the_sweep(tmp_path, monkeypatch):
    from corparius import llm
    from corparius.store import Store

    _sweepable(monkeypatch, {"groq": ["a"], "nvidia": ["x"]})

    def half_broken(name, timeout=8):
        if name == "groq":
            raise requests.ConnectionError("no")
        return ["x"]

    monkeypatch.setattr(llm, "list_models", half_broken)
    monkeypatch.setattr(preflight, "list_models", half_broken)
    store = Store(str(tmp_path))
    result = preflight.sweep(store, timeout=1)
    store.close()
    assert result["probed"] >= 1, "one unreachable provider ended the whole pass"


def test_only_providers_with_a_key_are_swept(monkeypatch):
    """Otherwise a sweep spends a minute proving that unconfigured endpoints are
    unconfigured."""
    from corparius import cfg

    monkeypatch.setattr(cfg, "get", lambda key, default="": "k" if key == "GROQ_API_KEY" else "")
    names = preflight.configured_providers()
    assert "groq" in names
    assert "openai" not in names
    # `ovh` needs no key, so it stays in.
    assert "ovh" in names


def test_two_sweeps_at_once_are_refused(tmp_path, monkeypatch):
    """Two threads probing the same rate-limited free tiers would turn every
    answer into a 429 and prove nothing."""
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "false")
    from corparius import webui

    state = webui.UiState(webui._fresh_settings(), tmp_path / ".env")
    state.sweep = {"running": True}
    ctx = types.SimpleNamespace(body={}, state=state, lang="en")
    status, payload = webui._route_sweep_post(ctx)
    state.close()
    assert status == 400 and "already running" in payload["error"]


def test_the_progress_endpoint_reads_state_and_calls_nobody(tmp_path, monkeypatch):
    """It is polled by the page. Probing there would be the polled-endpoint
    mistake with somebody's money attached."""
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: pytest.fail("the progress endpoint called a provider")
    )
    from corparius import webui

    state = webui.UiState(webui._fresh_settings(), tmp_path / ".env")
    preflight.remember(state.store(), [preflight.Probe("groq", "a", state=USABLE, status=200)])
    ctx = types.SimpleNamespace(body={}, state=state, lang="en")
    status, payload = webui._route_sweep_get(ctx)
    state.close()
    assert status == 200
    assert payload["known"] == 1 and payload["usable_by_provider"] == {"groq": 1}


# --------------------------------------------------------------------------
# What the measurement is actually for
# --------------------------------------------------------------------------


def test_recommended_routing_never_writes_a_tier_proved_uncallable():
    """The point of measuring 785 models. Without this the knowledge only
    filtered a dropdown, and "recommended routing" kept writing the pinned
    literal — which is exactly how openrouter's rotted default shipped."""
    from corparius.llm import OPENAI_COMPAT_PROVIDERS, recommended_routing

    default = OPENAI_COMPAT_PROVIDERS["groq"]["default_model"]
    proven = {
        "groq": {
            default: {"state": BLOCKED, "ms": 0},
            "slow-but-works": {"state": USABLE, "ms": 4000},
            "fast-and-works": {"state": USABLE, "ms": 300},
        }
    }
    plan = recommended_routing(["groq"], proven=proven)
    assert plan["CORP_NORMAL_MODEL"] == "groq:fast-and-works", "it picked the fastest proved model"
    assert default not in plan["CORP_NORMAL_MODEL"]


def test_a_working_default_is_never_second_guessed_for_a_faster_one():
    """The defaults are chosen for capability, not latency. Only a *blocked*
    default is replaced."""
    from corparius.llm import OPENAI_COMPAT_PROVIDERS, recommended_routing

    default = OPENAI_COMPAT_PROVIDERS["groq"]["default_model"]
    proven = {
        "groq": {
            default: {"state": USABLE, "ms": 4000},
            "something-faster": {"state": USABLE, "ms": 100},
        }
    }
    assert recommended_routing(["groq"], proven=proven)["CORP_NORMAL_MODEL"] == f"groq:{default}"


def test_with_nothing_measured_routing_is_exactly_what_it_was():
    """No preflight run means no knowledge, and no knowledge must not change
    anybody's configuration."""
    from corparius.llm import recommended_routing

    assert recommended_routing(["groq", "cerebras"]) == recommended_routing(
        ["groq", "cerebras"], proven={}
    )


def test_a_blocked_default_with_no_alternative_is_kept_and_reported(caplog):
    """Swapping it for nothing would be worse. Say so instead."""
    import logging

    from corparius.llm import OPENAI_COMPAT_PROVIDERS, recommended_routing

    default = OPENAI_COMPAT_PROVIDERS["groq"]["default_model"]
    proven = {"groq": {default: {"state": BLOCKED, "ms": 0}}}
    with caplog.at_level(logging.WARNING):
        plan = recommended_routing(["groq"], proven=proven)
    assert plan["CORP_NORMAL_MODEL"] == f"groq:{default}"
    assert "not callable" in caplog.text


# --------------------------------------------------------------------------
# Verdicts age
# --------------------------------------------------------------------------


def test_a_capacity_verdict_is_always_worth_asking_again(tmp_path):
    """It means "the provider was busy", which is not knowledge and never
    becomes knowledge by sitting in a table."""
    from corparius.store import Store

    store = Store(str(tmp_path))
    preflight.remember(
        store,
        [
            preflight.Probe("ovh", "cold", state=CAPACITY, status=503),
            preflight.Probe("groq", "fine", state=USABLE, status=200),
        ],
    )
    worth = preflight.stale(store)
    assert ("ovh", "cold", CAPACITY) in worth
    assert not any(m == "fine" for _, m, _ in worth)
    store.close()


def test_an_old_verdict_is_worth_asking_again(tmp_path):
    """A model blocked six months ago may be open today."""
    from corparius.store import Store

    store = Store(str(tmp_path))
    preflight.remember(store, [preflight.Probe("groq", "old", state=BLOCKED, status=404)])
    store.db.execute("UPDATE model_probes SET ts=?", (time.time() - 90 * 86400,))
    store.db.commit()
    assert ("groq", "old", BLOCKED) in preflight.stale(store)
    assert preflight.stale(store, days=365) == []
    store.close()


def test_the_map_carries_the_age_so_nothing_reads_as_current_fact(tmp_path):
    from corparius.store import Store

    store = Store(str(tmp_path))
    preflight.remember(store, [preflight.Probe("groq", "m", state=USABLE, status=200)])
    store.db.execute("UPDATE model_probes SET ts=?", (time.time() - 10 * 86400,))
    store.db.commit()
    entry = preflight.proven_map(store)["groq"]["m"]
    assert entry["age_days"] == 10 and entry["state"] == USABLE
    store.close()


def test_a_sweep_asks_the_provisional_questions_first(tmp_path, monkeypatch):
    """A sweep stopped early should have spent its calls on what was worth
    asking, not on re-confirming what was proved this morning."""
    from corparius.store import Store

    store = Store(str(tmp_path))
    preflight.remember(store, [preflight.Probe("groq", "c", state=CAPACITY, status=503)])
    seen = _sweepable(monkeypatch, {"groq": ["a", "b", "c", "d"]})
    preflight.sweep(store, timeout=1)
    store.close()
    assert seen[0] == ("groq", "c"), f"the provisional one was not asked first: {seen}"
