"""The two shapes the transport is made of. Rank 6.

`Ctx` is one request normalised — a handler is not told whether its parameters arrived in a
query string or a JSON body — and `Route` is one row of the table. Both are data, on purpose:
`Route.handler` is a function in a tuple, not a subclass, which is what makes the table
greppable and what `tests/test_route_table.py` reads.

Kept apart from the table itself so the direction of imports stays a straight line:
`contracts` knows only `state`, `handlers` knows `contracts`, `routes` knows both. A `Route`
defined next to `ROUTES` would have made `handlers` import the table that imports it — the
shape of all five cycles this restructuring removed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..kernel import httpkit
from ..store import Store
from .state import UiState


class RequestRefused(Exception):
    """Refuse a request before any handler sees it, with the status to send.
    Raised from body parsing, where returning a value would mean having already
    read the body we are refusing to read."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Ctx:
    """One request, normalised. GET reads its parameters from the query string
    and POST from the JSON body; handlers should not care which."""

    state: UiState
    path: str
    query: dict
    body: dict
    slug: str
    lang: str

    def store(self) -> Store:
        return self.state.store()


@dataclass(frozen=True)
class Route:
    """One endpoint.

    `public` defaults to False on purpose, and it is the whole point of this
    table. do_GET and do_POST used to be two independent if/elif chains, and the
    token check lived in one of them only - so every read endpoint was open,
    and nothing in the code made that visible. Here the unsafe choice has to be
    typed out, which makes it greppable and reviewable; adding a route without
    thinking about auth yields an authenticated one.

    `mutating` is derived from the method rather than stored: it is exactly
    true for POST in this API, and one fewer field to get wrong.
    """

    method: str
    path: str
    handler: Callable
    public: bool = False
    needs_slug: bool = False  # no company named -> fall through to 404
    # Per-endpoint body ceiling. One endpoint carries a file and the rest carry a
    # handful of fields, so the choice belongs next to the endpoint that needs it
    # rather than raised for everybody — a global ceiling wide enough for a 6 MB
    # PDF is a global ceiling wide enough for a flood through every other route.
    max_body: int = httpkit.MAX_BODY
