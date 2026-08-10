"""The settings registry as a client renders it, and the three facts it cannot work out itself.

The tab is **generated** from this payload: 80 fields across eight groups, and the component names not
one of them. A hand-written form would be a second copy of the registry, and `tests/test_registries.py`
exists because this project has already paid for that twice — a field the console offered that nothing
read, and a value the code read that the console could not set.

So what matters here is that the description is complete enough to render from, and honest about three
things no client could derive:

  * `value` is `null` for a secret, `configured` says whether there is one;
  * `editable` is `source != "env"`, because the process environment outranks the console;
  * `restart_required` for a bootstrap key, which lands in `.env` and applies next start.
"""

import json
import shutil
import threading
from http.client import HTTPConnection

import pytest


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from corparius.api.server import build_server
    from corparius.config import cfg
    from corparius.config.settings import Settings

    from .conftest import EXAMPLE_COMPANY

    # The data path and the home are **siblings**. Nesting the home inside the data path makes
    # `make_backup` walk every company file twice, and zipfile's "Duplicate name" warning becomes a
    # failure under `filterwarnings = ["error"]` — a fixture defect that reads as a backup defect.
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    for name in ("CORP_SESSION_TOKEN_BUDGET", "CORP_UI_PORT", "CORP_SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    shutil.copytree(EXAMPLE_COMPANY, home / "companies" / "example")
    monkeypatch.setenv("CORP_HOME", str(home))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _call(srv, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=10)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        {"Content-Type": "application/json"},
    )
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, json.loads(raw or b"{}")


def _field(data, key):
    return next(f for f in data["fields"] if f["key"] == key)


# --- enough to render from --------------------------------------------------------


def test_every_field_carries_what_a_form_needs(server):
    """Rendering is the contract. A field missing its type or its group is one a generated form cannot
    place, and the failure is a blank row rather than an error."""
    from corparius.config import settings_spec

    status, data = _call(server, "GET", "/api/v1/settings")
    assert status == 200
    assert len(data["fields"]) == len(settings_spec.SPEC) == 80
    groups = {g["name"] for g in data["groups"]}
    assert len(groups) == 8
    for f in data["fields"]:
        assert set(f) >= {
            "key",
            "group",
            "type",
            "secret",
            "default",
            "configured",
            "source",
            "editable",
            "restart_required",
            "advanced",
            "label_en",
            "label_fr",
        }, f["key"]
        assert f["group"] in groups, f"{f['key']} is in no group a client renders"
        assert f["type"] in {"bool", "float", "int", "password", "select", "text"}, f["type"]
        if f["type"] == "select":
            assert f["choices"], f"{f['key']} is a select with no choices to offer"


def test_no_field_is_left_out_of_a_group_the_payload_names(server):
    """Both ends. A group with no fields renders as an empty heading; a field in no group is a field a
    generated form silently drops."""
    _status, data = _call(server, "GET", "/api/v1/settings")
    named = {g["name"] for g in data["groups"]}
    used = {f["group"] for f in data["fields"]}
    assert used == named, f"only in fields: {used - named}; only in groups: {named - used}"


def test_a_secret_is_reported_as_set_and_never_returned(server):
    """The value never crosses. `configured` is the whole report a client gets about a credential,
    which is why the input shows a placeholder rather than a masked value it could reveal."""
    _status, before = _call(server, "GET", "/api/v1/settings")
    field = _field(before, "CORP_SMTP_PASSWORD")
    assert field["secret"] is True and field["value"] is None
    assert field["configured"] is False

    _status, after = _call(
        server, "POST", "/api/v1/settings", {"values": {"CORP_SMTP_PASSWORD": "app-password-here"}}
    )
    field = _field(after, "CORP_SMTP_PASSWORD")
    assert field["configured"] is True and field["value"] is None
    assert "app-password-here" not in json.dumps(after), "the answer echoed the credential"


def test_a_field_the_environment_owns_is_shown_and_not_editable(server, monkeypatch):
    """Shown, not hidden: an operator looking for it has to find it and read why it is not theirs to
    change here. `cfg.envTip` is that sentence, and `editable` is what puts it on screen."""
    from corparius.config import cfg

    monkeypatch.setenv("CORP_SESSION_TOKEN_BUDGET", "12345")
    cfg.invalidate()
    _status, data = _call(server, "GET", "/api/v1/settings")
    field = _field(data, "CORP_SESSION_TOKEN_BUDGET")
    assert field["source"] == "env"
    assert field["editable"] is False, "the console must not offer what the environment owns"
    assert field["value"] == "12345", "and it must show what is actually in force"


def test_a_bootstrap_field_says_it_needs_a_restart(server):
    """It lands in `.env` because it has to be readable before the store opens, so it applies next
    start. Saying so is the difference between a setting that looks broken and one that is waiting."""
    _status, data = _call(server, "GET", "/api/v1/settings")
    assert _field(data, "CORP_UI_PORT")["restart_required"] is True
    assert _field(data, "CORP_SESSION_TOKEN_BUDGET")["restart_required"] is False


def test_the_mail_group_carries_its_presets_and_its_test(server):
    """The hosts and ports are derived — that is the point of a preset. A form that made the operator
    type `imap.gmail.com` would be a form that gets it wrong once in ten."""
    _status, data = _call(server, "GET", "/api/v1/settings")
    mail = next(g for g in data["groups"] if g["name"] == "mail")
    assert mail.get("preset") is True and mail.get("test") == "mail"
    gmail = next(p for p in data["mail_presets"] if p["id"] == "gmail")
    assert gmail["host"] and gmail["port"] and gmail["imap_host"] and gmail["imap_port"]
    assert gmail["note_en"] and gmail["note_fr"], (
        "a preset with no note is a password nobody can make"
    )


def test_the_warning_travels_in_both_languages(server):
    """Three groups are flagged `warn` — payments, mail, publishing — and each one moves real money,
    sends real email or publishes a real site."""
    _status, data = _call(server, "GET", "/api/v1/settings")
    assert data["warning"]["en"] and data["warning"]["fr"]
    flagged = {g["name"] for g in data["groups"] if g.get("warn")}
    assert flagged == {"payments", "mail", "publishing"}


# --- the write -------------------------------------------------------------------


def test_saving_a_value_reports_it_back_configured(server):
    status, data = _call(
        server, "POST", "/api/v1/settings", {"values": {"CORP_SESSION_TOKEN_BUDGET": "50000"}}
    )
    assert status == 200
    field = _field(data, "CORP_SESSION_TOKEN_BUDGET")
    # `db`, not "store": `cfg.source` answers env / db / dotenv / default, and those four words are
    # what the console badges. Guessing a fifth was mine.
    assert field["value"] == "50000" and field["source"] == "db"


def test_clearing_a_field_lets_the_default_show_through_again(server):
    """`unset`, not a blank value. The row goes, so the layer below answers — which is what an operator
    asking for the default means. A stored empty string would mask it instead."""
    from corparius.config import settings_spec

    _call(server, "POST", "/api/v1/settings", {"values": {"CORP_SESSION_TOKEN_BUDGET": "50000"}})
    status, data = _call(
        server, "POST", "/api/v1/settings", {"unset": ["CORP_SESSION_TOKEN_BUDGET"]}
    )
    assert status == 200
    field = _field(data, "CORP_SESSION_TOKEN_BUDGET")
    assert field["source"] == "default"
    assert field["value"] == settings_spec.BY_KEY["CORP_SESSION_TOKEN_BUDGET"].default


def test_a_refusal_names_each_field_apart(server):
    """`detail.errors` carries them separately so a client can put each sentence next to the input that
    caused it. Joined into one string, the client would be splitting on "; " to do the same thing."""
    status, data = _call(
        server,
        "POST",
        "/api/v1/settings",
        {"values": {"CORP_SESSION_TOKEN_BUDGET": "lots", "CORP_UI_PORT": "eight-six-hundred"}},
    )
    assert status == 400 and data["error"]["code"] == "invalid"
    errors = data["error"]["detail"]["errors"]
    assert len(errors) == 2, errors
    assert any(e.startswith("CORP_SESSION_TOKEN_BUDGET:") for e in errors)
    assert any(e.startswith("CORP_UI_PORT:") for e in errors)


def test_nothing_is_written_when_one_value_is_refused(server):
    """All or nothing. A partial save would leave the operator's form disagreeing with the store, and
    they would have no way to tell which half landed."""
    _status, _ = _call(
        server,
        "POST",
        "/api/v1/settings",
        {"values": {"CORP_SESSION_TOKEN_BUDGET": "50000", "CORP_UI_PORT": "not-a-port"}},
    )
    _status, data = _call(server, "GET", "/api/v1/settings")
    assert _field(data, "CORP_SESSION_TOKEN_BUDGET")["source"] == "default", (
        "the good value was written despite the refusal"
    )


def test_an_unknown_setting_is_refused(server):
    status, data = _call(server, "POST", "/api/v1/settings", {"values": {"CORP_MADE_UP": "1"}})
    assert status == 400
    assert "unknown setting" in data["error"]["message"]


def test_the_host_allow_list_is_not_settable_here_either(server):
    """`CORP_UI_ALLOWED_HOSTS` decides which Host headers the server answers, which is what stops a
    DNS-rebinding page talking to a loopback core. Settable from a file, never over the API."""
    status, data = _call(
        server, "POST", "/api/v1/settings", {"values": {"CORP_UI_ALLOWED_HOSTS": "evil.example"}}
    )
    assert status == 400 and "unknown setting" in data["error"]["message"]


# --- backup ----------------------------------------------------------------------


def test_the_backup_names_the_file_and_carries_its_warning(server):
    """The warning is not boilerplate: no key leaves in plaintext, and the archive still holds the
    operator's companies and their journal. Offering the button without it would be handing over a
    file whose contents they do not know."""
    status, data = _call(server, "POST", "/api/v1/backup", {})
    assert status == 200
    assert data["name"].endswith(".zip") and data["size"] > 0
    assert data["warning"]["en"] and data["warning"]["fr"]
    assert "REDACTED" in data["warning"]["en"], (
        "the warning has to name the file that lists what to re-enter"
    )


def test_both_spellings_of_the_backup_answer_the_same_keys(server):
    _status, legacy = _call(server, "POST", "/api/backup", {})
    _status, versioned = _call(server, "POST", "/api/v1/backup", {})
    assert set(legacy) == set(versioned) == {"ok", "name", "size", "warning"}


# --- what the console's own settings claim ---------------------------------------


def test_the_theme_is_stored_on_the_server_not_in_the_browser(server):
    """`settings.desc` said "Stored in this browser only; they change nothing on the server", and that
    was false of the theme: `adapters.theme_file` writes `ui_theme.json` under the data path, and its
    own docstring says that is "what makes the theme follow the operator across browsers and devices
    on the same instance". Only the language is per-browser.

    Corrected in both languages, and asserted here so the label and the mechanism cannot drift again —
    which is the same class of defect as `doc.` printing *Diagnostics* on the Documents card.
    """
    import json as jsonlib
    import pathlib

    status, _ = _call(server, "POST", "/api/theme", {"mode": "light"})
    assert status == 200
    _status, back = _call(server, "GET", "/api/theme")
    assert back.get("mode") == "light", "the choice did not survive the round trip"

    en = jsonlib.loads(pathlib.Path("web/i18n/en.json").read_text(encoding="utf-8"))
    assert "this browser only" not in en["settings.desc"]
    assert "follows you" in en["settings.desc"] or "stored on this corparius" in en["settings.desc"]


def test_a_light_theme_needs_the_attribute_the_tokens_key_off(server):
    """`tokens.css` treats `:root` as dark and keys light off `[data-theme="light"]`, so a console that
    never writes the attribute gives every operator dark whatever they chose. The rebuilt one did not
    write it until this tab existed."""
    import pathlib

    tokens = pathlib.Path("web/src/tokens.css").read_text(encoding="utf-8")
    assert ':root, [data-theme="dark"]' in tokens
    assert '[data-theme="light"]' in tokens
    settings = pathlib.Path("web/src/Settings.svelte").read_text(encoding="utf-8")
    assert 'setAttribute("data-theme"' in settings
    assert 'removeAttribute("data-theme")' in settings, "resetting has to clear it, not set 'dark'"
