"""Scheduler (cadences) and Runtime (the tick loop that runs a company day).

A tick is one simulated hour. An agent is due when the tick is a multiple of its
cadence, so the roster is naturally staggered instead of firing all at once.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests

from .agents import ROSTER, AgentSpec, Executor
from .config import Settings
from .hitl import ApprovalGate
from .llm import HybridRouter
from .permissions import PermissionEngine
from .safety import CircuitBreaker, TokenBudget
from .skills import SkillLoader

log = logging.getLogger("corparius.orchestrator")


@dataclass
class RunContext:
    company: dict
    tick: int
    budget: TokenBudget
    breaker: CircuitBreaker
    data_path: str = "./data"
    memory: list[str] = field(default_factory=list)
    leads: list = field(default_factory=list)
    store: object = None
    role: str = ""
    structured: object = None  # the last structured.Result, when a tool asked for one
    skills: object = None  # a skills.SkillLoader, or None when skills are off


def _load_skills(settings, slug: str):
    """None rather than an empty loader when skills are off, so _messages has a
    single condition to check and a company with no skills pays nothing."""
    if not getattr(settings, "skills_enabled", True):
        return None
    loader = SkillLoader.for_company(slug, max_chars=getattr(settings, "skill_max_chars", None))
    if loader.skills:
        log.info("%d skill(s) loaded for %s", len(loader.skills), slug)
    return loader if loader.skills else None


def due_roles(tick: int, enabled: dict) -> list[AgentSpec]:
    specs = []
    for role, spec in ROSTER.items():
        if spec.cadence_hours is None:
            continue
        if not enabled.get(role.value, False):
            continue
        if tick % spec.cadence_hours == 0:
            specs.append(spec)
    return specs


class Runtime:
    def __init__(self, settings, store):
        self.settings = settings
        self.store = store
        self.router = HybridRouter(settings)

    def run(self, company: dict, ticks: int = 6, loop: bool = False, should_stop=None) -> dict:
        """should_stop() is polled at every tick and at each day boundary, so a
        loop started from the console can be stopped within one tick instead of
        running until the process dies."""
        should_stop = should_stop or (lambda: False)
        slug = company["slug"]
        budgets = company.get("budgets", {})
        gate = ApprovalGate(
            self.store, PermissionEngine.from_settings(self.settings, company, self.store)
        )
        executor = Executor(self.router, gate, self.store, self.settings)
        enabled = company.get("agents", {})

        skills = _load_skills(self.settings, slug)
        start = int(self.store.load_state(slug).get("tick", 0))
        # Yesterday's summaries. Re-read at every day boundary below: read once
        # here and a --loop company writes an EOD summary every day and never
        # reads one, planning each morning as if it had just been born.
        memory = self.store.recent_outputs(slug, "write_eod_summary", 3)
        days = 0
        ran = 0
        frozen = False
        stopped = False
        last = {"mode": CircuitBreaker.NORMAL, "budget_used": 0, "frozen": False}
        while True:
            budget = TokenBudget(budgets.get("session_tokens", self.settings.session_token_budget))
            breaker = CircuitBreaker(
                budgets.get("tokens_per_minute", self.settings.tokens_per_minute_limit)
            )
            done_ticks = 0
            for offset in range(ticks):
                if should_stop():
                    stopped = True
                    break
                tick = start + offset
                done_ticks = offset + 1
                # Answers arrive between ticks, from whichever surface the
                # operator happened to be in front of. Reading them back here is
                # what turns "held" into "moving again" without the run having
                # to be restarted.
                freed = self.store.release_waiting_tasks(slug)
                if freed["released"] or freed["refused"]:
                    log.info(
                        "tick %d unblocked %d task(s), %d refused",
                        tick,
                        freed["released"],
                        freed["refused"],
                    )
                ctx = RunContext(
                    company=company,
                    tick=tick,
                    budget=budget,
                    breaker=breaker,
                    data_path=self.settings.data_path,
                    memory=memory,
                    store=self.store,
                    skills=skills,
                )
                for spec in due_roles(tick, enabled):
                    try:
                        for line in executor.run_turn(slug, spec, ctx):
                            log.info("tick %d [%s] %s", tick, spec.role.value, line)
                    except requests.RequestException as exc:
                        # LLM unreachable even after retries: leave a trace the
                        # operator can see and stop cleanly instead of crashing.
                        log.error("tick %d [%s] LLM unreachable: %s", tick, spec.role.value, exc)
                        self.store.record_action(
                            slug,
                            "system",
                            "llm_unreachable",
                            {"agent": spec.role.value},
                            f"run stopped: {exc}. Check `python -m corparius.cli doctor`.",
                            False,
                        )
                        frozen = True
                        break
                    # Graceful degradation: a SAFE breaker freezes the whole session.
                    if breaker.mode == CircuitBreaker.SAFE:
                        log.error("tick %d circuit breaker SECURISE: freezing session", tick)
                        self.store.record_action(
                            slug,
                            "system",
                            "circuit_breaker_freeze",
                            {"mode": breaker.mode},
                            "session frozen, operator alerted",
                            False,
                        )
                        frozen = True
                        break
                if frozen:
                    break
                if breaker.mode == CircuitBreaker.CONSERVATIVE:
                    log.warning("tick %d circuit breaker CONSERVATEUR: reduced posture", tick)
            # Only bank the hours actually played: a stop mid-morning must not
            # skip the company's clock to the end of the day.
            start += done_ticks
            ran += done_ticks
            self.store.save_state(slug, {"tick": start, "updated": time.time()})
            last = {"mode": breaker.mode, "budget_used": budget.used, "frozen": frozen}
            days += 1
            if frozen or stopped or not loop:
                break
            # The day boundary is where a long-lived loop catches up with the
            # world: what the operator changed, and what the company itself
            # learned yesterday.
            memory = self.store.recent_outputs(slug, "write_eod_summary", 3)
            self.settings = Settings()
            self.router = HybridRouter(self.settings)
            # The gate is rebuilt for the same reason as the router: an operator
            # who tightens the permission mode mid-run expects tomorrow morning
            # to obey it, not the mode the process started with.
            gate = ApprovalGate(
                self.store, PermissionEngine.from_settings(self.settings, company, self.store)
            )
            skills = _load_skills(self.settings, slug)
            executor = Executor(self.router, gate, self.store, self.settings)
            time.sleep(1)
        # A rule granted "for this run" that outlived the run would be a standing
        # authorisation the operator never gave.
        self.store.clear_run_rules(slug)
        # `ran`, not ticks * days: a run stopped mid-day did not play a full day,
        # and reporting that it did would be the console lying about its own work.
        return {"ticks_run": ran, "next_tick": start, "days": days, "stopped": stopped, **last}
