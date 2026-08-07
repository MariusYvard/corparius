"""One-press Claude subscription setup: prove the CLI works, then flip the four
settings and point the tiers at it. The scattered toggles and hand-edited tier
strings were most of why nobody found this path."""

import threading

import pytest

from corparius import webui
from corparius.config import cfg
from corparius.config.settings import Settings
from corparius.kernel import proc
from corparius.providers import claudecli

from .test_webui import _call


@pytest.fixture(autouse=True)
def no_ollama_probe(monkeypatch):
    """The setup handler asks whether Ollama answers, to decide whether the
    trivial tier goes local or to a free provider. That is a real socket, and a
    unit test must not depend on one: on a runner where 127.0.0.1:11434 is
    filtered rather than refused, the connect timeout outlived the test
    client's own and these tests failed with a socket timeout rather than an
    assertion. Answer "not reachable" without leaving the process."""
    from corparius.providers import hardware, ollama_setup

    monkeypatch.setattr(
        ollama_setup, "status", lambda *a, **k: {"ok": False, "reachable": False, "missing": []}
    )
    # Its neighbour, missed the first time: the handler also asks which models
    # are installed, to decide which one the machine could serve. That is a
    # second real socket to the same filtered port, and patching one of the two
    # only made this fail less often.
    monkeypatch.setattr(hardware, "installed_models", lambda *a, **k: [])


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
    """Stands in for `kernel.proc.run`, returning the type it returns.

    This used to fake `subprocess.run` with a `SimpleNamespace` carrying three attributes,
    which passed for as long as the caller only read those three. `proc.Completed` is a real
    frozen dataclass, so a fake that drifts from the thing it fakes now fails here instead
    of passing a test the shipped code would not have survived.
    """
    return lambda cmd, **k: proc.Completed(
        args=list(cmd), returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_check_reports_installed_logged_in(monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(claudecli.proc, "run", _fake_run())
    r = claudecli.check()
    assert r["ok"] and r["installed"] and "no api key" in r["detail"].lower()


def test_check_says_install_when_missing(monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: None)
    r = claudecli.check()
    assert r["ok"] is False and r["installed"] is False and "claude login" in r["detail"]


def test_check_distinguishes_not_logged_in(monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        claudecli.proc,
        "run",
        _fake_run(returncode=1, stderr="Error: not logged in. Run claude login."),
    )
    r = claudecli.check()
    assert r["ok"] is False and r["installed"] is True
    assert "not logged in" in r["detail"] and "claude login" in r["detail"]


def test_one_press_setup_flips_everything_and_survives_restart(server, monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(claudecli.proc, "run", _fake_run())
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
    monkeypatch.setattr(claudecli.proc, "run", _fake_run())
    for k in ("CORP_LLM_MOCK", "CORP_CLOUD_ENABLED", "CORP_CLAUDE_CODE"):
        monkeypatch.delenv(k, raising=False)
    cfg.invalidate()
    status, d = _call(server, "POST", "/api/claude/setup", {})
    assert status == 200 and d["ok"]
    assert cfg.get("CORP_HARD_MODEL") == "claudecode:opus"
    assert not cfg.get("CORP_NORMAL_MODEL").startswith("claudecode:")
    # No Ollama here, so trivial lands on a free provider rather than local.
    assert not cfg.get("CORP_TRIVIAL_MODEL").startswith("claudecode:")
    # And the chain ends on Sonnet, not Opus: the chain is shared by every
    # tier, so the most expensive model must not be what a failed social post
    # escalates to.
    assert cfg.get("CORP_LLM_FALLBACK").endswith("claudecode:sonnet")
    assert "claudecode:opus" not in cfg.get("CORP_LLM_FALLBACK")


def test_all_tiers_is_available_when_asked_for(server, monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(claudecli.proc, "run", _fake_run())
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


def test_the_polled_providers_endpoint_makes_no_network_probe(server, monkeypatch):
    """/api/providers is polled by the console. It used to build the Claude
    plan, which needs to know whether Ollama answers — so every poll on a
    machine without Ollama paid a connect timeout, and on a runner where the
    port is filtered rather than refused it blocked past the client's own
    timeout. The payload now carries only what costs nothing to compute."""
    from corparius.providers import ollama_setup

    def explode(*a, **k):
        raise AssertionError("/api/providers probed the network")

    monkeypatch.setattr(ollama_setup, "status", explode)
    status, d = _call(server, "GET", "/api/providers")
    assert status == 200 and d["ok"]
    assert d["claude_hard_tier"] == claudecli.HARD_TIER
    # Everything the card needs to say "mixed or every tier" is already here.
    assert isinstance(d["providers"], list) and "configured" in d["providers"][0]


# --- the desktop-app trap --------------------------------------------------
def test_the_missing_cli_message_names_the_command(monkeypatch):
    """ "Install Claude Code" sent an operator to a product page. The command is
    what they need; a link is a detour."""
    monkeypatch.setattr(claudecli.shutil, "which", lambda name: None)
    monkeypatch.setattr(claudecli, "desktop_installed", lambda: False)
    out = claudecli.check()
    assert out["installed"] is False and out["desktop"] is False
    assert "npm install -g @anthropic-ai/claude-code" in out["detail"]
    assert "claude login" in out["detail"]
    assert "corparius claude --install" in out["detail"]


def test_the_desktop_app_is_named_as_a_different_product(monkeypatch):
    """The real report this came from: an operator with Claude Desktop read
    "install Claude Code" as something they had already done, and reasonably
    concluded corparius was broken. Desktop is the chat window; corparius drives
    the CLI headlessly, which a GUI cannot answer."""
    monkeypatch.setattr(claudecli.shutil, "which", lambda name: None)
    monkeypatch.setattr(claudecli, "desktop_installed", lambda: True)
    detail = claudecli.check()["detail"]
    assert "Claude Desktop" in detail and "chat app" in detail
    assert "same subscription" in detail.lower(), "nobody should think they must buy twice"
    assert "npm install -g @anthropic-ai/claude-code" in detail


def test_the_desktop_app_is_never_mistaken_for_the_cli(monkeypatch):
    """Detection changes what is said, never what is run: resolve() is still the
    only thing that decides whether the CLI can be called."""
    monkeypatch.setattr(claudecli.shutil, "which", lambda name: None)
    monkeypatch.setattr(claudecli, "desktop_installed", lambda: True)
    assert claudecli.installed() is False
    assert claudecli.check()["ok"] is False


def test_desktop_detection_never_raises(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert claudecli.desktop_installed() in (True, False)


def test_install_says_what_to_do_when_npm_is_absent(monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda name: None)
    out = claudecli.install()
    assert out["ok"] is False and "Node.js" in out["detail"]


def test_install_reports_the_npm_failure_rather_than_a_stack_trace(monkeypatch):
    monkeypatch.setattr(claudecli.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(
        claudecli.proc,
        "run",
        _fake_run(returncode=1, stdout="", stderr="EACCES: permission denied"),
    )
    out = claudecli.install()
    assert out["ok"] is False and "EACCES" in out["detail"]


def test_install_says_to_open_a_new_terminal_when_the_path_has_not_caught_up(monkeypatch):
    """npm can succeed while `claude` is still not resolvable in this process."""
    monkeypatch.setattr(claudecli.shutil, "which", lambda name: "/usr/bin/npm" if name else None)
    monkeypatch.setattr(claudecli.proc, "run", _fake_run(stdout="", stderr=""))
    monkeypatch.setattr(claudecli, "resolve", lambda: None)
    out = claudecli.install()
    assert out["ok"] is False and "new terminal" in out["detail"]


def test_the_console_never_installs_on_a_poll(server, monkeypatch):
    """Putting a global npm package on the operator's machine happens on a
    button, never as a side effect of the card refreshing."""

    def explode(*a, **k):
        raise AssertionError("the polled endpoint installed something")

    monkeypatch.setattr(claudecli, "install", explode)
    status, d = _call(server, "GET", "/api/providers")
    assert status == 200 and "claude_desktop" in d
