"""The CEO re-owns a task nothing can run, instead of asking the operator to.

The sixth mechanism from the NanoCorp logs, and the one
docs/reverse-engineering/nanocorp.md flagged as the next serious candidate: their
CEO creates and assigns work from what another agent produced.

Corparius held such a task and put a notice in front of the operator with two
select boxes. They said the plain version of it: *"I do not see it propose the agent
and the tool by itself. It is still too complicated for the user."* Offering choices
is not proposing — and this was never the operator's decision anyway. A held task is
one the CEO mis-assigned, and the CEO is the role that owns the backlog. So the CEO
reads the held tasks against the real roster and re-owns them; the operator is asked
only when the CEO cannot place one.
"""

import pytest

from corparius import inbox, tools
from corparius.agents import ROSTER
from corparius.store import Store


class _Ctx:
    def __init__(self, store, structured=None, agents=None):
        self.store = store
        self.company = {
            "slug": "c",
            "name": "C",
            "agents": agents
            or {"ceo": True, "design": True, "support": True, "strategy": True, "social": True},
        }
        self.structured = structured
        self.data_path = "unused"


class _Result:
    def __init__(self, data):
        self.data = data
        self.ok = True
        self.fell_back = False


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path))
    yield s
    s.close()


def _hold(store, title="Remove the badge from the site", target="support", why=""):
    """A task in the state `_hold_untooled` leaves behind."""
    task_id = store.add_task("c", title, target, status="approved", why=why)
    store.set_task_status(task_id, "waiting", "no tool: needs an owner or a tool before it can run")
    return task_id


# --- which tasks it looks at ---------------------------------------------------


def test_it_sees_a_task_held_for_want_of_a_tool(store):
    task_id = _hold(store)
    assert [t["id"] for t in tools._held_tasks(store, "c")] == [task_id]


def test_it_never_touches_a_task_waiting_on_the_operator(store):
    """`park_task` writes `approval:` or `question:`; `_hold_untooled` writes a
    sentence starting "no tool". Re-owning an approval behind the operator's back
    would be the CEO overruling them."""
    task_id = store.add_task("c", "Send the money", "finance", status="approved")
    store.park_task(task_id, "appr-1", "approval")
    assert tools._held_tasks(store, "c") == []


def test_nothing_held_means_nothing_asked(store):
    reason = tools.TOOLS["assign_held_tasks"].skip_reason(_Ctx(store))
    assert "no task is held" in reason
    _hold(store)
    assert tools.TOOLS["assign_held_tasks"].skip_reason(_Ctx(store)) == ""


# --- what the CEO is shown -----------------------------------------------------


def test_the_prompt_offers_only_playbook_tools(store):
    """A tool that is not on a role's playbook is one that role never runs, so
    offering it would produce an assignment that looks valid and does nothing — the
    untooled task again."""
    _hold(store)
    prompt = tools._assign_held_prompt(_Ctx(store))
    assert "design: " in prompt and "write_site_content" in prompt
    assert "send_outreach" not in prompt, "outreach is off in this company"
    for name in ROSTER[
        __import__("corparius.models", fromlist=["AgentRole"]).AgentRole.CEO
    ].playbook:
        if name not in ("review_kpis",):
            continue
    assert "id|role|tool" in prompt, "the shape has to be stated or the answer is unparseable"


def test_the_prompt_names_the_task_and_its_reason(store):
    _hold(store, title="Remove the badge", why="It is an invented number")
    prompt = tools._assign_held_prompt(_Ctx(store))
    assert "Remove the badge" in prompt and "invented number" in prompt


def test_the_prompt_says_leaving_one_out_is_allowed(store):
    """Better held than given a tool that would run and change nothing."""
    _hold(store)
    assert "stays held for the operator" in tools._assign_held_prompt(_Ctx(store))


def test_the_prompt_is_never_empty(store):
    assert tools._assign_held_prompt(_Ctx(store)).strip()


# --- what it applies -----------------------------------------------------------


def test_it_re_owns_a_held_task(store):
    task_id = _hold(store)
    ctx = _Ctx(store, _Result({"assignments": [f"{task_id}|design|write_site_content"]}))
    out = tools._assign_held(ctx)
    assert f"#{task_id} -> design/write_site_content" in out
    row = store.get_task(task_id)
    assert row["status"] == "approved"
    assert (row["target"], row["tool"]) == ("design", "write_site_content")
    assert "re-owned by the CEO" in row["note"]


def test_a_leading_hash_is_accepted(store):
    task_id = _hold(store)
    ctx = _Ctx(store, _Result({"assignments": [f"#{task_id} | design | write_site_content"]}))
    tools._assign_held(ctx)
    assert store.get_task(task_id)["tool"] == "write_site_content"


def test_a_tool_not_on_that_role_is_refused_and_named(store):
    """Named rather than silently dropped: an assignment the roster cannot honour is
    exactly the mistake that produced the held task."""
    task_id = _hold(store)
    ctx = _Ctx(store, _Result({"assignments": [f"{task_id}|design|draft_support_reply"]}))
    out = tools._assign_held(ctx)
    assert "Refused" in out and "not on that role's playbook" in out
    assert store.get_task(task_id)["status"] == "waiting", "it must stay held"


def test_a_disabled_role_is_refused(store):
    task_id = _hold(store)
    ctx = _Ctx(
        store,
        _Result({"assignments": [f"{task_id}|design|write_site_content"]}),
        agents={"ceo": True, "support": True, "design": False},
    )
    out = tools._assign_held(ctx)
    assert "Refused" in out and store.get_task(task_id)["status"] == "waiting"


def test_a_malformed_answer_changes_nothing(store):
    task_id = _hold(store)
    for bad in (
        "design write_site_content",
        "abc|design|write_site_content",
        "9999|design|review_site",
    ):
        ctx = _Ctx(store, _Result({"assignments": [bad]}))
        tools._assign_held(ctx)
        assert store.get_task(task_id)["status"] == "waiting", bad


def test_a_task_left_out_stays_held_and_is_counted(store):
    a, b = _hold(store, title="A"), _hold(store, title="B")
    ctx = _Ctx(store, _Result({"assignments": [f"{a}|design|write_site_content"]}))
    out = tools._assign_held(ctx)
    assert "1 still held for the operator" in out
    assert store.get_task(b)["status"] == "waiting"


def test_placing_a_task_answers_its_notice(store):
    """The notice existed to ask the operator. It has its answer."""
    task_id = _hold(store)
    inbox.notify(
        store,
        "c",
        "support",
        f"Task #{task_id} is waiting for an owner",
        "body",
        fix="backlog",
        options=(f"task:{task_id}",),
    )
    assert store.list_inbox("c", "pending")
    ctx = _Ctx(store, _Result({"assignments": [f"{task_id}|design|write_site_content"]}))
    tools._assign_held(ctx)
    assert not store.list_inbox("c", "pending"), "the operator is still being asked"


def test_notices_filed_before_they_carried_an_id_are_swept(store):
    """The operator was looking at two of those, pointing at tasks already re-owned."""
    task_id = _hold(store)
    inbox.notify(
        store, "c", "support", "A task is waiting for an owner", "old style", fix="backlog"
    )
    ctx = _Ctx(store, _Result({"assignments": [f"{task_id}|design|write_site_content"]}))
    tools._assign_held(ctx)
    assert not [i for i in store.list_inbox("c", "pending") if i["fix"] == "backlog"]


def test_a_notice_is_kept_while_a_task_is_still_held(store):
    """The sweep only fires when everything was placed. One task left means the
    operator still has a decision, and clearing their notice would hide it."""
    a, b = _hold(store, title="A"), _hold(store, title="B")
    inbox.notify(store, "c", "support", f"Task #{b} is waiting for an owner", "", fix="backlog")
    ctx = _Ctx(store, _Result({"assignments": [f"{a}|design|write_site_content"]}))
    tools._assign_held(ctx)
    assert [i for i in store.list_inbox("c", "pending") if i["fix"] == "backlog"]


def test_it_is_on_the_ceos_playbook_before_reviewing_new_proposals():
    """A task already approved and then held is work the CEO has said yes to.
    Arbitrating fresh ideas while leaving it for the operator is the wrong order."""
    from corparius.models import AgentRole

    book = ROSTER[AgentRole.CEO].playbook
    assert "assign_held_tasks" in book
    assert book.index("assign_held_tasks") < book.index("review_proposals")
