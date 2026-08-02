"""The ten-agent roster and the turn executor.

Control flow is deterministic: code decides which tools run, and in what order.
The LLM only drafts content. Routing stays out of the model. Each role carries a
difficulty tier (which picks the model) and may pin a task-adapted model, so a
simple scan runs on gemma4:e4b while the coder gets a dedicated code model.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from . import cfg, structured
from .models import AgentRole, Difficulty, ToolResult
from .permissions import risk_of
from .safety import BudgetExceeded, LoopGuard
from .tools import TOOLS

log = logging.getLogger("corparius.agents")


@dataclass
class AgentSpec:
    role: AgentRole
    cadence_hours: int | None  # None = on demand (not scheduled)
    difficulty: Difficulty
    system_prompt: str
    playbook: list[str]
    model: str | None = None  # pin a specific local model for this role


ROSTER: dict[AgentRole, AgentSpec] = {
    AgentRole.CEO: AgentSpec(
        AgentRole.CEO,
        12,
        Difficulty.EASY,
        "You are the CEO. Own the backlog, arbitrate proposals, keep the company solvent — "
        "and reread your own decisions before taking another. Stop work that produces "
        "nothing. Say when you do not know rather than filling the gap with a number.",
        [
            # Read the week and the last plan before deciding anything: the
            # order is the point. A CEO that decides first and reviews later is
            # the one that wrote three contradicting priorities in three hours.
            "review_commitments",
            "review_kpis",
            "weekly_review",
            "check_providers",
            "stop_useless_work",
            "set_daily_plan",
            "review_proposals",
            "create_tasks",
            "decide",
            "remember",
            "write_eod_summary",
        ],
    ),
    AgentRole.SOCIAL: AgentSpec(
        AgentRole.SOCIAL,
        2,
        Difficulty.TRIVIAL,
        "You run social media for the company.",
        ["draft_social_post", "schedule_post"],
    ),
    AgentRole.OUTREACH: AgentSpec(
        AgentRole.OUTREACH,
        3,
        Difficulty.EASY,
        "You run cold outbound to the ICP, and you follow up on who answered.",
        ["find_targets", "send_outreach", "scan_replies"],
    ),
    AgentRole.SUPPORT: AgentSpec(
        AgentRole.SUPPORT,
        3,
        Difficulty.EASY,
        "You handle customer support.",
        ["triage_inbox", "draft_support_reply", "propose_task"],
    ),
    AgentRole.ADS: AgentSpec(
        AgentRole.ADS,
        6,
        Difficulty.TRIVIAL,
        "You manage paid acquisition.",
        ["review_ad_budget", "adjust_bids"],
    ),
    AgentRole.FINANCE: AgentSpec(
        AgentRole.FINANCE,
        6,
        Difficulty.TRIVIAL,
        "You keep the books and the cashflow.",
        ["reconcile_stripe", "send_financial_transaction"],
    ),
    AgentRole.STRATEGY: AgentSpec(
        AgentRole.STRATEGY,
        24,
        Difficulty.HARD,
        "You own strategy, pricing, the roadmap and continuous improvement (kaizen).",
        ["review_kpis", "update_pricing", "kaizen", "remember"],
    ),
    AgentRole.COMPETITOR: AgentSpec(
        AgentRole.COMPETITOR,
        24,
        Difficulty.TRIVIAL,
        "You track the competitive landscape and buying signals.",
        ["scan_competitors", "scan_signals"],
    ),
    AgentRole.DESIGN: AgentSpec(
        AgentRole.DESIGN,
        24,
        Difficulty.EASY,
        "You own visual design, brand consistency and the sales site.",
        [
            # Write the sections first, then render them: building the page
            # before deciding what goes on it is how it stayed one screen.
            "write_site_content",
            "draft_design_brief",
            "produce_mockup",
            "build_sales_site",
        ],
    ),
    AgentRole.CODER: AgentSpec(
        AgentRole.CODER,
        None,
        Difficulty.HARD,
        "You ship product changes behind human review.",
        ["generate_code", "publish_production_code"],
        model="local:qwen2.5-coder:14b",
    ),  # task-adapted code model, kept on-prem
}


def _messages(spec: AgentSpec, ctx, tool) -> list[dict]:
    offer = ctx.company.get("offer", {})
    user = (
        f"Company: {ctx.company.get('name')}. "
        f"Offer: {offer.get('product', '')}. "
        f"Task: {tool.draft_prompt(ctx)}"
    )
    system = spec.system_prompt
    # What this company knows about this job, selected by code rather than by
    # the model: a skill is in scope when it names the tool about to run. The
    # catalogue is not sent — nothing downstream could act on it, since the
    # model has no way to ask for a skill it was not given.
    loader = getattr(ctx, "skills", None)
    if loader is not None:
        knowledge = loader.context_for(tool.name)
        if knowledge:
            system = f"{system}\n\nWhat this company knows about this job:\n{knowledge}"
    learned = _recall(ctx, tool)
    if learned:
        system = f"{system}\n\nWhat this company has learned:\n{learned}"
    # The company's language, in the one place every drafting tool passes
    # through. A French company was drafting `Reply drafted: "Thank you for
    # contacting us…"` to its French customers, because nothing in the prompt
    # had ever said which language it speaks.
    #
    # Phrased as the language of the *output*, never as "write 'reply' in
    # French" — that wording is what made the CEO chat answer with the word
    # "Réponse". Naming the field and naming the language in the same clause is
    # an instruction a model can read as a translation request.
    system = f"{system}\n\n{language_line(ctx.company)}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def language_line(company: dict) -> str:
    """One sentence naming the language everything drafted must be written in."""
    code = str(company.get("language") or "en").strip().lower()
    name = LANGUAGE_NAMES.get(code.split("-")[0], code)
    return (
        f"Write everything you produce in {name} ({code}) — this company's customers "
        f"read {name}. This applies to the text itself, never to field names or "
        f"JSON keys, which stay exactly as given."
    )


# Endonyms would be better manners, but the model is being told which language to
# use and English names are what it was trained to resolve reliably. A language
# not listed is passed through as its code, which every current model handles.
LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
}


def _recall(ctx, tool) -> str:
    """Durable facts, ranked against the prompt about to be sent.

    Separate from ctx.memory, which stays what it has always been: the last
    three end-of-day summaries, read positionally by set_daily_plan. Merging the
    two would have made memory[0] a fact instead of yesterday, and broken that
    tool without breaking a test.
    """
    store = getattr(ctx, "store", None)
    top_k = int(getattr(ctx, "memory_top_k", 0) or 0)
    if store is None or top_k <= 0 or not hasattr(store, "recall"):
        return ""
    rows = store.recall(ctx.company.get("slug", ""), query=tool.draft_prompt(ctx), limit=top_k)
    return "\n".join(f"- {r['fact']}" + (f" ({r['why']})" if r["why"] else "") for r in rows)


class Executor:
    """Runs one agent turn: walk the playbook, draft content via the router, and
    pass every step through the safety firewall and the HITL gate."""

    def __init__(self, router, gate, store, settings):
        self.router = router
        self.gate = gate
        self.store = store
        self.settings = settings

    def run_turn(self, company: str, spec: AgentSpec, ctx) -> list[str]:
        loop = LoopGuard(
            self.settings.loop_similarity_threshold,
            max_identical_calls=self.settings.max_identical_tool_calls,
        )
        done: list[str] = []
        ctx.role = spec.role.value
        # Non-CEO agents execute the top approved task for their role by running
        # its mapped tool for real, then completing it with the tool's output.
        if spec.role.value != "ceo":
            task = self.store.claim_next_task(company, spec.role.value)
            if task and self._work_task(company, spec, ctx, task, loop, done):
                return done
        if self._stood_down(company, spec, done):
            return done
        for tool_name in spec.playbook:
            result, stop = self._invoke(company, spec, ctx, tool_name, loop)
            if result is not None:
                done.append(f"{tool_name}: {result.output}")
            # A guard tripping halts the turn; a human being asked does not.
            # Waiting on an approval is not a failure of the agent, and the rest
            # of its playbook has nothing to do with the tool that is held, so
            # stopping here used to idle a whole company on one unanswered
            # question.
            if stop:
                break
        return done

    def _stood_down(self, company, spec, done) -> bool:
        """Skip this turn when what the role produces is piling up unread.

        The social agent was the largest line in one company's spend — 29 065
        tokens — writing posts nothing published, then writing more. An agent
        producing what nobody consumes should stop, not accelerate.

        The notice goes to the inbox once, not once per tick: a warning repeated
        every two hours is a warning nobody reads.
        """
        from . import inbox

        if spec.role is not AgentRole.SOCIAL:
            return False
        cap = cfg.get_int("CORP_SOCIAL_QUEUE_MAX", 5)
        waiting = self.store.count_unpublished(company)
        if waiting < cap:
            return False
        done.append(f"social stood down: {waiting} post(s) queued and nothing publishes them")
        inbox.notify(
            self.store,
            company,
            "social",
            "Posts are piling up unpublished",
            f"{waiting} posts are written and none is published. Nothing in corparius "
            "publishes to a social channel yet, so the social agent "
            "has stopped writing rather than keep spending on drafts nobody reads. Read or "
            "export them from the console, then they stop counting. Raise "
            "CORP_SOCIAL_QUEUE_MAX if you want a deeper queue.",
        )
        return True

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
        elif result is not None and result.pending:
            # Parked, not returned to the queue: `approved` would be claimed
            # again on the next turn and re-file the same request, so the agent
            # would spend every turn re-asking one question instead of doing the
            # next thing. store.release_waiting_tasks puts it back once answered.
            kind = "question" if result.question_id else "approval"
            blocker = result.question_id or result.approval_id
            self.store.park_task(task["id"], blocker, kind)
            done.append(f"backlog #{task['id']} parked, waiting on {kind} {blocker}")
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
        decision = self.gate.decide(tool, company)
        # Already queued for this operator, on this tool. Drafting again would
        # spend a model call to produce a second request saying the same thing,
        # and the queue is a place to decide, not a place to accumulate. Checked
        # before the draft rather than after, because the draft is the expensive
        # half. It does not widen the gate: nothing runs either way, and matching
        # an approval to an execution still compares parameters exactly, in
        # ApprovalGate.execute.
        if decision.needs_user:
            waiting = self.store.pending_approval_for(company, tool_name)
            if waiting:
                log.info("[%s] %s still held, moving on", spec.role.value, tool_name)
                return (
                    ToolResult(
                        ok=False,
                        output=f"still waiting on approval {waiting['id']}",
                        pending=True,
                        approval_id=waiting["id"],
                    ),
                    False,
                )
        # Before anything is spent. A needs_draft tool otherwise pays for a real
        # model call and only then discovers there was nothing to do — support
        # drafted a reply to nobody every three hours on a company with no
        # mailbox, and the log read as if it had done some work.
        skip = tool.skip_reason(ctx)
        if skip:
            self.store.record_action(company, spec.role.value, tool_name, {}, skip, True)
            return ToolResult(ok=True, output=skip), False
        draft = ""
        ctx.structured = None
        if tool.needs_draft and tool.schema:
            # Same shape out, whatever model answered. The harness may spend more
            # than one call (a repair round), but it accounts for every one.
            result = structured.ask(
                self.router, _messages(spec, ctx, tool), tool.schema, difficulty=spec.difficulty
            )
            for used in result.usages:  # a repair round is a real call; bill it
                ctx.budget.record_usage(used.input_tokens, used.output_tokens, used.cost)
                ctx.breaker.record(used.total)
                self.store.record_usage(
                    company, spec.role.value, used.input_tokens, used.output_tokens, used.cost
                )
            ctx.structured = result
            draft = json.dumps(result.data, ensure_ascii=False)
            if loop.observe_output(self.router.embed(draft)):
                log.warning("[%s] loop stop: semantic stutter", spec.role.value)
                return None, True
        elif tool.needs_draft:
            res = self.router.generate(
                _messages(spec, ctx, tool), difficulty=spec.difficulty, model=spec.model
            )
            ctx.budget.record_usage(res.usage.input_tokens, res.usage.output_tokens, res.usage.cost)
            ctx.breaker.record(res.usage.total)
            self.store.record_usage(
                company,
                spec.role.value,
                res.usage.input_tokens,
                res.usage.output_tokens,
                res.usage.cost,
            )
            if loop.observe_output(self.router.embed(res.text)):
                log.warning("[%s] loop stop: semantic stutter", spec.role.value)
                return None, True
            draft = res.text
        params = {"draft": draft[:80]} if tool.needs_draft else {}
        if loop.observe_tool_call(tool_name, params):
            log.warning("[%s] loop stop: repeated call to %s", spec.role.value, tool_name)
            return None, True
        # The decision is journalled next to the action, not instead of it: a log
        # that says a tool ran but not why it was allowed to answers half the
        # question an operator opens the audit trail to ask.
        result = self.gate.execute(company, spec.role.value, tool, ctx, draft, params)
        self.store.record_action(
            company,
            spec.role.value,
            tool_name,
            {**params, "risk": risk_of(tool), "why": decision.reason, "rule": decision.rule},
            result.output,
            result.ok,
        )
        if result.pending:
            log.info("[%s] paused for human approval on %s", spec.role.value, tool_name)
        return result, False
