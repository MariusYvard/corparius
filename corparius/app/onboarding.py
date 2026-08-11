"""The three steps between an empty install and a company working on its own. Rank 5.

A guided thread rather than a tour: each step reflects real state and ticks itself off, and the card
removes itself when all three are done. A blank powerful tool becomes a path.

This lived in the shipped page's JavaScript, which is why it was the last Overview card with no
resource behind it. Moving it here is not tidying — the logic contains three judgements a second client
would otherwise have to reimplement and could get wrong:

**Staying in mock is a finished choice, not an unfinished one.** Step one is satisfied by a real
provider *or* by having run once, because running once means the operator either wired a model or
accepted the mock deliberately. Treating mock as incomplete would nag someone who has already decided.

**The company doing its own work is not the human deciding.** Step three asks whether the *operator*
has answered anything, so a completed task must never tick it off. The page had this right and kept the
answer in `localStorage`, which lost it on a new browser and hid it from a phone entirely.
`store.decided_approvals` is the durable version: `set_approval_status` has exactly two callers and both
are the operator — one pressing the button, one asking the CEO to in the chat.

**Only one step leads at a time.** `lead` is the single next thing to do, so a client renders one call
to action instead of three competing ones. Derived here rather than in a client, because "which of these
is next" is the whole content of an onboarding thread and two clients answering it differently would be
two different products.

Dismissing the card stays a client-side preference and does **not** appear here. It is per-browser by
choice: the card retires itself once the three are done, so the worst a new browser costs is seeing a
thread that is nearly finished. A settings row for it would be a schema change to remember a shrug.
"""

from __future__ import annotations

# The step keys, in order. They are the `ob.*` i18n prefixes too — `ob.model`, `ob.modelHint`,
# `ob.modelCta` — so a client renders each one from its key without a table of its own.
STEPS = ("model", "run", "decide")

# What a client should do for each, in its own vocabulary: a tab to open, or an action to take. `run`
# is an action rather than a tab because the whole step is one button, and sending an operator to a tab
# to find it would be a step with two steps in it.
ACTIONS = {"model": {"tab": "providers"}, "run": {"act": "run"}, "decide": {"tab": "operations"}}


def steps(store, settings, slug: str, run: dict | None = None) -> list[dict]:
    """The three steps, each with whether it is done and whether it is the one to do next.

    `run` is the run view the caller already has — passed in rather than fetched, so this does not need
    to know how a caller learns about runs, and so a console holding an in-flight run in memory and a
    terminal reading the job row give the same answer.
    """
    status = store.status(slug)
    last = (run or {}).get("result") or {}
    # A run that ended in an error is not a run the operator watched work. Counting it would tick the
    # step off on the strength of a failure, which is the opposite of the reassurance it exists to give.
    ran_once = int(status.get("actions", 0)) > 0 or bool(last and not last.get("error"))
    done = {
        "model": (not settings.llm_mock) or ran_once,
        "run": ran_once,
        "decide": store.decided_approvals(slug) > 0,
    }
    out = []
    leading = True
    for key in STEPS:
        # The first unfinished step leads and the rest wait. Computed by walking in order rather than
        # by three conditions naming each other, which is how the page expressed it and how a fourth
        # step would have got the sequence wrong.
        lead = leading and not done[key]
        if lead:
            leading = False
        out.append({"key": key, "done": done[key], "lead": lead, **ACTIONS[key]})
    return out


def finished(rows: list[dict]) -> bool:
    """Whether the card should retire itself.

    A function rather than a field on the payload, because it is a property *of* the three steps and a
    client that computed it differently from this would keep showing a finished thread.
    """
    return all(row["done"] for row in rows)
