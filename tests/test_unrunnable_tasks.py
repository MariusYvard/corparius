"""A task nobody can run is refused out loud, on both paths that approve one.

The measured defect, from `executable_fields`' own docstring: **24 tasks for one role with no tool, 22
of them closed "done (no tool mapped)" having done nothing at all.** `executable_fields` fixed half of
it by mapping a role to its default tool. This file is the other half, and it exists because the fix
was incomplete in a way nothing could see: **five of the ten roles had no default** — ads, coder,
competitor, finance and the CEO — so a proposal aimed at any of them was approved, ran nothing, and
closed as done. The condition that produced it therefore survived, and the agent proposed it again.

Four of the five now have a default. The CEO deliberately does not: it arbitrates the backlog rather
than working it, and a refusal that names that is more useful than a mapping invented to silence a
test.

Both ends of the wire, because there are two approval paths and the first version of this fix reached
one: `app.tasks.edit` (the console's button and the command line) and `review_proposals` (the CEO's own
turn).
"""

import pytest

from corparius import company as company_mod
from corparius.app.tasks import Refused
from corparius.store import Store
from corparius.tools.spec import ROLE_TOOL, executable_fields, unrunnable_reason

COMPANY = "example"


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path))
    yield s
    s.close()


# --- the rule ------------------------------------------------------------------


def test_every_role_but_the_ceo_can_run_an_approved_task():
    """The gap this file was written for. Five roles had no default tool; four have one now, and the
    one that does not is the one that should not."""
    without = sorted(set(company_mod.ROLES) - set(ROLE_TOOL))
    assert without == ["ceo"], f"roles that would approve into nothing: {without}"


def test_the_defaults_are_tools_that_produce_something():
    """The rule the table is really written to, and the reason it is not derived from the playbook:
    `find_targets`, `review_kpis` and `triage_inbox` are the first playbook step for outreach, strategy
    and support, and all three only *look*. A task approved onto one of them finishes having produced
    nothing — the same nothing as no tool at all."""
    looks_only = {"find_targets", "review_kpis", "triage_inbox", "scan_signals", "check_providers"}
    for role, tool in sorted(ROLE_TOOL.items()):
        assert tool not in looks_only, f"{role}'s default only looks at things"

    # Not "the default must be in the role's playbook" — that was asserted first and it is false:
    # `write_note` is strategy's default and strategy's playbook is `review_kpis, update_pricing,
    # kaizen, remember`. The distinction is real and worth writing down. **A playbook is the cadence**
    # — what the role does every turn, unprompted. **A task's tool is what an approved task runs.**
    # Strategy's own docstring records the cost of confusing them: without `write_note` a strategy task
    # reached an agent with no tool that could carry it and was held for the operator, twice.
    from corparius import roster

    strategy = next(
        s for role, s in roster.ROSTER.items() if getattr(role, "value", role) == "strategy"
    )
    assert "write_note" not in strategy.playbook


def test_no_default_is_a_gated_tool():
    """A default that trips the human gate parks the task on the operator the moment the CEO approves
    it, which is not approval — it is a queue. `adjust_bids`, `send_financial_transaction` and
    `publish_production_code` are each the *other* producing tool of their role, and each is why."""
    from corparius.tools.spec import SPEC

    for role, tool in sorted(ROLE_TOOL.items()):
        assert not SPEC[tool].hitl, f"{role}'s default is gated, so approving it only queues it"


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ({"target": "ads"}, ""),
        ({"target": "design"}, ""),
        ({"tool": "write_note", "target": "ceo"}, ""),
        ({"target": "ceo"}, "arbitrates"),
        ({"target": ""}, "no role owns it"),
        ({"target": "nope"}, "no tool is mapped"),
    ],
)
def test_the_reason_is_a_sentence_or_nothing(task, expected):
    """A sentence rather than a boolean, because both callers put it in front of a person. "Rejected"
    with no cause is how the condition survives to produce the same proposal again."""
    reason = unrunnable_reason(task)
    assert expected in reason
    if expected:
        assert reason and reason[0].islower() and not reason.endswith(".")


# --- the console's and the command line's path ----------------------------------


def test_approving_something_nothing_can_run_is_refused(store):
    """The path the console's approve button and `corparius task` both take."""
    from corparius.app import tasks as app_tasks

    ident = store.add_task(COMPANY, "ceo idea", "ceo", status="proposed")
    with pytest.raises(Refused) as refused:
        app_tasks.edit(store, ident, decision="approved")
    assert "cannot run as approved" in str(refused.value)
    assert "arbitrates" in str(refused.value)
    assert store.get_task(ident)["status"] == "proposed", "a refused approval must change nothing"


def test_approving_something_runnable_still_works(store):
    """The guard on the guard: a rule that refuses everything is a rule nobody keeps."""
    from corparius.app import tasks as app_tasks

    ident = store.add_task(COMPANY, "review the ad budget", "ads", status="proposed")
    done = app_tasks.edit(store, ident, decision="approved")
    assert done["decision"] == "approved"
    after = store.get_task(ident)
    assert after["status"] == "approved"
    assert after["tool"] == ROLE_TOOL["ads"], "approval has to attach the tool that will run it"


def test_a_task_that_already_names_a_tool_is_left_alone(store):
    """`executable_fields` returns `{}` when a tool is set, and the refusal must agree: an operator who
    chose a tool has decided, and overruling that is the console taking the last word away."""
    ident = store.add_task(COMPANY, "write it up", "ceo", status="proposed")
    store.update_task(ident, tool="write_note")
    from corparius.app import tasks as app_tasks

    assert app_tasks.edit(store, ident, decision="approved")["decision"] == "approved"
    assert store.get_task(ident)["tool"] == "write_note"
    assert executable_fields(dict(store.get_task(ident))) == {}
