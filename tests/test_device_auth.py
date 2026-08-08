"""A named credential per device, two scopes, and the CSRF tier that a native app would have walked
straight through.

`CORP_UI_TOKEN` is one shared secret with no name, no scope and no way to withdraw it from one
device without changing it for all of them. Schema 20 is the other shape, and the interesting part
is not the table — it is what had to tighten around it.

**The tier that changed.** `_same_origin` had three tiers and the third was "neither
`Sec-Fetch-Site` nor `Origin` present ⇒ allowed". That was a reasonable local compromise, and the
code said so: it is what keeps curl, the CI smoke, this suite's `HTTPConnection` and the MCP server
working with no configuration. But **a native app sends neither header either**, so the moment a
second client is real, that tier stops meaning "not a browser, therefore local" and becomes the
door a remote write comes through. It now requires loopback — checked on the peer address, which a
caller cannot set — or a paired device.

**Two scopes and no more.** `read` may GET, `act` may also POST. A `read` device asking to act gets
**403 and not 401**, because the credential is good and the answer is still no: a client told 401
would re-pair, which would not help.

**No TLS, and the doctor fails.** `http.server` plus a self-signed certificate is a catastrophe of
an experience on iOS and would teach operators to click through certificate warnings. The plan's
answer is a tunnel, and the check that makes that honest fails rather than warns — a device token is
a bearer credential, and a warning about one leaking on the wire is a warning nobody acts on twice.
"""

import json
import threading
from http.client import HTTPConnection

import pytest

from corparius.kernel import tokens
from corparius.store import clients as clients_store


@pytest.fixture()
def server(tmp_path, monkeypatch):
    import shutil

    from corparius.api.server import build_server
    from corparius.config import cfg
    from corparius.config.settings import Settings

    from .conftest import EXAMPLE_COMPANY

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.setenv("CORP_UI_TOKEN", "shared-bootstrap")
    monkeypatch.delenv("CORP_UI_ALLOWED_ORIGINS", raising=False)
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


def _call(srv, method, path, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=10)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        {"Content-Type": "application/json", **(headers or {})},
    )
    res = conn.getresponse()
    raw = res.read()
    out = (res.status, dict(res.getheaders()), json.loads(raw or b"{}") if raw else {})
    conn.close()
    return out


def _pair(srv, name="a phone", scope=clients_store.READ):
    return srv.RequestHandlerClass.state.store().pair_client(name, scope)


# --- the credential -------------------------------------------------------------


def test_a_paired_device_is_admitted_by_bearer(server):
    device = _pair(server)
    status, _h, data = _call(
        server,
        "GET",
        "/api/v1/summary?company=example",
        headers={"Authorization": f"Bearer {device['token']}"},
    )
    assert status == 200 and data["ok"] is True


def test_the_old_header_still_works_for_a_device(server):
    """`X-Corp-Token` is what the shipped page has always sent, and stays an alias for a version.
    A client should not have to know which of two spellings this build understands."""
    device = _pair(server)
    status, _h, _d = _call(
        server, "GET", "/api/v1/summary?company=example", headers={"X-Corp-Token": device["token"]}
    )
    assert status == 200


def test_bearer_wins_when_both_headers_are_sent(server):
    """A client that sets `Authorization` meant it. Preferring the legacy header would let a stale
    one shadow a fresh credential and produce a 401 nobody could explain."""
    good = _pair(server, "good")
    status, _h, _d = _call(
        server,
        "GET",
        "/api/v1/summary?company=example",
        headers={"Authorization": f"Bearer {good['token']}", "X-Corp-Token": "rubbish"},
    )
    assert status == 200


def test_the_shared_token_still_opens_the_door(server):
    """It is the bootstrap credential and it does not stop working when a device is paired —
    otherwise pairing one from a terminal would lock the operator out of their own console."""
    status, _h, _d = _call(
        server,
        "GET",
        "/api/v1/summary?company=example",
        headers={"X-Corp-Token": "shared-bootstrap"},
    )
    assert status == 200


def test_a_wrong_or_missing_credential_is_401_with_a_code(server):
    for headers in ({}, {"X-Corp-Token": "nope"}, {"Authorization": "Bearer corp_dead.beef"}):
        status, _h, data = _call(server, "GET", "/api/v1/summary?company=example", headers=headers)
        assert status == 401, headers
        assert data["error"]["code"] == "unauthenticated"


def test_a_revoked_device_is_refused_from_its_next_request(server):
    device = _pair(server)
    head = {"Authorization": f"Bearer {device['token']}"}
    assert _call(server, "GET", "/api/v1/summary?company=example", headers=head)[0] == 200
    assert server.RequestHandlerClass.state.store().revoke_client(device["id"]) is True
    assert _call(server, "GET", "/api/v1/summary?company=example", headers=head)[0] == 401


def test_a_malformed_credential_is_a_failed_login_and_not_a_crash(server):
    """`tokens.split` is total on purpose: a credential that is not one of ours is not an
    exception, it is a failed authentication, and the caller has one branch for both."""
    for bad in ("", "Bearer", "corp_", "corp_noseparator", "corp_.", "corp_id.", "notours.x"):
        assert tokens.split(bad) == ("", "")
        status, _h, _d = _call(
            server, "GET", "/api/v1/summary?company=example", headers={"X-Corp-Token": bad}
        )
        assert status == 401, bad


def test_a_successful_request_records_when_the_device_was_last_seen(server):
    """The only thing a successful authentication writes, and it earns it: an operator deciding
    whether a paired device is still in use has no other way to know."""
    device = _pair(server)
    store = server.RequestHandlerClass.state.store()
    assert store.list_clients()[0]["last_seen"] is None
    _call(
        server,
        "GET",
        "/api/v1/summary?company=example",
        headers={"Authorization": f"Bearer {device['token']}"},
    )
    assert store.list_clients()[0]["last_seen"] is not None


def test_the_secret_is_never_stored_and_never_listed(server):
    """Shown once and kept as a hash. A store that could show it back is a store whose theft is
    enough to impersonate every paired device."""
    device = _pair(server)
    store = server.RequestHandlerClass.state.store()
    _cid, secret = tokens.split(device["token"])
    row = store.client(device["id"])
    assert secret not in json.dumps(row), "the secret itself must not be in the row"
    assert row["token_hash"] != secret
    listed = store.list_clients()[0]
    assert "token_hash" not in listed and "salt" not in listed


# --- scopes ---------------------------------------------------------------------


def test_a_read_device_may_look(server):
    device = _pair(server, "tablet", clients_store.READ)
    status, _h, _d = _call(
        server,
        "GET",
        "/api/v1/summary?company=example",
        headers={"Authorization": f"Bearer {device['token']}"},
    )
    assert status == 200


def test_a_read_device_may_not_act_and_is_told_403_not_401(server):
    """The distinction a client acts on: 401 means "your credential is wrong, get another one" and
    403 means "your credential is fine and the answer is no". Answering 401 here would send a
    device off to re-pair, which would change nothing."""
    device = _pair(server, "tablet", clients_store.READ)
    status, _h, data = _call(
        server,
        "POST",
        "/api/v1/runs",
        {"company": "example", "ticks": 1},
        {"Authorization": f"Bearer {device['token']}"},
    )
    assert status == 403
    assert data["error"]["code"] == "forbidden"
    assert data["error"]["detail"]["scope"] == clients_store.READ


def test_an_act_device_may_act(server):
    device = _pair(server, "phone", clients_store.ACT)
    status, _h, data = _call(
        server,
        "POST",
        "/api/v1/runs",
        {"company": "example", "ticks": 1},
        {"Authorization": f"Bearer {device['token']}"},
    )
    assert status == 200 and data["ok"] is True


def test_there_are_two_scopes_and_a_third_is_refused_at_the_source(server):
    """Not a validation message — an assertion. Ten scopes is a permission system nobody gets
    right, and this product already has one of those for what an *agent* may do."""
    store = server.RequestHandlerClass.state.store()
    assert clients_store.SCOPES == ("read", "act")
    with pytest.raises(AssertionError):
        store.pair_client("a device", "admin")


# --- the tier that tightened ----------------------------------------------------


def test_a_write_with_no_browser_headers_is_still_allowed_from_loopback(server):
    """What keeps curl, the CI smoke, this suite and the MCP server working with no configuration.
    The whole test suite depends on it, so it is asserted rather than assumed."""
    status, _h, _d = _call(
        server, "POST", "/api/theme", {"hue": "200"}, {"X-Corp-Token": "shared-bootstrap"}
    )
    assert status == 200


def test_a_write_from_a_foreign_origin_is_refused(server):
    status, _h, data = _call(
        server,
        "POST",
        "/api/theme",
        {"hue": "200"},
        {"X-Corp-Token": "shared-bootstrap", "Origin": "https://evil.example"},
    )
    assert status == 403 and "cross-site" in data["error"]


def test_the_third_tier_now_needs_loopback_or_a_device(server, monkeypatch):
    """The tightening, asserted where it can be: `_same_origin` is asked directly with a peer
    address that is not local, which is what a native app or a proxied browser looks like.

    Over HTTP this suite is always loopback, so the end-to-end version of this test would pass no
    matter what the code said — the connection itself supplies the thing being tested. Measuring
    the trip instead of the behaviour, which this restructuring has now done often enough to
    recognise on sight.
    """
    from corparius.api.server import Handler

    class _Stub:
        client_address = ("203.0.113.9", 51000)
        headers: dict = {}

        # The real one, over the stub's peer address. Writing a second implementation here would
        # test the copy: whether a peer counts as local is precisely the thing being asserted.
        _from_loopback = Handler._from_loopback

    stub = _Stub()
    # No browser headers and not loopback: refused without a device.
    assert Handler._same_origin(stub, None) is False
    # The same request with a paired device is allowed.
    assert Handler._same_origin(stub, {"id": "x", "scopes": "act"}) is True
    # And from loopback it is allowed with no device, which is the local default.
    stub.client_address = ("127.0.0.1", 51000)
    assert Handler._same_origin(stub, None) is True


def test_sec_fetch_site_still_decides_when_a_browser_sends_it(server):
    """Tier 1 is unchanged and is what blocks a plain <form> POST from a malicious page — the
    classic no-JS CSRF — with no CSRF token, no cookie and no login screen."""
    for site, ok in (("same-origin", True), ("none", True), ("cross-site", False)):
        status, _h, _d = _call(
            server,
            "POST",
            "/api/theme",
            {"hue": "210"},
            {"X-Corp-Token": "shared-bootstrap", "Sec-Fetch-Site": site},
        )
        assert (status == 200) is ok, site


# --- origins and the preflight --------------------------------------------------


def test_an_unlisted_origin_gets_a_403_preflight_and_no_cors_headers(server):
    status, headers, data = _call(
        server, "OPTIONS", "/api/v1/summary", headers={"Origin": "https://evil.example"}
    )
    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers
    assert data["error"]["code"] == "forbidden"


def test_a_listed_origin_gets_a_preflight_and_the_header_on_the_real_answer(server, monkeypatch):
    """Both halves are needed. Without the header on the actual response a browser refuses to let
    the page read it, which looks exactly like the server being down."""
    from corparius.config import cfg

    monkeypatch.setenv("CORP_UI_ALLOWED_ORIGINS", "http://localhost:5173")
    cfg.invalidate()
    status, headers, _d = _call(
        server, "OPTIONS", "/api/v1/summary", headers={"Origin": "http://localhost:5173"}
    )
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "Authorization" in headers["Access-Control-Allow-Headers"]
    assert "Idempotency-Key" in headers["Access-Control-Allow-Headers"]
    assert headers["Vary"] == "Origin"
    # No credentials header: there are no cookies here, and granting it would invite a browser to
    # attach ambient authority to a cross-origin write.
    assert "Access-Control-Allow-Credentials" not in headers

    device = _pair(server, "dev server", clients_store.ACT)
    status, headers, _d = _call(
        server,
        "GET",
        "/api/v1/summary?company=example",
        headers={
            "Origin": "http://localhost:5173",
            "Authorization": f"Bearer {device['token']}",
        },
    )
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


def test_the_allow_list_is_never_a_star_and_never_reflected(server, monkeypatch):
    """Reflecting `Origin` is the same permission spelled to look careful, and `*` hands the API to
    any page the operator happens to have open."""
    from corparius.api import server as server_mod
    from corparius.config import cfg

    monkeypatch.setenv("CORP_UI_ALLOWED_ORIGINS", "http://localhost:5173")
    cfg.invalidate()
    assert server_mod._allowed_origins() == frozenset({"http://localhost:5173"})
    status, headers, _d = _call(
        server, "OPTIONS", "/api/v1/summary", headers={"Origin": "http://localhost:5174"}
    )
    assert status == 403 and "Access-Control-Allow-Origin" not in headers


def test_the_two_new_keys_are_bootstrap_and_not_writable_through_the_api(server):
    """The reasoning `CORP_UI_ALLOWED_HOSTS` already carried, word for word: a security control
    must not be writable through the surface it protects. A cross-site write to `/api/settings`
    that could add its own origin would disable the defence permanently."""
    from corparius.config import cfg, settings_spec

    for key in ("CORP_UI_ALLOWED_ORIGINS", "CORP_UI_BEHIND_TLS"):
        assert key in cfg.BOOTSTRAP
        assert key not in settings_spec.WRITABLE, f"{key} must not be settable from the page"


# --- the doctor -----------------------------------------------------------------


def _devices_check(tmp_path, host, behind_tls=False, paired=True, monkeypatch=None):
    from corparius.config import cfg
    from corparius.config.settings import Settings
    from corparius.doctor import _check_devices
    from corparius.store import Store

    monkeypatch.setenv("CORP_UI_HOST", host)
    monkeypatch.setenv("CORP_UI_BEHIND_TLS", "true" if behind_tls else "false")
    cfg.invalidate()
    store = Store(str(tmp_path / "data"))
    try:
        if paired:
            store.pair_client("a phone", clients_store.ACT)
        return _check_devices(Settings(), store)
    finally:
        store.close()


def test_the_doctor_is_content_with_a_paired_device_on_loopback(tmp_path, monkeypatch):
    level, name, message = _devices_check(tmp_path, "127.0.0.1", monkeypatch=monkeypatch)
    assert level == "ok" and name == "devices"
    assert "a phone" in message


def test_the_doctor_fails_on_a_paired_device_and_an_off_loopback_console(tmp_path, monkeypatch):
    """Fails rather than warns, and that is the decision. A device token is a bearer credential, so
    this puts it in every request on the wire; a warning about a leaked credential is a warning
    nobody acts on twice. The message names both ways out."""
    check = _devices_check(tmp_path, "0.0.0.0", monkeypatch=monkeypatch)
    assert check[0] == "fail"
    assert "no TLS" in check[2]
    assert "tunnel" in check[2] and "CORP_UI_BEHIND_TLS" in check[2]


def test_the_operator_can_assert_a_proxy_terminates_tls(tmp_path, monkeypatch):
    """An assertion, not a detection, and the docstring says so: from inside this process a request
    from a local proxy and one from a laptop across a café look identical."""
    check = _devices_check(tmp_path, "0.0.0.0", behind_tls=True, monkeypatch=monkeypatch)
    assert check[0] == "ok" and "terminates in front" in check[2]


def test_no_paired_device_is_not_a_finding(tmp_path, monkeypatch):
    """Off-loopback with no device is `_check_exposure`'s business and it already covers it. Two
    checks reporting the same thing differently is how an operator learns to skim them."""
    check = _devices_check(tmp_path, "0.0.0.0", paired=False, monkeypatch=monkeypatch)
    assert check[0] == "ok" and "no paired device" in check[2]


def test_a_revoked_device_does_not_keep_the_doctor_worried(tmp_path, monkeypatch):
    from corparius.config import cfg
    from corparius.config.settings import Settings
    from corparius.doctor import _check_devices
    from corparius.store import Store

    monkeypatch.setenv("CORP_UI_HOST", "0.0.0.0")
    cfg.invalidate()
    store = Store(str(tmp_path / "data"))
    try:
        paired = store.pair_client("lost phone", clients_store.ACT)
        assert _check_devices(Settings(), store)[0] == "fail"
        store.revoke_client(paired["id"])
        assert _check_devices(Settings(), store)[0] == "ok"
    finally:
        store.close()


# --- the terminal ---------------------------------------------------------------


def test_pairing_from_a_terminal_prints_the_token_once(tmp_path, monkeypatch, capsys):
    import types

    from corparius.cli import access
    from corparius.config import cfg

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    assert access.cmd_pair(types.SimpleNamespace(name="Marius iPhone", act=True)) == 0
    out = capsys.readouterr().out
    assert "Marius iPhone" in out and "scope act" in out
    assert tokens.PREFIX in out
    assert "only time it is shown" in out

    assert access.cmd_clients(types.SimpleNamespace()) == 0
    listed = capsys.readouterr().out
    assert "Marius iPhone" in listed and "act" in listed
    assert "never" in listed, "a device paired and never used is what an operator wants to notice"
    assert tokens.PREFIX not in listed, "listing must never show a credential"


def test_revoking_an_unknown_id_is_non_zero(tmp_path, monkeypatch, capsys):
    import types

    from corparius.cli import access
    from corparius.config import cfg

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    assert access.cmd_revoke(types.SimpleNamespace(id="not-a-device")) == 1
    assert "no active device" in capsys.readouterr().out


def test_a_read_scope_is_the_default_and_the_command_says_so(tmp_path, monkeypatch, capsys):
    """The safe default, and named in the output: an operator who did not think about scope should
    be told which one they got and how to get the other."""
    import types

    from corparius.cli import access
    from corparius.config import cfg

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    access.cmd_pair(types.SimpleNamespace(name="tablet", act=False))
    out = capsys.readouterr().out
    assert "scope read" in out and "--act" in out


def test_clients_says_plainly_when_nothing_is_paired(tmp_path, monkeypatch, capsys):
    """And names what is answering instead, so an operator who expected a device is not left
    wondering whether the command worked."""
    import types

    from corparius.cli import access
    from corparius.config import cfg

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    assert access.cmd_clients(types.SimpleNamespace()) == 0
    out = capsys.readouterr().out
    assert "no paired device" in out and "CORP_UI_TOKEN" in out


def test_revoking_reports_success_and_the_listing_then_says_revoked(tmp_path, monkeypatch, capsys):
    """`revoked` is a column and not a `DELETE`: an operator asking "did I actually revoke that
    phone" needs an answer, and a deleted row cannot give one."""
    import types

    from corparius.cli import access
    from corparius.config import cfg

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    access.cmd_pair(types.SimpleNamespace(name="lost phone", act=True))
    printed = capsys.readouterr().out
    # The id through `tokens.split`, which is how a caller gets it — scanning the output for a
    # 16-hex word found nothing, because `pair` prints the credential and the id lives inside it.
    credential = next(w for w in printed.split() if w.startswith(tokens.PREFIX))
    client_id, _secret = tokens.split(credential)
    assert access.cmd_revoke(types.SimpleNamespace(id=client_id)) == 0
    assert "refused from its next request" in capsys.readouterr().out
    access.cmd_clients(types.SimpleNamespace())
    assert "revoked" in capsys.readouterr().out


def test_last_seen_reads_in_units_a_person_uses():
    """Four boundaries, and each one is a decision about what a person reading a list wants. A
    device last seen 40 hours ago is "1d ago" and not "40h ago"; one paired and never used is
    "never" and not a date that is not there."""
    import time

    from corparius.cli.access import _ago

    now = time.time()
    assert _ago(None) == "never"
    assert _ago(0) == "never", "a falsy timestamp is not a moment in 1970"
    assert _ago(now) == "0s ago"
    assert _ago(now - 30) == "30s ago"
    assert _ago(now - 600) == "10m ago"
    assert _ago(now - 7200) == "2h ago"
    assert _ago(now - 3 * 86400) == "3d ago"
