"""The MCP server's logic must work through its plain functions, with no `mcp`
dependency imported (only build_server needs it)."""

import shutil

import pytest

from corparius import mcp_server
from corparius.store import Store

from .conftest import EXAMPLE_COMPANY


@pytest.fixture(autouse=True)
def _reset_store_singleton(tmp_path, monkeypatch):
    """The server caches one Store for the process. Each test points settings at
    a fresh tmp_path, so the cached instance must be cleared or a test would
    reuse the previous test's (now closed) connection.

    And a private home, because `run_company("example", ticks=1)` below is a real
    tick: its tools save the company config and write documents, and with no
    CORP_HOME set they landed in the checkout's own tracked example — comments
    gone, `site:` block gone, four written documents rewritten.
    """
    home = tmp_path / "home"
    shutil.copytree(EXAMPLE_COMPANY, home / "companies" / "example")
    monkeypatch.setenv("CORP_HOME", str(home))
    mcp_server._store_singleton = None
    yield
    mcp_server._store_singleton = None


def _hermetic(monkeypatch, tmp_path):
    """Point the MCP server at a private store, through the **environment**.

    These tests patched attributes on `mcp_server.settings` — the module-level snapshot taken at
    import. That snapshot is gone: it made the data path whatever the environment said when the
    module loaded, so an MCP tool exercised from a test silently opened the developer's own store.
    Found by an assertion that failed because the approval it had just written was in a different
    database, and it is the fourth module to learn this after `backup.py`, `app.support.open_store`
    and the eight CLI groups.

    `_store_singleton` is cleared by the fixture either side, so each test resolves the path afresh.
    """
    from corparius.config import cfg

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    cfg.invalidate()
    mcp_server._store_singleton = None


def test_tool_calls_reuse_one_connection(tmp_path, monkeypatch):
    """The fix for the per-call Store leak: every tool call shares one Store
    instead of opening (and never closing) a new sqlite connection each time."""
    _hermetic(monkeypatch, tmp_path)
    Store(str(tmp_path)).save_state("example", {"tick": 0})
    mcp_server.company_status("example")
    first = mcp_server._store_singleton
    mcp_server.list_backlog("example")
    mcp_server.list_pending_approvals("example")
    assert mcp_server._store_singleton is first, "each tool call rebuilt the store"


def test_run_and_status(tmp_path, monkeypatch):
    _hermetic(monkeypatch, tmp_path)
    Store(str(tmp_path)).save_state("example", {"tick": 0})
    res = mcp_server.run_company("example", ticks=1)
    assert res["ticks_run"] == 1
    st = mcp_server.company_status("example")
    assert st["company"] == "example" and st["actions"] > 0


def test_decide_task_modifies_and_approves(tmp_path, monkeypatch):
    _hermetic(monkeypatch, tmp_path)
    store = Store(str(tmp_path))
    tid = store.add_task("example", "Idea", "support", 1, "proposed", "support")
    out = mcp_server.decide_task("example", tid, "approve", tool="draft_support_reply", priority=2)
    assert out["action"] == "approve" and "tool" in out["modified"]
    task = store.list_tasks("example", "approved")[0]
    assert task["tool"] == "draft_support_reply" and task["priority"] == 2
