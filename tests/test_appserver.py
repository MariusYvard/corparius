"""The endpoint that lets a company's site call the company's models.

Everything worth testing here is a refusal. The feature is one POST; what makes
it safe to expose is what it declines to do, and each of those declines is a way
someone else could otherwise spend the operator's subscription.

The console's own tests already cover the console. The one thing this file
insists on is that the two servers stay apart: a request for a console route
must find nothing here.
"""

import json
import threading
import time
from http.client import HTTPConnection

import pytest
import yaml

from corparius import appserver
from corparius.models import LLMResult, Usage

KEY = "test-key-not-a-secret"


def _call(server, method, path, body=None, headers=None):
    """Returns (status, json, response-headers).

    The headers are copied out rather than the response object returned: a
    caller reading `resp.getheader(...)` after `conn.close()` kept the socket
    reachable, and on Windows the collector then raised an unclosed-socket
    ResourceWarning inside whichever test happened to be running. With
    `filterwarnings = ["error"]` that fails a test that did nothing wrong.
    """
    conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    payload = json.dumps(body) if body is not None else None
    head = {"Content-Type": "application/json", **(headers or {})}
    try:
        conn.request(method, path, body=payload, headers=head)
        resp = conn.getresponse()
        raw = resp.read()
        status, got = resp.status, dict(resp.getheaders())
    finally:
        conn.close()
    try:
        return status, json.loads(raw or b"{}"), got
    except json.JSONDecodeError:
        return status, {}, got


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """CORP_HOME is what companies/ hangs off, and the hermetic fixture pins
    only CORP_DATA_PATH."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    company = tmp_path / "companies" / "t"
    (company / "apps").mkdir(parents=True)
    (company / "company.yaml").write_text(
        "slug: t\nname: T\noffer: {product: p, price_eur: 9}\n"
        "icp: {segment: s, channels: [linkedin], pains: [p]}\n",
        encoding="utf-8",
    )
    return tmp_path


def _app(home, **over):
    body = {
        "name": "faq",
        "system": "Answer questions.",
        "tier": "trivial",
        "daily_tokens": 20000,
        "rate_per_minute": 6,
        "origins": ["https://site.test"],
        **over,
    }
    path = home / "companies" / "t" / "apps" / f"{body['name']}.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return body


@pytest.fixture()
def server(home, monkeypatch):
    monkeypatch.setenv("CORP_APP_KEY_T_FAQ", KEY)
    from corparius import cfg

    cfg.invalidate()
    # A fresh limiter per test: it is process-global by design, and one test's
    # requests must not spend another's allowance.
    monkeypatch.setattr(appserver, "_limiter", appserver.RateLimiter())
    srv = appserver.build_server(host="127.0.0.1", port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    store = getattr(srv.RequestHandlerClass, "store", None)
    if store is not None:
        store.close()
    srv.server_close()


@pytest.fixture(autouse=True)
def model(monkeypatch):
    class _R:
        def __init__(self, settings):
            pass

        def generate(self, messages, difficulty=None, model=None, max_tokens=512):
            return LLMResult(text="answered", usage=Usage(10, 5, 0.0), model="m", provider="p")

    monkeypatch.setattr("corparius.llm.HybridRouter", _R)


_DEFAULT = object()  # not None: `None` is itself a body worth testing


def _post(server, body=_DEFAULT, **headers):
    head = {"X-Corp-App-Key": KEY, **headers}
    payload = {"input": "hi"} if body is _DEFAULT else body
    return _call(server, "POST", "/v1/apps/t/faq", payload, head)


# --- it works -------------------------------------------------------------


def test_a_valid_call_answers(server, home):
    _app(home)
    status, data, _ = _post(server)
    assert status == 200 and data == {"ok": True, "text": "answered"}


def test_the_answer_carries_nothing_the_operator_owns(server, home):
    """The caller is a web page. Which provider served it, which model, and what
    it cost are the operator's business and stay in the console."""
    _app(home)
    _, data, _ = _post(server)
    assert set(data) == {"ok", "text"}


def test_the_spend_lands_under_the_apps_name(server, home):
    from corparius.store import Store

    _app(home)
    _post(server)
    rows = Store(str(home / "data")).spend_by_agent("t")
    assert [r["agent"] for r in rows] == ["app:faq"]


# --- guard 1: rate --------------------------------------------------------


def test_the_rate_limit_refuses_past_the_apps_own_number(server, home):
    _app(home, rate_per_minute=2)
    assert _post(server)[0] == 200
    assert _post(server)[0] == 200
    status, data, _ = _post(server)
    assert status == 429 and "2/minute" in data["error"]


def test_the_rate_limit_is_a_sliding_minute():
    """Not a fixed bucket: a fixed one lets twice the allowance through across
    a boundary."""
    limiter = appserver.RateLimiter()
    now = 1000.0
    assert limiter.allow(("a", "ip"), 2, now) and limiter.allow(("a", "ip"), 2, now + 1)
    assert not limiter.allow(("a", "ip"), 2, now + 30)
    assert limiter.allow(("a", "ip"), 2, now + 61)


def test_one_caller_does_not_spend_anothers_allowance():
    limiter = appserver.RateLimiter()
    assert limiter.allow(("a", "1.1.1.1"), 1) and not limiter.allow(("a", "1.1.1.1"), 1)
    assert limiter.allow(("a", "2.2.2.2"), 1)


def test_one_app_does_not_spend_anothers_allowance():
    limiter = appserver.RateLimiter()
    assert limiter.allow(("faq", "ip"), 1) and not limiter.allow(("faq", "ip"), 1)
    assert limiter.allow(("other", "ip"), 1)


def test_idle_buckets_are_forgotten():
    """A long run must not accumulate one entry per IP that ever called."""
    limiter = appserver.RateLimiter()
    limiter.allow(("a", "ip"), 5, time.time() - 7200)
    limiter.forget(older_than=3600)
    assert limiter._hits == {}


def test_the_rate_limit_runs_before_the_database_is_touched(server, home, monkeypatch):
    """It is the only guard that costs nothing, and the only one that protects
    the others from running at all. A ceiling read ahead of it would turn a
    flood into a database round-trip per request."""
    from corparius import apps as apps_mod

    _app(home, rate_per_minute=1)
    assert _post(server)[0] == 200

    def explode(*a, **k):
        raise AssertionError("the ceiling was read for a rate-limited request")

    monkeypatch.setattr(apps_mod, "spent_today", explode)
    assert _post(server)[0] == 429


# --- guard 2: origin ------------------------------------------------------


def test_an_origin_off_the_list_is_refused(server, home):
    _app(home)
    status, data, _ = _post(server, Origin="https://evil.test")
    assert status == 403 and "origin" in data["error"]


def test_a_listed_origin_is_answered_and_echoed_back(server, home):
    _app(home)
    status, _, resp = _post(server, Origin="https://site.test")
    assert status == 200
    assert resp.get("Access-Control-Allow-Origin") == "https://site.test"
    assert resp.get("Vary") == "Origin"


def test_an_empty_origin_list_allows_no_browser_at_all(server, home):
    """Not "everyone". A default of "any page may call this" is how an endpoint
    ends up embedded in a site its owner never heard of."""
    _app(home, origins=[])
    assert _post(server, Origin="https://site.test")[0] == 403


def test_a_caller_that_sends_no_origin_is_not_a_browser(server, home):
    """curl and the site's own server-side code send none. They are still held
    by the rate limit, the key and the daily ceiling."""
    _app(home, origins=[])
    assert _post(server)[0] == 200


def test_the_preflight_answers_for_a_listed_origin(server, home):
    _app(home)
    status, _, resp = _call(
        server, "OPTIONS", "/v1/apps/t/faq", None, {"Origin": "https://site.test"}
    )
    assert status == 204
    assert resp.get("Access-Control-Allow-Origin") == "https://site.test"
    assert "X-Corp-App-Key" in resp.get("Access-Control-Allow-Headers", "")


def test_the_preflight_refuses_an_unlisted_origin(server, home):
    _app(home)
    status, _, _ = _call(server, "OPTIONS", "/v1/apps/t/faq", None, {"Origin": "https://evil.test"})
    assert status == 403


# --- guard 3: key ---------------------------------------------------------


def test_a_wrong_key_is_refused(server, home):
    _app(home)
    status, data, _ = _call(
        server, "POST", "/v1/apps/t/faq", {"input": "hi"}, {"X-Corp-App-Key": "nope"}
    )
    assert status == 401 and "key" in data["error"]


def test_a_missing_key_is_refused(server, home):
    _app(home)
    assert _call(server, "POST", "/v1/apps/t/faq", {"input": "hi"})[0] == 401


def test_an_app_with_no_key_configured_cannot_be_called(server, home, monkeypatch):
    """Absent must not read as "no key needed"."""
    from corparius import cfg

    monkeypatch.delenv("CORP_APP_KEY_T_FAQ", raising=False)
    cfg.invalidate()
    _app(home)
    assert (
        _call(server, "POST", "/v1/apps/t/faq", {"input": "hi"}, {"X-Corp-App-Key": ""})[0] == 401
    )


def test_the_key_variable_is_per_app():
    """One leaked key is revoked without touching the others."""
    assert appserver.key_env("t", "faq") == "CORP_APP_KEY_T_FAQ"
    assert appserver.key_env("my-co", "lead-form") == "CORP_APP_KEY_MY_CO_LEAD_FORM"


# --- guard 4: the day's ceiling -------------------------------------------


def test_the_daily_ceiling_refuses_before_calling_a_model(server, home, monkeypatch):
    from corparius import apps as apps_mod
    from corparius.store import Store

    _app(home, daily_tokens=100)
    Store(str(home / "data")).record_usage("t", "app:faq", 90, 20)

    def explode(*a, **k):
        raise AssertionError("a model was called past the ceiling")

    monkeypatch.setattr(apps_mod, "run", explode)
    status, data, _ = _post(server)
    assert status == 429 and "110/100" in data["error"]


# --- what this server is not ----------------------------------------------


def test_the_console_is_not_reachable_here(server, home):
    """Two servers, deliberately. If a console route answered on this port,
    publishing the endpoint would publish the control plane."""
    _app(home)
    for path in ("/api/settings", "/api/companies", "/", "/api/session", "/site/t"):
        assert _call(server, "GET", path)[0] == 404, path


def test_an_unknown_company_or_app_is_a_flat_404(server, home):
    _app(home)
    assert _post(server)[0] == 200
    for path in ("/v1/apps/nope/faq", "/v1/apps/t/nope", "/v1/apps/t", "/v1/apps/t/faq/extra"):
        assert _call(server, "POST", path, {"input": "hi"}, {"X-Corp-App-Key": KEY})[0] == 404, path


def test_health_answers_without_a_key(server, home):
    status, data, _ = _call(server, "GET", "/v1/health")
    assert status == 200 and data["ok"] is True


# --- the body -------------------------------------------------------------


def test_an_empty_input_is_a_400_not_a_call(server, home):
    _app(home)
    assert _post(server, {"input": "   "})[0] == 400
    assert _post(server, {})[0] == 400


def test_a_non_object_body_is_not_a_500(server, home):
    """Valid JSON that is not an object: [] or 123 or null."""
    _app(home)
    for body in ([], 123, None, "text"):
        assert _post(server, body)[0] == 400


def test_a_model_that_cannot_be_reached_is_a_503_not_a_traceback(server, home, monkeypatch):
    import requests

    class _Down:
        def __init__(self, settings):
            pass

        def generate(self, *a, **k):
            raise requests.ConnectionError("refused")

    monkeypatch.setattr("corparius.llm.HybridRouter", _Down)
    _app(home)
    status, data, _ = _post(server)
    assert status == 503 and data["ok"] is False


def test_a_refused_request_still_spends_its_rate_allowance(server, home):
    """The limiter runs first, so a wrong key costs the caller a slot. If it did
    not, guessing keys would be free — which is the one thing a rate limit on an
    unauthenticated endpoint is for."""
    _app(home, rate_per_minute=2)
    assert (
        _call(server, "POST", "/v1/apps/t/faq", {"input": "hi"}, {"X-Corp-App-Key": "no"})[0] == 401
    )
    assert _post(server)[0] == 200
    assert _post(server)[0] == 429
