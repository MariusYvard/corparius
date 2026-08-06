"""Getting a free API key is the sharpest edge of onboarding. The console links
straight to each provider's key page and flags the easy ones, driven by metadata
on the provider registry - so these assertions guard that the metadata stays
well-formed and reaches the payload the page renders from. The routing helpers
that turn a connected key into a working full configuration are covered too.
"""

import types

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
    assert recommended_routing([]) is None
    # gemini is connectable but has no default_model, so it cannot be auto-routed.
    assert recommended_routing(["gemini"]) is None


def test_recommended_routing_fills_every_tier_from_one_provider():
    """The gap this closes: one free key must leave no tier pointing at something
    unconfigured. With only Groq and no Ollama, all three land on Groq."""
    r = recommended_routing(["groq"])
    assert r["CORP_NORMAL_MODEL"] == "groq:llama-3.3-70b-versatile"
    assert r["CORP_HARD_MODEL"] == "groq:llama-3.3-70b-versatile"
    assert r["CORP_TRIVIAL_MODEL"] == "groq:llama-3.3-70b-versatile"
    assert r["CORP_LLM_FALLBACK"] == ""


def test_recommended_routing_uses_reasoning_for_hard_and_local_for_trivial():
    r = recommended_routing(["groq", "cerebras", "openrouter"], local_trivial="gemma:2b")
    assert r["CORP_NORMAL_MODEL"].startswith("groq:")  # fast general first
    assert r["CORP_HARD_MODEL"].startswith("openrouter:")  # reasoning model on hard
    # The caller measured the machine and named the model it can actually serve.
    assert r["CORP_TRIVIAL_MODEL"] == "local:gemma:2b"
    fb = r["CORP_LLM_FALLBACK"]
    assert "cerebras:" in fb and "openrouter:" in fb and "groq:" not in fb


def test_recommended_routing_ignores_providers_without_a_default_model():
    """github is connectable but carries no default_model, so it never appears in
    the routing even when 'configured'."""
    r = recommended_routing(["github", "cerebras"])
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


def test_the_doctor_offers_the_claude_path_when_the_cli_is_there(monkeypatch):
    """The discovery case: someone with a subscription and the CLI installed is
    paying for inference they could get from a login they already have. The old
    message just said "disabled"."""
    from corparius import doctor
    from corparius.config.settings import Settings

    s = Settings()
    s.claude_code_enabled = False
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/claude")
    level, _, message = doctor._check_claude_cli(s)
    assert level == "ok"
    assert "corparius claude" in message


def test_the_doctor_says_nothing_when_neither_is_installed(monkeypatch):
    """No subscription in evidence, no advice: the doctor lists what is wrong,
    not what could be bought."""
    from corparius import claudecli, doctor
    from corparius.config.settings import Settings

    s = Settings()
    s.claude_code_enabled = False
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(claudecli, "desktop_installed", lambda: False)
    assert "corparius claude" not in doctor._check_claude_cli(s)[2]


def test_the_one_command_writes_exactly_the_console_plan(tmp_path, monkeypatch, capsys):
    """The CLI and the console must apply the same four-way change. Two paths
    that drift is how an operator ends up half-configured.

    This once compared the CLI's result against `plan()` — also called with no
    arguments — so it agreed with the bug instead of catching it: with no
    connected providers and no local verdict passed in, `plan()` reads the
    machine as having nothing free and puts *every* tier on the subscription.
    The inputs are what has to match, not just the function.
    """
    from corparius import claudecli, hardware, llm
    from corparius.cli import cmd_claude
    from corparius.store import Store

    monkeypatch.setattr(claudecli, "check", lambda *a, **k: {"ok": True, "detail": "ready"})
    monkeypatch.setattr(llm, "connected_providers", lambda: ["groq", "openrouter"])
    monkeypatch.setattr(hardware, "recommended_local", lambda *a, **k: ("", "too slow"))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    cmd_claude(types.SimpleNamespace(check=False, all_tiers=False))
    written = Store(str(tmp_path)).all_settings()
    assert written == claudecli.plan(["groq", "openrouter"], "")
    assert not written["CORP_TRIVIAL_MODEL"].startswith("claudecode:"), (
        "the most frequent tier must stay on a free provider"
    )
    assert written["CORP_HARD_MODEL"] == "claudecode:opus"
    assert "haiku" in written["CORP_LLM_FALLBACK"]


def test_the_one_command_honours_all_tiers(tmp_path, monkeypatch, capsys):
    """--all-tiers was parsed and then never read."""
    from corparius import claudecli, hardware, llm
    from corparius.cli import cmd_claude
    from corparius.store import Store

    monkeypatch.setattr(claudecli, "check", lambda *a, **k: {"ok": True, "detail": "ready"})
    monkeypatch.setattr(llm, "connected_providers", lambda: ["groq"])
    monkeypatch.setattr(hardware, "recommended_local", lambda *a, **k: ("", "too slow"))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    cmd_claude(types.SimpleNamespace(check=False, all_tiers=True))
    written = Store(str(tmp_path)).all_settings()
    assert written["CORP_TRIVIAL_MODEL"] == "claudecode:haiku"
    assert "serving every tier" in capsys.readouterr().out


def test_the_one_command_puts_a_capable_machine_on_local(tmp_path, monkeypatch, capsys):
    """The measured verdict has to reach the CLI too, or `corparius bench` says
    the machine can serve a tier and `corparius claude` ignores it."""
    from corparius import claudecli, hardware, llm
    from corparius.cli import cmd_claude
    from corparius.store import Store

    monkeypatch.setattr(claudecli, "check", lambda *a, **k: {"ok": True, "detail": "ready"})
    monkeypatch.setattr(llm, "connected_providers", lambda: ["groq"])
    monkeypatch.setattr(hardware, "recommended_local", lambda *a, **k: ("gemma:2b", "40/s"))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    cmd_claude(types.SimpleNamespace(check=False, all_tiers=False))
    assert Store(str(tmp_path)).all_settings()["CORP_TRIVIAL_MODEL"] == "local:gemma:2b"


def test_the_cli_store_honours_the_redirected_data_path(tmp_path, monkeypatch):
    """cli._store() used the import-time settings snapshot, which is taken at
    collection — before the hermetic fixture redirects CORP_DATA_PATH. A test
    calling any cmd_* function therefore wrote to the developer's own store."""
    from corparius.cli import _store

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "elsewhere"))
    assert str(tmp_path / "elsewhere") in _store().path


def test_check_only_changes_nothing(tmp_path, monkeypatch, capsys):
    from corparius import claudecli
    from corparius.cli import cmd_claude
    from corparius.store import Store

    monkeypatch.setattr(claudecli, "check", lambda *a, **k: {"ok": True, "detail": "ready"})
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    cmd_claude(types.SimpleNamespace(check=True))
    assert Store(str(tmp_path)).all_settings() == {}


def test_a_failed_check_refuses_to_half_configure(tmp_path, monkeypatch):
    """Writing "cloud on, mock off" against a CLI that cannot answer would leave
    the operator worse off than before they ran anything."""
    import pytest

    from corparius import claudecli
    from corparius.cli import cmd_claude
    from corparius.store import Store

    monkeypatch.setattr(
        claudecli, "check", lambda *a, **k: {"ok": False, "detail": "not logged in"}
    )
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    with pytest.raises(SystemExit):
        cmd_claude(types.SimpleNamespace(check=False))
    assert Store(str(tmp_path)).all_settings() == {}


def test_a_hard_override_keeps_the_free_providers_underneath():
    """What "free first, subscription for the hard work" resolves to."""
    routing = recommended_routing(["groq", "openrouter"], "gemma:2b", hard="claudecode:opus")
    assert routing["CORP_TRIVIAL_MODEL"].startswith("local:")
    assert routing["CORP_NORMAL_MODEL"].startswith("groq:")
    assert routing["CORP_HARD_MODEL"] == "claudecode:opus"


def test_the_tail_is_the_last_remote_step_of_the_chain():
    """A free provider going down should escalate to the metered account, not
    drop straight to a local model that may not be installed."""
    chain = recommended_routing(
        ["groq", "openrouter"],
        "gemma:2b",
        hard="claudecode:opus",
        fallback_tail=("claudecode:haiku", "claudecode:sonnet"),
    )["CORP_LLM_FALLBACK"].split(",")
    # Cheapest rung first: a failed free provider tries Haiku before Sonnet.
    assert chain[-2:] == ["claudecode:haiku", "claudecode:sonnet"]
    assert any(step.startswith("openrouter:") for step in chain)


def test_the_hard_tier_never_lands_in_the_shared_chain():
    """The chain is walked by every tier, so the top-tier model must not sit in
    it — a failed social post would escalate to the most expensive model in the
    roster. `hard` and `fallback_tail` are separate for exactly this reason."""
    routing = recommended_routing(
        ["groq", "openrouter"],
        "gemma:2b",
        hard="claudecode:opus",
        fallback_tail=("claudecode:haiku", "claudecode:sonnet"),
    )
    assert routing["CORP_HARD_MODEL"] == "claudecode:opus"
    assert "claudecode:opus" not in routing["CORP_LLM_FALLBACK"]


def test_without_an_override_nothing_changes():
    assert "claudecode" not in str(recommended_routing(["groq"], "gemma:2b"))


def test_the_claude_plan_prefers_free_and_falls_back_to_every_tier():
    from corparius import claudecli

    mixed = claudecli.plan(["groq"], "gemma:2b")
    assert mixed["CORP_HARD_MODEL"] == "claudecode:opus"
    assert not mixed["CORP_NORMAL_MODEL"].startswith("claudecode:")
    # Sonnet backs the everyday work up once the free providers are exhausted.
    assert mixed["CORP_LLM_FALLBACK"].endswith("claudecode:sonnet")
    # Nothing free connected: there is nothing to prefer, so it serves everything.
    alone = claudecli.plan([], "")
    assert alone["CORP_NORMAL_MODEL"] == "claudecode:sonnet"
    assert alone["CORP_TRIVIAL_MODEL"] == "claudecode:haiku"


def test_the_tier_ladder_is_one_model_per_tier():
    """haiku / sonnet / opus, cheapest to most capable. A tier that repeats a
    model is a tier that isn't buying anything."""
    from corparius import claudecli

    ladder = [
        claudecli.TIERS[k] for k in ("CORP_TRIVIAL_MODEL", "CORP_NORMAL_MODEL", "CORP_HARD_MODEL")
    ]
    assert ladder == ["claudecode:haiku", "claudecode:sonnet", "claudecode:opus"]
    assert claudecli.HARD_TIER == claudecli.TIERS["CORP_HARD_MODEL"]


def test_opus_sits_on_the_least_frequent_tier():
    """The expensive model belongs where it is called least. HARD serves
    strategy (every 24h) and the coder (on demand) — nothing else."""
    from corparius.agents import ROSTER
    from corparius.kernel.records import Difficulty

    hard_roles = {r.value for r, spec in ROSTER.items() if spec.difficulty is Difficulty.HARD}
    assert hard_roles == {"strategy", "coder"}
    cadences = [ROSTER[r].cadence_hours for r in ROSTER if ROSTER[r].difficulty is Difficulty.HARD]
    # 24h, and None for the on-demand coder: the rarest tier in the roster.
    assert all(c is None or c >= 24 for c in cadences)


def test_an_incapable_machine_sends_the_trivial_tier_to_a_free_provider():
    """The behaviour the measurement exists for. `ollama_ready=True` used to be
    enough to hand this tier a 9.6 GB model on a box that runs at 8.6 tokens
    per second."""
    r = recommended_routing(["groq"], local_trivial="")
    assert not r["CORP_TRIVIAL_MODEL"].startswith("local:")
    assert r["CORP_TRIVIAL_MODEL"] == r["CORP_NORMAL_MODEL"]


def test_local_still_ends_the_chain_even_when_it_cannot_serve_a_tier():
    """Not serving a tier and not being the last resort are different things.
    The router always falls through to local after the chain — that safety net
    must survive a negative verdict."""
    from corparius.config.settings import Settings
    from corparius.llm import HybridRouter

    s = Settings()
    s.llm_mock = False
    s.llm_fallback = ["groq:x", "claudecode:haiku"]
    chain = HybridRouter(s)._chain("groq", "x")
    assert all(target != "local" for target, _ in chain)  # local is not *in* the chain
    assert s.local_model, "the router's final local fallback is still configured"


def test_the_ladder_climbs_cheapest_first():
    from corparius import claudecli

    assert claudecli.FALLBACK_LADDER == ("claudecode:haiku", "claudecode:sonnet")
    assert claudecli.HARD_TIER not in claudecli.FALLBACK_LADDER


def test_recommended_local_is_the_single_decider(tmp_path, monkeypatch):
    """The console button, the CLI and the doctor all ask this one function, so
    they cannot drift into three different answers."""
    from corparius import hardware
    from corparius.config.settings import Settings
    from corparius.store import Store

    store = Store(str(tmp_path))
    monkeypatch.setattr(
        hardware, "installed_models", lambda **k: [{"name": "gemma:2b", "size": 1_000_000_000}]
    )
    s = Settings()
    s.trivial_model = "local:gemma:2b"

    # Nothing measured: no local tier, and the reason says what to run.
    choice, why = hardware.recommended_local(store, s)
    assert choice == "" and "corparius bench" in why

    # Measured slow: still no local tier, and the reason shows the arithmetic.
    store.save_machine({"tokens_per_second": 8.6, "placement": "cpu", "model": "gemma:2b"})
    choice, why = hardware.recommended_local(store, s)
    assert choice == "" and "8.6 tokens/s" in why

    # Measured fast: the model it can serve, named.
    store.save_machine({"tokens_per_second": 40.0, "placement": "gpu", "model": "gemma:2b"})
    choice, why = hardware.recommended_local(store, s)
    assert choice == "gemma:2b" and "40.0 tokens/s" in why


def test_no_ollama_at_all_is_reported_as_such(tmp_path, monkeypatch):
    from corparius import hardware
    from corparius.config.settings import Settings
    from corparius.store import Store

    monkeypatch.setattr(hardware, "installed_models", lambda **k: [])
    choice, why = hardware.recommended_local(Store(str(tmp_path)), Settings())
    assert choice == "" and "not reachable" in why


def test_the_doctor_names_the_desktop_app_when_the_cli_is_missing(monkeypatch):
    """Same trap as the CLI message: someone holding Claude Desktop reads
    "install Claude Code" as done."""
    from corparius import claudecli, doctor
    from corparius.config.settings import Settings

    s = Settings()
    s.claude_code_enabled = False
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(claudecli, "desktop_installed", lambda: True)
    level, _, message = doctor._check_claude_cli(s)
    assert level == "ok" and "Claude Desktop" in message
    assert "corparius claude --install" in message


def test_the_doctor_fails_loudly_when_the_target_is_on_without_the_cli(monkeypatch):
    from corparius import claudecli, doctor
    from corparius.config.settings import Settings

    s = Settings()
    s.claude_code_enabled = True
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(claudecli, "desktop_installed", lambda: True)
    level, _, message = doctor._check_claude_cli(s)
    assert level == "fail" and "not the chat app" not in message
    assert "chat app" in message and "corparius claude --install" in message


def test_the_command_installs_only_when_asked(tmp_path, monkeypatch, capsys):
    """--install is the whole authorisation: a global npm package is not
    something a status check gets to decide."""
    import pytest

    from corparius import claudecli
    from corparius.cli import cmd_claude

    monkeypatch.setattr(claudecli, "installed", lambda: False)
    monkeypatch.setattr(
        claudecli, "check", lambda *a, **k: {"ok": False, "detail": "not installed"}
    )

    def explode(*a, **k):
        raise AssertionError("installed without --install")

    monkeypatch.setattr(claudecli, "install", explode)
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    with pytest.raises(SystemExit):
        cmd_claude(types.SimpleNamespace(check=False, all_tiers=False, install=False))


def test_the_command_installs_then_configures(tmp_path, monkeypatch, capsys):
    from corparius import claudecli, hardware, llm
    from corparius.cli import cmd_claude
    from corparius.store import Store

    calls = []
    monkeypatch.setattr(claudecli, "installed", lambda: False)
    monkeypatch.setattr(
        claudecli, "install", lambda *a, **k: (calls.append("npm"), {"ok": True, "detail": "in"})[1]
    )
    monkeypatch.setattr(claudecli, "check", lambda *a, **k: {"ok": True, "detail": "ready"})
    monkeypatch.setattr(llm, "connected_providers", lambda: ["groq"])
    monkeypatch.setattr(hardware, "recommended_local", lambda *a, **k: ("", "too slow"))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    cmd_claude(types.SimpleNamespace(check=False, all_tiers=False, install=True))
    assert calls == ["npm"]
    assert Store(str(tmp_path)).all_settings()["CORP_HARD_MODEL"] == "claudecode:opus"
