"""Human-in-the-loop gate. Flagged tools never execute until a human approves.
A rejection is handed back to the agent as a recoverable tool error, exactly as
an approval webhook (n8n, Slack) would return it.
"""
from __future__ import annotations
import hashlib
import time

from .models import ApprovalRequest, ToolResult

REJECTION_MESSAGE = "Tool execution denied: Approval rejected by administrator."


def _approval_id(company: str, tool: str, parameters: dict) -> str:
    raw = f"{company}|{tool}|{sorted(parameters.items())}"
    return f"{tool}-" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


class ApprovalGate:
    def __init__(self, store, hitl_tools):
        self.store = store
        self.hitl_tools = set(hitl_tools)

    def requires_approval(self, tool) -> bool:
        return tool.hitl or tool.name in self.hitl_tools

    def execute(self, company, agent, tool, ctx, draft, parameters) -> ToolResult:
        if not self.requires_approval(tool):
            return tool.run(ctx, draft)
        prior = self.store.find_approval(company, tool.name, parameters)
        if prior and prior["status"] == "approved":
            return tool.run(ctx, draft)
        if prior and prior["status"] == "rejected":
            return ToolResult(ok=False, output=REJECTION_MESSAGE, denied=True)
        req = ApprovalRequest(
            id=_approval_id(company, tool.name, parameters),
            company=company, agent=agent, tool=tool.name,
            parameters=parameters, status="pending", ts=time.time(),
        )
        self.store.add_approval(req)
        return ToolResult(ok=False, output="pending human approval", pending=True)
