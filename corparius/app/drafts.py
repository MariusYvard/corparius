"""What the social agent wrote, and what an operator does with it. Rank 5.

The drafts exist because they were being written and thrown away: the social agent was the largest
line in one company's spend and left nothing behind. Keeping them was half the fix.

**`published` is the operator's word, not a claim corparius made.** Nothing here posts to a social
channel, and an API a phone will read must not imply otherwise. What the state change actually does
is stop the post counting against the queue, which is what lets the agent resume — and the count
that gates it is `draft` **and** `queued` together, which is why `queued` travels back with the
answer rather than being recomputed by each caller.

Here as a service rather than inline in a handler because the same three lines were written twice —
once per version of the endpoint — and `tests/test_api_version.py` requires the two spellings of an
endpoint to be one operation offered twice rather than two implementations. A `corparius drafts`
command is the obvious third caller and does not exist yet; this is the seam it will use.
"""

from __future__ import annotations

from .errors import Refused

# Three words, and `queued` is in the list because putting one back is a real thing an operator asks
# for: it was marked published by mistake, and the agent's queue has to see it again.
STATES = ("published", "discarded", "queued")


def set_state(store, draft_id: object, state: str) -> dict:
    """Move one draft, or refuse and say which field was wrong.

    `found=False` for an id that is not there, rather than an exception: a stale list is not a
    malformed request, and the two deserve different answers from a client's point of view — one
    refreshes, the other fixes what it sent.
    """
    try:
        ident = int(draft_id)  # type: ignore[call-overload]  # refused below when it is not
    except (TypeError, ValueError) as exc:
        raise Refused("a draft id is required") from exc
    wanted = (state or "").strip()
    if wanted not in STATES:
        raise Refused(f"state must be one of {', '.join(STATES)}")
    return {"found": bool(store.set_draft_state(ident, wanted)), "id": ident, "state": wanted}
