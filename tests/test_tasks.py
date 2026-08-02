"""The CEO owns the backlog: it creates and arbitrates, others execute, others
may only propose."""

import types

from corparius import tools
from corparius.config import Settings
from corparius.orchestrator import Runtime
from corparius.store import Store
from corparius.structured import Result


def _settings(tmp) -> Settings:
    s = Settings()
    s.llm_mock = True
    s.data_path = str(tmp)
    return s


def test_store_task_lifecycle(tmp_path):
    store = Store(str(tmp_path))
    tid = store.add_task("c", "Do X", "outreach", 2, "approved", "ceo")
    assert store.list_tasks("c", "approved")
    task = store.claim_next_task("c", "outreach")
    assert task["id"] == tid
    assert store.list_tasks("c", "in_progress")
    store.complete_task(tid)
    assert store.list_tasks("c", "done")
    assert store.claim_next_task("c", "outreach") is None


def test_agents_propose_and_ceo_decides(tmp_path, monkeypatch):
    store = Store(str(tmp_path))
    # Two roles, not one role twice: a role keeps a single open idea with the
    # CEO now. Support ran every three hours and filed five identical "Idea from
    # support" rows in one measured session, none carrying a tool.
    for role in ("support", "design"):
        tools._propose_task(
            types.SimpleNamespace(
                company={"slug": "t"},
                store=store,
                role=role,
                structured=Result(
                    data={"idea": f"An idea from {role}", "why": ""}, ok=True, attempts=1
                ),
            )
        )
    assert len(store.list_tasks("t", "proposed")) == 2
    monkeypatch.setenv("CORP_CEO_APPROVE_CAP", "1")
    ceo_ctx = types.SimpleNamespace(company={"slug": "t"}, store=store)
    out = tools._review_proposals(ceo_ctx)
    assert "1 approved" in out and "1 rejected" in out
    assert not store.list_tasks("t", "proposed")  # every proposal was decided


def test_ceo_creates_and_agents_execute(tmp_path):
    s = _settings(tmp_path)
    store = Store(s.data_path)
    store.save_state("t", {"tick": 0})
    cfg = {
        "slug": "t",
        "name": "T",
        "offer": {"product": "p"},
        "icp": {"segment": "b", "pains": ["x"]},
        "agents": {
            "ceo": True,
            "outreach": True,
            "social": True,
            "support": True,
            "finance": False,
            "strategy": False,
            "competitor": False,
            "ads": False,
            "design": False,
            "coder": False,
        },
        "budgets": {"session_tokens": 100000, "tokens_per_minute": 100000},
        "hitl_tools": [],
    }
    Runtime(s, store).run(cfg, ticks=6)
    assert store.list_tasks("t", "done"), "agents should complete CEO-created tasks"


def test_ceo_modifies_proposal_on_approval(tmp_path):
    store = Store(str(tmp_path))
    tid = store.add_task("t", "Idea", "support", 1, "proposed", "support")
    ceo_ctx = types.SimpleNamespace(company={"slug": "t"}, store=store)
    tools._review_proposals(ceo_ctx)
    task = next(x for x in store.list_tasks("t") if x["id"] == tid)
    assert task["status"] == "approved"
    assert task["priority"] == 2  # re-prioritised by the CEO
    assert task["tool"] == "draft_support_reply"  # made executable by the CEO


def test_backlog_task_runs_the_real_tool(tmp_path):
    s = _settings(tmp_path)
    store = Store(s.data_path)
    store.save_state("t", {"tick": 0})
    store.record_action(
        "t", "competitor", "scan_signals", {}, "Signals detected (1): Acme is hiring a CISO", True
    )  # data for the CEO
    cfg = {
        "slug": "t",
        "name": "T",
        "offer": {"product": "p"},
        "icp": {"segment": "b", "pains": ["x"]},
        "agents": {
            "ceo": True,
            "outreach": True,
            "social": False,
            "support": False,
            "finance": False,
            "strategy": False,
            "competitor": False,
            "ads": False,
            "design": False,
            "coder": False,
        },
        "budgets": {"session_tokens": 100000, "tokens_per_minute": 100000},
        "hitl_tools": [],
    }
    Runtime(s, store).run(cfg, ticks=1)
    done = store.list_tasks("t", "done")
    assert done and done[0]["tool"] == "send_outreach"  # task carried a tool
    assert store.status("t")["by_agent"].get("outreach", 0) >= 1  # the tool ran


def test_ceo_creates_tasks_from_signals(tmp_path):
    store = Store(str(tmp_path))
    store.record_action(
        "t", "competitor", "scan_signals", {}, "Signals detected (2): Beta raised a round", True
    )
    ctx = types.SimpleNamespace(
        company={"slug": "t", "agents": {"outreach": True, "social": True, "support": True}},
        store=store,
    )
    tools._create_tasks(ctx)
    outreach = [t for t in store.list_tasks("t", "approved") if t["target"] == "outreach"]
    assert outreach and outreach[0]["tool"] == "send_outreach"
    assert outreach[0]["priority"] == 3  # a live signal raises the priority


def test_ceo_queues_baseline_without_data(tmp_path):
    store = Store(str(tmp_path))
    ctx = types.SimpleNamespace(
        company={"slug": "t", "agents": {"outreach": True, "social": True, "support": True}},
        store=store,
    )
    tools._create_tasks(ctx)
    targets = {t["target"] for t in store.list_tasks("t", "approved")}
    assert targets == {"social", "support"}  # no data -> baseline only, no outreach


# --------------------------------------------------------------------------
# A backlog row has to say what it is
# --------------------------------------------------------------------------


def _idea(text, why=""):
    return Result(data={"idea": text, "why": why}, ok=True, attempts=1)


def _ctx(store, role="support", **kw):
    return types.SimpleNamespace(company={"slug": "t"}, store=store, role=role, **kw)


def test_a_proposal_says_what_it_is(tmp_path):
    """The title was generated from the role — "Idea from support", forever. The
    operator saw four of them in a column and could not tell one from another,
    and neither could the CEO reviewing them."""
    store = Store(str(tmp_path))
    ctx = _ctx(store, structured=_idea("Answer the three refund tickets", "two are 4 days old"))
    out = tools._propose_task(ctx)

    task = store.list_tasks("t", "proposed")[0]
    assert task["title"] == "Answer the three refund tickets"
    assert task["why"] == "two are 4 days old"
    assert "Idea from" not in task["title"] and "Idea from" not in out
    store.close()


def test_nothing_to_propose_files_nothing(tmp_path):
    """An empty backlog is readable. A backlog of placeholders is not."""
    store = Store(str(tmp_path))
    out = tools._propose_task(_ctx(store, structured=_idea("   ")))
    assert store.list_tasks("t") == []
    assert "nothing specific" in out
    store.close()


def test_the_same_idea_is_not_filed_twice(tmp_path):
    """One per role stopped the pile growing while the title was generated. Now
    that the agent writes it, the same thought worded identically must not come
    back after the CEO has already ruled on it."""
    store = Store(str(tmp_path))
    tools._propose_task(_ctx(store, structured=_idea("Answer the refund tickets")))
    store.set_task_status(store.list_tasks("t")[0]["id"], "rejected", "declined by CEO")

    out = tools._propose_task(_ctx(store, structured=_idea("answer the REFUND tickets")))
    assert "already proposed" in out
    assert len(store.list_tasks("t")) == 1
    store.close()


def test_the_reason_survives_the_ceo_deciding(tmp_path, monkeypatch):
    """`set_task_status` overwrites `note` on every transition — "validated by
    CEO" — so the reason a task existed died the moment somebody acted on it,
    which is the one moment it was worth having."""
    store = Store(str(tmp_path))
    tools._propose_task(_ctx(store, structured=_idea("Ship the pricing page", "3 asked for it")))
    monkeypatch.setenv("CORP_CEO_APPROVE_CAP", "1")
    tools._review_proposals(types.SimpleNamespace(company={"slug": "t"}, store=store))

    task = store.list_tasks("t", "approved")[0]
    assert task["note"] == "validated by CEO", "who decided is still recorded"
    assert task["why"] == "3 asked for it", "and so is why it was proposed"
    store.close()


def test_a_second_idea_costs_nothing_to_refuse(tmp_path):
    """`propose_task` needs a draft now, so the cap has to be checked before the
    model is called. Support reaches this tool every three hours; without the
    guard it would pay for a proposal the effect then discards."""
    store = Store(str(tmp_path))
    tools._propose_task(_ctx(store, structured=_idea("Answer the refund tickets")))
    assert "already has an idea" in tools.TOOLS["propose_task"].skip_reason(_ctx(store))
    assert tools.TOOLS["propose_task"].skip_reason(_ctx(store, role="design")) == ""
    store.close()
