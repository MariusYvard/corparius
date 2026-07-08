"""Scheduler (cadences) and Runtime (the tick loop that runs a company day).

A tick is one simulated hour. An agent is due when the tick is a multiple of its
cadence, so the roster is naturally staggered instead of firing all at once.
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass

from .agents import ROSTER, Executor, AgentSpec
from .safety import TokenBudget, CircuitBreaker
from .llm import HybridRouter
from .hitl import ApprovalGate

log = logging.getLogger("corparius.orchestrator")


@dataclass
class RunContext:
    company: dict
    tick: int
    budget: TokenBudget
    breaker: CircuitBreaker


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

    def run(self, company: dict, ticks: int = 6, loop: bool = False) -> dict:
        slug = company["slug"]
        budgets = company.get("budgets", {})
        gate = ApprovalGate(self.store, company.get("hitl_tools", self.settings.hitl_tools))
        executor = Executor(self.router, gate, self.store, self.settings)
        enabled = company.get("agents", {})

        start = int(self.store.load_state(slug).get("tick", 0))
        days = 0
        frozen = False
        last = {"mode": CircuitBreaker.NORMAL, "budget_used": 0, "frozen": False}
        while True:
            budget = TokenBudget(budgets.get("session_tokens", self.settings.session_token_budget))
            breaker = CircuitBreaker(
                budgets.get("tokens_per_minute", self.settings.tokens_per_minute_limit))
            for offset in range(ticks):
                tick = start + offset
                ctx = RunContext(company=company, tick=tick, budget=budget, breaker=breaker)
                for spec in due_roles(tick, enabled):
                    for line in executor.run_turn(slug, spec, ctx):
                        log.info("tick %d [%s] %s", tick, spec.role.value, line)
                    # Graceful degradation: a SAFE breaker freezes the whole session.
                    if breaker.mode == CircuitBreaker.SAFE:
                        log.error("tick %d circuit breaker SECURISE: freezing session", tick)
                        self.store.record_action(slug, "system", "circuit_breaker_freeze",
                                                 {"mode": breaker.mode},
                                                 "session frozen, operator alerted", False)
                        frozen = True
                        break
                if frozen:
                    break
                if breaker.mode == CircuitBreaker.CONSERVATIVE:
                    log.warning("tick %d circuit breaker CONSERVATEUR: reduced posture", tick)
            start += ticks
            self.store.save_state(slug, {"tick": start, "updated": time.time()})
            last = {"mode": breaker.mode, "budget_used": budget.used, "frozen": frozen}
            days += 1
            if frozen or not loop:
                break
            time.sleep(1)
        return {"ticks_run": ticks * days, "next_tick": start, **last}
