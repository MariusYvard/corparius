"""Making a company over v1, which had the read and not the write.

The defect was visible from the outside and nowhere else: the new console's header rendered a
`<select>` of the slugs that already existed, and beside it nothing. **There was no way to create a
company from the console at all** — the answer to "start a second one" was the terminal or the old
single-file page.

And the interesting part is where it was missing. Every layer under the route existed and had for a
long time: `app.companies.create`, `adapters.create_company`, and even a handler (`companies_post`)
wired to the legacy path. What was absent was one line of route table for the v1 spelling the new
console speaks, plus the button. Reachable and never reached, once again, and the shape has a
signature by now: the service tests all passed, because they call the service.

So this file goes through the route. It builds a real server and talks HTTP to it, because a test
that imported the handler would have passed on the broken build too.
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
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=20)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        # `Sec-Fetch-Site` because this is a write and the server refuses cross-site POSTs. A test
        # that omitted it would be testing the CSRF guard rather than the route.
        {"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"},
    )
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, json.loads(raw or b"{}")


def test_the_route_exists_at_all(server):
    """The whole bug, in one assertion. Before the route was declared this answered 404, which is
    indistinguishable from a typo in the path and is what the console would have gotten."""
    status, body = _call(
        server,
        "POST",
        "/api/v1/companies",
        {"name": "Atelier Nord", "product": "Quarterly compliance audits"},
    )
    assert status == 200, f"{status}: {body}"
    assert body["ok"] is True and body["slug"] == "atelier-nord"


def test_what_was_made_is_in_the_list_the_console_reads_next(server):
    """Both verbs on one resource, in the order the console uses them. The create answers with the
    new list itself so the header can switch to the new company without a second round trip, and
    that list has to agree with what a fresh read says."""
    _, made = _call(
        server, "POST", "/api/v1/companies", {"name": "Atelier Nord", "product": "Audits"}
    )
    _, listed = _call(server, "GET", "/api/v1/companies")
    assert made["companies"] == listed["companies"]
    assert "atelier-nord" in listed["companies"] and "example" in listed["companies"]


def test_the_offer_is_required_and_the_refusal_says_which_field(server):
    """Found by running the console rather than by reading it: the dialog asked for a name and a
    one-liner, posted, and was refused with `offer.product is required` — a field the operator had
    never been shown. The form asks for it now, and the refusal stays useful for any other client."""
    status, body = _call(server, "POST", "/api/v1/companies", {"name": "Nameless Ltd"})
    assert status == 400
    assert body["ok"] is False and "product" in body["error"]


def test_the_same_name_twice_is_refused_rather_than_overwriting(server):
    """A company folder is where the operator's work lives. Creating over one would be the most
    expensive destructive act in the product, arrived at by typing a name that already exists."""
    _call(server, "POST", "/api/v1/companies", {"name": "Atelier Nord", "product": "Audits"})
    status, body = _call(
        server, "POST", "/api/v1/companies", {"name": "Atelier Nord", "product": "Autre chose"}
    )
    assert status == 400 and "already exists" in body["error"]


def test_the_language_travels_with_it(server):
    """A company created from the French console writes French. The charter, the site copy and every
    agent prompt read that field, so leaving it out would make the operator's own language something
    they have to go and find afterwards."""
    from corparius import company as company_mod

    _, made = _call(
        server,
        "POST",
        "/api/v1/companies",
        {"name": "Atelier Nord", "product": "Audits trimestriels", "lang": "fr"},
    )
    written = company_mod.path_for(made["slug"]).read_text(encoding="utf-8")
    assert "Audits trimestriels" in written


def test_a_creation_is_not_slug_scoped(server):
    """It is the call that *returns* a slug, so requiring one would be a chicken and an egg. Stated
    as a test because `needs_slug` is one keyword away and every neighbouring write has it."""
    from corparius.api import routes

    route = next(r for r in routes.ROUTES if r.method == "POST" and r.path == "/api/v1/companies")
    assert route.needs_slug is False


# --- settling a diverged repository from the console -------------------------------


def test_the_resolve_endpoint_refuses_a_company_with_no_repository(server):
    """The common case for a company that was never versioned, and it has to be a refusal with a
    sentence rather than a 500: the console offers this button off an inbox notice, and a notice can
    outlive the repository it was written about."""
    status, body = _call(
        server, "POST", "/api/v1/repo/resolve", {"company": "example", "keep": "mine"}
    )
    assert status == 400
    assert body["ok"] is False and "repository" in body["error"]


def test_an_unknown_choice_is_refused_at_the_route(server):
    """This argument decides which version of a file survives and it arrives from a browser. A value
    the core does not understand must not fall through to a default."""
    status, body = _call(
        server, "POST", "/api/v1/repo/resolve", {"company": "example", "keep": "whatever"}
    )
    assert status == 400 and "whatever" in body["error"]


def test_settling_it_also_closes_the_notice_that_asked(server, monkeypatch):
    """The last step, and leaving it undone would be the thing being fixed: a product that settles
    the divergence and leaves "the company repository is behind" on screen has asked the operator to
    tidy up by hand.

    The id is derived from the title on both sides — `inbox.item_id` keys on it — so this also holds
    the two spellings together. A notice filed by yesterday's run in another process is found by
    today's endpoint without anything carrying an id between them.
    """
    from corparius import inbox
    from corparius.api import state
    from corparius.providers import companyrepo

    store = state.UiState(state.fresh_settings(), None).store()
    store.add_inbox("example", "system", inbox.NOTIFICATION, inbox.REPO_BEHIND, "", (), "repo")
    assert [i["title"] for i in store.list_inbox("example", "pending")] == [inbox.REPO_BEHIND]

    monkeypatch.setattr(companyrepo, "resolve", lambda slug, keep: {"ok": True, "pushed": True})
    status, _ = _call(
        server, "POST", "/api/v1/repo/resolve", {"company": "example", "keep": "mine"}
    )
    assert status == 200
    assert store.list_inbox("example", "pending") == [], "the notice outlived the problem"
