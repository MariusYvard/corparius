"""The shapes the transport is made of, including the one a refusal takes. Rank 6.

`Ctx` is one request normalised — a handler is not told whether its parameters arrived in a
query string or a JSON body — and `Route` is one row of the table. Both are data, on purpose:
`Route.handler` is a function in a tuple, not a subclass, which is what makes the table
greppable and what `tests/test_route_table.py` reads.

Kept apart from the table itself so the direction of imports stays a straight line:
`contracts` knows only `state`, `handlers` knows `contracts`, `routes` knows both. A `Route`
defined next to `ROUTES` would have made `handlers` import the table that imports it — the
shape of all five cycles this restructuring removed.

## The error envelope, and why only v1 gets it

Measured across `api/`: **57 payloads carry an `error` key, and all 57 carry a human sentence.**
32 are literals ("no run in progress"), 11 are `str(exc)`, 8 are f-strings. A second client can
do nothing with that but match substrings, which breaks the moment a message is reworded — and
rewording a message for a person is something this project does often and on purpose.

`refuse()` is the v1 answer: `{"ok": false, "error": {"code", "message", "detail"}}`. The code
is for the client, the message is for the person, and `detail` carries the machine-readable
particulars (which company, which key, how many bytes) instead of them being welded into prose.

**The 54 legacy routes keep the flat string, and that is a decision rather than laziness.** The
shipped page reads `data.error` as a string in fourteen places — `throw new Error(data.error ||
…)` — so an object there renders as "[object Object]" on exactly the failures an operator most
needs to read. Rebuilding that page is stage 9. A shape that differs by version is what
versioning *is*, and `tests/test_api_version.py` already declares which set a path is in.

The vocabulary is small and closed on purpose: a client switches on it, so it is a fixed set of
words rather than a growing list of sentences. `tests/test_error_envelope.py` holds both ends —
every code emitted is declared, and every code declared is emitted somewhere.

The second half earned its place immediately. The first version of this list also had `refused`
(for `app.errors.Refused`) and `conflict` ("a run is already in progress"), and the test reported
both as never sent — correctly: no v1 route takes a POST yet, so there is nothing for either word
to describe. They were a vocabulary written for imagined routes. They go in when a route sends
them, which is the only moment at which a client could act on them anyway.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..kernel import httpkit
from ..store import Store
from .state import UiState

# What a refusal can be. Eight words, each answering "what should the client do now".
UNKNOWN_COMPANY = "unknown_company"  # the slug names nothing here; not a typo the client can fix
NOT_FOUND = "not_found"  # the path, or the id in it, does not exist
INVALID = "invalid"  # the request was understood and is wrong; `detail` says which field
UNAUTHENTICATED = "unauthenticated"  # no token or the wrong one
FORBIDDEN = "forbidden"  # a token that is not enough, or a request from somewhere not allowed
TOO_LARGE = "too_large"  # over the route's ceiling, refused before the body was read
INTERNAL = "internal"  # a bug here; the detail is in the server log and not in the response

CODES = frozenset(
    {
        UNKNOWN_COMPANY,
        NOT_FOUND,
        INVALID,
        UNAUTHENTICATED,
        FORBIDDEN,
        TOO_LARGE,
        INTERNAL,
    }
)


def envelope(code: str, message: str, **detail) -> dict:
    """The v1 refusal body.

    `assert code in CODES` rather than a lookup that quietly passes an unknown word through: a
    typo in a code is a client branch that never runs, which is the silent kind of wrong this
    project keeps finding. The test scans for the codes actually emitted, and this catches the
    case the scanner cannot — a code computed rather than written out.
    """
    assert code in CODES, f"{code!r} is not a declared error code"
    return {"ok": False, "error": {"code": code, "message": message, "detail": detail}}


def refuse(status: int, code: str, message: str, **detail) -> tuple[int, dict]:
    """The same thing a handler can return directly: `(status, body)`.

    Two functions rather than one because the dispatcher has the status already and needs only
    the body — the four checks every request passes before a handler is reached (host, size,
    origin, token) are refusals too, and they must speak the same vocabulary as the handlers or
    a client would need two ways to read one API.
    """
    return status, envelope(code, message, **detail)


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
