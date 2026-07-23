"""MCP server exposing corparius to any MCP host (Claude Cowork, Claude Code, or
an MCP-capable agent runtime). The logic lives in plain functions so it stays
testable without the optional `mcp` dependency; the FastMCP wrapper is thin.

Install and run:
    pip install -r requirements-mcp.txt
    python -m corparius.mcp_server        # stdio transport
"""

from __future__ import annotations

import os
import threading

from . import deploy as deploy_mod
from . import paths, sitegen
from .cli import _load_company
from .config import settings
from .store import Store

# One connection for the whole server, not one per tool call. FastMCP.run() is a
# long-lived process, so the per-call Store this used to build never got closed:
# an MCP host polling status() a few hundred times leaked that many sqlite
# handles, each re-running the schema and migration, and on Windows each open
# handle keeps corparius.sqlite locked against backup. Store guards its own
# connection, so sharing it across tool calls is safe. Mirrors UiState.store().
_store_singleton: Store | None = None
_store_lock = threading.Lock()


def _store() -> Store:
    global _store_singleton
    if _store_singleton is None:
        with _store_lock:
            if _store_singleton is None:
                _store_singleton = Store(settings.data_path)
    return _store_singleton


def _open(company: str):
    cfg = _load_company(company)
    return cfg, _store()


def run_company(company: str, ticks: int = 6) -> dict:
    from .orchestrator import Runtime

    cfg, store = _open(company)
    return Runtime(settings, store).run(cfg, ticks=ticks, loop=False)


def company_status(company: str) -> dict:
    cfg, store = _open(company)
    state = store.load_state(cfg["slug"])
    return {"company": cfg["slug"], "tick": state.get("tick", 0), **store.status(cfg["slug"])}


def list_backlog(company: str) -> list:
    cfg, store = _open(company)
    return store.list_tasks(cfg["slug"])


def decide_task(
    company: str, task_id: int, action: str = "", title=None, target=None, tool=None, priority=None
) -> dict:
    _, store = _open(company)
    fields = {
        k: v
        for k, v in (("title", title), ("target", target), ("tool", tool), ("priority", priority))
        if v is not None
    }
    if fields:
        store.update_task(task_id, **fields)
    if action == "approve":
        store.set_task_status(task_id, "approved", "via MCP")
    elif action == "reject":
        store.set_task_status(task_id, "rejected", "via MCP")
    return {"task": task_id, "action": action or "modify", "modified": list(fields)}


def list_pending_approvals(company: str) -> list:
    cfg, store = _open(company)
    return store.list_approvals(cfg["slug"], "pending")


def decide_approval(company: str, approval_id: str, approve: bool = True, note: str = "") -> dict:
    _, store = _open(company)
    status = "approved" if approve else "rejected"
    return {
        "approval": approval_id,
        "status": status,
        "found": store.set_approval_status(approval_id, status, note),
    }


def build_site(company: str) -> dict:
    cfg, _ = _open(company)
    out = str(paths.site_dir(settings.data_path, cfg["slug"]))
    return {"path": sitegen.build_site(cfg, out)}


def publish_site(company: str) -> dict:
    cfg, _ = _open(company)
    out = str(paths.site_dir(settings.data_path, cfg["slug"]))
    if not os.path.exists(os.path.join(out, "index.html")):
        sitegen.build_site(cfg, out)
    return {"result": deploy_mod.deploy_site(out)}


def build_server():
    """Wrap the functions above as MCP tools. Requires the `mcp` package."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("corparius")

    @server.tool()
    def run(company: str, ticks: int = 6) -> dict:
        """Run a company's autonomous loop for N simulated hours (ticks)."""
        return run_company(company, ticks)

    @server.tool()
    def status(company: str) -> dict:
        """Company status: actions, tokens, pending approvals, open tasks, clock."""
        return company_status(company)

    @server.tool()
    def tasks(company: str) -> list:
        """List the CEO-governed task backlog."""
        return list_backlog(company)

    @server.tool()
    def task(
        company: str,
        id: int,
        action: str = "",
        title: str = "",
        target: str = "",
        tool: str = "",
        priority: int = 0,
    ) -> dict:
        """Modify and/or decide a task (CEO authority). action is approve, reject or empty."""
        return decide_task(
            company, id, action, title or None, target or None, tool or None, priority or None
        )

    @server.tool()
    def approvals(company: str) -> list:
        """List pending human-in-the-loop approvals."""
        return list_pending_approvals(company)

    @server.tool()
    def approve(company: str, id: str, approve: bool = True, note: str = "") -> dict:
        """Approve or reject a pending HITL request by id."""
        return decide_approval(company, id, approve, note)

    @server.tool()
    def site(company: str) -> dict:
        """Build the sales site; returns the file path."""
        return build_site(company)

    @server.tool()
    def deploy(company: str) -> dict:
        """Publish the sales site via the deploy provider chain."""
        return publish_site(company)

    return server


def main():
    build_server().run()


if __name__ == "__main__":
    main()
