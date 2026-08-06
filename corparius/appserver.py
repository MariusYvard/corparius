"""The apps endpoint: a company's own applications calling its own providers.

A second server, deliberately not the console. The console is the operator's
control plane — settings, keys, approvals, the whole company — and it binds to
127.0.0.1 behind a token. This one exists to be called by something else, so
putting the two in one process would mean one slipped check exposing both.

What is reused rather than re-derived is the part that was hard to get right:
`host_only` (bracket-aware IPv6 parsing, from a real bug), `LOOPBACK` and
`MAX_BODY` — now from `kernel/httpkit`, not from webui. Reusing them was always
correct; reaching into the *console* to get them was what made this module and
that one a cycle.

Four guards, cheapest first, before any model is called:

  1. rate limit, per (app, caller) and in memory
  2. origin, when the app lists any
  3. key, compared with hmac.compare_digest
  4. the day's token ceiling, read from token_usage

That order is not the one a checklist suggests. The daily ceiling is a SQLite
read, so putting it ahead of the rate limit would let a flood do a database
round-trip per request — the limiter has to be the first thing a request meets.

Off unless CORP_APPS_ENABLED, and bound to 127.0.0.1 unless told otherwise:
publishing it is a tunnel or a reverse proxy the operator sets up knowing what
it is. See docs/apps.md.
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import apps as apps_mod
from .apps import key_env
from .config import cfg
from .config.settings import Settings
from .kernel import paths
from .kernel.httpkit import MAX_BODY, host_only

log = logging.getLogger("corparius.appserver")

DEFAULT_PORT = 8610


class RateLimiter:
    """Requests per minute, per (app, caller). In memory on purpose.

    A counter in SQLite would mean a write per request, which turns a flood
    into disk pressure — the limiter would become the thing it is defending
    against. Losing the counts on restart is the right trade: the daily ceiling
    survives restarts, and it is the one that guards the money.
    """

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, bucket: tuple[str, str], per_minute: int, now: float | None = None) -> bool:
        stamp = time.time() if now is None else now
        with self._lock:
            hits = self._hits[bucket]
            while hits and stamp - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= per_minute:
                return False
            hits.append(stamp)
            return True

    def forget(self, older_than: float = 3600) -> None:
        """Drop buckets nobody has used, so a long run does not accumulate one
        entry per IP that ever called."""
        cutoff = time.time() - older_than
        with self._lock:
            for bucket in [b for b, h in self._hits.items() if not h or h[-1] < cutoff]:
                del self._hits[bucket]


_limiter = RateLimiter()


def _companies() -> set[str]:
    base = paths.companies_dir()
    return {p.parent.name for p in base.glob("*/company.yaml")} if base.is_dir() else set()


def _company(slug: str) -> dict | None:
    from . import company as company_mod

    try:
        return company_mod.load(paths.companies_dir() / slug / "company.yaml")
    except (FileNotFoundError, ValueError):
        return None


def _origin_allowed(origin: str, app) -> bool:
    """Is this browser origin on the app's list?

    An empty list allows nothing, rather than everything. A default of "any
    page may call this" is how an endpoint ends up embedded in a site its owner
    never heard of.

    This restrains browsers and only browsers: CORS is enforced by the browser,
    not by us, so curl ignores it entirely. What holds against a non-browser is
    the rate limit and the daily ceiling, which apply to every caller.
    """
    if not origin:
        return True  # not a browser; the other three guards still apply
    return origin.strip().rstrip("/").lower() in {
        o.strip().rstrip("/").lower() for o in app.origins
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "corparius-apps"
    store = None  # injected by build_server

    def log_message(self, fmt, *args):
        log.debug("%s " + fmt, self.address_string(), *args)

    # --- plumbing ---------------------------------------------------------
    def _send(self, status: int, payload: dict, origin: str = "") -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        """DNS-rebinding defence, the same one the console makes, for the same
        reason: bound to loopback, a request whose Host is someone else's name
        did not mean to reach this machine."""
        settings = Settings()
        bind = cfg.get("CORP_APPS_HOST", settings.ui_host or "127.0.0.1")
        if bind not in ("127.0.0.1", "localhost", "::1"):
            return True  # published on purpose; the proxy owns the Host header
        return host_only(self.headers.get("Host") or "") in ("127.0.0.1", "localhost", "::1", "")

    def _route(self) -> tuple[str, str] | None:
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "v1" and parts[1] == "apps":
            return parts[2], parts[3]
        return None

    # --- verbs ------------------------------------------------------------
    def do_GET(self) -> None:
        if urlparse(self.path).path == "/v1/health":
            self._send(200, {"ok": True, "service": "corparius-apps"})
            return
        # Nothing else is served here. The console's routes live in the console.
        self._send(404, {"ok": False, "error": "not found"})

    def do_OPTIONS(self) -> None:
        target = self._route()
        origin = (self.headers.get("Origin") or "").strip()
        app = apps_mod.get(*target) if target else None
        if app is None or not _origin_allowed(origin, app):
            self._send(403, {"ok": False, "error": "origin not allowed"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Corp-App-Key")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_POST(self) -> None:
        if not self._host_ok():
            self._send(403, {"ok": False, "error": "host not allowed"})
            return
        target = self._route()
        if target is None:
            self._send(404, {"ok": False, "error": "not found"})
            return
        slug, name = target
        if slug not in _companies():
            self._send(404, {"ok": False, "error": "not found"})
            return
        app = apps_mod.get(slug, name)
        if app is None:
            self._send(404, {"ok": False, "error": "not found"})
            return

        origin = (self.headers.get("Origin") or "").strip()
        caller = self.client_address[0] if self.client_address else "?"

        # 1. Rate. First, because it is the only guard that costs nothing and
        #    the only one that protects the others from being run at all.
        if not _limiter.allow((f"{slug}/{name}", caller), app.rate_per_minute):
            self._send(429, {"ok": False, "error": f"rate limit: {app.rate_per_minute}/minute"})
            return
        # 2. Origin, for browsers.
        if not _origin_allowed(origin, app):
            self._send(403, {"ok": False, "error": "origin not allowed"})
            return
        # 3. Key.
        expected = cfg.get(key_env(slug, name), "").strip()
        given = (self.headers.get("X-Corp-App-Key") or "").strip()
        if not expected or not hmac.compare_digest(expected, given):
            self._send(401, {"ok": False, "error": "unknown app key"}, origin)
            return
        # 4. The day's ceiling, last: it is a database read.
        spent = apps_mod.spent_today(self.store, slug, app)
        if spent >= app.daily_tokens:
            self._send(
                429,
                {"ok": False, "error": f"daily ceiling reached: {spent}/{app.daily_tokens} tokens"},
                origin,
            )
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._send(413, {"ok": False, "error": "body too large"}, origin)
            return
        try:
            parsed = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            parsed = {}
        body = parsed if isinstance(parsed, dict) else {}
        user_input = str(body.get("input") or "").strip()
        if not user_input:
            self._send(400, {"ok": False, "error": "empty input"}, origin)
            return

        result = apps_mod.run(app, slug, self.store, user_input[:MAX_BODY], _company(slug))
        # The caller is a web page. It learns whether it worked and what was
        # said; the provider, the model and the cost are the operator's
        # business and stay in the console.
        if not result["ok"]:
            self._send(503, {"ok": False, "error": result["error"]}, origin)
            return
        self._send(200, {"ok": True, "text": result["text"]}, origin)


def build_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    from .store import Store

    settings = Settings()
    bind = host or cfg.get("CORP_APPS_HOST", "127.0.0.1")
    where = port or cfg.get_int("CORP_APPS_PORT", DEFAULT_PORT)
    handler = type("BoundHandler", (Handler,), {"store": Store(settings.data_path)})
    return ThreadingHTTPServer((bind, where), handler)


def serve(host: str | None = None, port: int | None = None) -> int:
    server = build_server(host, port)
    # From the socket, not from the setting: with port 0 the kernel picks, and
    # printing the requested value would name a port nothing is listening on.
    bind, where = str(server.server_address[0]), server.server_address[1]
    log.info("apps endpoint on http://%s:%s", bind, where)
    print(f"apps endpoint on http://{bind}:{where}  (POST /v1/apps/<company>/<app>)")
    if bind in ("127.0.0.1", "localhost", "::1"):
        print("Local only. To publish it, put a tunnel or a reverse proxy in front —")
        print("see docs/apps.md. Opening the bind address instead skips every check")
        print("a proxy would give you.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    finally:
        store = getattr(server.RequestHandlerClass, "store", None)
        if store is not None:
            store.close()
    return 0
