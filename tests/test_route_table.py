"""Both ends of the route table — the last registry in the project without them.

`tests/test_registries.py` exists because nine bugs in this project had one shape: something
produced and never consumed, or reachable and never reached. The route table had neither end
checked. A handler that fell out of the table is 40 lines nothing can call and nothing says so;
a table row naming a function that is gone is an AttributeError on whichever request first tries
it, in production, on a path a test may not cover.

**There are two tables**, and that is the finding this file came out of. `ROUTES` is matched
exactly and `PREFIX_ROUTES` after it, so `/api/site` can never be shadowed by a prefix that
starts the same way — a real reason for two. But anything *auditing* the surface has to see
both, and one thing did not: `test_webui_security`'s "every non-public route demands a token"
iterated `ROUTES` alone. A non-public prefix route would have sat outside a guard that reads as
exhaustive. `webui.ALL_ROUTES` is now the name for the whole surface, and that check uses it.

Written against `webui` because that is where the table is today. When stage 6 finishes and it
becomes `api/`, these assertions move with it — they read the module, not a path, so a move
cannot silently make them read nothing. Three tests in this suite were doing the latter and the
last move broke all three.
"""

import ast
import collections
import inspect
from pathlib import Path

import pytest

from corparius import webui

SOURCE = Path("corparius/webui.py")


def _defined() -> set[str]:
    """Every `_route_*` function in the module, from the AST."""
    return {
        node.name
        for node in ast.parse(SOURCE.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_route")
    }


def _reached() -> set[str]:
    return {route.handler.__name__ for route in webui.ALL_ROUTES}


# --- the guard on the guard -----------------------------------------------------


def test_there_is_a_table_to_check():
    """An empty scan would make everything below vacuously true, which is the failure this
    file exists to catch one level down."""
    assert len(webui.ALL_ROUTES) >= 50, f"only {len(webui.ALL_ROUTES)} routes found"
    assert len(_defined()) >= 50, "the handler scan found almost nothing"


def test_the_canonical_table_is_the_two_tables():
    """`ALL_ROUTES` exists so nothing has to remember there are two. If a third appears and is
    not folded in, this is where that shows."""
    assert set(webui.ALL_ROUTES) == set(webui.ROUTES) | set(webui.PREFIX_ROUTES)
    assert len(webui.ALL_ROUTES) == len(webui.ROUTES) + len(webui.PREFIX_ROUTES)


# --- both ends ------------------------------------------------------------------


def test_every_handler_is_reachable_through_the_table():
    """A handler that fell out of the table is code nothing can call, and nothing says so. It
    is the same defect as `documents.images()` having no caller for two releases, and as
    `ask_operator` sitting in TOOLS with no path."""
    orphans = sorted(_defined() - _reached())
    assert not orphans, (
        f"these handlers are defined and no route reaches them: {orphans}. Add a route, or "
        "delete the handler — an unreachable one reads as a feature to the next person."
    )


def test_every_row_names_a_handler_that_exists():
    """The mirror. A row pointing at a function that is gone is an AttributeError on the first
    request that takes that path, which is not where anyone wants to find out."""
    ghosts = sorted(_reached() - _defined())
    assert not ghosts, f"the table names handlers that are not defined here: {ghosts}"


def test_no_two_routes_answer_to_the_same_method_and_path():
    """A duplicate is not two routes: `_EXACT` is a dict, so the second silently replaces the
    first, and the handler that loses is unreachable while still looking wired."""
    keys = [(r.method, r.path) for r in webui.ALL_ROUTES]
    dupes = sorted(k for k, n in collections.Counter(keys).items() if n > 1)
    assert not dupes, f"these (method, path) pairs are declared twice: {dupes}"


def test_no_prefix_route_shadows_an_exact_one():
    """The reason there are two tables. `_match` checks exact first, so this cannot currently
    happen — and stating it is what keeps a future reordering from making it possible."""
    exact = {(r.method, r.path) for r in webui.ROUTES}
    for prefix in webui.PREFIX_ROUTES:
        shadowed = sorted(p for m, p in exact if m == prefix.method and p.startswith(prefix.path))
        assert not shadowed, (
            f"the prefix route {prefix.path} covers exact routes {shadowed}; matching order is "
            "the only thing keeping them reachable"
        )


# --- what a handler is ----------------------------------------------------------


@pytest.mark.parametrize("route", sorted(webui.ALL_ROUTES, key=lambda r: (r.method, r.path)))
def test_every_handler_takes_the_request(route):
    """The inverse of the `app/` rule, and both together are what make the split real: a
    service must **not** take a request (`tests/test_app_layer.py`), and a route handler must.
    A handler that takes no `ctx` cannot read a body, a query or a header, so it is a service
    that has been left in the transport."""
    params = list(inspect.signature(route.handler).parameters)
    assert params and params[0] == "ctx", (
        f"{route.handler.__name__} takes {params or 'nothing'}; a route handler receives the "
        "request"
    )


@pytest.mark.parametrize("route", sorted(webui.ALL_ROUTES, key=lambda r: (r.method, r.path)))
def test_no_route_declares_a_company_it_never_reads(route):
    """A dead flag reads as a feature to the next person who greps for it.

    `needs_slug` makes `_dispatch` resolve the company and fall through to 404 when none is
    named. A route declaring it whose handler never touches `ctx.slug` is asking for a
    resolution nothing uses — the same shape as `sees_images` on a tool that calls no model,
    which `tests/test_images.py` guards for the same reason.

    **The other direction is deliberately not asserted here**, and this is the audit so nobody
    repeats it. Eight handlers read `ctx.slug` without declaring `needs_slug`, and every one of
    them is guarded — either the value only ever becomes a SQL parameter (`_route_chat_post`
    down to `store.status(slug)`, where a bogus slug returns empty rows) or the guard is one
    call away (`_route_company_delete` -> `_delete_company`, which starts with
    `slug not in _companies()`; `_route_deploy_post` -> `_deploy` -> `_load_company`). Checking
    that statically means following the call graph, and a version that stopped at the handler
    body would report all eight — a detector that cries wolf is a detector nobody keeps.
    """
    if not route.needs_slug:
        return
    assert "ctx.slug" in inspect.getsource(route.handler), (
        f"{route.handler.__name__}'s route declares needs_slug and the handler never reads "
        "ctx.slug, so the resolution it forces is spent on nothing"
    )
