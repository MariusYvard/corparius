"""Every tool has to be reachable by something.

Found by sweeping for the defect class that produced the images bug: `ask_operator`
and `set_roster` sat in TOOLS on no playbook, in no queue, and named by no other
module. One was that way by design — its prompt is written for a task — and the
other by omission: "the most CEO decision there is", per its own docstring, and no
CEO could take it.

Nothing could tell those two apart, which is the whole problem. A tool that runs
only when a task names it now says so (`by_task_only`), and this file demands that
every tool have a path. The next one added without one fails here instead of
sitting unreachable for months.
"""

import re
from pathlib import Path

from corparius.agents import ROSTER
from corparius.tools import ROLE_TOOL, TOOLS

TOOLS_SRC = Path("corparius/tools.py").read_text(encoding="utf-8")


def _on_a_playbook() -> set[str]:
    return {name for spec in ROSTER.values() for name in spec.playbook}


def _queued_by_the_ceo() -> set[str]:
    """Tools `_create_tasks` can put on the backlog.

    Read out of the source rather than kept in a second list here: the queue is
    six hardcoded (title, target, tool) triples, and a list in this file would
    drift from them exactly the way the changelog drifted from the code.
    """
    return set(re.findall(r'queue\([^,]+,\s*"[a-z_]+",\s*"([a-z_]+)"', TOOLS_SRC))


def test_every_tool_is_reachable_by_something():
    """The guard. A tool reaches a turn one of four ways: a role's playbook, the
    CEO's queue, a role's default tool, or a task that names it — and the last one
    has to be declared, because "on no playbook" is also what a forgotten tool
    looks like.
    """
    reachable = _on_a_playbook() | _queued_by_the_ceo() | set(ROLE_TOOL.values())
    declared = {name for name, tool in TOOLS.items() if tool.by_task_only}
    orphans = sorted(set(TOOLS) - reachable - declared)
    assert not orphans, (
        f"these tools cannot be reached: {orphans}. Put them on a playbook, let the "
        "CEO queue them, or declare by_task_only=True if a task is meant to name them."
    )


def test_the_guard_would_have_caught_the_two_it_was_written_for():
    """Non-vacuous: with the flag ignored and set_roster off the playbook, both
    come back as orphans. A guard that cannot fail is decoration."""
    reachable = (_on_a_playbook() - {"set_roster"}) | _queued_by_the_ceo() | set(ROLE_TOOL.values())
    orphans = set(TOOLS) - reachable  # flag deliberately not consulted
    assert {"ask_operator", "set_roster"} <= orphans


def test_a_task_only_tool_is_never_on_a_playbook():
    """The flag says "a task names me". A tool that is also on a playbook would be
    claiming both, and the flag would stop meaning anything."""
    both = sorted(
        name for name, tool in TOOLS.items() if tool.by_task_only and name in _on_a_playbook()
    )
    assert not both, f"declared by_task_only and also on a playbook: {both}"


def test_the_task_only_tools_are_the_ones_whose_prompt_is_task_shaped():
    """Each of these is meaningless without a task to be about, and the list is
    spelled out so adding a fourth is a decision rather than a drift.

    - `ask_operator` asks for what *this task* cannot proceed without.
    - `deploy_site` publishes because something decided to.
    - `write_note` writes the document a task asked for; on a playbook it would
      write a note about nothing, every turn.
    """
    assert sorted(n for n, t in TOOLS.items() if t.by_task_only) == [
        "ask_operator",
        "deploy_site",
        "write_note",
    ]


def test_set_roster_belongs_to_the_ceo_and_to_nobody_else():
    """ "Hire and fire. The most CEO decision there is" — its own docstring. It has
    to be on the CEO's playbook specifically, not merely somewhere."""
    from corparius.models import AgentRole

    holders = [role for role, spec in ROSTER.items() if "set_roster" in spec.playbook]
    assert holders == [AgentRole.CEO]


def test_the_ceo_cannot_undo_a_stand_down_the_operator_set(tmp_path):
    """Wiring it onto the playbook without this would have had the CEO clearing the
    operator's own pauses twice a day — the exact failure standing directives were
    introduced to end, arriving through the tool meant to respect them."""
    import types

    from corparius.store import Store
    from corparius.tools import CEO_STAND_DOWN, _set_roster

    store = Store(str(tmp_path))
    store.add_directive("acme", "pause", "social", "asked in the CEO chat")
    store.add_directive("acme", "pause", "ads", CEO_STAND_DOWN)
    ctx = types.SimpleNamespace(company={"slug": "acme"}, store=store)

    said = _set_roster(ctx, "social ads")
    still_paused = {d["target"] for d in store.directives("acme", "pause")}
    assert "social" in still_paused, "the operator's stand-down was cleared"
    assert "ads" not in still_paused, "the CEO's own stand-down should lift"
    # And it says so rather than reporting a change it did not make.
    assert "social" in said and "you stood them down" in said
    store.close()
