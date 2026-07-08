"""The ten-agent roster and the turn executor.

Control flow is deterministic: code decides which tools run, and in what order.
The LLM only drafts content. Routing stays out of the model. Each role carries a
difficulty tier (which picks the model) and may pin a task-adapted model, so a
simple scan runs on gemma4:e4b while the coder gets a dedicated code model.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from .models import AgentRole, Difficulty
from .tools import TOOLS
from .safety import BudgetExceeded, LoopGuard

log = logging.getLogger("corparius.agents")


@dataclass
class AgentSpec:
    role: AgentRole
    cadence_hours: int | None   # None = on demand (not scheduled)
    difficulty: Difficulty
    system_prompt: str
    playbook: list[str]
    model: str | None = None    # pin a specific local model for this role


ROSTER: dict[AgentRole, AgentSpec] = {
    AgentRole.CEO: AgentSpec(
        AgentRole.CEO, 12, Difficulty.EASY,
        "You are the CEO. Own the backlog: create and arbitrate tasks, keep the company solvent.",
        ["set_daily_plan", "review_proposals", "create_tasks", "write_eod_summary"]),
    AgentRole.SOCIAL: AgentSpec(
        AgentRole.SOCIAL, 2, Difficulty.TRIVIAL,
        "You run social media for the company.",
        ["draft_social_post", "schedule_post"]),
    AgentRole.OUTREACH: AgentSpec(
        AgentRole.OUTREACH, 3, Difficulty.EASY,
        "You run cold outbound to the ICP.",
        ["find_targets", "send_outreach"]),
    AgentRole.SUPPORT: AgentSpec(
        AgentRole.SUPPORT, 3, Difficulty.EASY,
        "You handle customer support.",
        ["triage_inbox", "draft_support_reply", "propose_task"]),
    AgentRole.ADS: AgentSpec(
        AgentRole.ADS, 6, Difficulty.TRIVIAL,
        "You manage paid acquisition.",
        ["review_ad_budget", "adjust_bids"]),
    AgentRole.FINANCE: AgentSpec(
        AgentRole.FINANCE, 6, Difficulty.TRIVIAL,
        "You keep the books and the cashflow.",
        ["reconcile_stripe", "send_financial_transaction"]),
    AgentRole.STRATEGY: AgentSpec(
        AgentRole.STRATEGY, 24, Difficulty.HARD,
        "You own strategy, pricing and the roadmap.",
        ["review_kpis", "update_pricing", "propose_task"]),
    AgentRole.COMPETITOR: AgentSpec(
        AgentRole.COMPETITOR, 24, Difficulty.TRIVIAL,
        "You track the competitive landscape and buying signals.",
        ["scan_competitors", "scan_signals"]),
    AgentRole.DESIGN: AgentSpec(
        AgentRole.DESIGN, 24, Difficulty.EASY,
        "You own visual design, brand consistency and the sales site.",
        ["draft_design_brief", "produce_mockup", "build_sales_site"]),
    AgentRole.CODER: AgentSpec(
        AgentRole.CODER, None, Difficulty.HARD,
        "You ship product changes behind human review.",
        ["generate_code", "publish_production_code"],
        model="local:qwen2.5-coder:14b"),   # task-adapted code model, kept on-prem
}


def _messages(spec: AgentSpec, ctx, tool) -> list[dict]:
    offer = ctx.company.get("offer", {})
    user = (f"Company: {ctx.company.get('name')}. "
            f"Offer: {offer.get('product', '')}. "
            f"Task: {tool.draft_prompt(ctx)}")
    return [{"role": "system", "content": spec.system_prompt},
            {"role": "user", "content": user}]


class Executor:
    """Runs one agent turn: walk the playbook, draft content via the router, and
    pass every step through the safety firewall and the HITL gate."""

    def __init__(self, router, gate, store, settings):
        self.router = router
        self.gate = gate
        self.store = store
        self.settings = settings

    def run_turn(self, company: str, spec: AgentSpec, ctx) -> list[str]:
        loop = LoopGuard(self.settings.loop_similarity_threshold,
                         max_identical_calls=self.settings.max_identical_tool_calls)
        done: list[str] = []
        ctx.role = spec.role.value
        # Non-CEO agents execute the top approved task for their role by running
        # its mapped tool for real, then completing it with the tool's output.
        if spec.role.value != "ceo":
            task = self.store.claim_next_task(company, spec.role.value)
            if task and self._work_task(company, spec, ctx, task, loop, done):
                return done
        for tool_name in spec.playbook:
            result, stop = self._invoke(company, spec, ctx, tool_name, loop)
            if result is not None:
                done.append(f"{tool_name}: {result.output}")
            if stop or (result is not None and result.pending):
                break
        return done

    def _work_task(self, company, spec, ctx, task, loop, done) -> bool:
        """Run a backlog task's tool for real. Returns True if a guard tripped."""
        tool_name = (task.get("tool") or "").strip()
        if tool_name not in TOOLS:
            self.store.complete_task(task["id"], "done (no tool mapped)")
            done.append(f"backlog #{task['id']} {task['title']} (symbolic)")
            return False
        result, stop = self._invoke(company, spec, ctx, tool_name, loop)
        if result is not None and result.ok and not result.pending:
            self.store.complete_task(task["id"], result.output[:120])
            done.append(f"backlog #{task['id']} done via {tool_name}: {result.output}")
        else:
            self.store.set_task_status(task["id"], "approved", "returned to backlog")
            done.append(f"backlog #{task['id']} returned to backlog")
        return stop

    def _invoke(self, company, spec, ctx, tool_name, loop):
        """Run one tool through budget, draft, loop guards and the HITL gate.
        Returns (result, stop); stop=True means a guard tripped, halt the turn."""
        tool = TOOLS[tool_name]
        try:
            ctx.budget.check_before()
        except BudgetExceeded as exc:
            log.warning("[%s] budget stop: %s", spec.role.value, exc)
            self.store.record_action(company, spec.role.value, tool_name, {}, str(exc), False)
            return None, True
        draft = ""
        if tool.needs_draft:
            res = self.router.generate(_messages(spec, ctx, tool),
                                       difficulty=spec.difficulty, model=spec.model)
            ctx.budget.record_usage(res.usage.input_tokens, res.usage.output_tokens)
            ctx.breaker.record(res.usage.total)
            self.store.record_usage(company, spec.role.value,
                                    res.usage.input_tokens, res.usage.output_tokens)
            if loop.observe_output(self.router.embed(res.text)):
                log.warning("[%s] loop stop: semantic stutter", spec.role.value)
                return None, True
            draft = res.text
        params = {"draft": draft[:80]} if tool.needs_draft else {}
        if loop.observe_tool_call(tool_name, params):
            log.warning("[%s] loop stop: repeated call to %s", spec.role.value, tool_name)
            return None, True
        result = self.gate.execute(company, spec.role.value, tool, ctx, draft, params)
        self.store.record_action(company, spec.role.value, tool_name, params,
                                 result.output, result.ok)
        if result.pending:
            log.info("[%s] paused for human approval on %s", spec.role.value, tool_name)
        return result, False
