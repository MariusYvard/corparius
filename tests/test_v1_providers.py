"""The providers tab's endpoints, and the rule that shapes all of them.

**No probe is reachable from a read.** That rule was written after `/api/providers` opened a socket on
every refresh, and it is why the read reports `claude_installed` from the filesystem and omits the
Claude tier plan entirely: building that plan needs to know whether Ollama answers, which on a machine
without it costs a connect timeout per poll — on a runner where the port is filtered rather than
refused, long enough to fail this suite.

So every probe is its own POST. A client decides when to spend the operator's account, and the verb
says so. `test_the_reads_open_no_socket` is what makes that a property rather than an intention.
"""

import json
import shutil
import socket
import threading
from http.client import HTTPConnection

import pytest


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from corparius.api.server import build_server
    from corparius.config import cfg
    from corparius.config.settings import Settings

    from .conftest import EXAMPLE_COMPANY

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    for name in ("GROQ_API_KEY", "OPENAI_API_KEY", "CORP_SESSION_TOKEN_BUDGET"):
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


# --- the read, and what it must not do ------------------------------------------


def test_the_read_says_which_providers_exist_and_never_returns_a_key(server):
    """Write-only, and this is the assertion that keeps it that way. A payload echoing a credential
    would put it in every client's cache and every proxy log; `key_set` is a boolean instead."""
    status, data = _call(server, "GET", "/api/v1/providers")
    assert status == 200 and data["providers"]
    for p in data["providers"]:
        assert set(p) >= {"name", "key_env", "configured", "key_set", "signup"}
        assert "key" not in p and "value" not in p
    blob = json.dumps(data)
    assert "gsk-" not in blob and "sk-" not in blob


def test_the_reads_open_no_socket(tmp_path, monkeypatch):
    """The rule, as a property. Three reads, and none may reach the network.

    The services are called directly rather than over HTTP, and that is deliberate: the first version
    of this test went through the test client and caught **the request itself** — a request *is* a
    socket, so it was measuring the trip rather than the handler. The same mistake
    `test_the_capabilities_open_no_socket` documents.

    `v1_ollama` is included and it is the interesting one: `ollama_setup.status` talks to a local
    daemon, so this asserts the *cached* path only — `hardware.profile` reads what a bench left behind
    and never takes one. A daemon check on a polled endpoint is the same defect at 127.0.0.1.
    """
    from corparius.api import adapters
    from corparius.config import cfg
    from corparius.config.settings import Settings
    from corparius.store import Store

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()

    def refuse(*a, **k):
        raise AssertionError("a read on the providers tab opened a socket")

    store = Store(str(tmp_path / "data"))
    try:
        monkeypatch.setattr(socket.socket, "connect", refuse)
        payload = adapters.providers_payload()
        assert payload["providers"], "it has to answer something"
        assert "claude_installed" in payload
        # The Claude tier plan is deliberately absent: building it needs to know whether Ollama
        # answers. The page derives the same "mixed vs every tier" note from `providers[].configured`.
        assert "claude_plan" not in payload
        from corparius.providers import hardware

        assert hardware.profile(store, max_age_days=30) is None, "nothing benched, nothing measured"
        assert hardware.recommended_local(store, Settings(), models=[])[0] == ""
    finally:
        monkeypatch.undo()
        store.close()


def test_the_claude_read_is_filesystem_only(server):
    """`desktop` exists so the card can say "that is the chat app, not the CLI" — the commonest
    confusion in this setup — without costing a probe."""
    status, data = _call(server, "GET", "/api/v1/claude")
    assert status == 200
    assert set(data) >= {"installed", "desktop", "ready", "install_cmd", "hard_tier"}
    assert all(isinstance(data[k], bool) for k in ("installed", "desktop", "ready"))


def test_the_ollama_read_answers_the_cached_measurement(server):
    """`tokens_per_second`, `placement`, `cores` — the fields `hardware.profile_save` writes, so the
    card can say "measured at N tokens/s on the GPU" rather than "reachable", which is not the same
    claim. Reachable is not capable, and the absence of a measurement is reported as such."""
    status, data = _call(server, "GET", "/api/v1/ollama")
    assert status == 200
    assert set(data) >= {"reachable", "missing", "installed", "machine", "local_model"}
    assert data["machine"] is None, "nothing has been benched in this fixture"
    assert data["local_model"] == "", "and so local must not be offered a tier"
    assert data["local_reason"], "the reason is a sentence, and it has to be said"


# --- the write, sharing the fix from the sixth divergence ------------------------


def test_saving_a_key_reports_it_set_without_returning_it(server):
    status, data = _call(
        server, "POST", "/api/v1/providers", {"values": {"GROQ_API_KEY": "  gsk-secret  "}}
    )
    assert status == 200
    groq = next(p for p in data["providers"] if p["name"] == "groq")
    assert groq["key_set"] is True
    assert "gsk-secret" not in json.dumps(data), "the answer must not echo the credential"


def test_the_write_coerces_a_registry_field_here_too(server):
    """The sixth divergence, asserted at the v1 spelling. This route had its own check —
    `key in WRITABLE` then `strip()` — so a registry field arrived unvalidated and `cfg.get_int` then
    answered the caller's fallback."""
    status, data = _call(
        server,
        "POST",
        "/api/v1/providers",
        {"values": {"CORP_SESSION_TOKEN_BUDGET": "not-a-number"}},
    )
    assert status == 400
    assert data["error"]["code"] == "invalid"
    assert "whole number" in data["error"]["message"]
    # `detail.errors` carries them apart, so a client is not left splitting on "; ".
    assert any("whole number" in e for e in data["error"]["detail"]["errors"])


def test_an_unsettable_variable_is_still_refused(server):
    """`CORP_UI_ALLOWED_HOSTS` decides which Host headers the server answers. It is settable from a
    file and never over the API, whichever route asks."""
    status, data = _call(
        server, "POST", "/api/v1/providers", {"values": {"CORP_UI_ALLOWED_HOSTS": "evil.example"}}
    )
    assert status == 400 and data["error"]["code"] == "invalid"
    assert "unknown setting" in data["error"]["message"]


def test_a_blank_credential_is_kept_rather_than_cleared(server, tmp_path):
    """Revoking, not resetting. A cleared row lets `.env` show through and the key comes back — which
    is why `app_settings.CREDENTIALS` is a separate class, measured rather than assumed."""
    from corparius.config import cfg

    (tmp_path / ".env").write_text("GROQ_API_KEY=from-dot-env\n", encoding="utf-8")
    cfg.invalidate()
    _status, data = _call(server, "POST", "/api/v1/providers", {"values": {"GROQ_API_KEY": ""}})
    groq = next(p for p in data["providers"] if p["name"] == "groq")
    assert groq["key_set"] is False, "the file value must stay masked, not resurface"


def test_a_toggle_the_environment_shadows_is_reported_and_not_faked(server):
    """The first version of this asserted `llm_mock is False` after writing "false", and it failed —
    correctly. `CORP_LLM_MOCK=true` is in this fixture's *process environment*, and `os.environ`
    outranks both the store and `.env`: nothing the console writes can win against it.

    That is the right layering — the environment belongs to whoever started the process — and the
    contract is that the write is *reported as shadowed* rather than appearing to have worked. Which is
    exactly what `persist` returns `shadowed` for, and what a client needs to say "saved, but your
    environment is overriding it" instead of showing a switch that springs back.
    """
    status, data = _call(
        server,
        "POST",
        "/api/v1/providers",
        {"values": {"CORP_LLM_MOCK": "false", "CORP_CLOUD_ENABLED": "true"}},
    )
    assert status == 200
    assert "CORP_LLM_MOCK" in data["shadowed"], "a write the environment overrides must say so"
    assert data["llm_mock"] is True, "and must not claim it took effect"
    # `CORP_CLOUD_ENABLED` is not in the environment here, so that one really does land.
    assert data["cloud_enabled"] is True
    assert "CORP_CLOUD_ENABLED" not in data["shadowed"]


# --- the probes, each its own POST ----------------------------------------------


def test_an_unknown_provider_is_not_found_on_both_probes(server):
    for path in ("/api/v1/providers/probe", "/api/v1/providers/models"):
        status, data = _call(server, "POST", path, {"name": "nope"})
        assert status == 404, (path, data)
        assert data["error"]["code"] == "not_found"
        assert data["error"]["detail"]["name"] == "nope"


def test_listing_models_when_a_provider_does_not_answer(server, monkeypatch):
    """A provider that does not answer is `ok: false` **with the proven list**, not an envelope
    refusal: the request was fine, and a client holding the proven models can still fill a tier.

    Measured on NVIDIA with a real key: 10 of 18 catalogue entries answered 404. That is why the
    proven set travels alongside the catalogue rather than being folded into it.

    The failure is injected rather than provoked. The first version of this let the call reach
    `api.groq.com` for real — non-hermetic, slow, and dependent on whether the runner has a network —
    and it surfaced as a `ResourceWarning` about an unclosed socket, which `filterwarnings = ["error"]`
    turned into a failure about the wrong thing entirely.
    """
    from corparius.providers import llm

    def refuse(name, timeout=8):
        raise OSError("no route to host")

    monkeypatch.setattr(llm, "list_models", refuse)
    status, data = _call(server, "POST", "/api/v1/providers/models", {"name": "groq"})
    assert status == 200, "not answering is not the request being wrong"
    assert data["ok"] is False
    assert data["models"] == [] and data["proved"] == {}
    assert "preflight" in data["error"]


def test_preflight_refuses_in_mock_mode_with_a_code(server):
    """`conflict`, not `invalid`: the request is well formed and the core is in a state where it
    cannot be served. A client retries after turning mock off rather than sending something else."""
    status, data = _call(server, "POST", "/api/v1/preflight", {})
    assert status == 409 and data["error"]["code"] == "conflict"
    assert "mock mode" in data["error"]["message"]


def test_recommending_routing_works_on_a_fresh_install_with_no_key_at_all(server):
    """Measured, and it corrected the assumption this test started from.

    `connected_providers()` answers `["ovh"]` on a machine with no credentials whatsoever: OVH AI
    Endpoints is `key_optional` and carries a default base URL, so **a fresh install can route without
    the operator pasting anything.** The first version of this asserted a 409 and failed, which is a
    better outcome than it passing would have been.

    It also turns mock off and cloud on, because a coherent routing that nothing is allowed to call is
    the trap the defaults already leave.
    """
    status, data = _call(server, "POST", "/api/v1/tiers/recommend", {})
    assert status == 200, data
    assert data["routing"], "a routing was produced"
    assert data["cloud_enabled"] is True
    # Every tier filled, so none is left pointing at a provider nobody configured.
    assert all(data["tiers"][tier] for tier in ("trivial", "normal", "hard"))


def test_recommending_routing_is_a_conflict_when_truly_nothing_is_connected(server, monkeypatch):
    """The branch the test above showed is nearly unreachable in practice. Kept, and reached by
    injection, because clearing OVH's base URL is a thing an operator can do."""
    from corparius.api import handlers

    monkeypatch.setattr(handlers, "connected_providers", lambda: [])
    status, data = _call(server, "POST", "/api/v1/tiers/recommend", {})
    assert status == 409 and data["error"]["code"] == "conflict"
    assert "free provider" in data["error"]["message"]


def test_claude_setup_refuses_when_the_cli_does_not_answer(server, monkeypatch):
    """The proof comes before the write: never switch a company to a provider that will not answer.
    `check` rides back in the detail so a client can show *why* rather than only that it failed."""
    from corparius.providers import claudecli

    monkeypatch.setattr(
        claudecli, "check", lambda **k: {"ok": False, "detail": "claude: command not found"}
    )
    status, data = _call(server, "POST", "/api/v1/claude/setup", {})
    assert status == 409 and data["error"]["code"] == "conflict"
    assert "not found" in data["error"]["message"]
    assert data["error"]["detail"]["check"]["ok"] is False


def test_nothing_was_written_when_claude_setup_refused(server, monkeypatch):
    """The half that matters. A refusal that had already flipped mock off would leave a company
    pointing at a CLI that does not answer."""
    from corparius.providers import claudecli

    monkeypatch.setattr(claudecli, "check", lambda **k: {"ok": False, "detail": "nope"})
    before = _call(server, "GET", "/api/v1/providers")[1]
    _call(server, "POST", "/api/v1/claude/setup", {})
    after = _call(server, "GET", "/api/v1/providers")[1]
    assert after["llm_mock"] == before["llm_mock"]
    assert after["tiers"] == before["tiers"]
