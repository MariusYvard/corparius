"""A task that closes without doing anything, and the loop it creates.

Measured in a real store, from a real run: **24 tasks for one role carrying no
tool, 22 of them closed with the note "done (no tool mapped)"**. Nothing had
happened. And because nothing had happened, the condition that produced the task
was still there on the next turn, so the agent proposed it again — six
near-identical proposals about one badge on one landing page, each approved, each
closed, none of it done. The board showed green rows and the site never changed.

Three separate defects met there, and each has its own test below.

1. `ROLE_TOOL` makes an approved task executable, and only one of the two
   approval paths reached it. The CEO's `review_proposals` attached the tool; the
   operator's own button in the console did not — and that is the one the operator
   presses. The registry rule, one more time: both ends of the wire.
2. A task nothing can run was completed rather than held, which is a lie the
   backlog tells about itself.
3. The proposer was the owner, always. Support therefore owned "remove the
   unverified badge from the landing page", and support's tool drafts a support
   reply: the badge stayed, an unrelated reply was written, the task went green.
"""

import pytest

from corparius import tools
from corparius.store import Store
from corparius.tools import ROLE_TOOL, TOOLS, executable_fields


class _Ctx:
    def __init__(self, store, slug="c", role="support", agents=None, structured=None):
        self.store = store
        self.company = {
            "slug": slug,
            "name": "Vigil",
            "agents": agents if agents is not None else {"support": True, "design": True},
        }
        self.role = role
        self.structured = structured


class _Result:
    def __init__(self, data):
        self.data = data


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path))
    yield s
    s.close()


# --- 1. the tool, at both ends of the wire -----------------------------------


def test_the_registry_is_reached_when_the_console_approves(store):
    """The end that was missing. An operator pressing Approve has to leave the
    task in the same state the CEO would have left it in."""
    from corparius.webui import _edit_task

    task_id = store.add_task("c", "Remove the unverified badge", "design", status="proposed")
    code, body = _edit_task(store, {"id": task_id, "decision": "approved"})
    assert code == 200, body
    row = store.get_task(task_id)
    assert row["status"] == "approved"
    assert row["tool"] == ROLE_TOOL["design"], (
        "approved from the console and still not executable: this is the bug"
    )


def test_the_registry_is_reached_when_the_ceo_approves(store):
    task_id = store.add_task("c", "Remove the unverified badge", "design", status="proposed")
    tools._review_proposals(_Ctx(store, role="ceo"))
    assert store.get_task(task_id)["tool"] == ROLE_TOOL["design"]


def test_both_ends_leave_a_task_in_the_same_state(store):
    """Stated as the property rather than as two examples, because the next
    approval path added should have to satisfy it too."""
    from corparius.webui import _edit_task

    by_console = store.add_task("c", "A", "support", status="proposed")
    by_ceo = store.add_task("c", "B", "support", status="proposed")
    _edit_task(store, {"id": by_console, "decision": "approved"})
    tools._review_proposals(_Ctx(store, role="ceo"))
    assert store.get_task(by_console)["tool"] == store.get_task(by_ceo)["tool"] != ""


def test_a_tool_the_operator_chose_is_not_overwritten(store):
    from corparius.webui import _edit_task

    task_id = store.add_task("c", "A", "support", status="proposed")
    _edit_task(store, {"id": task_id, "decision": "approved", "tool": "write_site_content"})
    assert store.get_task(task_id)["tool"] == "write_site_content"


def test_executable_fields_says_nothing_when_there_is_nothing_to_say():
    assert executable_fields({"target": "support", "tool": "draft_support_reply"}) == {}
    assert executable_fields({"target": "finance", "tool": ""}) == {}  # no default for that role
    assert executable_fields({"target": "", "tool": ""}) == {}


def test_every_role_tool_default_can_actually_change_something():
    """`build_sales_site` renders the copy already in company.yaml. A task "change
    what the page says" completed through it rebuilds the same page and reports
    success — which is the same lie by a different route."""
    assert ROLE_TOOL["design"] == "write_site_content"
    assert all(name in TOOLS for name in ROLE_TOOL.values())


# --- 2. held, not closed -----------------------------------------------------


def test_a_task_nothing_can_run_is_held_and_not_marked_done(store, monkeypatch):
    from corparius.agents import Executor

    task_id = store.add_task("c", "Audit the landing page", "finance", status="approved")
    task = store.claim_next_task("c", "finance")
    agent = Executor.__new__(Executor)  # no LLM, no router: this path calls neither
    agent.store = store
    done: list[str] = []
    agent._hold_untooled("c", task, done)

    row = store.get_task(task_id)
    assert row["status"] == "waiting", f"status is {row['status']}, so it will run again forever"
    assert row["status"] != "done", "a task that did nothing must not be marked done"
    assert "no tool" in row["note"]
    assert done and "held" in done[0] and "Audit the landing page" in done[0]


def test_the_path_that_runs_a_task_is_the_one_that_holds_it(store):
    """Through `_work_task`, not through the helper. The first version of these
    tests called `_hold_untooled` directly and passed against the old code, which
    still completed the task — a test of a function nothing calls proves nothing.
    That is the same mistake this whole file is about."""
    from corparius.agents import Executor

    task_id = store.add_task("c", "Audit the landing page", "finance", status="approved")
    agent = Executor.__new__(Executor)
    agent.store = store
    done: list[str] = []

    class Ctx:
        """`_work_task` sets and clears `ctx.task` on every path now, so it needs
        somewhere to put it. Nothing else here is touched on the untooled path."""

        task = None

    ctx = Ctx()
    stop = agent._work_task("c", None, ctx, store.claim_next_task("c", "finance"), None, done)
    assert ctx.task is None, "the task must not outlive the call, even on this path"
    assert stop is False
    assert store.get_task(task_id)["status"] == "waiting"
    assert "(symbolic)" not in " ".join(done)


def test_holding_it_tells_the_operator_where_to_go(store):
    from corparius.agents import Executor
    from corparius.inbox import FIXES

    task = {"id": 1, "title": "Audit the landing page", "target": "finance"}
    agent = Executor.__new__(Executor)
    agent.store = store
    agent._hold_untooled("c", task, [])
    items = store.list_inbox("c", "pending")
    assert items, "held silently is held invisibly"
    assert items[0]["fix"] == "backlog" and FIXES["backlog"] == "operations"


def test_a_held_task_is_not_picked_up_again(store):
    """`claim_next_task` orders by priority then age. A task that can never run
    and stays in the queue is picked first for that role forever, so everything
    behind it starves."""
    from corparius.agents import Executor

    stuck = store.add_task("c", "Cannot run", "finance", priority=5, status="approved")
    runnable = store.add_task("c", "Can run", "finance", priority=1, status="approved")
    agent = Executor.__new__(Executor)
    agent.store = store
    agent._hold_untooled("c", store.claim_next_task("c", "finance"), [])
    assert store.claim_next_task("c", "finance")["id"] == runnable
    assert store.get_task(stuck)["status"] == "waiting"


def test_a_held_task_is_not_released_by_the_poller(store):
    """`release_waiting_tasks` releases what an approval or a question was holding.
    A task waiting on a human decision names no blocker, so it must stay put
    rather than come back untooled."""
    from corparius.agents import Executor

    task_id = store.add_task("c", "Cannot run", "finance", status="approved")
    agent = Executor.__new__(Executor)
    agent.store = store
    agent._hold_untooled("c", store.claim_next_task("c", "finance"), [])
    assert store.release_waiting_tasks("c") == {"released": 0, "refused": 0}
    assert store.get_task(task_id)["status"] == "waiting"


# --- 3. the owner is whoever does the work -----------------------------------


def test_a_proposal_can_name_the_role_that_should_do_it(store):
    ctx = _Ctx(store, structured=_Result({"idea": "Remove the badge", "owner": "design"}))
    out = tools._propose_task(ctx)
    assert "for design" in out
    assert store.list_tasks("c")[0]["target"] == "design"


def test_no_owner_named_keeps_it_with_the_proposer(store):
    ctx = _Ctx(store, structured=_Result({"idea": "Answer the doctor", "owner": ""}))
    tools._propose_task(ctx)
    assert store.list_tasks("c")[0]["target"] == "support"


def test_an_owner_that_is_not_a_role_is_named_not_swallowed(store):
    ctx = _Ctx(store, structured=_Result({"idea": "Fix the page", "owner": "webmaster"}))
    out = tools._propose_task(ctx)
    assert "webmaster" in out and "not a role" in out
    assert store.list_tasks("c")[0]["target"] == "support"


def test_an_owner_the_company_switched_off_is_refused_out_loud(store):
    """Not silently retargeted: an agent asked for something, and a proposal
    quietly moved to whoever happens to be running is a decision nobody made."""
    ctx = _Ctx(
        store,
        agents={"support": True, "design": False},
        structured=_Result({"idea": "Rewrite the hero", "owner": "design"}),
    )
    out = tools._propose_task(ctx)
    assert "off" in out and "design" in out
    assert store.list_tasks("c")[0]["target"] == "support"


def test_the_owner_field_is_in_the_prompt_the_model_reads():
    """A schema field the prompt never mentions is a field the model leaves at its
    default, which is how `_CEO_SCHEMA["model"]` shipped doing nothing."""
    tool = next(t for t in TOOLS.values() if t.name == "propose_task")
    assert "owner" in tool.schema
    ctx = _Ctx(None)
    assert "owner" in tool.draft_prompt(ctx) and "design" in tool.draft_prompt(ctx)


# --- and the roster refusal --------------------------------------------------


def test_a_refused_roster_change_is_not_reported_as_a_change(store):
    """Measured on a real run: "Roster changed — left off, you stood them down:
    social", on turn after turn, while the roster was exactly as the operator had
    left it."""
    store.add_directive("c", "pause", "social", "paused by the operator")
    out = tools._set_roster(_Ctx(store, role="ceo", agents={"social": True}), "social")
    assert out.startswith("Roster unchanged"), out
    assert "social" in out and "stood them down" in out


def test_a_real_roster_change_still_reports_one(store):
    out = tools._set_roster(_Ctx(store, role="ceo"), "-social")
    assert out.startswith("Roster changed") and "off: social" in out


# --- and who a proposal is actually for --------------------------------------


def test_a_proposal_is_not_counted_as_the_operators_when_a_ceo_reviews_them(tmp_path, monkeypatch):
    """The console counted every proposal in its "needs you" badge and labelled
    the column "your call". So an agent noticing that the landing page claimed 12
    early-access users with nothing behind it read, to the operator, as the company
    stopping to ask permission for trivia. The CEO reviews proposals; that is what
    a CEO is for."""
    from corparius import webui

    monkeypatch.setattr(
        webui, "_load_company", lambda slug: {"slug": slug, "agents": {"ceo": True}}
    )
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    state = webui.UiState(webui._fresh_settings(), tmp_path / ".env")
    try:
        state.store().add_task("c", "Remove the unverified badge", "design", status="proposed")
        assert webui._overview(state, "c")["proposals_need_you"] is False
    finally:
        state.close()


def test_it_is_the_operators_when_no_ceo_will_look(tmp_path, monkeypatch):
    """A CEO switched off, and the proposals really would sit there forever.
    Saying nothing then is worse than one badge too many."""
    from corparius import webui

    monkeypatch.setattr(
        webui, "_load_company", lambda slug: {"slug": slug, "agents": {"ceo": False}}
    )
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    state = webui.UiState(webui._fresh_settings(), tmp_path / ".env")
    try:
        state.store().add_task("c", "A", "design", status="proposed")
        assert webui._overview(state, "c")["proposals_need_you"] is True
    finally:
        state.close()


def test_it_is_the_operators_when_the_ceo_is_stood_down(tmp_path, monkeypatch):
    from corparius import webui

    monkeypatch.setattr(
        webui, "_load_company", lambda slug: {"slug": slug, "agents": {"ceo": True}}
    )
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    state = webui.UiState(webui._fresh_settings(), tmp_path / ".env")
    try:
        state.store().add_directive("c", "pause", "ceo", "paused by the operator")
        assert webui._overview(state, "c")["proposals_need_you"] is True
    finally:
        state.close()


def test_the_column_has_a_label_for_both_cases_in_both_languages():
    from pathlib import Path

    html = Path("corparius/webui.html").read_text(encoding="utf-8")
    assert html.count('"col.proposedCeo"') == 3, "en, fr, and the one place that reads it"
    assert '"col.proposedCeo":"Proposed, for the CEO"' in html
    assert '"col.proposedCeo":"Proposées, pour le CEO"' in html


# --- and the operator can correct it on the board ------------------------------


def test_the_task_editor_offers_the_agent_and_the_tool():
    """`/api/tasks` has accepted `target` and `tool` all along and the editor never
    offered them, so a task on the wrong role — or with no tool at all — could not
    be corrected from the board where it is shown. The operator said it plainly:
    even in the backlog, I cannot change the agent or the tool."""
    from pathlib import Path

    html = Path("corparius/webui.html").read_text(encoding="utf-8")
    editor = html[html.index("function openTaskEditor(") : html.index("const reducedMotion")]
    assert 'data-f="target"' in editor and 'data-f="tool"' in editor
    assert "agent_tools" in editor, "the lists must be the real roles and playbooks"
    assert 'value=""' in editor, "a task may legitimately have no tool"


def test_the_editor_sends_them_only_when_it_rendered_them():
    """A console with no enabled agents must not blank a task's target by saving a
    field that was never on screen."""
    from pathlib import Path

    html = Path("corparius/webui.html").read_text(encoding="utf-8")
    handler = html[html.index("if (b.dataset.taskSave)") : html.index("if (b.dataset.taskCancel)")]
    assert 'if (pick("target")) body.target' in handler
    assert 'if (pick("tool")) body.tool' in handler


def test_changing_the_agent_in_the_editor_re_offers_its_tools():
    from pathlib import Path

    html = Path("corparius/webui.html").read_text(encoding="utf-8")
    assert 'ev.target.closest("[data-task-owner]")' in html
    block = html[html.index('ev.target.closest("[data-task-owner]")') :][:800]
    assert "agent_tools" in block and "box.innerHTML" in block


def test_the_api_accepts_what_the_editor_now_sends(store):
    """The other end of the wire, exercised rather than read."""
    from corparius.webui import _edit_task

    task_id = store.add_task("c", "Remove the badge", "support", status="approved")
    code, body = _edit_task(
        store, {"id": task_id, "target": "design", "tool": "write_site_content"}
    )
    assert code == 200, body
    row = store.get_task(task_id)
    assert (row["target"], row["tool"]) == ("design", "write_site_content")


def test_an_unknown_tool_is_refused_rather_than_stored(store):
    """A task scoped to a tool nobody has never applies, silently — worse than the
    untooled task it was meant to fix."""
    from corparius.webui import _edit_task

    task_id = store.add_task("c", "x", "support", status="approved")
    code, body = _edit_task(store, {"id": task_id, "tool": "no_such_tool"})
    assert code == 400 and "unknown tool" in body["error"]
    code, body = _edit_task(store, {"id": task_id, "target": "webmaster"})
    assert code == 400 and "unknown agent" in body["error"]
