"""Getting a free API key is the sharpest edge of onboarding. The console links
straight to each provider's key page and flags the easy ones, driven by metadata
on the provider registry - so these assertions guard that the metadata stays
well-formed and reaches the payload the page renders from.
"""

from corparius.llm import OPENAI_COMPAT_PROVIDERS
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
