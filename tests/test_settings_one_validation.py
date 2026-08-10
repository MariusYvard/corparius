"""Two settings write paths, one of which did not validate. The sixth live divergence.

Found the same way as the other five: by reading two surfaces that claim to do the same job and
comparing what each knows. `POST /api/settings` came through `app_settings.validate` — coerce against
the field registry, refuse what does not fit, clear on empty. `POST /api/providers` had its own check,
`key in settings_spec.WRITABLE` and `str(value).strip()`, and nothing else.

Measured before the fix, on a real store:

                        unknown key   "not-a-number" for an int field   empty value
    POST /api/settings    refused     refused, with the reason          clears the setting
    POST /api/providers   refused     **stored verbatim**               stored as ""

and the consequence: with `CORP_SESSION_TOKEN_BUDGET` holding `"not-a-number"`, `cfg.get_int`
answers the *caller's fallback*. A session budget that silently becomes whatever the reader guessed.

**The empty-value column is not drift, and that is the interesting half.** A stored empty string
masks `.env`: with `GROQ_API_KEY=from-dot-env` in the file and `""` in the settings table, `cfg.get`
reads `""`; delete the row and the file value comes back. So clearing on empty would resurrect a
credential the operator had just revoked. Two rules, because the two classes of key differ — and both
now live in one function instead of one per route.
"""

import pathlib
import tempfile

import pytest

from corparius.app import settings as app_settings
from corparius.config import cfg, settings_spec
from corparius.store import Store


@pytest.fixture()
def bench(monkeypatch):
    """A store and a .env, with the process environment cleared of what we are about to test.

    `os.environ` outranks both layers, so a `GROQ_API_KEY` inherited from the developer's shell would
    make every assertion below read the wrong layer and pass for the wrong reason.
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    for name in ("GROQ_API_KEY", "CORP_SESSION_TOKEN_BUDGET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp / "data"))
    env = tmp / ".env"
    env.write_text("", encoding="utf-8")
    cfg.set_dotenv_path(env)
    cfg.invalidate()
    store = Store(str(tmp / "data"))
    yield store, env
    store.close()
    cfg.invalidate()


# --- the vocabularies ------------------------------------------------------------


def test_the_two_classes_of_writable_key_partition_the_writable_set():
    """`validate` accepts a key if the registry has it **or** it is a declared credential, and the
    security tests assert what is *not* writable against `WRITABLE`. Those two vocabularies have to
    be the same set, or a key could be refused by one list and accepted by the other.

    Measured: 108 writable, 80 registry fields, 28 credentials, and `BY_KEY - WRITABLE` empty.
    """
    writable = frozenset(settings_spec.WRITABLE)
    registry = frozenset(settings_spec.BY_KEY)
    assert registry <= writable, (
        f"these are registry fields that `WRITABLE` excludes: {sorted(registry - writable)}. "
        "`validate` accepts any registry field, so such a key would be writable through the API "
        "while the security tests, which read `WRITABLE`, would report it as not settable."
    )
    assert registry | app_settings.CREDENTIALS == writable
    assert not (registry & app_settings.CREDENTIALS), "a key cannot be in both classes"
    # Pinned, so growing either class is a line somebody reads.
    assert len(writable) == 108 and len(registry) == 80 and len(app_settings.CREDENTIALS) == 28


def test_the_host_allow_list_is_in_neither_class():
    """The one that matters most. `CORP_UI_ALLOWED_HOSTS` decides which Host headers the server
    answers, so planting a value there turns off the check that stops a DNS-rebinding page from
    talking to a loopback core. It is settable from a file and never over the API."""
    assert "CORP_UI_ALLOWED_HOSTS" not in settings_spec.WRITABLE
    assert "CORP_UI_ALLOWED_HOSTS" not in settings_spec.BY_KEY
    assert "CORP_UI_ALLOWED_HOSTS" not in app_settings.CREDENTIALS
    clean, drop, errors = app_settings.validate(
        {"CORP_UI_ALLOWED_HOSTS": "evil.example"}, credentials=app_settings.CREDENTIALS
    )
    assert not clean and not drop
    assert errors and "unknown setting" in errors[0]


# --- the half that was drift: coercion ------------------------------------------


@pytest.mark.parametrize(
    ("value", "says"),
    [("not-a-number", "whole number"), ("12.5", "whole number"), ("-", "whole number")],
)
def test_a_registry_field_is_coerced_whichever_route_asked(value, says):
    """The defect, at the parameter that used to bypass it. `credentials=` must not turn coercion
    off for keys that are not credentials."""
    clean, _drop, errors = app_settings.validate(
        {"CORP_SESSION_TOKEN_BUDGET": value}, credentials=app_settings.CREDENTIALS
    )
    assert not clean, f"{value!r} was accepted for an int field"
    assert errors and says in errors[0]


def test_the_providers_route_now_refuses_what_the_settings_route_refuses(bench):
    """Both spellings, one answer. Through `adapters.set_env`, which is the function that carried the
    weaker check, so this fails if the shortcut comes back."""
    from corparius.api import adapters, state

    store, env = bench
    ui = state.UiState(type("S", (), {"data_path": str(store.path)})(), env)  # type: ignore[arg-type]
    ui._store = store
    result = adapters.set_env(ui, {"CORP_SESSION_TOKEN_BUDGET": "not-a-number"})
    assert result["ok"] is False
    assert "whole number" in result["error"]
    assert store.get_setting("CORP_SESSION_TOKEN_BUDGET") is None, (
        "refused and still written: the check ran after the write"
    )


def test_a_good_value_still_goes_through_the_providers_route(bench):
    from corparius.api import adapters, state

    store, env = bench
    ui = state.UiState(type("S", (), {"data_path": str(store.path)})(), env)  # type: ignore[arg-type]
    ui._store = store
    result = adapters.set_env(ui, {"GROQ_API_KEY": "  gsk-abc  ", "CORP_TRIVIAL_MODEL": "groq/x"})
    assert result["ok"] is not False, result
    assert store.get_setting("GROQ_API_KEY") == "gsk-abc", "a pasted key carries whitespace"
    assert store.get_setting("CORP_TRIVIAL_MODEL") == "groq/x"


# --- the half that was not drift: what an empty value means ---------------------


def test_an_empty_credential_is_stored_because_that_is_what_masks_dot_env(bench):
    """The measurement that makes the two rules right rather than inconsistent.

    An operator who empties the key field is revoking it. Clearing the row would let `.env` show
    through again and the key would come back — which is the opposite of what they asked for.
    """
    store, env = bench
    env.write_text("GROQ_API_KEY=from-dot-env\n", encoding="utf-8")
    cfg.invalidate()
    assert cfg.get("GROQ_API_KEY", "") == "from-dot-env", "the fixture has to start from the file"

    clean, drop, errors = app_settings.validate(
        {"GROQ_API_KEY": ""}, credentials=app_settings.CREDENTIALS
    )
    assert not errors
    assert clean == {"GROQ_API_KEY": ""}, "a blank credential is a value, not a clear"
    assert "GROQ_API_KEY" not in drop

    app_settings.persist(store, env, clean, drop)
    cfg.invalidate()
    assert cfg.get("GROQ_API_KEY", "") == "", "revoked, and the file value must stay masked"

    # And the other direction, so the masking is shown rather than asserted once.
    store.delete_setting("GROQ_API_KEY")
    cfg.invalidate()
    assert cfg.get("GROQ_API_KEY", "") == "from-dot-env"


def test_an_empty_registry_field_clears_so_the_layer_below_shows_through(bench):
    """The opposite rule, and the reason it is opposite: a registry field has a default, so clearing
    it means "go back to the default" — where a credential has no default to go back to."""
    store, env = bench
    clean, drop, errors = app_settings.validate(
        {"CORP_SESSION_TOKEN_BUDGET": "50000"}, credentials=app_settings.CREDENTIALS
    )
    assert not errors
    app_settings.persist(store, env, clean, drop)
    assert store.get_setting("CORP_SESSION_TOKEN_BUDGET") == "50000"

    clean, drop, errors = app_settings.validate(
        {"CORP_SESSION_TOKEN_BUDGET": ""}, credentials=app_settings.CREDENTIALS
    )
    assert not errors and not clean
    assert drop == ["CORP_SESSION_TOKEN_BUDGET"], "empty means clear for a field with a default"
    app_settings.persist(store, env, clean, drop)
    assert store.get_setting("CORP_SESSION_TOKEN_BUDGET") is None


def test_the_credentials_set_is_the_keys_with_no_field_to_coerce_against():
    """Derived, not listed. A hand-kept second list is the thing this project keeps finding rotted —
    and it would rot in the dangerous direction: a new provider key missing from it would be coerced
    against a registry field that does not exist and refused as unknown."""
    import inspect

    source = inspect.getsource(app_settings)
    assert "WRITABLE" in source and "BY_KEY" in source
    for key in ("GROQ_API_KEY", "OPENAI_API_KEY", "CORP_TRIVIAL_MODEL", "CORP_LLM_MOCK"):
        assert key in app_settings.CREDENTIALS, f"{key} should be free text"
    for key in ("CORP_SESSION_TOKEN_BUDGET", "CORP_APPS_PORT"):
        assert key not in app_settings.CREDENTIALS, f"{key} has a field and must be coerced"


def test_the_terminal_reaches_the_same_validation(tmp_path, monkeypatch, capsys):
    """`corparius set` was already the third caller of `validate`, and it stays the reason the
    parameter is a parameter: a terminal writing a provider key has to be able to blank it too."""
    import types

    from corparius.cli import configure

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    configure.cmd_set(
        types.SimpleNamespace(pairs=["CORP_SESSION_TOKEN_BUDGET=not-a-number"], unset="")
    )
    assert "whole number" in capsys.readouterr().out
