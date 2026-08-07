"""What a service raises when the caller asked for something that cannot be done. Rank 5.

One exception, and its whole job is to *not* be a status code. A service that raises the
console's 400 can only be called by the console — which is the fact `app/` exists to change, so
this is the type that lets a refusal cross the boundary without carrying HTTP with it.

The pattern is not new here. `kernel/dotenv.merge` raises `LineBreakRefused` and
`webui._merge_env_file` turns it into a 400; `kernel/proc` raises `ProcError` where a caller
might have expected a `CalledProcessError`. This is the same move one rank up, and
`tests/test_app_layer.py` is what keeps it from being optional.

The message is written for a person, in one sentence, because both callers show it to one: the
console puts it in an error envelope and a terminal prints it.
"""

from __future__ import annotations


class Refused(ValueError):
    """The request was understood and cannot be honoured. The message says why.

    `ValueError` rather than a bare `Exception` so that a caller which forgets to handle it
    still fails in a way its own tests will catch, and so `except ValueError` at a boundary
    keeps meaning what it meant.
    """
