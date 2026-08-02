"""The CEO's powers, and the promise each one keeps.

Before these, the chat read the store and wrote nothing. The operator's own
session: "too early for cold emailing, I want a working prototype first" — the
CEO answered "I will pause the campaigns" — the next tick drafted another one.
A conversation held over a machine that could not hear it.
"""

import tempfile
import types

import pytest

from corparius import webui
from corparius.models import AgentRole
from corparius.orchestrator import cadence_overrides, due_roles, paused_roles
from corparius.store import Store
from corparius.tools import TOOLS

SLUG = "vigil"
ENABLED = {r.value: True for r in AgentRole}


@pytest.fixture
def store():
    s = Store(tempfile.mkdtemp())
    yield s
    s.close()


def _due(store, tick=0):
    return sorted(
        s.role.value
        for s in due_roles(tick, ENABLED, paused_roles(store, SLUG), cadence_overrides(store, SLUG))
    )


def test_pausing_a_role_stops_it_on_the_next_tick(store):
    assert "social" in _due(store)
    webui._apply_directives(store, SLUG, {"pause": ["social", "outreach"]}, "en")
    due = _due(store)
    assert "social" not in due and "outreach" not in due
    assert "ceo" in due, "pausing one role must not stop the company"


def test_resuming_brings_it_back(store):
    webui._apply_directives(store, SLUG, {"pause": ["social"]}, "en")
    webui._apply_directives(store, SLUG, {"resume": ["social"]}, "en")
    assert "social" in _due(store)


def test_a_role_the_model_invented_is_dropped_not_promised(store):
    """Promising to pause `marketing` — which is not a role — would be exactly
    the empty promise this mechanism replaces."""
    said = webui._apply_directives(store, SLUG, {"pause": ["marketing", "social"]}, "en")
    assert "marketing" not in said and "social" in said
    assert {d["target"] for d in store.directives(SLUG, "pause")} == {"social"}


def test_a_priority_replaces_the_housekeeping_backlog(store):
    """The bug in the run log: `social stood down: 9 post(s) queued` and, three
    lines later, the CEO queueing "Publish a post today" for that same role.
    Standing a role down has to stop the whole company asking it for work."""
    webui._apply_directives(
        store, SLUG, {"pause": ["social"], "focus": "finish the prototype"}, "en"
    )
    ctx = types.SimpleNamespace(store=store, company={"slug": SLUG, "name": "V", "agents": ENABLED})
    TOOLS["create_tasks"].run(ctx)
    queued = [t["target"] for t in store.list_tasks(SLUG) if t["created_by"] == "ceo"]
    assert "social" not in queued, "the CEO re-armed a role the operator had paused"
    assert queued, "a stated priority should still produce work"


def test_clearing_the_priority_brings_the_baseline_back(store):
    webui._apply_directives(store, SLUG, {"focus": "one thing"}, "en")
    assert store.directives(SLUG, "focus")
    webui._apply_directives(store, SLUG, {"focus": ""}, "en")
    assert store.directives(SLUG, "focus") == []


def test_a_cadence_is_a_sentence_not_a_yaml_edit(store):
    webui._apply_directives(store, SLUG, {"cadence": {"support": 24}}, "en")
    assert cadence_overrides(store, SLUG) == {"support": 24}
    assert "support" in _due(store, 0)
    assert "support" not in _due(store, 3), "the roster default still applied"
    assert "support" in _due(store, 24)


@pytest.mark.parametrize("hours", [0, -1, 10_000, "soon", None])
def test_a_cadence_that_means_nothing_is_refused(store, hours):
    """Zero would busy-loop a role and a year is indistinguishable from off.
    Neither is what anybody means, so neither is silently clamped."""
    webui._apply_directives(store, SLUG, {"cadence": {"social": hours}}, "en")
    assert cadence_overrides(store, SLUG) == {}


def test_saying_the_same_thing_twice_leaves_one_directive(store):
    webui._apply_directives(store, SLUG, {"pause": ["social"]}, "en")
    webui._apply_directives(store, SLUG, {"pause": ["social"]}, "en")
    assert len([d for d in store.directives(SLUG, "pause") if d["target"] == "social"]) == 1


def test_approving_in_words_resolves_the_request_that_exists(store):
    """Bonus, and narrow on purpose: it approves a request already raised and
    already shown. The console button is untouched."""
    from corparius.hitl import ApprovalGate
    from corparius.permissions import PermissionEngine

    gate = ApprovalGate(store, PermissionEngine(["send_outreach"]))
    ctx = types.SimpleNamespace(store=store, company={"slug": SLUG, "name": "V"}, leads=[])
    gate.execute(SLUG, "outreach", TOOLS["send_outreach"], ctx, "Bonjour…", {"draft": "x"})
    assert store.pending_approval_for(SLUG, "send_outreach")

    said = webui._apply_directives(store, SLUG, {"approve": ["send_outreach"]}, "en")
    assert "send_outreach" in said
    assert store.pending_approval_for(SLUG, "send_outreach") is None


def test_approving_something_nobody_asked_for_does_nothing(store):
    said = webui._apply_directives(store, SLUG, {"approve": ["deploy_site"]}, "en")
    assert "deploy_site" not in said


def test_an_ordinary_answer_changes_nothing(store):
    """Most messages are conversation. Empty fields must stay empty."""
    assert webui._apply_directives(store, SLUG, {"reply": "hello"}, "en") == ""
    assert store.directives(SLUG) == []


def test_the_reply_reports_what_happened_not_what_was_intended(store):
    said = webui._apply_directives(
        store, SLUG, {"pause": ["social"], "focus": "ship the prototype"}, "en"
    )
    assert "social" in said and "ship the prototype" in said
