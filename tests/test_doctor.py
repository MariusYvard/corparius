"""The doctor must diagnose without crashing in every mode and say what to do."""

from corparius.config import Settings
from corparius.doctor import run_checks


def _s(tmp_path, **kw):
    s = Settings()
    s.data_path = str(tmp_path)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_mock_mode_is_green_without_network(tmp_path):
    results = run_checks(_s(tmp_path, llm_mock=True))
    by = {r["name"]: r for r in results}
    assert by["mode"]["level"] == "ok"
    assert by["store"]["level"] == "ok"
    assert by["network"]["level"] == "ok"  # not needed in mock
    assert by["ollama"]["level"] in ("ok", "warn")  # absent ollama only warns


def test_live_without_keys_warns_actionably(tmp_path, monkeypatch):
    for spec_env in (
        "GROQ_API_KEY",
        "ANTHROPIC_API_KEY",
        "CEREBRAS_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
    ):
        monkeypatch.delenv(spec_env, raising=False)
    results = run_checks(_s(tmp_path, llm_mock=False, cloud_enabled=True))
    by = {r["name"]: r for r in results}
    assert by["providers"]["level"] == "warn"
    assert "Groq" in by["providers"]["message"]


def test_claude_cli_check_fails_when_enabled_but_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    results = run_checks(_s(tmp_path, claude_code_enabled=True))
    by = {r["name"]: r for r in results}
    assert by["claude cli"]["level"] == "fail"


def test_routing_check_is_quiet_in_mock_mode(tmp_path):
    by = {r["name"]: r for r in run_checks(_s(tmp_path, llm_mock=True))}
    assert by["routing"]["level"] == "ok"
    assert "fix" not in by["routing"]


def test_routing_check_flags_an_incoherent_tier_with_a_fix(tmp_path, monkeypatch):
    """The trap: cloud on, but tiers still point at unconfigured providers. The
    check must warn and carry the one-click fix hint the console renders."""
    for env in ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "CEREBRAS_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    from corparius import cfg

    cfg.invalidate()
    s = _s(
        tmp_path,
        llm_mock=False,
        cloud_enabled=True,
        normal_model="groq:llama-3.3-70b-versatile",  # no GROQ_API_KEY set
        hard_model="cloud:claude-3-5-sonnet-20241022",  # no ANTHROPIC key
        trivial_model="local:gemma4:e4b",  # local is fine
    )
    routing = {r["name"]: r for r in run_checks(s)}["routing"]
    assert routing["level"] == "warn"
    assert routing["fix"] == "recommend_routing"
    assert "normal" in routing["message"] and "hard" in routing["message"]
    assert "trivial" not in routing["message"]  # local resolves, not flagged


def test_routing_check_is_green_when_every_tier_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    from corparius import cfg

    cfg.invalidate()
    s = _s(
        tmp_path,
        llm_mock=False,
        cloud_enabled=True,
        trivial_model="groq:llama-3.3-70b-versatile",
        normal_model="groq:llama-3.3-70b-versatile",
        hard_model="local:gemma4:e4b",
    )
    routing = {r["name"]: r for r in run_checks(s)}["routing"]
    assert routing["level"] == "ok" and "fix" not in routing


def _doctor_settings(**over):
    from corparius.config import Settings

    s = Settings()
    s.llm_mock = False
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_a_model_the_provider_no_longer_lists_is_flagged(monkeypatch):
    """The failure this exists for: the shipped OpenRouter default,
    deepseek/deepseek-r1-0528:free, stopped being listed while its paid variant
    stayed, so recommended routing wrote a hard tier that 404s. Any hardcoded
    model name rots the same way."""
    from corparius import doctor

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(doctor, "list_models", lambda name, **kw: ["openai/gpt-oss-20b:free"])
    level, _, message, *fix = doctor._check_model_catalog(
        _doctor_settings(hard_model="openrouter:deepseek/deepseek-r1-0528:free")
    )
    assert level == "warn"
    assert "deepseek" in message and "hard" in message


def test_a_live_model_passes(monkeypatch):
    from corparius import doctor

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(doctor, "list_models", lambda name, **kw: ["openai/gpt-oss-20b:free"])
    level, _, _ = doctor._check_model_catalog(
        _doctor_settings(hard_model="openrouter:openai/gpt-oss-20b:free")
    )
    assert level == "ok"


def test_an_unreachable_catalogue_is_not_evidence(monkeypatch):
    """Silence must not be read as "the model is gone". A provider that does not
    answer, or answers with nothing, proves only that it did not answer."""
    import requests

    from corparius import doctor

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    for stub in (
        lambda name, **kw: (_ for _ in ()).throw(requests.RequestException("down")),
        lambda name, **kw: [],
    ):
        monkeypatch.setattr(doctor, "list_models", stub)
        level, _, _ = doctor._check_model_catalog(
            _doctor_settings(hard_model="openrouter:anything-at-all")
        )
        assert level == "ok"


def test_mock_mode_checks_nothing(monkeypatch):
    from corparius import doctor

    monkeypatch.setattr(
        doctor, "list_models", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called"))
    )
    s = _doctor_settings()
    s.llm_mock = True
    assert doctor._check_model_catalog(s)[0] == "ok"


def test_a_tier_with_no_key_is_not_checked(monkeypatch):
    """Without a key there is no catalogue to compare against, and the routing
    check already reports the missing key."""
    from corparius import doctor

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        doctor, "list_models", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called"))
    )
    level, _, _ = doctor._check_model_catalog(_doctor_settings(hard_model="openrouter:whatever"))
    assert level == "ok"


# --- apps ------------------------------------------------------------------
def _seed_app(home, slug="t", name="faq", **over):
    import yaml

    company = home / "companies" / slug
    (company / "apps").mkdir(parents=True, exist_ok=True)
    (company / "company.yaml").write_text("slug: t\nname: T\n", encoding="utf-8")
    body = {"name": name, "system": "s", **over}
    (company / "apps" / f"{name}.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")


def test_the_doctor_is_quiet_when_no_app_is_defined(tmp_path, monkeypatch):
    from corparius import doctor

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    level, name, message = doctor._check_apps(Settings())
    assert (level, name) == ("ok", "apps") and "none defined" in message


def test_the_doctor_says_the_endpoint_is_off(tmp_path, monkeypatch):
    from corparius import cfg, doctor

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_APPS_ENABLED", "false")
    cfg.invalidate()
    _seed_app(tmp_path)
    level, _, message = doctor._check_apps(Settings())
    assert level == "ok" and "endpoint is off" in message


def test_the_doctor_names_an_app_that_can_never_answer(tmp_path, monkeypatch):
    """Defined, looks ready, and every call to it is refused for want of a key.
    Nothing else would say so."""
    from corparius import cfg, doctor

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_APPS_ENABLED", "true")
    monkeypatch.delenv("CORP_APP_KEY_T_FAQ", raising=False)
    cfg.invalidate()
    _seed_app(tmp_path)
    level, _, message = doctor._check_apps(Settings())
    assert level == "warn" and "t/faq" in message and "corparius apps key" in message


def test_the_doctor_flags_an_app_no_browser_can_call(tmp_path, monkeypatch):
    """The right default, and the likeliest thing to be mistaken for a bug."""
    from corparius import cfg, doctor

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_APPS_ENABLED", "true")
    monkeypatch.setenv("CORP_APP_KEY_T_FAQ", "k")
    cfg.invalidate()
    _seed_app(tmp_path, origins=[])
    level, _, message = doctor._check_apps(Settings())
    assert level == "ok" and "no browser can call them" in message


def test_the_doctor_is_content_with_a_fully_wired_app(tmp_path, monkeypatch):
    from corparius import cfg, doctor

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_APPS_ENABLED", "true")
    monkeypatch.setenv("CORP_APP_KEY_T_FAQ", "k")
    cfg.invalidate()
    _seed_app(tmp_path, origins=["https://site.test"])
    level, _, message = doctor._check_apps(Settings())
    assert level == "ok" and "browser" not in message


# --- a ceiling too low to run --------------------------------------------
def _company(home, slug, tpm):
    folder = home / "companies" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "company.yaml").write_text(
        f"slug: {slug}\nname: {slug.title()}\nbudgets:\n"
        f"  session_tokens: 120000\n  tokens_per_minute: {tpm}\n",
        encoding="utf-8",
    )


def test_the_doctor_names_a_company_whose_budget_will_freeze_it(tmp_path, monkeypatch):
    """Measured: a company declaring 8000 froze six times in one session, and
    the log said the breaker tripped without saying which ceiling. Raised to
    60000 the same 24 ticks ran with none."""
    from corparius import doctor
    from corparius.config import Settings

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    _company(tmp_path, "vigil", 8000)
    level, name, message = doctor._check_budgets(Settings())
    assert (level, name) == ("warn", "budgets")
    assert "vigil (8000)" in message and "20000" in message


def test_a_workable_ceiling_is_not_flagged(tmp_path, monkeypatch):
    from corparius import doctor
    from corparius.config import Settings

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    _company(tmp_path, "acme", 60000)
    level, _, message = doctor._check_budgets(Settings())
    assert level == "ok" and "none with a ceiling too low" in message


def test_the_operators_own_number_is_reported_never_overridden(tmp_path, monkeypatch):
    """It is theirs to choose — two tests set a tiny one deliberately to trip
    the breaker. Silently rewriting a value someone typed is a worse habit than
    the freeze it would prevent."""
    from corparius import company as company_mod
    from corparius import doctor
    from corparius.config import Settings

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    _company(tmp_path, "vigil", 8000)
    doctor._check_budgets(Settings())
    cfg_after = company_mod.load(tmp_path / "companies" / "vigil" / "company.yaml", "vigil")
    # Not raised to the 20000 the warning recommends. (A pre-existing floor of
    # 100 still applies to absurd values; that is not this check's doing.)
    assert cfg_after["budgets"]["tokens_per_minute"] == 8000
