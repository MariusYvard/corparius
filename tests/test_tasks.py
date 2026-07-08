"""The CEO owns the backlog: it creates and arbitrates, others execute, others
may only propose."""
import types

from app.config import Settings
from app.store import Store
from app.orchestrator import Runtime
from app import tools


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
    agent_ctx = types.SimpleNamespace(company={"slug": "t"}, store=store, role="support")
    tools._propose_task(agent_ctx)
    tools._propose_task(agent_ctx)
    assert len(store.list_tasks("t", "proposed")) == 2
    monkeypatch.setenv("CORP_CEO_APPROVE_CAP", "1")
    ceo_ctx = types.SimpleNamespace(company={"slug": "t"}, store=store)
    out = tools._review_proposals(ceo_ctx)
    assert "1 approved, 1 rejected" in out
    assert not store.list_tasks("t", "proposed")   # every proposal was decided


def test_ceo_creates_and_agents_execute(tmp_path):
    s = _settings(tmp_path)
    store = Store(s.data_path)
    store.save_state("t", {"tick": 0})
    cfg = {
        "slug": "t", "name": "T", "offer": {"product": "p"},
        "icp": {"segment": "b", "pains": ["x"]},
        "agents": {"ceo": True, "outreach": True, "social": True, "support": True,
                   "finance": False, "strategy": False, "competitor": False,
                   "ads": False, "design": False, "coder": False},
        "budgets": {"session_tokens": 100000, "tokens_per_minute": 100000},
        "hitl_tools": [],
    }
    Runtime(s, store).run(cfg, ticks=6)
    assert store.list_tasks("t", "done"), "agents should complete CEO-created tasks"
