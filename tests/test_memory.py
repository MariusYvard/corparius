"""Company memory: yesterday's summary survives into the next run, and a loop
that runs for days actually reads the summaries it writes."""

from corparius import orchestrator
from corparius.config import Settings
from corparius.orchestrator import Runtime
from corparius.store import Store


def _settings(tmp) -> Settings:
    s = Settings()
    s.llm_mock = True
    s.data_path = str(tmp)
    return s


def _cfg() -> dict:
    return {
        "slug": "m",
        "name": "M",
        "offer": {"product": "p"},
        "agents": {
            "ceo": True,
            "social": False,
            "finance": False,
            "outreach": False,
            "support": False,
            "strategy": False,
            "competitor": False,
            "ads": False,
            "design": False,
            "coder": False,
        },
        "budgets": {"session_tokens": 100000, "tokens_per_minute": 100000},
        "hitl_tools": [],
    }


def test_eod_summary_is_remembered(tmp_path):
    s = _settings(tmp_path)
    store = Store(s.data_path)
    store.save_state("m", {"tick": 0})
    Runtime(s, store).run(_cfg(), ticks=1)  # CEO runs at tick 0 and writes a summary
    memory = store.recent_outputs("m", "write_eod_summary", 3)
    assert memory and "EOD summary" in memory[0]


def test_a_running_loop_reads_the_summaries_it_writes(tmp_path, monkeypatch):
    """The regression this file used to miss: it proved the summary reached the
    store, never that it reached a prompt. A --loop company wrote one every day
    and planned every morning as if newborn, because memory was read once before
    the loop and never again.

    The mock provider echoes its prompt, so set_daily_plan's recorded output
    contains the exact "Yesterday: ..." the CEO was handed.
    """
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    store = Store(str(tmp_path))
    store.save_state("m", {"tick": 0})

    # run(loop=True) never returns; cut it off at the third day boundary.
    calls = {"n": 0}

    def stop_after_three_days(_seconds):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(orchestrator.time, "sleep", stop_after_three_days)

    try:
        Runtime(Settings(), store).run(_cfg(), ticks=24, loop=True)
    except KeyboardInterrupt:
        pass

    plans = [
        r["output"]
        for r in store.db.execute(
            "SELECT output FROM actions WHERE company='m' AND tool='set_daily_plan' ORDER BY ts"
        )
    ]
    assert len(plans) > 2, "the loop should have planned on several days"
    # Day one is blind for real: nothing had happened yet.
    assert "no prior summary" in plans[0]
    # Every later day must carry yesterday in.
    assert all("EOD summary" in p for p in plans[2:]), (
        "a day after the first planned with no memory of the day before"
    )
