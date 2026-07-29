"""An app is the company's own use of the providers corparius already has.

The thing being prevented is an operator copying an API key into a web page to
give their site a FAQ. So an app has to reach the same router the agents use,
and carry its own ceilings — an endpoint that calls a model for whoever asks is
a way to spend someone else's subscription, and a limit added later is a limit
that was missing when it mattered.
"""

import time

import pytest
import yaml

from corparius import apps
from corparius.models import Difficulty, LLMResult, Usage
from corparius.store import Store

FAQ = {
    "name": "faq",
    "description": "Answers one question about the offer.",
    "system": "You answer questions about the offer. Never invent a price.",
    "tier": "trivial",
    "max_tokens": 300,
    "daily_tokens": 20000,
    "rate_per_minute": 6,
    "origins": ["https://example.test"],
}


def _app_file(tmp_path, data=None, name="faq.yaml"):
    directory = tmp_path / "companies" / "t" / "apps"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(yaml.safe_dump(FAQ if data is None else data), encoding="utf-8")
    return path


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """paths.user_home() follows CORP_HOME, which the hermetic fixture does not
    pin — in a source checkout it resolves to the repository root, so a test
    that forgets this reads (or writes) the real companies/ folder."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    return tmp_path


def test_an_app_is_parsed_with_its_ceilings(home):
    app = apps.parse(_app_file(home))
    assert app is not None
    assert app.name == "faq" and app.tier is Difficulty.TRIVIAL
    assert (app.max_tokens, app.daily_tokens, app.rate_per_minute) == (300, 20000, 6)
    assert app.origins == ["https://example.test"]


def test_the_spend_is_attributed_to_a_name_the_console_already_renders():
    """record_usage groups by agent and the console renders that grouping, so
    `app:faq` shows up in the cost breakdown with no new reporting code."""
    app = apps.App(name="faq", system="s")
    assert app.agent == "app:faq"


def test_missing_ceilings_fall_back_to_the_defaults_not_to_none(home):
    app = apps.parse(_app_file(home, {"name": "bare", "system": "s"}))
    assert app is not None
    assert app.daily_tokens == apps.DEFAULT_DAILY_TOKENS
    assert app.rate_per_minute == apps.DEFAULT_RATE_PER_MINUTE
    assert app.max_tokens == apps.DEFAULT_MAX_TOKENS


def test_a_nonsense_ceiling_falls_back_rather_than_disabling_the_limit(home):
    """0 or "lots" must not read as "no limit". That is the direction that
    costs money."""
    for bad in (0, -5, "lots", None):
        app = apps.parse(_app_file(home, {"name": "b", "system": "s", "daily_tokens": bad}))
        assert app is not None and app.daily_tokens == apps.DEFAULT_DAILY_TOKENS


def test_an_app_with_no_system_prompt_is_refused(home, caplog):
    """The system prompt is the whole definition. Defaulting it would invent a
    company's voice."""
    assert apps.parse(_app_file(home, {"name": "empty"})) is None


def test_a_malformed_app_is_skipped_not_raised(home):
    path = home / "companies" / "t" / "apps" / "broken.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("just a string, not a mapping", encoding="utf-8")
    assert apps.parse(path) is None
    _app_file(home)
    assert [a.name for a in apps.load("t")] == ["faq"], "one bad file must not hide the good ones"


def test_no_apps_directory_is_an_empty_list_not_an_error(home):
    assert apps.load("nobody") == []
    assert apps.get("nobody", "faq") is None


def test_an_unknown_tier_lands_on_the_cheapest(home):
    """A typo must not silently promote a FAQ to the hard tier, which is the
    one that costs the most per call."""
    app = apps.parse(_app_file(home, {"name": "t", "system": "s", "tier": "expensive"}))
    assert app is not None and app.tier is Difficulty.TRIVIAL


def test_normal_is_accepted_as_the_rosters_word_for_easy(home):
    app = apps.parse(_app_file(home, {"name": "t", "system": "s", "tier": "normal"}))
    assert app is not None and app.tier is Difficulty.EASY


# --- running --------------------------------------------------------------


def _router(monkeypatch, text="ok", usage=(10, 5, 0.0)):
    seen = {}

    class _R:
        def __init__(self, settings):
            pass

        def generate(self, messages, difficulty=None, model=None, max_tokens=512):
            seen["messages"] = messages
            seen["difficulty"] = difficulty
            seen["max_tokens"] = max_tokens
            return LLMResult(text=text, usage=Usage(*usage), model="m", provider="p")

    monkeypatch.setattr("corparius.llm.HybridRouter", _R)
    return seen


def test_running_an_app_records_its_spend_under_its_own_name(tmp_path, monkeypatch):
    seen = _router(monkeypatch)
    store = Store(str(tmp_path))
    app = apps.App(name="faq", system="s", tier=Difficulty.TRIVIAL, max_tokens=300)
    out = apps.run(app, "t", store, "how much?")
    assert out["ok"] and out["text"] == "ok"
    assert seen["difficulty"] is Difficulty.TRIVIAL and seen["max_tokens"] == 300
    assert store.spend_by_agent("t")[0]["agent"] == "app:faq"


def test_the_company_is_quoted_to_the_model(tmp_path, monkeypatch):
    """Without it the app answers about businesses in general. The config is
    already parsed, so quoting it costs nothing to keep true."""
    seen = _router(monkeypatch)
    app = apps.App(name="faq", system="Answer questions.")
    apps.run(
        app, "t", Store(str(tmp_path)), "how much?", {"name": "CVBoost", "offer": {"price_eur": 9}}
    )
    system = seen["messages"][0]["content"]
    assert "CVBoost" in system and "9" in system
    assert seen["messages"][1] == {"role": "user", "content": "how much?"}


def test_an_unreachable_model_is_a_refusal_not_a_traceback(tmp_path, monkeypatch):
    """This runs behind a public endpoint. A visitor gets a refusal and the
    site that called stays up."""
    import requests

    class _R:
        def __init__(self, settings):
            pass

        def generate(self, *a, **k):
            raise requests.ConnectionError("refused")

    monkeypatch.setattr("corparius.llm.HybridRouter", _R)
    out = apps.run(apps.App(name="faq", system="s"), "t", Store(str(tmp_path)), "hi")
    assert out["ok"] is False and "no model" in out["error"]


# --- the daily ceiling ----------------------------------------------------


def test_spending_is_counted_from_midnight(tmp_path):
    store = Store(str(tmp_path))
    app = apps.App(name="faq", system="s")
    assert apps.spent_today(store, "t", app) == 0
    store.record_usage("t", "app:faq", 100, 40)
    assert apps.spent_today(store, "t", app) == 140


def test_yesterdays_spending_does_not_count_against_today(tmp_path):
    store = Store(str(tmp_path))
    app = apps.App(name="faq", system="s")
    store.record_usage("t", "app:faq", 100, 40)
    tomorrow = time.time() + 86400
    assert apps.spent_today(store, "t", app, now=tomorrow) == 0


def test_another_apps_spending_does_not_count_against_this_one(tmp_path):
    store = Store(str(tmp_path))
    store.record_usage("t", "app:other", 5000, 5000)
    store.record_usage("t", "ceo", 5000, 5000)
    assert apps.spent_today(store, "t", apps.App(name="faq", system="s")) == 0


# --- the site block on company.yaml ---------------------------------------


def test_the_site_block_survives_company_load(tmp_path):
    """It used to be dropped: `load` rebuilds a normalised dict, so a key that
    is not named there disappears no matter what the YAML said."""
    from corparius import company as company_mod

    path = tmp_path / "company.yaml"
    path.write_text(
        "slug: t\nname: T\nsite:\n  faq_app: faq\n  faq: ['How much?']\n", encoding="utf-8"
    )
    cfg = company_mod.load(path)
    assert cfg["site"] == {"faq_app": "faq", "faq": ["How much?"]}


def test_a_company_with_no_site_block_carries_no_empty_one(tmp_path):
    from corparius import company as company_mod

    path = tmp_path / "company.yaml"
    path.write_text("slug: t\nname: T\n", encoding="utf-8")
    assert "site" not in company_mod.load(path)


def test_half_a_site_block_is_warned_about_not_silently_ignored():
    """An app named with no questions produces nothing, and looks configured."""
    from corparius import company as company_mod

    _cfg, _errors, warnings = company_mod.validate(
        {"slug": "t", "name": "T", "site": {"faq_app": "faq"}}
    )
    assert any("lists no question" in w for w in warnings)
    _cfg, _errors, warnings = company_mod.validate(
        {"slug": "t", "name": "T", "site": {"faq": ["q"]}}
    )
    assert any("names no app" in w for w in warnings)


def test_a_site_block_that_is_not_a_mapping_is_an_error():
    from corparius import company as company_mod

    _cfg, errors, _warnings = company_mod.validate({"slug": "t", "name": "T", "site": "yes"})
    assert any("expected a mapping" in e for e in errors)
