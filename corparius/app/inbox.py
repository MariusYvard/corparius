"""Answering a question the company asked. Rank 5.

Two store calls, and three surfaces had a copy of them: the console handler, the terminal's
`corparius inbox`, and the MCP host's `answer_inbox`. All three happened to agree — this one was
caught before it drifted rather than after — and that is the whole argument for the service. The
approvals version of the same shape did **not** agree, and the console was the surface that had
quietly stopped releasing the work parked on the answer.

**First responder wins.** A second answer to a decided item is refused rather than overwriting one
the waiting work has already moved on from. That distinction has a code now: `conflict`, not
`not_found` — a client told "already answered" refreshes its list, where one told "no such item"
would conclude something quite different about its own state.

**Answering releases.** An operator supplied what was missing, so the task that was parked on the
question goes back in the queue rather than being closed: `release_waiting_tasks` reads the answer
back through the task's own note, which is why the two calls belong together and neither caller
should have to remember the second.
"""

from __future__ import annotations


def answer(store, item_id: str, text: str = "", slug: str = "") -> dict:
    """Resolve one inbox item and put back what was waiting on it.

    `answered=False` means the item was already decided or never existed, and nothing else is
    attempted — releasing on a failed answer would unblock work on a question nobody answered.

    `slug` is optional because the item carries no company in every caller's hands: the console
    knows it from the request, a terminal from `--company`. Without one the answer still lands and
    the release is skipped, which is honest — the run loop releases on its next tick anyway.
    """
    answered = bool(store.resolve_inbox(item_id, text))
    freed = (
        store.release_waiting_tasks(slug) if answered and slug else {"released": 0, "refused": 0}
    )
    return {
        "answered": answered,
        "released": int(freed.get("released", 0)),
        "refused": int(freed.get("refused", 0)),
    }
