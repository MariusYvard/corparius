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
from corparius.tools import TOOLS


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


# --- and the CEO turns what the agents wrote into work -------------------------


def _doc(tmp_path, monkeypatch, name, text, stamp=None):
    from corparius import documents

    monkeypatch.setattr(documents.paths, "companies_dir", lambda: tmp_path)
    folder = tmp_path / "c" / "documents" / "written"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.md"
    path.write_text(f"# {name}\n\n{text}\n", encoding="utf-8")
    if stamp:
        import os

        os.utime(path, (stamp, stamp))
    return path


def test_the_ceo_reads_what_its_agents_wrote(store, tmp_path, monkeypatch):
    """`review_site` wrote sixteen named changes to documents, quoting the text to
    fix, and nothing read it. Data that arrives and is thrown away, with the data
    now being a whole document."""
    _doc(tmp_path, monkeypatch, "site-review", "index.html: replace 'we detect burnout'")
    prompt = tools._plan_from_docs_prompt(_Ctx(store))
    assert "we detect burnout" in prompt
    assert "role|tool|title" in prompt
    assert "design: " in prompt, "the roster has to be offered or the answer is unusable"


def test_it_never_plans_from_the_ceos_own_summary(store, tmp_path, monkeypatch):
    """`end-of-day.md` is rewritten on every CEO turn, so by mtime it is always the
    newest document — it would crowd out every finding another agent made. Measured:
    the first version read the summary while a design review naming sixteen changes
    sat fourth and never entered the window."""
    _doc(tmp_path, monkeypatch, "site-review", "REVIEW", stamp=1_000_000)
    _doc(tmp_path, monkeypatch, "end-of-day", "MIRROR", stamp=2_000_000)
    names = [d.path.stem for d in tools._agent_documents("c")]
    assert names == ["site-review"], names
    assert "MIRROR" not in tools._plan_from_docs_prompt(_Ctx(store))


def test_only_what_the_agents_wrote_is_read(store, tmp_path, monkeypatch):
    """A file the operator dropped in is theirs. Turning their price list into a
    backlog nobody asked for would be the product deciding what it means."""
    from corparius import documents

    monkeypatch.setattr(documents.paths, "companies_dir", lambda: tmp_path)
    root = tmp_path / "c" / "documents"
    root.mkdir(parents=True, exist_ok=True)
    (root / "operator-dropped.md").write_text("MINE", encoding="utf-8")
    _doc(tmp_path, monkeypatch, "site-review", "THEIRS")
    prompt = tools._plan_from_docs_prompt(_Ctx(store))
    assert "THEIRS" in prompt and "MINE" not in prompt


def test_nothing_written_means_nothing_asked(store, tmp_path, monkeypatch):
    from corparius import documents

    monkeypatch.setattr(documents.paths, "companies_dir", lambda: tmp_path)
    (tmp_path / "c").mkdir(parents=True, exist_ok=True)
    assert "no documents yet" in TOOLS["plan_from_documents"].skip_reason(_Ctx(store))


def test_it_queues_what_the_roster_can_honour(store, tmp_path, monkeypatch):
    _doc(tmp_path, monkeypatch, "site-review", "x")
    ctx = _Ctx(store, _Result({"tasks": ["design|write_site_content|Rewrite the hero"]}))
    out = tools._plan_from_docs(ctx)
    assert "Queued 1" in out
    row = store.list_tasks("c")[0]
    assert (row["target"], row["tool"], row["status"]) == (
        "design",
        "write_site_content",
        "approved",
    )
    assert row["title"] == "Rewrite the hero"


def test_an_off_playbook_pair_is_refused_and_named(store, tmp_path, monkeypatch):
    _doc(tmp_path, monkeypatch, "site-review", "x")
    ctx = _Ctx(store, _Result({"tasks": ["design|reconcile_stripe|Nope"]}))
    out = tools._plan_from_docs(ctx)
    assert "Refused" in out and not store.list_tasks("c")


def test_a_title_already_on_the_board_is_not_queued_twice(store, tmp_path, monkeypatch):
    _doc(tmp_path, monkeypatch, "site-review", "x")
    store.add_task("c", "Rewrite the hero", "design", status="approved")
    ctx = _Ctx(store, _Result({"tasks": ["design|write_site_content|Rewrite the hero"]}))
    out = tools._plan_from_docs(ctx)
    assert "already on the board" in out
    assert len(store.list_tasks("c")) == 1


def test_a_stood_down_role_is_not_given_work(store, tmp_path, monkeypatch):
    """The CEO's own stand-down has to hold against its own planning."""
    _doc(tmp_path, monkeypatch, "site-review", "x")
    store.add_directive("c", "pause", "design", "stood down")
    ctx = _Ctx(store, _Result({"tasks": ["design|write_site_content|Anything"]}))
    assert "stood down" in tools._plan_from_docs(ctx)
    assert not store.list_tasks("c")


def test_the_work_in_progress_limit_still_applies(
    store,
    tmp_path,
    monkeypatch,
):
    _doc(tmp_path, monkeypatch, "site-review", "x")
    for i in range(4):
        store.add_task("c", f"open {i}", "design", status="approved")
    ctx = _Ctx(store, _Result({"tasks": ["design|write_site_content|One more"]}))
    out = tools._plan_from_docs(ctx)
    assert "work-in-progress limit" in out


def test_at_most_four_tasks_come_out_of_one_document(store, tmp_path, monkeypatch):
    """A document naming sixteen changes must not become sixteen tasks in one turn."""
    _doc(tmp_path, monkeypatch, "site-review", "x")
    ctx = _Ctx(
        store,
        _Result({"tasks": [f"support|draft_support_reply|Task {i}" for i in range(9)]}),
    )
    tools._plan_from_docs(ctx)
    assert len(store.list_tasks("c")) <= 4


def test_it_is_on_the_ceos_playbook_after_the_baseline():
    """A design review naming sixteen changes is worth more than "Publish a post
    today", and should not compete with it for the work-in-progress limit."""
    from corparius.models import AgentRole

    book = ROSTER[AgentRole.CEO].playbook
    assert book.index("plan_from_documents") > book.index("create_tasks")
