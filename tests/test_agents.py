"""The roster is a static registry, so nothing catches drift between it and the
toolbox until an agent turn hits a KeyError mid-run. Executor._invoke indexes
TOOLS[tool_name] with no guard, which makes a typo in a playbook a crash for
that company's day, on the tick the role happens to be due.
"""
from app.agents import ROSTER
from app.models import AgentRole, Difficulty
from app.tools import TOOLS


def test_every_role_has_a_spec():
    assert set(ROSTER) == set(AgentRole)


def test_specs_are_self_consistent():
    for role, spec in ROSTER.items():
        assert spec.role is role, f"{role.value} spec carries the wrong role"
        assert isinstance(spec.difficulty, Difficulty)
        assert spec.system_prompt.strip(), f"{role.value} has no system prompt"
        assert spec.playbook, f"{role.value} has an empty playbook"


def test_every_playbook_tool_exists():
    """The assertion that catches roster/toolbox drift before a run does."""
    for role, spec in ROSTER.items():
        for tool_name in spec.playbook:
            assert tool_name in TOOLS, f"{role.value} plays a tool that does not exist: {tool_name}"


def test_cadences_are_positive_or_on_demand():
    for role, spec in ROSTER.items():
        if spec.cadence_hours is None:
            continue   # on demand, never scheduled
        assert spec.cadence_hours > 0, f"{role.value} has a non-positive cadence"


def test_only_the_coder_is_on_demand():
    """due_roles skips cadence_hours=None entirely, so a role that quietly
    becomes on-demand stops running without any error to notice."""
    assert {r for r, s in ROSTER.items() if s.cadence_hours is None} == {AgentRole.CODER}


def test_the_ceo_owns_the_backlog():
    """create_tasks and review_proposals write the backlog every other agent
    pulls from; they belong to the CEO alone."""
    ceo = ROSTER[AgentRole.CEO].playbook
    assert "create_tasks" in ceo and "review_proposals" in ceo
    for role, spec in ROSTER.items():
        if role is AgentRole.CEO:
            continue
        assert "create_tasks" not in spec.playbook
        assert "review_proposals" not in spec.playbook
