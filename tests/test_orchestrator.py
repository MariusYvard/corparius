"""A simulated day must run every enabled agent, record its work, and hold the
money-moving tool at the human gate until it is approved."""

from app.config import Settings
from app.models import AgentRole
from app.orchestrator import Runtime, due_roles
from app.store import Store


def _cfg() -> dict:
    return {
        "slug": "t",
        "name": "T",
        "offer": {"product": "p"},
        "agents": {
            "ceo": True,
            "social": True,
            "finance": True,
            "outreach": True,
            "support": True,
            "strategy": True,
            "competitor": True,
            "ads": False,
            "coder": False,
        },
        "budgets": {"session_tokens": 100000, "tokens_per_minute": 100000},
        "hitl_tools": ["send_financial_transaction", "publish_production_code"],
    }


def _settings(tmp) -> Settings:
    s = Settings()
    s.llm_mock = True
    s.data_path = str(tmp)
    return s


def test_cadences_are_staggered():
    enabled = {r.value: True for r in AgentRole}
    due0 = {s.role for s in due_roles(0, enabled)}
    assert AgentRole.CEO in due0 and AgentRole.SOCIAL in due0
    assert due_roles(1, enabled) == []  # nothing divides hour 1
    due2 = {s.role for s in due_roles(2, enabled)}
    assert AgentRole.SOCIAL in due2 and AgentRole.CEO not in due2


def test_day_runs_and_records_actions(tmp_path):
    s = _settings(tmp_path)
    store = Store(s.data_path)
    store.save_state("t", {"tick": 0})
    result = Runtime(s, store).run(_cfg(), ticks=6, loop=False)
    assert result["ticks_run"] == 6
    status = store.status("t")
    assert status["actions"] > 0
    assert status["tokens"] > 0
    # Finance tries to pay an invoice: that tool is gated, so one approval waits.
    assert status["pending_approvals"] >= 1


def test_money_tool_waits_then_executes_after_approval(tmp_path):
    s = _settings(tmp_path)
    store = Store(s.data_path)
    store.save_state("t", {"tick": 0})
    Runtime(s, store).run(_cfg(), ticks=6)
    pending = store.list_approvals("t", "pending")
    assert pending, "the money transfer should be held for approval"
    store.set_approval_status(pending[0]["id"], "approved")
    Runtime(s, store).run(_cfg(), ticks=6)  # next day
    assert store.find_approval("t", "send_financial_transaction", {}, "approved")


def test_circuit_breaker_freezes_the_session(tmp_path):
    s = _settings(tmp_path)
    store = Store(s.data_path)
    store.save_state("t", {"tick": 0})
    cfg = _cfg()
    cfg["budgets"]["tokens_per_minute"] = 1  # trips on the first draft call
    result = Runtime(s, store).run(cfg, ticks=6)
    assert result["frozen"] is True
    # It froze inside the first tick, so most of the roster never ran.
    assert store.status("t")["actions"] < 10


def test_dead_llm_stops_the_run_cleanly(tmp_path, monkeypatch):
    """An unreachable LLM must leave a system action in the store and stop the
    run instead of crashing without a trace."""
    import requests as _requests

    from app.orchestrator import Runtime

    s = _settings(tmp_path)
    s.llm_mock = False
    store = Store(s.data_path)
    rt = Runtime(s, store)

    def _boom(*a, **k):
        raise _requests.exceptions.ConnectionError("ollama down")

    monkeypatch.setattr(rt.router, "generate", _boom)
    result = rt.run(_cfg(), ticks=2)
    assert result["frozen"] is True
    rows = store.db.execute(
        "SELECT tool, output FROM actions WHERE company='t' AND tool='llm_unreachable'"
    ).fetchall()
    assert len(rows) == 1
    assert "doctor" in rows[0]["output"]
