"""Every POST the console makes to a route that needs a company names one.

The defect this was written for: **the CEO chat answered "not found" to every message.** Not a
degraded answer, not a slow one, the whole tab was dead, and it shipped.

The mechanism is one asymmetry in the server, and it is a reasonable one:

    GET   the company comes from the query string   /api/v1/chat?company=vigil
    POST  the company comes from the request body   {"company": "vigil", ...}

`CEO.svelte` had the GET right and the POST wrong, sending `{message}` alone. A route marked
`needs_slug` with no slug is refused at `server.py` before any handler runs, so the failure was a
bare 404 with `not_found` and no hint that the *shape* was the problem. Nothing was broken in the
chat code at all, which is why reading it found nothing.

Two ends, as everywhere else in this project. The route table says which POSTs require a company;
the Svelte sources say which POSTs the console makes. Crossing them is a text comparison, and this
file is the only place that does it: the Python tests exercise handlers with well-formed bodies, and
the front-end has no test that speaks to a real route table. That gap is exactly the width of this
bug.

**Static, and deliberately so.** A test that booted the console and clicked would catch this too and
would cost a browser; the mistake here is visible in the source, so it is caught in the source.
"""

import pathlib
import re

import pytest

SRC = pathlib.Path("web/src")
ROUTES = pathlib.Path("corparius/api/routes.py")

# `post("/api/v1/thing", { a, b }, ...)` — the path, and the object literal that follows it. Not a
# JS parser: the console writes these calls one way, and the assertion below fails loudly rather
# than silently skipping if that stops being true.
CALL = re.compile(r"""post\(\s*["'`](?P<path>/api/[^"'`]+)["'`]\s*,\s*(?P<body>\{[^}]*\})""")


def _routes_needing_a_company() -> set[str]:
    text = ROUTES.read_text(encoding="utf-8")
    found = set()
    for line in text.splitlines():
        if "needs_slug=True" not in line or '"POST"' not in line:
            continue
        path = re.search(r'"POST",\s*"([^"]+)"', line)
        if path:
            found.add(path.group(1))
    return found


def _calls() -> list[tuple[str, str, str]]:
    out = []
    for file in sorted(SRC.rglob("*.svelte")):
        source = file.read_text(encoding="utf-8")
        for hit in CALL.finditer(source):
            out.append((file.name, hit.group("path"), hit.group("body")))
    return out


def test_the_two_ends_are_both_findable():
    """Guards the guard. A regex that matched nothing would make every assertion below vacuous, and
    a silently empty both-ends test is worse than no test: it reports green forever."""
    assert SRC.is_dir() and ROUTES.is_file()
    routes = _routes_needing_a_company()
    assert len(routes) >= 8, f"the route table stopped parsing: {sorted(routes)}"
    assert "/api/v1/chat" in routes, "the route this file exists for is not in the parsed set"
    assert len(_calls()) >= 15, "the console's POST calls stopped parsing"


def test_every_post_to_a_company_route_sends_the_company():
    """The rule, over every component. `company` has to be a key of the object literal: the server
    reads `body["company"]` and a slug in the query string of a POST is not read at all."""
    needed = _routes_needing_a_company()
    missing = [
        f"{where}: post({path!r}, {body.strip()})"
        for where, path, body in _calls()
        if path in needed and not re.search(r"\bcompany\b", body)
    ]
    assert not missing, (
        "these POST to a route that requires a company and do not send one, so the server refuses "
        "them with a bare 404 before the handler runs:\n  " + "\n  ".join(missing)
    )


@pytest.mark.parametrize("path", ["/api/v1/chat", "/api/v1/chat/forget"])
def test_the_ceo_chat_in_particular(path):
    """Named as well as covered by the rule above. This is the one that shipped broken, and a
    parametrize that stops matching would otherwise fail silently into the general case."""
    calls = [(w, b) for w, p, b in _calls() if p == path]
    assert calls, f"nothing posts to {path} any more; if the console changed, change this test"
    for where, body in calls:
        assert re.search(r"\bcompany\b", body), f"{where} posts to {path} without a company"


def test_a_get_is_not_held_to_the_same_rule():
    """The other half of the asymmetry, so the rule above is understood rather than cargo-culted. A
    GET carries the company in its query string, which is why `CEO.svelte` looked correct: it was,
    on the read, and the two calls sit four lines apart."""
    ceo = (SRC / "CEO.svelte").read_text(encoding="utf-8")
    assert "get(`/api/v1/chat?${q()}`" in ceo
    assert "company=${encodeURIComponent(company)}" in ceo
