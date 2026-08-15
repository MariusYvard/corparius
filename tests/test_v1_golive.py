"""Going live: the checkout link, the mail account, the public address — and the site itself.

The five endpoints that finish the Overview tab, and one rule that shapes them: **`payments` must not
be polled.** With `STRIPE_API_KEY` set it lists charges over HTTPS on the operator's own account and
rate limit. The shipped page has this right — `loadPayments()` is in its boot sequence and its
five-second interval calls `refresh()` alone — and a test here holds the rebuilt one to the same thing,
because "we know not to" is not a mechanism.

`deploy` is the pair the **second** live divergence of this restructuring was about: the console
honoured `paths.owned_site(slug)` and `cmd_deploy` always built the generated path, so on the owner's
own company the two published different directories and both reported success.
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

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
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
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=30)
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


# --- go live ----------------------------------------------------------------------


def test_the_three_gates_are_reported_as_booleans_plus_the_url(server):
    """One card has to walk an operator from a company that simulates to one that can take money, so
    each of the three says whether it is wired and the hosting one says where."""
    status, data = _call(server, "GET", "/api/v1/golive?company=example")
    assert status == 200
    assert set(data) >= {"payment", "mail", "hosting"}
    assert data["payment"]["wired"] is False and data["payment"]["link"] == ""
    assert data["mail"]["wired"] is False
    # `published` and `published_url` are two facts, not one. A `local:` deploy is a real publish
    # with no address to click, and the roster waits on the first while a person uses the second —
    # see `corparius/readiness.py`, which both this card and the scheduler now read.
    assert data["hosting"] == {"token_set": False, "published": False, "published_url": ""}


def test_hosting_has_three_states_and_not_two(server, tmp_path):
    """Not hosted, a token set with nothing published, and live at a URL. Collapsing the middle one
    would tell an operator who has done half the work that they have done none of it.

    **`published_url`, not `url`** — the field name matters because reading the wrong one is silent: the
    live address simply never appears and the card says "token set, not published yet" forever. My
    first version of the Overview card read `.url`.
    """
    from corparius.config import cfg
    from corparius.kernel import paths

    monkeypatch_url = "https://example-co.netlify.app"
    marker = paths.site_dir(str(tmp_path / "data"), "example") / ".published"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"netlify:{monkeypatch_url}", encoding="utf-8")
    cfg.invalidate()
    _status, data = _call(server, "GET", "/api/v1/golive?company=example")
    assert data["hosting"]["published_url"] == monkeypatch_url
    assert "url" not in data["hosting"], "one name for it, or a client reads the wrong one"


def test_a_payment_link_from_the_company_wires_the_gate(server, tmp_path):
    """The company's own offer wins over the bootstrap setting: a link in `company.yaml` is a decision
    about that company, and a global one is a default."""
    import yaml

    path = tmp_path / "home" / "companies" / "example" / "company.yaml"
    company = yaml.safe_load(path.read_text(encoding="utf-8"))
    company.setdefault("offer", {})["payment_link"] = "https://buy.stripe.com/test"
    path.write_text(yaml.safe_dump(company, allow_unicode=True), encoding="utf-8")
    _status, data = _call(server, "GET", "/api/v1/golive?company=example")
    assert data["payment"]["wired"] is True
    assert data["payment"]["link"] == "https://buy.stripe.com/test"


def test_an_unknown_company_is_refused_by_code(server):
    for path in ("/api/v1/golive?company=nope", "/api/v1/site?company=nope"):
        status, data = _call(server, "GET", path)
        assert status == 404, (path, data)
        assert data["error"]["code"] == "unknown_company"


# --- the site ---------------------------------------------------------------------


def test_the_site_read_says_it_is_not_built_yet(server):
    status, data = _call(server, "GET", "/api/v1/site?company=example")
    assert status == 200
    assert data["built"] is False and data["mtime"] is None
    assert data["owned"] is False and data["pages"] == []


def test_building_the_site_makes_the_read_true(server):
    status, built = _call(server, "POST", "/api/v1/site", {"company": "example"})
    assert status == 200 and built["built"] is True
    _status, data = _call(server, "GET", "/api/v1/site?company=example")
    assert data["built"] is True and data["mtime"]


def test_an_empty_headline_means_let_the_agent_write_one(server):
    """`headline or None`, not the empty string. Passing "" through as a headline would replace a
    written line with nothing, which is a different request from having no preference."""
    import inspect

    from corparius.api import handlers

    source = inspect.getsource(handlers.v1_site_post)
    assert "headline or None" in source
    status, _ = _call(server, "POST", "/api/v1/site", {"company": "example", "headline": "   "})
    assert status == 200


def test_the_read_says_which_site_it_is_showing(server):
    """`owned` exists because the console once previewed the generated path while `cmd_deploy`
    published the owned one, and both reported success. Reporting which of the two is on screen is what
    stops a preview being silently a different page from the one that goes out."""
    _status, data = _call(server, "GET", "/api/v1/site?company=example")
    assert "owned" in data, "a client cannot tell which folder it is looking at otherwise"


# --- publishing -------------------------------------------------------------------


def test_publishing_with_no_provider_says_so_rather_than_failing(server):
    """The envelope succeeded; whether anything published is the payload's news. Three answers a client
    must keep apart: a provider published, every provider failed, or none is configured."""
    status, data = _call(server, "POST", "/api/v1/site", {"company": "example"})
    assert status == 200
    status, data = _call(server, "POST", "/api/v1/deploy", {"company": "example"})
    assert status == 200, data
    # The local provider is always available, so something always publishes — which is exactly why the
    # settings help says anything ordered after it never runs.
    assert set(data) >= {"provider", "published"}
    assert "folder" not in data, "the server's own path is not a client's business"


def test_the_publish_answer_has_no_url_field(server):
    """Stated because I assumed one. `app_publish.publish` answers `published`, `provider`, `skipped`
    and `errors` — a client that rendered `done.url` would show nothing and look broken."""
    _call(server, "POST", "/api/v1/site", {"company": "example"})
    _status, data = _call(server, "POST", "/api/v1/deploy", {"company": "example"})
    assert "url" not in data


# --- payments, and the rule about them --------------------------------------------


def test_payments_answers_a_mock_when_there_is_no_key(server):
    """An empty card could mean "no sales" or "not configured", and those need different actions. The
    mock says which, and `source` is how a client knows not to read samples as revenue."""
    status, data = _call(server, "GET", "/api/v1/payments")
    assert status == 200
    assert data["source"] == "mock"
    assert data["payments"] and data["total_paid"] > 0


def test_the_source_vocabulary_is_the_one_the_client_branches_on():
    """`stripe`, `mock`, `error` — and never `live`, which was my invention when writing the card. A
    client testing `source !== "live"` would have labelled real charges as samples."""
    import pathlib
    import re

    source = pathlib.Path("corparius/providers/integrations.py").read_text(encoding="utf-8")
    values = set(re.findall(r'"source":\s*"(\w+)"', source))
    assert values == {"stripe", "mock", "error"}, values
    # The **comparison**, not the bare string: the first version of this failed on the comment that
    # explains the mistake, which is a scanner too crude to tell code from prose about code.
    card = pathlib.Path("web/src/Overview.svelte").read_text(encoding="utf-8")
    for compared in re.findall(r'payments\.source\s*[!=]==\s*"(\w+)"', card):
        assert compared in values, (
            f"the card branches on source == {compared!r}, which cannot happen"
        )


def test_the_payments_read_is_never_on_the_interval():
    """The rule, as a mechanism rather than a habit.

    With a Stripe key set this endpoint calls `api.stripe.com`. `/api/providers` opening a socket on
    every refresh is why "never a network probe from a polled endpoint" is written down at all, and a
    Stripe key has the operator's money attached rather than a rate limit alone.

    Held by reading the component: the path may appear in `loadOnce`, which runs on arrival and after a
    write, and nowhere inside `refresh`, which is what the interval calls.
    """
    import pathlib

    card = pathlib.Path("web/src/Overview.svelte").read_text(encoding="utf-8")
    assert "/api/v1/payments" in card, "the scan would be vacuous if the card did not fetch it"

    start = card.index("async function refresh(")
    end = card.index("async function loadOnce(")
    polled = card[start:end]
    assert "/api/v1/payments" not in polled, (
        "the Stripe read is inside the polled function. It calls api.stripe.com with the operator's "
        "key: load it on arrival, never on the interval."
    )
    # And the interval calls `refresh`, not `loadOnce` — otherwise the split above proves nothing.
    assert "setInterval(() => refresh(), POLL_MS)" in card


def test_the_golive_and_site_reads_open_no_socket(tmp_path, monkeypatch):
    """These two *may* sit beside a polled resource, and this is why: config, two settings and a
    `.published` marker. Asserted rather than assumed, because the difference between them and
    `payments` is the whole reason the cadences differ."""
    import socket

    from corparius.api import adapters
    from corparius.config import cfg
    from corparius.kernel import paths

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()

    def refuse(*a, **k):
        raise AssertionError("a golive or site read opened a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    try:
        status = adapters.golive_status("example")
        assert set(status) >= {"payment", "mail", "hosting"}
        assert paths.site_index(str(tmp_path / "data"), "example").is_file() is False
    finally:
        monkeypatch.undo()
