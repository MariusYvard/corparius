"""One-press Claude subscription setup: prove the CLI works, then flip the four
settings and point the tiers at it. The scattered toggles and hand-edited tier
strings were most of why nobody found this path."""

import threading
import types

import pytest

from corparius import cfg, claudecli, webui
from corparius.config import Settings

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


def _fake_run(returncode=0, stdout='{"result": "ready", "model": "claude-sonnet"}', stderr=""):
    return lambda *a, **k: types.SimpleNamespace(
        returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_check_reports_installed_logged_in(monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(claudecli.subprocess, "run", _fake_run())
    r = claudecli.check()
    assert r["ok"] and r["installed"] and "no api key" in r["detail"].lower()


def test_check_says_install_when_missing(monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: None)
    r = claudecli.check()
    assert r["ok"] is False and r["installed"] is False and "claude login" in r["detail"]


def test_check_distinguishes_not_logged_in(monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        claudecli.subprocess,
        "run",
        _fake_run(returncode=1, stderr="Error: not logged in. Run claude login."),
    )
    r = claudecli.check()
    assert r["ok"] is False and r["installed"] is True
    assert "not logged in" in r["detail"] and "claude login" in r["detail"]


def test_one_press_setup_flips_everything_and_survives_restart(server, monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(claudecli.subprocess, "run", _fake_run())
    # The hermetic fixture pins these toggles in the environment (layer 1), which
    # correctly shadows the console (layer 2). Clear them so the store's writes
    # are what answers; leaving them set would be testing the honesty contract,
    # not the setup.
    for k in ("CORP_LLM_MOCK", "CORP_CLOUD_ENABLED", "CORP_CLAUDE_CODE"):
        monkeypatch.delenv(k, raising=False)
    cfg.invalidate()
    # Before: the default, mock on, tiers not on claudecode.
    assert cfg.get_bool("CORP_LLM_MOCK", "true") is True
    status, d = _call(server, "POST", "/api/claude/setup", {})
    assert status == 200 and d["ok"]
    # Every gate is now open and the hard tier routes to the subscription.
    assert cfg.get_bool("CORP_LLM_MOCK", "true") is False
    assert cfg.get_bool("CORP_CLOUD_ENABLED") is True
    assert cfg.get_bool("CORP_CLAUDE_CODE") is True
    assert cfg.get("CORP_HARD_MODEL") == "claudecode:opus"
    assert claudecli.already_on() is True
    # Stored, not just in-process: a restart keeps it.
    cfg.invalidate()
    assert claudecli.already_on() is True


def test_setup_leaves_the_simple_work_on_a_free_provider(server, monkeypatch):
    """A subscription is metered in usage windows, not tokens, so spending one
    on draft_social_post — TRIVIAL, every two hours — is the expensive mistake.
    OVH answers without a key, so there is always something free to prefer."""
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(claudecli.subprocess, "run", _fake_run())
    for k in ("CORP_LLM_MOCK", "CORP_CLOUD_ENABLED", "CORP_CLAUDE_CODE"):
        monkeypatch.delenv(k, raising=False)
    cfg.invalidate()
    status, d = _call(server, "POST", "/api/claude/setup", {})
    assert status == 200 and d["ok"]
    assert cfg.get("CORP_HARD_MODEL") == "claudecode:opus"
    assert not cfg.get("CORP_NORMAL_MODEL").startswith("claudecode:")
    # And the subscription is the last remote step before local, so a free
    # provider going down escalates instead of dropping to a model that may not
    # be installed.
    assert cfg.get("CORP_LLM_FALLBACK").endswith("claudecode:opus")


def test_all_tiers_is_available_when_asked_for(server, monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(claudecli.subprocess, "run", _fake_run())
    for k in ("CORP_LLM_MOCK", "CORP_CLOUD_ENABLED", "CORP_CLAUDE_CODE"):
        monkeypatch.delenv(k, raising=False)
    cfg.invalidate()
    status, d = _call(server, "POST", "/api/claude/setup", {"all_tiers": True})
    assert status == 200 and d["ok"]
    assert cfg.get("CORP_TRIVIAL_MODEL") == "claudecode:haiku"
    assert cfg.get("CORP_NORMAL_MODEL") == "claudecode:sonnet"
    assert cfg.get("CORP_HARD_MODEL") == "claudecode:opus"


def test_setup_refuses_when_the_cli_will_not_answer(server, monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: None)
    status, d = _call(server, "POST", "/api/claude/setup", {})
    # It must not switch a company onto a provider that cannot reply.
    assert status == 400 and d["ok"] is False
    assert cfg.get_bool("CORP_LLM_MOCK", "true") is True  # unchanged
    assert cfg.get("CORP_NORMAL_MODEL", "x") != "claudecode:sonnet"


def test_providers_payload_exposes_readiness(server, monkeypatch):
    monkeypatch.setattr(claudecli, "installed", lambda: True)
    status, d = _call(server, "GET", "/api/providers")
    assert status == 200 and "claude_installed" in d and "claude_ready" in d
