"""Pinning and forgetting what a company learned. Rank 5.

The operator owns their company's memory the way they own its secrets: a wrong thing an agent wrote
down has to be removable without opening the database. Pinning is the other half — the curator
archives a fact that has gone 90 days unused, and a pin is how an operator says this one stays
regardless of the counter.

Three surfaces reach these two store calls, and the third is where the divergence was. Measured:

                        forget   pin   unpin
    console handler       yes    yes    yes
    corparius memory      yes    yes    **no**

`cmd_memory` took `--forget` and `--pin` and stopped there, so a fact pinned by mistake from a
terminal could only be unpinned from the console. Smaller than the approvals one — nobody is blocked
— but it is the same shape, and the shape is what the service is for: one place that knows the
vocabulary, so a surface cannot implement two thirds of it.
"""

from __future__ import annotations

from .errors import Refused

# What an operator can ask of a fact. Closed, and refused by name rather than falling through to a
# no-op: `pin_memroy` arriving as an `action` should be an error a client can see, not silence.
ACTIONS = ("pin", "unpin", "forget")


def decide(store, memory_id: object, action: str) -> dict:
    """Apply one of the three, or refuse and say which part was wrong.

    `object` for the id, like `app.tasks.edit`, and for the same reason: the callers hand this
    whatever a body or an argv carried. Refusing it here is what stops the console and the terminal
    inventing the same message twice.

    `found=False` rather than an exception for a fact that is not there. It is not a bad request —
    the client asked a well-formed question about a row somebody else may have forgotten a moment
    ago — and each surface says so its own way: 404 with `not_found` from the API, one line of
    English from the terminal.
    """
    try:
        ident = int(memory_id)  # type: ignore[call-overload]  # refused below when it is not
    except (TypeError, ValueError) as exc:
        raise Refused("a memory id is required") from exc
    wanted = (action or "").strip()
    if wanted not in ACTIONS:
        raise Refused(f"action must be one of {', '.join(ACTIONS)}")
    if wanted == "forget":
        done = bool(store.forget(ident))
    else:
        done = bool(store.pin_memory(ident, wanted == "pin"))
    return {"found": done, "id": ident, "action": wanted}
