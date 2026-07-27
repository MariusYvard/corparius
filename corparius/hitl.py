"""Human-in-the-loop gate. Flagged tools never execute until a human approves.
A rejection is handed back to the agent as a recoverable tool error, exactly as
an approval webhook (n8n, Slack) would return it.

What may run without asking is decided by corparius/permissions.py; this module
owns what happens once the answer is "ask": minting a request the operator can
recognise, and matching a later verdict back to the exact call that raised it.
"""

from __future__ import annotations

import hashlib
import time

from .models import ApprovalRequest, ToolResult
from .permissions import PermissionEngine

REJECTION_MESSAGE = "Tool execution denied: Approval rejected by administrator."
BLOCKED_MESSAGE = "Tool execution blocked: {reason}."


def _approval_id(company: str, tool: str, parameters: dict) -> str:
    raw = f"{company}|{tool}|{sorted(parameters.items())}"
    return f"{tool}-" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


class ApprovalGate:
    def __init__(self, store, engine):
        """`engine` accepts a bare list of tool names as well as a
        PermissionEngine, so a caller that only cares about the gated names —
        several tests, and any embedder of the runtime — keeps working."""
        self.store = store
        self.engine = engine if isinstance(engine, PermissionEngine) else PermissionEngine(engine)

    def decide(self, tool, company: str = ""):
        return self.engine.evaluate(tool, company)

    def requires_approval(self, tool, company: str = "") -> bool:
        return self.decide(tool, company).needs_user

    def execute(self, company, agent, tool, ctx, draft, parameters) -> ToolResult:
        decision = self.decide(tool, company)
        if decision.allowed:
            return tool.run(ctx, draft)
        if not decision.needs_user:
            # Refused outright (discuss mode). Same shape as a rejection, so the
            # agent handles one case rather than two.
            return ToolResult(
                ok=False, output=BLOCKED_MESSAGE.format(reason=decision.reason), denied=True
            )
        prior = self.store.find_approval(company, tool.name, parameters)
        if prior and prior["status"] == "approved":
            return tool.run(ctx, draft)
        if prior and prior["status"] == "rejected":
            return ToolResult(ok=False, output=REJECTION_MESSAGE, denied=True)
        approval_id = _approval_id(company, tool.name, parameters)
        req = ApprovalRequest(
            id=approval_id,
            company=company,
            agent=agent,
            tool=tool.name,
            parameters=parameters,
            status="pending",
            ts=time.time(),
        )
        self.store.add_approval(req)
        return ToolResult(
            ok=False, output="pending human approval", pending=True, approval_id=approval_id
        )
