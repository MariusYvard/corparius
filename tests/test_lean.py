"""Lean layer: a pull system with a WIP cap, flow metrics, and a kaizen signal."""
import types

from app import tools
from app.store import Store


def test_wip_count_and_flow_metrics(tmp_path):
    store = Store(str(tmp_path))
    store.add_task("c", "a", "outreach", 2, "approved", "ceo")
    store.add_task("c", "b", "outreach", 2, "in_progress", "ceo")
    store.add_task("c", "c", "social", 2, "done", "ceo")
    assert store.wip_count("c", "outreach") == 2
    fm = store.flow_metrics("c")
    assert fm["throughput"] == 1 and fm["wip"] == 2
    assert fm["bottleneck"] == "outreach"
    assert "defects" in fm and "waiting" in fm   # the seven-wastes lens


def test_create_tasks_respects_wip_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_WIP_LIMIT", "1")
    store = Store(str(tmp_path))
    # An existing open social task (different tool, so dedup does not hide the WIP cap).
    store.add_task("t", "existing", "social", 2, "approved", "ceo", tool="manual")
    ctx = types.SimpleNamespace(
        company={"slug": "t", "agents": {"social": True, "support": True}}, store=store)
    tools._create_tasks(ctx)
    social = [x for x in store.list_tasks("t") if x["target"] == "social"]
    assert len(social) == 1                      # WIP cap of 1 blocks a second social task
    assert any(x["target"] == "support" for x in store.list_tasks("t"))   # support still queued


def test_kaizen_flags_the_bottleneck(tmp_path):
    store = Store(str(tmp_path))
    for i in range(3):
        store.add_task("t", f"x{i}", "outreach", 2, "approved", "ceo")
    ctx = types.SimpleNamespace(company={"slug": "t"}, store=store)
    out = tools._kaizen(ctx)
    assert "bottleneck outreach" in out
    proposed = store.list_tasks("t", "proposed")
    assert proposed and proposed[0]["target"] == "outreach"
