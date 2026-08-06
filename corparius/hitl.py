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

from .config.permissions import PermissionEngine
from .kernel.records import ApprovalRequest, ToolResult

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

        # One pending request per (company, tool), whatever the wording.
        #
        # The id hashes `parameters`, and for a drafting tool those carry the
        # first 80 characters of a freshly generated draft. The model rewrites
        # it every tick, so every tick minted a *new* approval: a real run left
        # eight distinct pending `send_outreach` requests for one action the
        # operator had already been asked about. Approving one changed nothing,
        # because the next tick asked again under a new id.
        #
        # An operator approving "send outreach to these targets" is approving
        # the action, not that phrasing of it. So an outstanding request for the
        # same tool *is* this request.
        waiting = self.store.pending_approval_for(company, tool.name)
        if waiting:
            return ToolResult(
                ok=False,
                output="pending human approval",
                pending=True,
                approval_id=waiting["id"],
            )
        approval_id = _approval_id(company, tool.name, parameters)
        req = ApprovalRequest(
            id=approval_id,
            company=company,
            agent=agent,
            tool=tool.name,
            parameters=parameters,
            status="pending",
            ts=time.time(),
            # What the operator needs to judge it. None of this is hashed, so
            # the draft can be whole: `parameters` had to cut it to 80
            # characters or every tick would file a fresh request for the same
            # thing, and approving an outreach email you cannot read is not
            # approval, it is assent.
            detail={
                "draft": draft or "",
                # getattr: a plugin registers its own tool objects through
                # PluginAPI.register_tool, and several tests pass doubles.
                # A missing description is a blank line in a panel, not a
                # crash in the gate that holds the money tools.
                "does": getattr(tool, "description", ""),
                "risk": decision.rule or "",
                "why": decision.reason or "",
            },
        )
        self.store.add_approval(req)
        return ToolResult(
            ok=False, output="pending human approval", pending=True, approval_id=approval_id
        )
