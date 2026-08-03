"""Outreach with no source of leads: established once, not forty times.

This is the loop the operator reported, in its purest measured form. One real run
logged

    find_targets: No lead found. Sources configured: none.
    send_outreach: No lead with an email address, so there is nobody to write to.

**more than forty times in a single session**, while the CEO queued a fresh
outreach task on top of it every cycle — and `stop_useless_work` answered "Every
role still has somewhere for its work to go" throughout. Every line was true, and
every one was rediscovered from scratch.

NanoCorp's worker handles the same shape once and then stops (see
docs/reverse-engineering/nanocorp.md): on a blocked channel it recorded the exact
blocker and wrote *"so the next task can focus narrowly on account access instead
of rediscovery"*. That is the whole idea, and Corparius already had the mechanism
for it — `_stop_useless_work` stands a role down through a `pause` directive that
the CEO reads, and `_create_tasks` refuses to queue a paused role. Social had it.
Outreach did not.
"""

from pathlib import Path

import pytest

from corparius import leadsource, mailbox, tools
from corparius.store import Store
from corparius.tools import NO_LEAD_SOURCE, TRIES_BEFORE_STAND_DOWN


class _Ctx:
    def __init__(self, store, agents=None):
        self.store = store
        self.company = {
            "slug": "c",
            "name": "C",
            "agents": agents or {"outreach": True, "social": True, "support": True, "ceo": True},
        }
        self.role = "ceo"
        self.structured = None


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path))
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _no_mailbox(monkeypatch):
    """Keep the support stand-down out of the way; it has its own tests."""
    monkeypatch.setattr(mailbox, "configured", lambda: True)


def _fruitless(store, times=TRIES_BEFORE_STAND_DOWN):
    """The evidence the stand-down requires: real turns that found nobody.

    The trigger is measured, not declared. An earlier version fired the moment no
    source was configured, which stood outreach down on the first tick of a fresh
    company — a role stopped before it had a chance. `tests/test_tasks.py` caught
    that, which is the whole argument for keeping this fixture honest.
    """
    for _ in range(times):
        store.record_action(
            "c", "outreach", "find_targets", {}, "No lead found. Sources configured: none.", True
        )


def test_no_lead_source_stands_outreach_down(store, monkeypatch):
    monkeypatch.setattr(leadsource, "configured_sources", lambda: [])
    _fruitless(store)
    out = tools._stop_useless_work(_Ctx(store))
    assert "outreach" in out and "Stood down" in out
    paused = {d["target"]: d["note"] for d in store.directives("c", "pause")}
    assert paused.get("outreach") == NO_LEAD_SOURCE


def test_and_then_the_ceo_stops_queueing_outreach(store, monkeypatch):
    """The half that closes the loop. The CEO queued an outreach task every cycle
    while every one of them came back "nobody to write to"."""
    monkeypatch.setattr(leadsource, "configured_sources", lambda: [])
    _fruitless(store)
    ctx = _Ctx(store)
    tools._stop_useless_work(ctx)
    out = tools._create_tasks(ctx)
    assert "outreach" not in out, out
    assert not [t for t in store.list_tasks("c") if t["target"] == "outreach"]


def test_a_configured_source_puts_it_straight_back(store, monkeypatch):
    monkeypatch.setattr(leadsource, "configured_sources", lambda: [])
    _fruitless(store)
    ctx = _Ctx(store)
    tools._stop_useless_work(ctx)
    monkeypatch.setattr(leadsource, "configured_sources", lambda: ["local"])
    out = tools._stop_useless_work(ctx)
    assert "Restarted" in out and "local" in out
    assert "outreach" not in {d["target"] for d in store.directives("c", "pause")}


def test_it_never_clears_a_stand_down_the_operator_wrote(store, monkeypatch):
    """The exact reason the note is matched exactly rather than searched for. An
    operator who paused outreach by hand must not have it restarted because a
    lead source appeared."""
    store.add_directive("c", "pause", "outreach", "paused by the operator")
    monkeypatch.setattr(leadsource, "configured_sources", lambda: ["local"])
    tools._stop_useless_work(_Ctx(store))
    paused = {d["target"]: d["note"] for d in store.directives("c", "pause")}
    assert paused.get("outreach") == "paused by the operator"


def test_it_does_not_stand_down_a_role_already_paused(store, monkeypatch):
    """Twice-said is once-meant. A second directive for the same (kind, target)
    replaces the first, so writing this one over the operator's own note would
    erase it."""
    store.add_directive("c", "pause", "outreach", "paused by the operator")
    monkeypatch.setattr(leadsource, "configured_sources", lambda: [])
    _fruitless(store)
    out = tools._stop_useless_work(_Ctx(store))
    assert "outreach" not in out
    assert store.directives("c", "pause")[0]["note"] == "paused by the operator"


def test_a_company_with_a_source_is_left_alone(store, monkeypatch):
    monkeypatch.setattr(leadsource, "configured_sources", lambda: ["search"])
    out = tools._stop_useless_work(_Ctx(store))
    assert out == "Every role still has somewhere for its work to go"
    assert not store.directives("c", "pause")


def test_the_note_is_a_constant_both_ends_share():
    """It is written in one place and matched in one place. A literal repeated
    twice is how a stand-down becomes unclearable."""
    src = Path(tools.__file__).read_text(encoding="utf-8")
    assert src.count('"no lead source configured, so there is nobody to find"') == 1
    assert src.count("NO_LEAD_SOURCE") >= 3  # the constant, the write, the clear


def test_one_empty_turn_is_not_enough(store, monkeypatch):
    """A role stood down before it has had a chance is a different mistake, and a
    worse one. The evidence for this stand-down was forty identical lines in one
    session, not one."""
    monkeypatch.setattr(leadsource, "configured_sources", lambda: [])
    _fruitless(store, times=TRIES_BEFORE_STAND_DOWN - 1)
    out = tools._stop_useless_work(_Ctx(store))
    assert out == "Every role still has somewhere for its work to go"
    assert not store.directives("c", "pause")


def test_a_fresh_company_is_never_stood_down(store, monkeypatch):
    """No history at all. This is the case that broke a real test: the CEO had a
    buying signal to act on and the role was already off."""
    monkeypatch.setattr(leadsource, "configured_sources", lambda: [])
    assert tools._stop_useless_work(_Ctx(store)) == (
        "Every role still has somewhere for its work to go"
    )
