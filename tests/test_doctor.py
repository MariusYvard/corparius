"""The doctor must diagnose without crashing in every mode and say what to do."""

from corparius.config.settings import Settings
from corparius.doctor import run_checks


def _s(tmp_path, **kw):
    s = Settings()
    s.data_path = str(tmp_path)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_one_run_opens_one_store_and_closes_it(tmp_path, monkeypatch):
    """Seven checks used to open a connection each and only three closed it, so
    every doctor call opened seven and leaked four. Nothing failed — the leak is
    invisible until a slow runner makes the console's own poll time out, which is
    how it was finally noticed, in CI, days later.

    A count is the only thing that sees it, so this counts.
    """
    from corparius import doctor
    from corparius import store as store_mod

    opened, closed = [], []
    real = store_mod.Store

    class Counting(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            opened.append(self)

        def close(self):
            closed.append(self)
            super().close()

    monkeypatch.setattr(store_mod, "Store", Counting)
    monkeypatch.setattr(doctor, "Store", Counting, raising=False)
    run_checks(_s(tmp_path, llm_mock=True))
    assert len(opened) == 1, f"the doctor opened {len(opened)} store connections, not 1"
    assert closed == opened, "the doctor opened a store it never closed"


def test_a_lent_store_is_not_closed_under_its_owner(tmp_path):
    """The console holds one connection for its whole life and lends it to answer
    a poll. Closing somebody else's store would break every later request."""
    from corparius.store import Store

    store = Store(str(tmp_path))
    try:
        run_checks(_s(tmp_path, llm_mock=True), store)
        assert store.all_settings() == {}  # still usable, so still open
    finally:
        store.close()


def test_every_check_that_needs_a_store_is_handed_one(tmp_path):
    """The store has no default on purpose. It had one, and two tests called
    those checks without it and got a cheerful "ok, nothing to see" instead of
    the stale measurement and the from-the-future schema they had just written.
    A required argument turns that silence into a TypeError."""
    import inspect

    from corparius import doctor

    for name, fn in vars(doctor).items():
        if not name.startswith("_check_"):
            continue
        params = inspect.signature(fn).parameters
        if "store" not in params:
            continue
        assert params["store"].default is inspect.Parameter.empty, (
            f"{name} defaults its store, so a caller that forgets it gets a wrong answer"
        )


def test_no_two_checks_share_a_name():
    """A check's `name` is its key, and nothing said so.

    Four tests in this file — and the console — do `{r["name"]: r for r in results}`. A
    duplicate name therefore does not read as two checks: the second silently **replaces** the
    first, and every assertion about the first starts describing the second. It happened while
    a check reading the routing journal was added next to `_check_tier_coherence`, both called
    "routing", and `test_tier_coherence` below would have quietly started asserting against the
    wrong one.

    A registry keyed by name with no uniqueness guard is the same defect this project keeps
    finding in other registries (test_registries.py). Here it is.
    """
    import collections

    names = [r["name"] for r in run_checks()]
    duplicated = sorted(n for n, count in collections.Counter(names).items() if count > 1)
    assert not duplicated, (
        f"two checks answer to the same name: {duplicated}. The name is the key the console "
        "and these tests index by, so one of them is invisible."
    )


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
    from corparius.config import cfg

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
    from corparius import doctor
    from corparius.config import cfg

    # Setting a key makes `_check_model_catalog` proceed, and it asks the
    # provider for real. This test is about the *routing* check, and a suite
    # that dials out to a third party fails for reasons that have nothing to do
    # with the code under test.
    monkeypatch.setattr(doctor, "list_models", lambda name, timeout=8: [])
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
    from corparius.config.settings import Settings

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
    from corparius import doctor
    from corparius.config import cfg

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_APPS_ENABLED", "false")
    cfg.invalidate()
    _seed_app(tmp_path)
    level, _, message = doctor._check_apps(Settings())
    assert level == "ok" and "endpoint is off" in message


def test_the_doctor_names_an_app_that_can_never_answer(tmp_path, monkeypatch):
    """Defined, looks ready, and every call to it is refused for want of a key.
    Nothing else would say so."""
    from corparius import doctor
    from corparius.config import cfg

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_APPS_ENABLED", "true")
    monkeypatch.delenv("CORP_APP_KEY_T_FAQ", raising=False)
    cfg.invalidate()
    _seed_app(tmp_path)
    level, _, message = doctor._check_apps(Settings())
    assert level == "warn" and "t/faq" in message and "corparius apps key" in message


def test_the_doctor_flags_an_app_no_browser_can_call(tmp_path, monkeypatch):
    """The right default, and the likeliest thing to be mistaken for a bug."""
    from corparius import doctor
    from corparius.config import cfg

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_APPS_ENABLED", "true")
    monkeypatch.setenv("CORP_APP_KEY_T_FAQ", "k")
    cfg.invalidate()
    _seed_app(tmp_path, origins=[])
    level, _, message = doctor._check_apps(Settings())
    assert level == "ok" and "no browser can call them" in message


def test_the_doctor_is_content_with_a_fully_wired_app(tmp_path, monkeypatch):
    from corparius import doctor
    from corparius.config import cfg

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
    from corparius.config.settings import Settings

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    _company(tmp_path, "vigil", 8000)
    level, name, message = doctor._check_budgets(Settings())
    assert (level, name) == ("warn", "budgets")
    assert "vigil (8000)" in message and "20000" in message


def test_a_workable_ceiling_is_not_flagged(tmp_path, monkeypatch):
    from corparius import doctor
    from corparius.config.settings import Settings

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
    from corparius.config.settings import Settings

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    _company(tmp_path, "vigil", 8000)
    doctor._check_budgets(Settings())
    cfg_after = company_mod.load(tmp_path / "companies" / "vigil" / "company.yaml", "vigil")
    # Not raised to the 20000 the warning recommends. (A pre-existing floor of
    # 100 still applies to absurd values; that is not this check's doing.)
    assert cfg_after["budgets"]["tokens_per_minute"] == 8000


# --- the local check says what local actually does here ------------------------


def _routing(tmp_path, **models):
    s = _s(tmp_path, llm_mock=False, cloud_enabled=True)
    s.trivial_model = models.get("trivial", "groq:llama-3.3-70b-versatile")
    s.normal_model = models.get("normal", "groq:llama-3.3-70b-versatile")
    s.hard_model = models.get("hard", "claudecode:opus")
    s.local_model = "qwen2.5:7b-instruct"
    s.embed_model = "nomic-embed-text"
    return s


class _Tags:
    def __init__(self, names=()):
        self._names = names

    def raise_for_status(self):
        pass

    def json(self):
        return {"models": [{"name": n} for n in self._names]}


def test_a_missing_model_no_tier_uses_is_not_a_warning(tmp_path, monkeypatch):
    """`needs_local` read `... or True`, so the condition was dead and every install
    was told to pull the local models. Measured on the owner's: all three tiers are
    remote and every fallback step is remote, so Ollama is reached only if every
    remote provider fails at once. Telling them to download 4.7 GB for that is a
    chore dressed as a warning."""
    from corparius import doctor

    monkeypatch.setattr(doctor.requests, "get", lambda *a, **k: _Tags(["gemma3:4b"]))
    level, _, message = doctor._check_ollama(_routing(tmp_path))
    assert level == "ok", message
    assert "no tier uses it" in message
    assert "Optional:" in message, "the pulls are offered, not demanded"
    assert "nowhere to fall back to" in message, "and the cost of not doing it is said"


def test_a_tier_pointed_at_a_missing_model_is_a_warning(tmp_path, monkeypatch):
    """That tier cannot run, which is a different fact entirely."""
    from corparius import doctor

    monkeypatch.setattr(doctor.requests, "get", lambda *a, **k: _Tags(["gemma3:4b"]))
    level, _, message = doctor._check_ollama(
        _routing(tmp_path, trivial="local:qwen2.5:7b-instruct")
    )
    assert level == "warn"
    assert "cannot run" in message and "ollama pull" in message


def test_the_embedding_fallback_is_named_rather_than_implied(tmp_path, monkeypatch):
    from corparius import doctor

    monkeypatch.setattr(doctor.requests, "get", lambda *a, **k: _Tags(["qwen2.5:7b-instruct"]))
    level, _, message = doctor._check_ollama(_routing(tmp_path))
    assert level == "ok"
    assert "built-in hash" in message and "repetition guard" in message


def test_unreachable_fails_only_when_a_tier_depends_on_it(tmp_path, monkeypatch):
    import requests as req

    from corparius import doctor

    def down(*a, **k):
        raise req.ConnectionError("refused")

    monkeypatch.setattr(doctor.requests, "get", down)
    level, _, message = doctor._check_ollama(_routing(tmp_path))
    assert level == "warn" and "nothing is blocked" in message
    level, _, message = doctor._check_ollama(_routing(tmp_path, hard="local:qwen2.5:7b-instruct"))
    assert level == "fail" and "cannot run" in message


def test_mock_mode_never_demands_it(tmp_path, monkeypatch):
    import requests as req

    from corparius import doctor

    def down(*a, **k):
        raise req.ConnectionError("refused")

    monkeypatch.setattr(doctor.requests, "get", down)
    s = _routing(tmp_path)
    s.llm_mock = True
    level, _, message = doctor._check_ollama(s)
    assert level == "warn" and "does not need it" in message
