"""Deciding an approval. One gesture, one service. Rank 5.

**The fourth live divergence this restructuring has found, and the widest.** Three surfaces
implemented "decide an approval" and all three did something different:

```text
                        set status   grant the standing rule   release parked tasks
console handler             yes              yes                      NO
corparius approve           yes              yes (always only)        yes
MCP decide_approval         yes              NO                       NO
```

The console is the primary surface and it is the one that left work parked. An operator approves,
the board still reads "Held, waiting on you", and nothing moves until a run ticks — which they may
not start *because* the board looks stuck. Measured: five callers reach `release_waiting_tasks`
(the inbox handler, `cmd_decide`, `cmd_inbox`, the MCP server's inbox, and the run loop) and the
console's approval path was not one of them.

`tests/test_two_callers_agree.py` could not catch it, and the reason is worth writing down: it
asks whether both callers reach the *same service*, and there was no service — three copies of the
same twenty lines, which is precisely the state that ratchet exists to end. It is a declared pair
now.

Three decisions the shape encodes:

**One gesture, so one call.** "Yes, and stop asking" is a single operator intention. The old
comment in the handler said it: splitting it in two "invites the half that never runs". Releasing
the parked work is part of the same gesture for the same reason — an approval that does not unblock
what was waiting on it has not finished.

**A tool gated by name is never silenced.** `hitl_tools` in the company file is the operator's own
list of things they want to see every time, and a standing rule would overrule the file they wrote
it in. Refused, and the refusal is reported rather than swallowed, so a console can say why the
button did nothing.

**`remember` is a scope, not a boolean.** `run` expires with the run that granted it, `always`
persists. The CLI could only ever grant `always`; passing the scope through means it can offer both
without a second implementation.
"""

from __future__ import annotations

from ..config import permissions
from ..tools.spec import SPEC

SCOPES = ("run", "always")


def decide(
    store,
    settings,
    approval_id: str,
    decision: str,
    *,
    note: str = "",
    remember: str = "",
    company: dict | None = None,
) -> dict:
    """Decide one approval, and finish the job: grant, release, report.

    Answers with what happened rather than a bare boolean, because three different things can be
    worth telling an operator — the decision landed, a standing rule was or was not granted, and
    some parked work moved. A caller that wants none of it can ignore the dict; a caller that
    reports "approved" and nothing else is how the console came to look stuck.

    `found=False` for an id that is not there, and nothing else is attempted: granting a rule from
    an approval that does not exist would be inventing a permission.
    """
    if decision not in ("approved", "rejected"):
        from .errors import Refused

        raise Refused("decision must be approved or rejected")

    # Read before writing: the approval carries its own company, so this is not slug-scoped and an
    # approval can be decided from anywhere it is visible.
    approval = store.get_approval(approval_id)
    found = store.set_approval_status(approval_id, decision, note)
    if not found or approval is None:
        return {"found": False, "remembered": "", "released": 0, "refused": 0, "gated": ""}

    slug = str(approval.get("company") or "")
    remembered, gated = "", ""
    scope = (remember or "").strip()
    if decision == "approved" and scope in SCOPES:
        tool = SPEC.get(str(approval.get("tool") or ""))
        engine = permissions.PermissionEngine.from_settings(settings, company or {}, store)
        if tool is None or engine.evaluate(tool, slug).rule == "hitl":
            # Named in the company's own `hitl_tools`. Reported rather than silently skipped: a
            # console that offered "and stop asking" has to be able to say the answer was no.
            gated = str(approval.get("tool") or "")
        else:
            store.add_rule(slug, approval["tool"], scope, "granted by the operator")
            remembered = scope

    # Whatever decided it, work parked on this approval can move again. This is the line the
    # console did not have, and it is why this function exists.
    freed = store.release_waiting_tasks(slug) if slug else {"released": 0, "refused": 0}
    return {
        "found": True,
        "remembered": remembered,
        "gated": gated,
        "released": int(freed.get("released", 0)),
        "refused": int(freed.get("refused", 0)),
        "company": slug,
    }
