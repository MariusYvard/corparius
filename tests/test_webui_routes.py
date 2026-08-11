"""The route table exists to make one class of bug impossible rather than fixed.

do_GET and do_POST used to be two independent if/elif chains, and the token
check lived in one of them only. Nothing in the code made that visible, and
nothing failed when it drifted. These tests are what replaces "someone will
notice": the set of endpoints reachable without a token is written down, and
changing it fails here.
"""

import pytest

from corparius.api import contracts, routes

# Every route that answers without a token. Adding to this list is a decision
# about what the console exposes, so it has to be made here, in a diff a
# reviewer reads, rather than as a side effect of adding an endpoint.
PUBLIC = {
    ("GET", "/"),  # the console shell, built or shipped; carries no operator data
    ("GET", "/legacy"),  # the same shipped page, at a path of its own now that `/` is the new one
    ("GET", "/api/session"),  # how the page learns a token is required
    # For the same reason as `/api/session`, one step earlier: a second client has to learn
    # what it is talking to before it can authenticate to it — and refuse a core too old for
    # it rather than failing one authenticated request at a time. It names no secret, no
    # company and no setting *value*; `capabilities` is booleans about configuration.
    ("GET", "/api/v1/meta"),
    ("GET", "/site/"),  # the generated site, rendered in an iframe
    # The built console, public for the same reason `/` is: it carries no operator data, and it has
    # to load before it can ask for a token. Every request it then makes is authenticated normally,
    # and the directory it serves from holds nothing but what `npm run build` put there.
    ("GET", "/app/"),
}


def _all_routes():
    return list(routes.ROUTES) + list(routes.PREFIX_ROUTES)


def test_public_routes_are_exactly_the_declared_set():
    actual = {(r.method, r.path) for r in _all_routes() if r.public}
    assert actual == PUBLIC


def test_routes_default_to_authenticated():
    """The inversion that makes the table worth having: `public` defaults to
    False, so forgetting to think about auth yields the safe answer."""
    from dataclasses import fields

    default = {f.name: f.default for f in fields(contracts.Route)}["public"]
    assert default is False


def test_no_duplicate_routes():
    seen = [(r.method, r.path) for r in routes.ROUTES]
    assert len(seen) == len(set(seen))


def test_every_route_has_a_callable_handler():
    for route in _all_routes():
        assert callable(route.handler), f"{route.method} {route.path} has no handler"


def test_methods_are_get_or_post():
    assert {r.method for r in _all_routes()} == {"GET", "POST"}


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/api/site", "site_get"),  # exact wins
        ("GET", "/site/acme/", "site_serve"),  # prefix only after exact misses
        ("GET", "/site/", "site_serve"),
        ("POST", "/api/site", "site_post"),
    ],
)
def test_exact_routes_are_never_shadowed_by_a_prefix(method, path, expected):
    """/site/ is the only non-exact match in the table. If prefixes were checked
    first, or in the same pass, /api/site would be ambiguous."""
    route = routes.match(method, path)
    assert route is not None and route.handler.__name__ == expected


def test_unknown_paths_and_methods_do_not_match():
    assert routes.match("GET", "/api/nope") is None
    assert routes.match("POST", "/") is None  # the page is GET-only
    assert routes.match("GET", "/api/run") is None  # runs are POST-only


def test_mutating_routes_are_exactly_the_post_routes():
    """`mutating` is derived from the method rather than stored. This pins that
    the API really does keep every write behind POST, which is what makes that
    derivation safe."""
    assert not any(
        r.method == "GET"
        for r in _all_routes()
        if not r.public and r.path.endswith(("/delete", "/stop", "/pull", "/setup"))
    )
