"""Getting a free API key is the sharpest edge of onboarding. The console links
straight to each provider's key page and flags the easy ones, driven by metadata
on the provider registry - so these assertions guard that the metadata stays
well-formed and reaches the payload the page renders from. The routing helpers
that turn a connected key into a working full configuration are covered too.
"""

from corparius.llm import OPENAI_COMPAT_PROVIDERS, list_models, recommended_routing
from corparius.settings_spec import LLM_SERVER_PRESETS
from corparius.webui import _providers_payload


def test_every_real_provider_has_an_https_signup_link():
    """custom is self-hosted (no signup); every other provider must point at a
    real https key page, since the console renders it as a 'get a key' link."""
    for name, spec in OPENAI_COMPAT_PROVIDERS.items():
        if name == "custom":
            assert "signup" not in spec
            continue
        signup = spec.get("signup", "")
        assert signup.startswith("https://"), f"{name} has no https signup link"


def test_recommended_providers_are_the_easy_ones():
    """'Start here' must mean what it says: no card, and a known-good model to
    route to on one click. An over-promised recommendation is worse than none."""
    recommended = {n for n, s in OPENAI_COMPAT_PROVIDERS.items() if s.get("recommended")}
    assert recommended == {"groq", "cerebras"}
    for name in recommended:
        spec = OPENAI_COMPAT_PROVIDERS[name]
        assert spec.get("no_card") is True, f"{name} is recommended but not no_card"
        assert spec.get("default_model"), f"{name} is recommended but has no default_model"


def test_no_card_flag_is_kept_factual():
    """Only providers the docs confirm need no payment card carry the badge."""
    no_card = {n for n, s in OPENAI_COMPAT_PROVIDERS.items() if s.get("no_card")}
    assert no_card == {"groq", "cerebras", "github", "ovh"}


def test_default_models_belong_to_providers_that_can_be_activated():
    """One-click activation routes the normal tier to `<provider>:<default_model>`,
    so a default_model only makes sense on a provider that takes a key/endpoint."""
    for name, spec in OPENAI_COMPAT_PROVIDERS.items():
        if spec.get("default_model"):
            assert spec.get("key_env"), f"{name} has a default_model but no key_env"


def test_payload_surfaces_the_onboarding_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    from corparius import cfg

    cfg.invalidate()
    payload = _providers_payload()
    by_name = {p["name"]: p for p in payload["providers"]}
    groq = by_name["groq"]
    assert groq["signup"] == "https://console.groq.com/keys"
    assert groq["no_card"] is True and groq["recommended"] is True
    assert groq["default_model"] == "llama-3.3-70b-versatile"
    # custom carries the fields too, empty/false, so the page can render uniformly.
    custom = by_name["custom"]
    assert custom["signup"] == "" and custom["recommended"] is False


# --- recommended routing: one connected key -> a coherent full config ----------


def test_recommended_routing_is_none_without_a_usable_provider():
    assert recommended_routing([], ollama_ready=False) is None
    # gemini is connectable but has no default_model, so it cannot be auto-routed.
    assert recommended_routing(["gemini"], ollama_ready=False) is None


def test_recommended_routing_fills_every_tier_from_one_provider():
    """The gap this closes: one free key must leave no tier pointing at something
    unconfigured. With only Groq and no Ollama, all three land on Groq."""
    r = recommended_routing(["groq"], ollama_ready=False)
    assert r["CORP_NORMAL_MODEL"] == "groq:llama-3.3-70b-versatile"
    assert r["CORP_HARD_MODEL"] == "groq:llama-3.3-70b-versatile"
    assert r["CORP_TRIVIAL_MODEL"] == "groq:llama-3.3-70b-versatile"
    assert r["CORP_LLM_FALLBACK"] == ""


def test_recommended_routing_uses_reasoning_for_hard_and_local_for_trivial():
    r = recommended_routing(["groq", "cerebras", "openrouter"], ollama_ready=True)
    assert r["CORP_NORMAL_MODEL"].startswith("groq:")  # fast general first
    assert r["CORP_HARD_MODEL"].startswith("openrouter:")  # reasoning model on hard
    assert r["CORP_TRIVIAL_MODEL"] == "local:gemma4:e4b"  # Ollama up -> keep it local
    fb = r["CORP_LLM_FALLBACK"]
    assert "cerebras:" in fb and "openrouter:" in fb and "groq:" not in fb


def test_recommended_routing_ignores_providers_without_a_default_model():
    """github is connectable but carries no default_model, so it never appears in
    the routing even when 'configured'."""
    r = recommended_routing(["github", "cerebras"], ollama_ready=False)
    assert "github:" not in "".join(r.values())
    assert r["CORP_NORMAL_MODEL"].startswith("cerebras:")


# --- model listing -------------------------------------------------------------


def test_list_models_returns_sorted_ids(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "b-model"}, {"id": "a-model"}, {"id": ""}]}

    monkeypatch.setattr("corparius.llm.requests.get", lambda *a, **k: _Resp())
    assert list_models("groq") == ["a-model", "b-model"]


def test_list_models_empty_when_no_endpoint():
    # custom with no CORP_CUSTOM_LLM_URL set has no base, so nothing to query.
    assert list_models("custom") == []
    assert list_models("not-a-provider") == []


# --- OmniRoute: one endpoint, many free tiers, keyless out of the box ----------


def test_omniroute_is_a_server_preset_with_the_real_endpoint():
    omni = next((p for p in LLM_SERVER_PRESETS if p["id"] == "omniroute"), None)
    assert omni is not None, "OmniRoute should be offered as a custom-target preset"
    assert omni["url"] == "http://localhost:20128/v1"
    assert "docker run" in omni["note_en"] and "docker run" in omni["note_fr"]
