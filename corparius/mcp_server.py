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

from . import sitegen
from .app import companies as app_companies
from .config.settings import Settings
from .kernel import paths
from .providers import deploy as deploy_mod
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
    """`Settings()` at first use, not a snapshot taken at import.

    This read the module-level `settings` singleton, captured when `mcp_server` was imported — so
    the data path was whatever the environment said at *import* time. In a real host the two agree,
    because that is microseconds earlier; in a test they do not, and a test exercising an MCP tool
    silently opened the developer's own store. That is the fourth module to learn this, after
    `backup.py`, `app.support.open_store` and the eight CLI groups, and it was found by an assertion
    that failed because the approval it had just written was in a different database.

    The singleton stays and is right: `FastMCP.run()` is one long-lived process, and per-call stores
    leaked a handle each — an MCP host polling status a few hundred times re-ran the schema that many
    times and, on Windows, held the file against backup.
    """
    global _store_singleton
    if _store_singleton is None:
        with _store_lock:
            if _store_singleton is None:
                _store_singleton = Store(Settings().data_path)
    return _store_singleton


def _open(company: str):
    """Resolve the company, or let the refusal reach the host as a tool error.

    This used to be `cli._load_company`, which ends in `sys.exit` — so a bad company name in a
    tool call raised `SystemExit` inside a process built to stay up. The resolving is now
    `app_companies.load` and it raises `Refused`, a `ValueError`: a terminal turns that into an
    exit code and a server reports a failed call, which is the answer each caller needs.
    """
    cfg = app_companies.load(company)
    return cfg, _store()


def run_company(company: str, ticks: int = 6) -> dict:
    from .orchestrator import Runtime

    cfg, store = _open(company)
    return Runtime(Settings(), store).run(cfg, ticks=ticks, loop=False)


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


def decide_approval(
    company: str, approval_id: str, approve: bool = True, note: str = "", remember: str = ""
) -> dict:
    """Decide one approval, through the same service the console and the CLI use.

    This set the status and stopped there: it granted no standing rule and released none of the work
    parked on the approval, so a host driving corparius left tasks `waiting` that a terminal would
    have unblocked. Three surfaces, three behaviours — see `app/approvals.py`.

    `remember` is new here and is a scope (`run` or `always`), so a host can offer "and stop asking"
    without reimplementing the gate that refuses it for a tool the company names in `hitl_tools`.
    """
    from .app import approvals as app_approvals

    cfg, store = _open(company)
    status = "approved" if approve else "rejected"
    done = app_approvals.decide(
        store, Settings(), approval_id, status, note=note, remember=remember, company=cfg
    )
    return {"approval": approval_id, "status": status, **done}


def list_inbox(company: str) -> list:
    """Questions and notices waiting on the operator. A host driving corparius
    should see the same queue the console does, or it will report a company as
    idle when it is in fact blocked on a person."""
    cfg, store = _open(company)
    return store.list_inbox(cfg["slug"], "pending")


def answer_inbox(company: str, item_id: str, answer: str = "") -> dict:
    from .app import inbox as app_inbox

    cfg, store = _open(company)
    return {"item": item_id, **app_inbox.answer(store, item_id, answer, cfg["slug"])}


def build_site(company: str) -> dict:
    cfg, store = _open(company)
    out = str(paths.site_dir(Settings().data_path, cfg["slug"]))
    return {"path": sitegen.build_site(cfg, out, store=store)}


def publish_site(company: str) -> dict:
    cfg, store = _open(company)
    out = str(paths.site_dir(Settings().data_path, cfg["slug"]))
    if not os.path.exists(os.path.join(out, "index.html")):
        sitegen.build_site(cfg, out, store=store)
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
    def inbox(company: str) -> list:
        """Questions and notices waiting on the operator."""
        return list_inbox(company)

    @server.tool()
    def answer(company: str, id: str, text: str = "") -> dict:
        """Answer a question or dismiss a notice, and release any task it held."""
        return answer_inbox(company, id, text)

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
