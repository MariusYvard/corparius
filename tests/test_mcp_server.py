"""The MCP server's logic must work through its plain functions, with no `mcp`
dependency imported (only build_server needs it)."""

from app import mcp_server
from app.store import Store


def test_run_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server.settings, "data_path", str(tmp_path))
    monkeypatch.setattr(mcp_server.settings, "llm_mock", True)
    Store(str(tmp_path)).save_state("example", {"tick": 0})
    res = mcp_server.run_company("example", ticks=1)
    assert res["ticks_run"] == 1
    st = mcp_server.company_status("example")
    assert st["company"] == "example" and st["actions"] > 0


def test_decide_task_modifies_and_approves(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server.settings, "data_path", str(tmp_path))
    store = Store(str(tmp_path))
    tid = store.add_task("example", "Idea", "support", 1, "proposed", "support")
    out = mcp_server.decide_task("example", tid, "approve", tool="draft_support_reply", priority=2)
    assert out["action"] == "approve" and "tool" in out["modified"]
    task = store.list_tasks("example", "approved")[0]
    assert task["tool"] == "draft_support_reply" and task["priority"] == 2
