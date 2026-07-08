"""Simple company memory: yesterday's summary survives into the next run."""
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
        "slug": "m", "name": "M", "offer": {"product": "p"},
        "agents": {"ceo": True, "social": False, "finance": False, "outreach": False,
                   "support": False, "strategy": False, "competitor": False,
                   "ads": False, "design": False, "coder": False},
        "budgets": {"session_tokens": 100000, "tokens_per_minute": 100000},
        "hitl_tools": [],
    }


def test_eod_summary_is_remembered(tmp_path):
    s = _settings(tmp_path)
    store = Store(s.data_path)
    store.save_state("m", {"tick": 0})
    Runtime(s, store).run(_cfg(), ticks=1)   # CEO runs at tick 0 and writes a summary
    memory = store.recent_outputs("m", "write_eod_summary", 3)
    assert memory and "EOD summary" in memory[0]
