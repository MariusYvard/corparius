"""Everything a caller needs to say how a company is doing. Rank 5.

The console polls this; a terminal could not reach it, and the barrier was the same one as the
chat's: `state.runs.get(slug, {})`, a dict living in the console's process. It is a parameter
now — the console passes its in-flight run, a terminal passes nothing and gets a company at
rest, which is the truth for a one-shot command.

`corparius status` showed four numbers: actions, tokens, pending approvals, and a count per
agent. It could not show **money spent**, the **flow** — work in progress, what is blocked, which
role is the bottleneck — or the **warnings** the console renders. An operator on a headless box
had the cheapest half of what the product knows about their company.

The approval enrichment is the part that is genuinely logic rather than assembly, and it is why
this belongs in a service: each pending request is resolved into what the tool does, why it
stopped, what the agent wrote and what saying yes will do. "An approval that shows a tool name
and 80 characters of JSON is a decision made blind" — and it was made blind from a terminal,
where `corparius approvals` shows exactly that.

**This payload is 54 KB and the console polls it every five seconds** — 37 MB an hour per
client. Splitting it into narrow, separately-pollable resources is stage 8 of the plan, and it
happens here now that there is a here: one function to split rather than a handler to unpick.
"""

from __future__ import annotations

import json

from .. import inbox as inbox_mod
from ..config import permissions
from ..roster import ROSTER
from ..tools.spec import ROLE_TOOL, SPEC

# Completed tasks sent to a caller. They accumulate for the life of a company and this payload is
# polled; the store keeps all of them, and `done_total` reports the true count.
DONE_KEPT = 60


def build(store, settings, slug: str, company: dict | None = None, run: dict | None = None) -> dict:
    st = store.status(slug)
    flow = store.flow_metrics(slug)
    tasks = store.list_tasks(slug)
    tick = int(store.load_state(slug).get("tick", 0))
    # Through the Store API rather than store.db: the connection is guarded by a
    # lock now, so reaching past it from here would be the unsynchronised access
    # that lock exists to prevent.
    spend = store.spend_by_agent(slug)
    actions = store.recent_actions(slug)
    frozen = store.count_actions_by_tool(slug, "circuit_breaker_freeze")
    approvals = store.list_approvals(slug, "pending")
    s = settings
    company_cfg = company or {}
    engine = permissions.PermissionEngine.from_settings(s, company_cfg, store)
    for a in approvals:  # parameters are stored as a JSON string
        if isinstance(a.get("parameters"), str):
            try:
                a["parameters"] = json.loads(a["parameters"])
            except json.JSONDecodeError:
                pass
        tool = SPEC.get(a.get("tool", ""))
        a["risk"] = permissions.risk_of(tool) if tool else permissions.READ
        # A tool gated by name can never be silenced by a standing rule, so the
        # console must not offer a button that would do nothing.
        a["can_remember"] = bool(tool) and engine.evaluate(tool, slug).rule != "hitl"
        # Everything the "learn more" panel needs, resolved here rather than in
        # the page: what the tool does, why this one stopped, what the agent
        # actually wrote, and what saying yes will do. An approval that shows a
        # tool name and 80 characters of JSON is a decision made blind.
        detail = a.get("detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                detail = {}
        detail = detail or {}
        a["detail"] = {
            "draft": detail.get("draft", ""),
            "does": detail.get("does") or (tool.description if tool else ""),
            "why": detail.get("why", ""),
            "risk_means": permissions.explain(a["risk"]),
            "on_approve": (
                f"{a.get('tool', 'the tool')} runs once, now, with exactly what you see here."
            ),
            "on_reject": "Nothing runs, and the agent moves on to the rest of its playbook.",
        }
    run = run or {}
    by_status: dict[str, list] = {
        "proposed": [],
        "approved": [],
        "in_progress": [],
        "waiting": [],
        "done": [],
    }
    for t in tasks:
        by_status.setdefault(t["status"], []).append(t)
    # Finished work is history, and it only ever grows. Newest first, because a
    # column that opens on the first task the company ever completed is showing
    # the least useful end of it, and bounded, because this payload is polled.
    done_total = len(by_status["done"])
    by_status["done"] = list(reversed(by_status["done"]))[:DONE_KEPT]
    return {
        "ok": True,
        "company": slug,
        "tick": tick,
        "status": st,
        "flow": flow,
        "tasks": by_status,
        # The true count, not the number of rows sent: the column header must
        # not read 60 when the company has completed three hundred.
        "done_total": done_total,
        # Whether a proposal is actually the operator's to decide.
        #
        # It normally is not: the CEO reviews proposals on its own cadence, which
        # is the point of having a CEO. But the console counted every proposal in
        # the "needs you" badge and labelled the column "your call", so an agent
        # noticing something small — "the landing page claims 12 early-access
        # users and nothing backs it" — read as the company stopping to ask
        # permission for trivia. The operator said the plain version of it: these
        # are decisions it could make on its own.
        #
        # It becomes the operator's only when nobody else will look: a CEO the
        # company switched off, or one the operator stood down. Then the proposals
        # really would sit there forever, and saying nothing would be worse.
        "proposals_need_you": not (company_cfg.get("agents", {}) or {}).get("ceo", True)
        or any(d.get("target") == "ceo" for d in store.directives(slug, "pause")),
        "approvals": approvals,
        "rules": store.list_rules(slug),
        "inbox": store.list_inbox(slug, "pending"),
        # Which console tab settles each kind of notice. Sent rather than
        # duplicated in the page: two copies of this table would drift, and the
        # failure mode is a button that silently does nothing.
        "inbox_fixes": inbox_mod.FIXES,
        # Which agent could carry which tool, so a notice about a task with no owner
        # can offer the real choices instead of sending the operator to find out
        # what tool names exist. The playbook is the honest list: a tool that is not
        # on a role's playbook is one that role never runs.
        #
        # Suggested, not decided: the default is what the roster would use for that
        # role, and the operator picks. Inventing the answer from the task's wording
        # would be a guess dressed as a recommendation.
        "agent_tools": {
            role.value: sorted(set(spec.playbook) | {ROLE_TOOL.get(role.value, "")} - {""})
            for role, spec in ROSTER.items()
            if (company_cfg.get("agents", {}) or {}).get(role.value, False)
        },
        "role_tool": ROLE_TOOL,
        "memory": store.list_memory(slug) if s.memory_enabled else [],
        "memory_enabled": s.memory_enabled,
        "permission_mode": engine.mode,
        "ask_above": engine.ask_above,
        "spend_by_agent": spend,
        # Whether any provider reported a cost at all. Without it a total of
        # 0.00 is indistinguishable from a free run, and the page would tell
        # an operator on a paid key that they spent nothing.
        "cost_reported": store.cost_reported(slug),
        "recent_actions": actions,
        "freezes": frozen,
        "session_budget": s.session_token_budget,
        "llm_mock": s.llm_mock,
        "cloud_enabled": s.cloud_enabled,
        "running": bool(run.get("running")),
        "last_run": run.get("result"),
        "loop": bool(run.get("loop")),
        "stopping": bool(run.get("running") and run.get("stop") and run["stop"].is_set()),
    }
