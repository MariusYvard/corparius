"""What the operator should do next, and where. Rank 5.

The CEO tab could answer questions and could not answer *the* question. An operator who does not know
what to do has nothing to type, and "ask the agent that holds the plan" is only useful to somebody who
already knows what to ask it. So this computes the answer from real state and, crucially, says **where
each answer lives** — a step an operator can press rather than a sentence they have to act on.

Three decisions this module exists to hold.

**Derived, never generated.** A model asked "what should I do?" will produce a plausible list, and a
plausible list is the worst possible answer here: it can name a tab that does not apply, or miss the
two approvals actually holding the company up. Every step below is a fact about the store or the
settings. The CEO's prose is free to explain them — `chat` is given this list so its answer agrees
with the buttons under it — but the buttons come from here.

**Ordered by what blocks the company, not by what is easiest.** Money and outbound mail waiting on a
human beat a missing Stripe key, because nothing moves until a person answers and everything else is
merely unfinished. `onboarding.lead` comes first when the install is not done, for the same reason it
leads the Overview card: an operator with no model connected has one useful next move.

**One destination per step, and it must exist.** `tab` values are the console's own tab ids and `act`
is a named action a client already implements. `tests/test_guidance.py` holds both ends: every step
names a real destination, and every rule that can fire has a string in both languages. A step that
sends somebody to a tab that does not exist is worse than no step.
"""

from __future__ import annotations

from . import onboarding

# Every destination a step may name. `tab` is a console tab id; `act` is an action the client performs
# in place. Closed on purpose and asserted in tests: a typo here is a button that goes nowhere.
TABS = ("overview", "operations", "documents", "providers", "ceo", "settings", "plugins")
ACTS = ("run",)


def _step(key: str, *, tab: str = "", act: str = "", detail: str = "") -> dict:
    """One thing to do. `key` is also the i18n prefix — `next.<key>` and `next.<key>Why`."""
    return {"key": key, "tab": tab, "act": act, "detail": detail}


def next_steps(
    store,
    settings,
    slug: str,
    run: dict | None = None,
    golive: dict | None = None,
    limit: int = 4,
) -> list[dict]:
    """The operator's next moves, most blocking first.

    Bounded at four. A list of everything that could be better is a backlog, and handing somebody a
    backlog when they asked what to do is the same as handing them nothing — the whole point is to name
    the next move, which is why `onboarding` reduces three steps to one `lead` rather than showing all
    three as equals.
    """
    steps: list[dict] = []

    # The install, while it is unfinished. `onboarding` already decides which of its three leads.
    for row in onboarding.steps(store, settings, slug, run=run):
        if row.get("lead") and not row.get("done"):
            where = onboarding.ACTIONS.get(row["key"], {})
            steps.append(
                _step(f"ob.{row['key']}", tab=where.get("tab", ""), act=where.get("act", ""))
            )
            break

    # Nothing moves while a human is the blocker, so these come before anything merely unfinished.
    waiting = store.list_approvals(slug) if hasattr(store, "list_approvals") else []
    if waiting:
        steps.append(
            _step("approvals", tab="operations", detail=", ".join(r["tool"] for r in waiting[:3]))
        )

    asked = _inbox_open(store, slug)
    if asked:
        steps.append(_step("inbox", tab="operations", detail=str(len(asked))))

    # Written and never sent. The company did the work and it is sitting in a drawer — which is the
    # state an operator is least likely to discover on their own, because nothing is failing.
    drafts = store.list_drafts(slug, state="draft") if hasattr(store, "list_drafts") else []
    if drafts:
        steps.append(_step("drafts", tab="operations", detail=str(len(drafts))))

    # Only once the company is actually running: telling somebody to wire Stripe before they have run a
    # day is answering a question they have not reached.
    if len(steps) < limit and golive and _has_run(store, slug):
        for key, ready in _golive_gaps(golive):
            if not ready:
                steps.append(_step(f"golive.{key}", tab="settings"))
                break

    return steps[:limit]


def _inbox_open(store, slug: str) -> list:
    """Questions an agent asked the operator and nobody answered."""
    if not hasattr(store, "list_inbox"):
        return []
    try:
        return [row for row in store.list_inbox(slug) if row.get("state") == "open"]
    except TypeError:
        # A store double with a different arity is a test's business, not a reason to break the tab.
        return []


def _has_run(store, slug: str) -> bool:
    status = store.status(slug) if hasattr(store, "status") else {}
    return int((status or {}).get("actions", 0)) > 0


def _golive_gaps(golive: dict) -> list[tuple[str, bool]]:
    """The three things that turn a simulated company into one that can take money.

    **Passed in, not re-derived.** `api.adapters.golive_status` already answers this — reading the
    company's offer, the Stripe link, the SMTP pair and the `.published` marker — and a second
    implementation here would be two answers to "is the checkout wired", which is the shape of defect
    this project keeps paying for. It also lives at rank 6 and this is rank 5, so importing it would
    be the layer rule catching what the duplication argument already forbids.

    The order is the order an operator should do them in: money first, because a company that can
    publish and mail but cannot be paid has done the hard parts for nothing.
    """
    return [
        ("payment", bool((golive.get("payment") or {}).get("wired"))),
        ("email", bool((golive.get("mail") or {}).get("wired"))),
        ("hosting", bool((golive.get("hosting") or {}).get("published"))),
    ]
