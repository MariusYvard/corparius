"""Editing a backlog task: its title, its priority, the agent that owns it, the tool that
carries it, and whether it is approved. Rank 5.

**This one closes a live bug rather than only a gap.** Two callers reached the backlog and they
were fixed in opposite directions, each blind to the other:

  * the console could approve or reject a task and not edit its fields;
  * the command line could retitle and reprioritise and not decide.

They were repaired separately. `webui._edit_task` grew the validation — the agent has to be a
real role, the tool has to be in the registry — and, more importantly, it grew the call to
`executable_fields` on approval. `cli.cmd_task` kept calling `store.update_task(id, **fields)`
directly, so it had **none of it**. Measured just now on a real store: the command line accepts
`target='not-a-real-agent'` and `tool='not-a-real-tool'` and writes both.

The approval path is the part that cost something. From `executable_fields`' own docstring:
measured in a real store, **24 tasks for one role carried no tool and 22 of them closed
"done (no tool mapped)" having done nothing at all** — so the condition that produced them
survived, the agent proposed it again, and again. `tests/test_registries.py` asserts the
registry behind it is real; this is the other end of the same wire, and the command line was
never attached to it.

One service, both callers. A `Refused` says why; the console turns it into a 400 and a terminal
prints it.
"""

from __future__ import annotations

from ..kernel.records import AgentRole
from ..tools.spec import SPEC, executable_fields, unrunnable_reason
from .errors import Refused

DECISIONS = ("approved", "rejected")
MAX_PRIORITY = 5


def edit(
    store,
    # `object`, not `int`: the callers hand this whatever a body or an argv carried, and the
    # first thing this function does is refuse what is not a number. Annotating `int` would
    # push that refusal onto the caller, which is the console and the terminal — both of which
    # would then have to invent the same error message.
    task_id: object,
    *,
    title: str | None = None,
    priority: int | str | None = None,
    target: str | None = None,
    tool: str | None = None,
    decision: str | None = None,
    note: str = "",
) -> dict:
    """Apply what was asked, or refuse and say why. Returns what changed.

    Keyword-only and one parameter per field, rather than the `body` dict the console handler
    took: a dict shaped like a request body is a request, and the point of this layer is that
    the caller does not have to be an HTTP one. `None` means "not mentioned"; an empty string
    for `tool` means "clear it", which is a real thing an operator asks for.
    """
    try:
        ident = int(task_id)  # type: ignore[call-overload]  # refused below when it is not
    except (TypeError, ValueError) as exc:
        raise Refused("a task id is required") from exc
    if decision is not None and decision not in DECISIONS:
        raise Refused(f"decision must be one of {', '.join(DECISIONS)}")

    fields: dict = {}
    if title is not None:
        clean = str(title).strip()
        if not clean:
            raise Refused("title cannot be empty")
        fields["title"] = clean
    if priority is not None:
        try:
            fields["priority"] = max(0, min(int(priority), MAX_PRIORITY))
        except (TypeError, ValueError) as exc:
            raise Refused("priority must be a whole number") from exc
    if target is not None:
        clean = str(target).strip()
        if clean not in {r.value for r in AgentRole}:
            raise Refused(f"unknown agent '{clean}'")
        fields["target"] = clean
    if tool is not None:
        clean = str(tool).strip()
        # An empty string clears the tool, which is why this is not `if clean`.
        if clean and clean not in SPEC:
            raise Refused(f"unknown tool '{clean}'")
        fields["tool"] = clean
    if not fields and decision is None:
        raise Refused("nothing to change")

    if decision == "approved":
        # `{}`, not None, for a row that is not there — the store says so in its docstring, and
        # a truthiness check is what reads correctly against both.
        current = store.get_task(ident)
        if not current:
            raise Refused(f"no task {ident}")
        # The same thing the CEO does on approval, and the end of the wire the command line was
        # never attached to: a task approved with no tool closes "done (no tool mapped)" having
        # done nothing, so the condition survives and the agent proposes it again.
        fields = {**executable_fields({**dict(current), **fields}), **fields}
        # And when nothing can make it executable, say so instead of approving it. The half of
        # the defect `executable_fields` cannot reach: it maps a role to its default tool, and
        # for the five roles that had no default — and for the CEO, which has none on purpose —
        # there was nothing to map, so the task was approved and closed "done (no tool mapped)"
        # having done nothing. A refusal naming the cause is what stops the agent proposing the
        # same thing again next cadence.
        why = unrunnable_reason({**dict(current), **fields})
        if why:
            raise Refused(f"this cannot run as approved: {why}")
    if fields:
        store.update_task(ident, **fields)
    if decision:
        store.set_task_status(ident, decision, note or "edited")
    return {"id": ident, "changed": sorted(fields), "decision": decision or ""}
