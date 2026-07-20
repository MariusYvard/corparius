"""Regression suite for the console's request-level defences.

The console binds localhost and ships with no token, which is the right default
for a tool that refuses to put a login screen in front of your own machine. It
also meant that until these checks existed, any page the operator happened to
visit could POST to 127.0.0.1:8600 and start a run, save provider keys, publish
a site or delete a company.

The design constraint every test here exists to hold: none of this may require
the operator to configure anything. A browser passes on headers it sets itself;
a non-browser client passes because it sends neither.
"""

import json
import threading
from http.client import HTTPConnection

import pytest

from corparius import cfg, webui
from corparius.config import Settings


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    monkeypatch.delenv("CORP_UI_ALLOWED_HOSTS", raising=False)
    cfg.invalidate()
    srv = webui.build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()  # release the listening socket, not just the loop
    srv.RequestHandlerClass.state.close()


def _call(srv, method, path, body=None, headers=None, raw_body=None):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=5)
    payload = raw_body if raw_body is not None else (json.dumps(body) if body is not None else None)
    conn.request(method, path, payload, {"Content-Type": "application/json", **(headers or {})})
    res = conn.getresponse()
    res.read()
    conn.close()
    return res.status


# --- cross-site writes ----------------------------------------------------


def test_cross_site_origin_is_refused(server):
    assert (
        _call(
            server,
            "POST",
            "/api/run",
            {"company": "example", "ticks": 1},
            headers={"Origin": "https://evil.example"},
        )
        == 403
    )


def test_cross_site_fetch_metadata_is_refused(server):
    """A <form> POST from a malicious page: no JS, no Origin the attacker
    controls, but the browser still labels it cross-site."""
    assert (
        _call(
            server,
            "POST",
            "/api/run",
            {"company": "example", "ticks": 1},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        == 403
    )


def test_same_site_is_refused_too(server):
    """A sibling subdomain is not our page. Only same-origin and none pass."""
    assert _call(server, "POST", "/api/backup", {}, headers={"Sec-Fetch-Site": "same-site"}) == 403


def test_our_own_page_passes_with_nothing_configured(server):
    """The zero-config case: what a browser on 127.0.0.1 actually sends."""
    assert (
        _call(
            server,
            "POST",
            "/api/theme",
            {"mode": "dark"},
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        == 200
    )


def test_address_bar_navigation_passes(server):
    assert _call(server, "GET", "/", headers={"Sec-Fetch-Site": "none"}) == 200


def test_a_client_sending_neither_header_is_allowed(server):
    """curl, the CI smoke job, the MCP server and this suite. Breaking this
    would break the offline-first promise, so it is asserted, not assumed."""
    assert _call(server, "POST", "/api/theme", {"mode": "dark"}) == 200


def test_reads_are_not_origin_checked(server):
    """A cross-site read has no side effect and the caller cannot see the
    response without CORS, which is never granted."""
    assert _call(server, "GET", "/api/companies", headers={"Origin": "https://evil.example"}) == 200


# --- DNS rebinding --------------------------------------------------------


def test_rebound_host_is_refused(server):
    """evil.example rebinds its A record to 127.0.0.1. The browser now considers
    the request same-origin and sends a matching Origin, so the Origin check
    passes - this is the one that catches it."""
    assert (
        _call(
            server,
            "GET",
            "/api/settings",
            headers={
                "Host": "evil.example",
                "Origin": "http://evil.example",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        == 403
    )


def test_rebinding_is_blocked_on_writes_too(server):
    assert (
        _call(server, "POST", "/api/run", {"company": "example"}, headers={"Host": "evil.example"})
        == 403
    )


def test_loopback_hosts_are_accepted(server):
    port = server.socket.getsockname()[1]
    for host in (f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1"):
        assert _call(server, "GET", "/api/companies", headers={"Host": host}) == 200


def test_an_operator_can_name_their_own_host(server, monkeypatch):
    """The escape hatch for a reverse proxy. Named in the 403 body so the
    operator who hits it knows what to set."""
    monkeypatch.setenv("CORP_UI_ALLOWED_HOSTS", "corparius.internal")
    cfg.invalidate()
    assert _call(server, "GET", "/api/companies", headers={"Host": "corparius.internal"}) == 200
    assert _call(server, "GET", "/api/companies", headers={"Host": "other.host"}) == 403


def test_allowed_hosts_cannot_be_set_through_the_api(server):
    """The control must not be writable through the surface it protects: a
    successful cross-site write to /api/settings would otherwise let an attacker
    add their own host and disable the defence for good."""
    assert "CORP_UI_ALLOWED_HOSTS" in cfg.BOOTSTRAP
    assert "CORP_UI_ALLOWED_HOSTS" not in webui.ALLOWED_VARS


# --- body limits ----------------------------------------------------------


def test_oversized_body_is_refused_without_reading_it(server):
    assert (
        _call(
            server,
            "POST",
            "/api/run",
            raw_body=b"{}",
            headers={"Content-Length": str(webui.MAX_BODY + 1)},
        )
        == 413
    )


def test_malformed_content_length_is_a_400_not_a_500(server):
    assert (
        _call(server, "POST", "/api/run", raw_body=b"", headers={"Content-Length": "not-a-number"})
        == 400
    )


def test_chunked_bodies_are_refused(server):
    """http.server does not decode chunked, so Content-Length is absent and the
    ceiling above would be bypassable."""
    assert (
        _call(server, "POST", "/api/run", raw_body=b"", headers={"Transfer-Encoding": "chunked"})
        == 411
    )


# --- token ----------------------------------------------------------------


def test_every_non_public_route_requires_the_token(server, monkeypatch):
    """The check now runs once in _dispatch for both verbs, driven by the
    route's own flag. It used to live in do_POST alone."""
    monkeypatch.setenv("CORP_UI_TOKEN", "s3cret")
    cfg.invalidate()
    for route in webui.ROUTES:
        if route.public or route.method != "GET":
            continue
        path = route.path + ("?company=example" if route.needs_slug else "")
        assert _call(server, "GET", path) == 401, f"{route.path} answered without a token"


def test_public_routes_still_answer_with_a_token_set(server, monkeypatch):
    """The page has to be able to load in order to ask for the token, and
    /api/session is how it learns one is needed."""
    monkeypatch.setenv("CORP_UI_TOKEN", "s3cret")
    cfg.invalidate()
    assert _call(server, "GET", "/") == 200
    assert _call(server, "GET", "/api/session") == 200


def test_a_wrong_token_is_refused(server, monkeypatch):
    monkeypatch.setenv("CORP_UI_TOKEN", "s3cret")
    cfg.invalidate()
    assert _call(server, "GET", "/api/settings", headers={"X-Corp-Token": "wrong"}) == 401
    assert _call(server, "GET", "/api/settings", headers={"X-Corp-Token": "s3cret"}) == 200


def test_a_non_ascii_token_does_not_crash_the_comparison(server, monkeypatch):
    """compare_digest raises TypeError on a non-ASCII str, which would surface
    as a 500 and tell the caller their guess was interesting."""
    monkeypatch.setenv("CORP_UI_TOKEN", "s3cret")
    cfg.invalidate()
    assert _call(server, "GET", "/api/settings", headers={"X-Corp-Token": "clé-évidente"}) == 401
