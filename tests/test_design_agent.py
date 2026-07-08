"""The design agent must run its site-building tool end to end through the
executor (it receives a RunContext, not a raw company dict)."""
import os

from app.config import Settings
from app.store import Store
from app.orchestrator import Runtime


def _settings(tmp) -> Settings:
    s = Settings()
    s.llm_mock = True
    s.data_path = str(tmp)
    return s


def _cfg() -> dict:
    return {
        "slug": "d", "name": "D", "offer": {"product": "p", "price_eur": 5},
        "icp": {"segment": "buyers", "pains": ["slow"]},
        "agents": {"ceo": False, "social": False, "finance": False, "outreach": True,
                   "support": False, "strategy": False, "competitor": False,
                   "ads": False, "design": True, "coder": False},
        "budgets": {"session_tokens": 100000, "tokens_per_minute": 100000},
        "hitl_tools": ["deploy_site"],
    }


def test_design_agent_builds_the_site(tmp_path):
    s = _settings(tmp_path)
    store = Store(s.data_path)
    store.save_state("d", {"tick": 0})
    Runtime(s, store).run(_cfg(), ticks=1)   # design (daily) runs at tick 0
    status = store.status("d")
    assert status["by_agent"].get("design", 0) >= 1
    assert os.path.isfile(os.path.join(str(tmp_path), "sites", "d", "index.html"))
