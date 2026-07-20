"""The settings screen's contract: every field the operator can set, what layer
answers for it, and never a secret's value on the wire."""

import json
import threading

import pytest

from app import cfg, settings_spec, webui
from app.config import Settings

from .test_webui import _call


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = webui.build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()  # release the listening socket, not just the loop


def test_lists_every_registry_field_with_its_source(server):
    status, data = _call(server, "GET", "/api/settings")
    assert status == 200 and data["ok"]
    keys = {f["key"] for f in data["fields"]}
    assert keys == set(settings_spec.BY_KEY)
    groups = {g["name"] for g in data["groups"]}
    assert {"access", "payments", "mail", "publishing", "leads", "safety"} <= groups
    stripe = next(f for f in data["fields"] if f["key"] == "STRIPE_API_KEY")
    assert stripe["secret"] and stripe["value"] is None and stripe["source"] == "default"


def test_a_mail_account_is_three_questions_not_thirteen(server):
    """Sending and reading are one account, so they are one group; the hosts and
    ports the provider preset fills are folded away as derived."""
    status, data = _call(server, "GET", "/api/settings")
    mail = [f for f in data["fields"] if f["group"] == "mail"]
    upfront = [f["key"] for f in mail if not f["advanced"]]
    assert upfront == ["CORP_SMTP_USER", "CORP_SMTP_PASSWORD", "CORP_OUTREACH_TEST_TO"]
    # Both directions are reachable, just derived.
    derived = {f["key"] for f in mail if f["advanced"]}
    assert {"CORP_SMTP_HOST", "CORP_SMTP_PORT", "CORP_IMAP_HOST", "CORP_IMAP_PORT"} <= derived
    presets = {p["id"]: p for p in data["mail_presets"]}
    assert presets["gmail"]["host"] == "smtp.gmail.com" and presets["gmail"]["port"] == 587
    assert presets["gmail"]["imap_host"] == "imap.gmail.com"
    # A send-only relay has no mailbox, and must not pretend to.
    assert "imap_host" not in presets["brevo"]


def test_round_trip_and_clear(server):
    status, data = _call(server, "POST", "/api/settings", {"values": {"CORP_WIP_LIMIT": "9"}})
    assert status == 200 and data["ok"]
    wip = next(f for f in data["fields"] if f["key"] == "CORP_WIP_LIMIT")
    assert wip["value"] == "9" and wip["source"] == "db"
    assert cfg.get_int("CORP_WIP_LIMIT", 4) == 9
    # Clearing must remove the row, not store "", so the layer below shows again.
    status, data = _call(server, "POST", "/api/settings", {"values": {"CORP_WIP_LIMIT": ""}})
    assert status == 200
    wip = next(f for f in data["fields"] if f["key"] == "CORP_WIP_LIMIT")
    assert wip["source"] == "default" and wip["value"] == "4"


def test_secrets_are_write_only(server):
    status, data = _call(
        server, "POST", "/api/settings", {"values": {"STRIPE_API_KEY": "sk_live_dontleakme"}}
    )
    assert status == 200 and data["ok"]
    assert "sk_live_dontleakme" not in json.dumps(data)
    stripe = next(f for f in data["fields"] if f["key"] == "STRIPE_API_KEY")
    assert stripe["value"] is None and stripe["configured"] is True
    status, data = _call(server, "GET", "/api/settings")
    assert "sk_live_dontleakme" not in json.dumps(data)


def test_types_are_validated(server):
    status, data = _call(
        server, "POST", "/api/settings", {"values": {"CORP_WIP_LIMIT": "not-a-number"}}
    )
    assert status == 400 and data["ok"] is False and "whole number" in data["error"]
    status, data = _call(server, "POST", "/api/settings", {"values": {"CORP_LOG_LEVEL": "LOUD"}})
    assert status == 400 and data["ok"] is False
    status, data = _call(server, "POST", "/api/settings", {"values": {"PATH": "evil"}})
    assert data["ok"] is False


def test_env_pinned_field_is_reported_not_editable(server, monkeypatch):
    """The honesty contract: a value the page cannot change must say so instead
    of accepting an edit that would do nothing."""
    monkeypatch.setenv("CORP_WIP_LIMIT", "7")
    status, data = _call(server, "GET", "/api/settings")
    wip = next(f for f in data["fields"] if f["key"] == "CORP_WIP_LIMIT")
    assert wip["source"] == "env" and wip["editable"] is False and wip["value"] == "7"
    # Saving anyway is not silently swallowed: the response names it as shadowed.
    status, data = _call(server, "POST", "/api/settings", {"values": {"CORP_WIP_LIMIT": "3"}})
    assert status == 200 and "CORP_WIP_LIMIT" in data.get("shadowed", [])


def test_bootstrap_keys_go_to_dotenv_and_ask_for_a_restart(server, tmp_path, monkeypatch):
    monkeypatch.delenv("CORP_UI_PORT", raising=False)
    status, data = _call(server, "POST", "/api/settings", {"values": {"CORP_UI_PORT": "9100"}})
    assert status == 200 and data["ok"]
    assert "CORP_UI_PORT" in data.get("restart_required", [])
    # It cannot live in the store: it is needed before the store can be opened.
    assert "CORP_UI_PORT=9100" in (tmp_path / ".env").read_text()
    assert server.RequestHandlerClass.state.store().get_setting("CORP_UI_PORT") is None
    assert cfg.get("CORP_UI_PORT", "8600") == "9100"


def test_session_reports_token_requirement_without_serving_it(server, monkeypatch):
    status, data = _call(server, "GET", "/api/session")
    assert status == 200 and data["token_required"] is False
    monkeypatch.setenv("CORP_UI_TOKEN", "s3cret")
    status, data = _call(server, "GET", "/api/session")
    assert data["token_required"] is True
    assert "s3cret" not in json.dumps(data)
