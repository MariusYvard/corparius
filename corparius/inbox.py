"""Everything that needs a human, other than an approval.

Approvals answer "may I do this". They are the whole of the human gate today,
and they leave two things with nowhere to go.

An agent that lacks a fact cannot ask for it. Outreach with no mailbox
configured, a deploy with no provider, a reconciliation with no Stripe key: each
of those dead-ends inside a tool, returns a line to the action log and is never
seen again. The company keeps running as if nothing had happened, which is the
same failure as inventing an answer, one layer down.

And a session that freezes itself has no way to say so. A circuit-breaker trip
or an unreachable model writes one row to the action log; unless the operator
thinks to read it, a company can sit dead for a day.

So: two more kinds beside the approval. A **question** blocks the work that
raised it, exactly as an approval does — same `pending` result, same parked
task — and unblocks it when answered. A **notification** blocks nothing and is
there to be seen.

Identity is a hash of what is being asked, not a fresh id per attempt, so a
re-run of the same tick finds the question it already asked instead of asking
twice. Modelled on OpenWorker's inbox.py, whose (session, tool_call_id) key
serves the same purpose; see docs/reverse-engineering/openworker.md.
"""

from __future__ import annotations

import hashlib
import logging

log = logging.getLogger("corparius.inbox")

QUESTION = "question"
NOTIFICATION = "notification"
KINDS = (QUESTION, NOTIFICATION)

PENDING, RESOLVED = "pending", "resolved"


def item_id(company: str, kind: str, agent: str, title: str) -> str:
    """Deterministic, so the same question asked again *is* the same question.

    Deliberately not keyed on the body: a question's wording may be regenerated
    while the thing being asked is unchanged, and an operator who has already
    answered "which mailbox?" should not be asked it again because a sentence
    came out differently.
    """
    raw = f"{company}|{kind}|{agent}|{title}"
    return f"{kind[:4]}-" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def ask(ctx, title: str, body: str = "", options=()) -> str:
    """File a question and return its id, or "" when there is no store to file
    it in. Callable from a tool's effect: the tool then returns a pending
    ToolResult carrying the id, and the executor parks the work exactly as it
    parks work waiting on an approval."""
    store = getattr(ctx, "store", None)
    if store is None:
        return ""
    slug = ctx.company.get("slug", "company")
    agent = getattr(ctx, "role", "") or "system"
    answered = store.resolved_inbox(slug, QUESTION, title)
    if answered:
        # Already answered. The caller reads the answer through
        # `answer_to`; re-filing would ask a decided question again.
        return ""
    return store.add_inbox(slug, agent, QUESTION, title, body, options)


def answer_to(ctx, title: str) -> str:
    """The operator's answer to a question with this title, or "" if it has not
    been answered. This is how a tool picks up, on a later turn, what it was
    blocked on — the polled equivalent of OpenWorker's reconcile_on_resume."""
    store = getattr(ctx, "store", None)
    if store is None:
        return ""
    row = store.resolved_inbox(ctx.company.get("slug", "company"), QUESTION, title)
    return str(row["resolution"]) if row else ""


def notify(store, company: str, agent: str, title: str, body: str = "") -> str:
    """Something the operator should see, blocking nothing. Idempotent on the
    title, so a breaker that trips on three consecutive days leaves one live
    notice rather than a wall of them."""
    if store is None:
        return ""
    return store.add_inbox(company, agent, NOTIFICATION, title, body, ())
