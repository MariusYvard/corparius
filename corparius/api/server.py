"""The stdlib HTTP server, and the checks a request passes before a handler sees it. Rank 6,
and the only module in the package that may import `http.server`.

Host allow-listing (the DNS-rebinding defence), same-origin for writes, the token, and the
per-route body ceiling — in that order, each documented where it happens. Two of those orders
are load-bearing and say so in place: the body is read before auth is decided, and it is
deliberately *not* read when a client announces more than the ceiling.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..config import cfg
from ..config.settings import Settings
from ..kernel import httpkit, paths, tokens
from ..store import clients as clients_store
from . import contracts, state
from .adapters import oops
from .contracts import Ctx, RequestRefused
from .routes import match
from .state import UiState

V1 = "/api/v1/"


def _allowed_origins() -> frozenset[str]:
    """Origins permitted to make a cross-origin request, exactly as written.

    A bootstrap key rather than a stored setting, because it decides who may reach the console and
    that must not depend on the console being reachable. **Never `*`** and never `Origin` reflected
    back: reflecting is the same permission spelled to look careful, and `*` would hand the API to
    any page the operator happens to have open.
    """
    raw = cfg.get("CORP_UI_ALLOWED_ORIGINS", "")
    return frozenset(o.strip().rstrip("/") for o in raw.split(",") if o.strip())


log = logging.getLogger("corparius.api.server")


# The writable home, for the .env the console writes. Resolves to the repository layout from a
# source checkout and to the frozen bundle when packaged.
#
# The comment here used to end "kept as module attributes so the tests can monkeypatch them",
# about this and `PAGE`. Measured while splitting the file: no test patches either one. The
# reason was true of some earlier version and outlived it, which is the failure mode of a
# comment that states a purpose instead of a fact.
ROOT = paths.user_home()


class Handler(BaseHTTPRequestHandler):
    # Injected by build_server, and the one place in `api/` where the word means the console's
    # object rather than the `state` module: it is only ever reached as an attribute
    # (`self.state` here, `RequestHandlerClass.state` in six test files), so it shadows nothing.
    state: UiState
    server_version = "corparius-ui"

    def log_message(self, fmt, *args):  # quiet by default, keep the app log
        log.debug("%s " + fmt, self.address_string(), *args)

    def _is_v1(self) -> bool:
        return urlparse(self.path).path.startswith(V1)

    def _refuse(self, status: int, code: str, message: str, **detail) -> None:
        """One refusal, two shapes, chosen by the version in the path.

        A v1 client gets `{"error": {"code", …}}` and can branch on it; the 54 legacy routes get
        the flat sentence the shipped page has read for its whole life. The four checks below
        are the ones every request passes regardless of route, so a client that could branch on
        a handler's refusal and not on a 401 would be able to branch on almost nothing.
        """
        if self._is_v1():
            self._send(status, contracts.envelope(code, message, **detail))
        else:
            self._send(status, {"ok": False, "error": message})

    def _matches_etag(self, tag: str) -> bool:
        """`If-None-Match`, honestly parsed: a list, and `*` means "any copy at all".

        Weak validators (`W/"…"`) compare equal to the strong one here, which is correct for
        this: the entity either hashed the same or it did not.
        """
        header = self.headers.get("If-None-Match", "")
        if not header:
            return False
        offered = [x.strip().removeprefix("W/") for x in header.split(",")]
        return "*" in offered or tag in offered

    def _send(self, code: int, payload: dict | bytes, ctype="application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        # A v1 GET that answered gets a validator, so a client at rest re-downloads nothing.
        # What this saves is **bandwidth, not work**: the payload is built and then hashed, so
        # the query still runs. Narrowing what a client polls is what makes the query small —
        # `/api/v1/summary` is 2 859 bytes where `/api/overview` is 48 530 — and this is what
        # makes the unchanged 2 859 free on the wire.
        if code == 200 and self.command == "GET" and self._is_v1():
            tag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
            if self._matches_etag(tag):
                self.send_response(304)
                self.send_header("ETag", tag)
                # `no-store` on the rest of the API forbids keeping the copy at all, which would
                # make revalidation impossible — the client would have nothing to revalidate.
                # `no-cache` is the one that means "keep it, and ask before reusing it".
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return  # 304 carries no body, by the spec and by the point of it
            self.send_response(code)
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_response(code)
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # The preflight alone is not enough: without this on the real answer a browser refuses to
        # let the page read it, which looks exactly like the server being down. Only for an
        # allow-listed origin, and echoed from the list rather than from the request.
        origin = (self.headers.get("Origin") or "").strip()
        if origin and origin in _allowed_origins():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self, ceiling: int = httpkit.MAX_BODY) -> dict:
        # Chunked bodies are not decoded by http.server, so Content-Length is
        # absent and the ceiling below would be trivially bypassable. The page
        # never sends chunked; refusing is safer than reading an unbounded body.
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            raise RequestRefused(411, "chunked bodies are not accepted")
        raw = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw)
        except ValueError:
            # Attacker-controlled: int() used to raise inside the handler and
            # surface as a 500 rather than a 400.
            raise RequestRefused(400, "malformed Content-Length") from None
        if length < 0:
            raise RequestRefused(400, "malformed Content-Length")
        if length > ceiling:
            # Refused without reading, which deliberately breaks the
            # read-before-refuse rule documented in _dispatch. That rule exists
            # so the page reliably sees a 401; it does not need to hold for a
            # client announcing four gigabytes, and honouring it there is the
            # denial of service. Do not "fix" this back.
            raise RequestRefused(413, f"body larger than {ceiling} bytes")
        if not length:
            return {}
        try:
            parsed = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}
        # A body that is valid JSON but not an object ([], 123, "x", null) would
        # make the handler's body.get(...) raise AttributeError and surface as a
        # 500. Treat it as no fields, the same as an empty body.
        return parsed if isinstance(parsed, dict) else {}

    def _presented(self) -> str:
        """The credential a client sent, from either spelling.

        `Authorization: Bearer` is what a second client will reach for; `X-Corp-Token` is what the
        shipped page has always sent and stays an alias for a version. Bearer wins when both are
        present, because a client that sets it meant it.
        """
        auth = (self.headers.get("Authorization") or "").strip()
        if auth[:7].lower() == "bearer ":
            return auth[7:].strip()
        return (self.headers.get("X-Corp-Token") or "").strip()

    def _device(self):
        """The paired device this request is, or None.

        Costs one indexed lookup and one SHA-256 — the id travels in the clear inside the
        credential precisely so it does not cost one hash per paired device. See
        `kernel/tokens.py` for why the hash is SHA-256 and not scrypt; the short version is that
        87 ms and 16 MiB per attempt would be a denial-of-service lever protecting 256 bits of
        entropy that need no protecting.
        """
        client_id, secret = tokens.split(self._presented())
        if not client_id:
            return None
        row = self.state.store().client(client_id)
        if row is None or row["revoked"]:
            return None
        if not tokens.verify(secret, row["salt"], row["token_hash"]):
            return None
        return row

    def _from_loopback(self) -> bool:
        """Whether the peer is on this machine. The address, not a header — a header is whatever
        the caller says it is, and this decides whether an unauthenticated write is allowed."""
        return (self.client_address[0] if self.client_address else "") in httpkit.LOOPBACK

    def _authorized(self, device=None) -> bool:
        """Either credential opens the door; a device also has to be in scope.

        Order matters and reads as the sentence it is: a valid device is authorised whatever
        `CORP_UI_TOKEN` says, because it was paired deliberately and the shared token is the
        bootstrap secret rather than the authority.
        """
        if device is not None:
            return True
        token = cfg.get("CORP_UI_TOKEN", "").strip()
        if not token:
            return True  # no token configured: the zero-config local default
        supplied = self._presented()
        # compare_digest wants two byte strings and raises on non-ASCII str.
        return hmac.compare_digest(token.encode("utf-8"), supplied.encode("utf-8", "replace"))

    def _in_scope(self, device, method: str) -> bool:
        """Two scopes, derived from the method exactly as `mutating` is.

        `read` may GET; `act` may do both. Ten scopes would be a permission system nobody gets
        right, and this product already has one of those for what an *agent* may do — what a
        *device* may do is look, or also act.
        """
        if device is None:
            return True  # the shared token has no scope, and never had one
        return method == "GET" or device["scopes"] == clients_store.ACT

    def _host_allowed(self) -> bool:
        """Reject a request whose Host is not one this console answers to.

        This is the DNS-rebinding defence, and it is a different check from the
        Origin one below. If evil.com rebinds its A record to 127.0.0.1, the
        browser treats the request as same-origin and sends a matching Origin,
        so the Origin check passes. What does not match is the console's own
        identity: the request still arrives with Host: evil.com.
        """
        host = httpkit.host_only(self.headers.get("Host") or "")
        allowed = {
            h.strip().lower() for h in cfg.get("CORP_UI_ALLOWED_HOSTS", "").split(",") if h.strip()
        }
        if allowed:
            return host in allowed
        bind = state.fresh_settings().ui_host
        if bind not in httpkit.LOOPBACK:
            # Bound off-loopback means Docker or a reverse proxy, where the
            # operator's real hostname is unknown to us. A strict default would
            # break every existing deployment on upgrade, so permit and let
            # CORP_UI_ALLOWED_HOSTS narrow it. doctor already fails this case
            # when no token is set.
            return True
        return host in httpkit.LOOPBACK or not host

    def _same_origin(self, device=None) -> bool:
        """Reject a cross-site write.

        Three tiers, in order. Both headers are on the browser's forbidden list,
        so a page on evil.com cannot set or spoof either one.

        1. Sec-Fetch-Site, which current browsers always send. `none` is a
           bookmark or the address bar; `same-origin` is our own page.
        2. Origin, compared against the Host we were reached on.
        3. Neither present: not a browser. Allowed **only from loopback, or with a paired
           device** — and that tightening is the point of this stage.

           It used to be allowed outright, and that was a reasonable local compromise: it is what
           keeps curl, the CI smoke job, the test suite's HTTPConnection and the MCP server
           working with no configuration, and the token check still applies to them
           independently. But a native app sends neither header either, so the moment a second
           client is a real thing, this tier stops being "not a browser, therefore local" and
           becomes the door a remote write comes through. Loopback is checked on the peer
           address, which the caller cannot set; a device is checked on its credential.

        4. An allow-listed origin, for a front-end dev server. `CORP_UI_ALLOWED_ORIGINS` is an
           explicit list — never `*`, and never reflected back from `Origin`, which would be the
           same thing spelled to look careful.

        Tier 1 is also what blocks a plain <form> POST from a malicious page -
        the classic no-JS CSRF - without a CSRF token, a cookie, or a login
        screen, which the console deliberately refuses to be.
        """
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if site:
            return site in ("same-origin", "none")
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return self._from_loopback() or device is not None
        parsed = urlparse(origin)
        if not parsed.netloc:
            return False  # "null" origin: a sandboxed iframe or a file:// page
        if parsed.netloc.lower() == (self.headers.get("Host") or "").strip().lower():
            return True
        return origin in _allowed_origins()

    def _drain_body(self) -> None:
        """Read the announced body so a refusal reaches the client instead of a reset.

        The rule is stated a few lines below, for the 401: "closing the connection on an unread
        body makes the client see a reset instead of our 401". The Host check did not honour it,
        and that made `test_rebinding_is_blocked_on_writes_too` fail about once in two thousand
        runs — the 403 is written, then the connection closes over an unread body, and that is an
        RST which can take the response with it. A security refusal the client sometimes does not
        receive is the worst kind of intermittent.

        Bounded by the default ceiling and deliberately not honoured above it: a client announcing
        four gigabytes gets the reset, which is the same trade `_json_body` documents at 413.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if 0 < length <= httpkit.MAX_BODY:
            self.rfile.read(length)

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        lang = ""
        try:
            # Host first, on every request including GET: it costs nothing and
            # a rebound name should not reach a handler at all.
            if not self._host_allowed():
                log.warning(
                    "refused Host %r (set CORP_UI_ALLOWED_HOSTS to allow it)",
                    self.headers.get("Host"),
                )
                self._drain_body()
                self._refuse(
                    403,
                    contracts.FORBIDDEN,
                    "Host not allowed. If you reach this console through a proxy or another "
                    "name, list it in CORP_UI_ALLOWED_HOSTS (comma separated) and restart.",
                    setting="CORP_UI_ALLOWED_HOSTS",
                )
                return
            # POST carries its parameters in the body; GET has none to read. The
            # body is read before auth is decided, even when we are about to
            # refuse: closing the connection on an unread body makes the client
            # see a reset instead of our 401, and the page needs the 401 to know
            # it should ask for a token.
            # The route is matched before the body is read, because the ceiling
            # the body is measured against belongs to the route. Matching touches
            # nothing but the method and the path, so this does not weaken the
            # read-before-refuse rule below: an unmatched path still has its body
            # read at the default ceiling before it gets its 404.
            route = match(method, url.path)
            ceiling = route.max_body if route is not None else httpkit.MAX_BODY
            body = self._json_body(ceiling) if method == "POST" else {}
            source = body if method == "POST" else query
            lang = str(source.get("lang", ""))
            slug = str(source.get("company", ""))
            if route is None or (route.needs_slug and not slug):
                self._refuse(404, contracts.NOT_FOUND, "not found", path=url.path)
                return
            # Writes must come from our own page. Reads are exempt: they carry
            # no side effect, and a cross-site reader cannot see the response
            # anyway without CORS, which is never granted.
            device = self._device()
            if method == "POST" and not self._same_origin(device):
                log.warning(
                    "refused cross-site POST %s from Origin %r",
                    url.path,
                    self.headers.get("Origin"),
                )
                self._refuse(403, contracts.FORBIDDEN, "cross-site request refused")
                return
            # One check, both verbs, driven by the route's own `public` flag.
            # This used to run in do_POST only, which left every read endpoint
            # open even when the operator had configured a token.
            if not route.public and not self._authorized(device):
                self._refuse(
                    401,
                    contracts.UNAUTHENTICATED,
                    "missing or wrong credential (Authorization: Bearer, or X-Corp-Token)",
                )
                return
            if not self._in_scope(device, method):
                # A `read` device asking to act. Distinct from a 401 on purpose: the credential is
                # good and the answer is still no, so a client must not respond by re-pairing.
                self._refuse(
                    403,
                    contracts.FORBIDDEN,
                    f"this device is paired for {clients_store.READ} only",
                    scope=device["scopes"],
                )
                return
            if device is not None:
                self.state.store().touch_client(device["id"])
            ctx = Ctx(
                state=self.state,
                path=url.path,
                query=query,
                body=body,
                slug=slug,
                lang=lang,
                # The one header a handler is given, and it is given because a client on a bad
                # connection has no other way to say "this is the request I already sent".
                idempotency_key=(self.headers.get("Idempotency-Key") or "").strip()[:200],
            )
            self._send(*route.handler(ctx))
        except RequestRefused as refused:
            # Raised from body parsing: a chunked body, a malformed Content-Length, or one over
            # the route's ceiling. `too_large` is the one a client acts on differently — it
            # shrinks what it sends rather than retrying the same thing.
            #
            # Written out rather than a ternary on purpose. The first version computed the code
            # into a variable and `tests/test_error_envelope.py` reported both words as never
            # sent, because a code the AST cannot see is a code nobody can grep for either.
            if refused.status == 413:
                self._refuse(413, contracts.TOO_LARGE, refused.message)
            else:
                self._refuse(refused.status, contracts.INVALID, refused.message)
        except Exception:
            log.exception("%s %s failed", method, self.path)
            # The detail stays in the server log. An internal error's particulars are the one
            # thing a response must not carry: they are ours, not the caller's.
            self._refuse(500, contracts.INTERNAL, oops(lang))

    def do_OPTIONS(self) -> None:  # noqa: N802 (stdlib naming)
        """The preflight a browser sends before a cross-origin write.

        Needed because a front-end dev server is a different origin from the console it talks to,
        which is stage 9's whole arrangement. Answered **only** for an origin on the list: an
        unlisted one gets a 403 and no CORS headers at all, rather than a 200 that says nothing —
        a client that cannot tell "not allowed" from "allowed but silent" retries forever.
        """
        origin = (self.headers.get("Origin") or "").strip()
        if origin and origin in _allowed_origins():
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization, X-Corp-Token, Idempotency-Key, If-None-Match",
            )
            # No `Access-Control-Allow-Credentials`: there are no cookies here, and granting it
            # would invite a browser to attach ambient authority to a cross-origin write.
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
            self.end_headers()
            return
        self._refuse(403, contracts.FORBIDDEN, "origin not allowed", origin=origin)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")


def build_server(
    settings: Settings,
    host: str | None = None,
    port: int | None = None,
    env_file: Path | None = None,
) -> ThreadingHTTPServer:
    path = env_file or ROOT / ".env"
    cfg.set_dotenv_path(path)  # the console and the resolver must agree on it
    ui = UiState(settings, path)
    # A job left `running` by a process that is gone becomes `interrupted`, here, before anything
    # can ask. Not resumed: "it stopped, start it again" is honest, and picking it up silently
    # would claim the ticks it did not run and the day boundary it never banked. The comparison is
    # on a per-process token rather than the PID, because a reused PID would make a dead run look
    # live forever — see `store/jobs.py`.
    orphans = ui.store().interrupt_orphans()
    if orphans:
        log.info("marked %d job(s) interrupted: %s", len(orphans), ", ".join(orphans))
    handler = type("BoundHandler", (Handler,), {"state": ui})
    return ThreadingHTTPServer(
        (host or settings.ui_host, settings.ui_port if port is None else port), handler
    )


def port_in_use(host: str, port: int) -> bool:
    """Probe before binding. allow_reuse_address lets a second bind quietly
    succeed on some platforms (Windows especially), so checking the bind result
    is not reliable; a connection that answers is."""
    import socket

    probe = "127.0.0.1" if host in ("", "0.0.0.0") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        try:
            return s.connect_ex((probe, port)) == 0
        except OSError:
            return False


def serve(settings: Settings, host: str | None = None, port: int | None = None) -> int:
    from .. import plugins

    plugins.load()  # no-op unless CORP_PLUGINS_ENABLED; extends the registries
    want = settings.ui_port if port is None else port
    host = host or settings.ui_host
    if port_in_use(host, want):
        print(
            f"corparius: port {want} is already in use. Another console may be "
            f"running (open http://127.0.0.1:{want}), or pick a free port: "
            f"python -m corparius.cli ui --port 8601  (or set CORP_UI_PORT)."
        )
        return 1
    try:
        server = build_server(settings, host, port)
    except OSError as exc:
        print(f"corparius: could not start the console on {host}:{want}: {exc}")
        return 1
    bound = server.socket.getsockname()
    log.info("operator console on http://%s:%d (Ctrl+C to stop)", bound[0], bound[1])
    print(f"corparius console: http://{bound[0]}:{bound[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    finally:
        drain_and_close(server.RequestHandlerClass.state)  # type: ignore[attr-defined]  # injected in build_server
    return 0


def drain_and_close(ui: UiState, join_timeout: float = 5.0) -> None:
    """Stop any in-flight run, let it unwind, then close the store.

    A --loop run checks should_stop() at the top of each tick but still banks the
    day with a save_state() afterwards, so closing the connection out from under
    it would make that final write hit a closed database. Signal every run, join
    the daemon workers briefly, then close - the connection outlives the request
    that opened it, and on Windows nothing can move or delete the store while it
    is open."""
    for run in list(ui.runs.values()):
        ev = run.get("stop")
        if ev is not None:
            ev.set()
    for t in threading.enumerate():
        if t.name.startswith("corparius-run-"):
            t.join(timeout=join_timeout)
    # **And every program a company wrote.** These are real processes, started by corparius and
    # holding loopback ports; a console that exits leaving them behind is one an operator has to hunt
    # for in a task manager, and the port they hold is the one the next launch needs. After the runs
    # join, so a tick that was mid-request against its own app is not shot from under it.
    from ..providers import apprunner

    stopped = apprunner.stop_all()
    if stopped:
        log.info("stopped %d company program(s) on the way out", stopped)
    ui.close()
