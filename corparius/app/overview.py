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

**This payload was 48 KB and the console polls it every five seconds** — 34 MB an hour per
client. Stage 8 splits it, and measuring first changed the shape of the split. On the real
company, three keys are **94%** of it:

```text
  21 115  43.5%  tasks           six columns, `done` bounded at 60 of 71
  17 706  36.5%  memory          46 facts, and they change almost never
   6 765  13.9%  recent_actions  the last 25
   2 944   6.1%  the other 26 keys together
```

So the parts are `summary`, `tasks`, `memory` and `activity`, and **`approvals` and `inbox` stay
in the summary** — the plan named them as separate resources, and the measurement says they are
613 bytes together. They are also the two things an operator must not have to ask a second time
for. Splitting on the plan's guess rather than on the number would have cost two round trips to
save nothing.

`build` is unchanged and is now exactly the union of the four parts. `tests/test_overview_parts.py`
holds that: a key that fell out of every part would vanish from the legacy payload, and a key in
two parts is a value with two homes, which is how two copies of a thing start to disagree.
"""

from __future__ import annotations

import json

from .. import inbox as inbox_mod
from ..config import permissions
from ..roster import ROSTER
from ..tools.spec import ROLE_TOOL, SPEC
from . import onboarding

# Completed tasks sent to a caller. They accumulate for the life of a company and this payload is
# polled; the store keeps all of them, and `done_total` reports the true count.
DONE_KEPT = 60


def build(store, settings, slug: str, company: dict | None = None, run: dict | None = None) -> dict:
    """The whole thing, for the console's legacy `/api/overview` and for `corparius status`.

    Kept byte-identical in its key set because 54 routes and a 3 617-line page read it. The v1
    resources are the four parts below; this is their union, and it stays until the page is
    rebuilt (stage 9).
    """
    return {
        **summary(store, settings, slug, company=company, run=run),
        **tasks(store, slug),
        **memory(store, settings, slug),
        **activity(store, slug),
    }


def tasks(store, slug: str) -> dict:
    """The kanban. 21 KB of the 48, and the half that changes on every tick.

    `done_total` travels with it rather than with the summary, because it is the true count for
    a column whose rows are bounded — a header reading 60 when the company has completed three
    hundred is the failure it exists to prevent, and it can only be checked next to the rows.
    """
    rows = store.list_tasks(slug)
    by_status: dict[str, list] = {
        "proposed": [],
        "approved": [],
        "in_progress": [],
        "waiting": [],
        "done": [],
    }
    for t in rows:
        by_status.setdefault(t["status"], []).append(t)
    # Finished work is history, and it only ever grows. Newest first, because a
    # column that opens on the first task the company ever completed is showing
    # the least useful end of it, and bounded, because this payload is polled.
    done_total = len(by_status["done"])
    by_status["done"] = list(reversed(by_status["done"]))[:DONE_KEPT]
    return {"tasks": by_status, "done_total": done_total}


def memory(store, settings, slug: str) -> dict:
    """46 facts, 17.7 KB, and they change almost never — so this is the resource an ETag pays
    for most. `memory_enabled` travels with the list because an empty list and a switched-off
    feature are different answers and a caller must not have to guess which it got.

    **`cap` and `chars` travel with it because this list has a ceiling and nothing said so.**
    Measured on the real company: 55 facts, 13 933 characters, 16 pinned, written over 6.9 days —
    about eight a day. `store.remember` caps the *unpinned* rows at `CORP_MEMORY_MAX` (200) and
    deletes the oldest beyond it, so at that rate the company starts silently forgetting in roughly
    three weeks. A console that renders an unbounded scroll of 253-character paragraphs and never
    mentions either number is hiding both the cost and the ceiling.

    `chars` is the honest unit here rather than the row count: these facts are pasted into prompts by
    `store.recall`, so their length is what the operator actually pays for — the same reasoning as
    `skills.always_on_chars()`, which already counts the tax an unscoped skill puts on every turn.
    """
    rows = store.list_memory(slug) if settings.memory_enabled else []
    return {
        "memory": rows,
        "memory_enabled": settings.memory_enabled,
        # The cap counts unpinned rows only, and so does this: a pin is the operator saying "this one
        # stays", which is neither counted against the cap nor dropped by it. Reporting the total
        # against the cap would tell them they are 16 facts nearer a limit they are not.
        "unpinned": sum(1 for row in rows if not row.get("pinned")),
        # `settings.memory_max`, not a `cfg.get_int("CORP_MEMORY_MAX", 200)` of its own. It resolves to
        # the same value `tools.effects._remember` passes to `store.remember`, which is the point —
        # a console drawing a ceiling the store does not enforce is this project's recurring defect,
        # two surfaces claiming one number. The first version of this line did write the literal, and
        # `test_two_callers_agree` caught it as a status code, which it is not; the objection was
        # wrong and the rule was still right, because the literal did not belong here either.
        "cap": settings.memory_max,
        "chars": sum(len(row.get("fact") or "") + len(row.get("why") or "") for row in rows),
    }


def activity(store, slug: str) -> dict:
    """The last 25 actions. 6.8 KB, and it is a log: a client that has seen them has seen them."""
    return {"recent_actions": store.recent_actions(slug)}


def summary(
    store, settings, slug: str, company: dict | None = None, run: dict | None = None
) -> dict:
    """Everything else: 2.9 KB, and the one a client should poll.

    Including `approvals` and `inbox`, which are 613 bytes together and are the two things an
    operator must not have to make a second request to see.
    """
    st = store.status(slug)
    flow = store.flow_metrics(slug)
    tick = int(store.load_state(slug).get("tick", 0))
    # Through the Store API rather than store.db: the connection is guarded by a
    # lock now, so reaching past it from here would be the unsynchronised access
    # that lock exists to prevent.
    spend = store.spend_by_agent(slug)
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
    return {
        "ok": True,
        "company": slug,
        "tick": tick,
        "status": st,
        "flow": flow,
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
        "permission_mode": engine.mode,
        "ask_above": engine.ask_above,
        "spend_by_agent": spend,
        # Whether any provider reported a cost at all. Without it a total of
        # 0.00 is indistinguishable from a free run, and the page would tell
        # an operator on a paid key that they spent nothing.
        "cost_reported": store.cost_reported(slug),
        "freezes": frozen,
        "session_budget": s.session_token_budget,
        "llm_mock": s.llm_mock,
        "cloud_enabled": s.cloud_enabled,
        # The onboarding thread. In `summary` rather than behind its own route because this is the one
        # resource the Overview tab already polls, and the whole card is three booleans plus which step
        # leads — a second request for that would cost more than it carries. One extra COUNT.
        "onboarding": onboarding.steps(store, s, slug, run=run),
        "running": bool(run.get("running")),
        "last_run": run.get("result"),
        "loop": bool(run.get("loop")),
        "stopping": bool(run.get("running") and run.get("stop") and run["stop"].is_set()),
    }
