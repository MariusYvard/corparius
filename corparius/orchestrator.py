"""Scheduler (cadences) and Runtime (the tick loop that runs a company day).

A tick is one simulated hour. An agent is due when the tick is a multiple of its
cadence, so the roster is naturally staggered instead of firing all at once.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace

import requests

from . import documents, inbox, llm
from .agents import ROSTER, AgentSpec, Executor
from .config import Settings
from .hitl import ApprovalGate
from .llm import HybridRouter
from .models import AgentRole
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
    memory_top_k: int = 0  # durable facts recalled per prompt; 0 disables recall
    # The company's own files, extracted once per tick. A pitch deck, a spec,
    # a price list: knowledge that had no way into a prompt at all before —
    # only the config, a hand-written skill, or nothing.
    documents: str = ""
    # The pictures among them, read and ready to send. The product said an image
    # was "offered to the models that accept images" for two releases while
    # `documents.images()` had no caller at all and nothing here could have sent
    # one. This is the field that makes the sentence true.
    images: list = field(default_factory=list)
    # What could not be sent, and why. Carried rather than dropped, because "no
    # silent truncation" covers a picture left behind as much as a cut document.
    images_skipped: list = field(default_factory=list)


def _load_skills(settings, slug: str):
    """None rather than an empty loader when skills are off, so _messages has a
    single condition to check and a company with no skills pays nothing."""
    if not getattr(settings, "skills_enabled", True):
        return None
    loader = SkillLoader.for_company(slug, max_chars=getattr(settings, "skill_max_chars", None))
    if loader.skills:
        log.info("%d skill(s) loaded for %s", len(loader.skills), slug)
    return loader if loader.skills else None


def _memory_top_k(settings) -> int:
    """0 when memory is off, which is the single condition _recall checks."""
    if not getattr(settings, "memory_enabled", True):
        return 0
    return max(0, int(getattr(settings, "memory_top_k", 5)))


def due_roles(
    tick: int,
    enabled: dict,
    paused: set[str] | None = None,
    overrides: dict[str, int] | None = None,
    session_start: bool = False,
) -> list[AgentSpec]:
    """Which roles run this tick.

    `paused` is the set of roles the operator has told the CEO to stand down.
    Cadence answers "has enough time passed"; it has no way to answer "is this
    worth doing", and the two are not the same question. An operator who says
    "too early for cold emailing, I want a working prototype first" is answering
    the second, and until this argument existed the runtime could not hear it:
    the CEO replied that it would pause the campaigns and the next tick drafted
    another one.
    """
    paused = paused or set()
    overrides = overrides or {}
    specs = []
    for role, spec in ROSTER.items():
        if spec.cadence_hours is None:
            continue
        if not enabled.get(role.value, False):
            continue
        if role.value in paused:
            continue
        # The CEO is the one role whose turn should follow an event, not a
        # clock. Twelve hours meant that starting a run, watching it produce
        # something wrong, and starting it again changed nothing until half a
        # day had passed — the operator could not get a decision out of it when
        # a decision was exactly what was wanted. So it runs at the top of every
        # session as well as on its cadence.
        if session_start and role is AgentRole.CEO:
            specs.append(spec)
            continue
        # "social once a day, not every two hours" is a sentence, not a YAML
        # edit. The operator's own period wins over the roster's default.
        every = overrides.get(role.value) or spec.cadence_hours
        if tick % every == 0:
            specs.append(spec)
    return specs


def cadence_overrides(store, slug: str) -> dict[str, int]:
    """Per-role periods the operator set in the CEO chat, in hours."""
    if store is None:
        return {}
    out: dict[str, int] = {}
    try:
        for d in store.directives(slug, "cadence"):
            try:
                hours = int(d.get("note") or 0)
            except (TypeError, ValueError):
                continue
            if d.get("target") and hours > 0:
                out[d["target"]] = hours
    except Exception:  # noqa: BLE001 - an unreadable directive must not stop a run
        return {}
    return out


def model_overrides(store, slug: str) -> dict[str, str]:
    """Per-role model pins the operator set, as `{role: "target:name"}`.

    The gap this closes: only three tiers are configurable, and nine of the ten
    roles take theirs from one of them. So giving the design agent a model that can
    read a picture meant moving the whole normal tier — measured on the owner's own
    configuration, that trades 535 tok/s for 49 across the CEO, outreach, support
    and design to gain vision on one of them. The alternative was editing
    `agents.py`, which is not configuration.

    Validated here rather than trusted: an unknown provider prefix would make every
    turn of that role fall through the chain to local, which looks like a slow day
    rather than a typo.
    """
    if store is None:
        return {}
    out: dict[str, str] = {}
    try:
        for d in store.directives(slug, "model"):
            role, model = d.get("target"), str(d.get("note") or "").strip()
            if role and model and _known_target(model):
                out[role] = model
    except Exception:  # noqa: BLE001 - an unreadable directive must not stop a run
        return {}
    return out


def _known_target(model: str) -> bool:
    """`target:name` with a target this build routes to, prefix spelled out.

    Deliberately **not** written on top of `llm._split`, which defaults an unknown
    prefix to local so that a bare Ollama tag like `gemma4:e4b` works in the tier
    settings. That default makes `opnerouter:typo` indistinguishable from an Ollama
    tag — both come back as local — so a pin validated through it would accept the
    typo and quietly send every turn of that role to Ollama.

    A pin therefore has to name its target: `local:gemma4:e4b`, not `gemma4:e4b`.
    The refusal is reported, so the operator learns the prefix rather than
    wondering why one role got slow.
    """
    from .llm import OPENAI_COMPAT_PROVIDERS

    prefix, sep, rest = str(model or "").partition(":")
    if not sep or not rest.strip():
        return False
    return prefix in ("local", "cloud", "claudecode") or prefix in OPENAI_COMPAT_PROVIDERS


def paused_roles(store, slug: str) -> set[str]:
    """Roles under a live `pause` directive. Read fresh every tick, so telling
    the CEO to stop takes effect on the next one rather than on a restart."""
    if store is None:
        return set()
    try:
        return {d["target"] for d in store.directives(slug, "pause") if d.get("target")}
    except Exception:  # noqa: BLE001 - a directive table that cannot be read must not stop a run
        return set()


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
        memory_top_k = _memory_top_k(self.settings)
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
            budget = TokenBudget(
                budgets.get("session_tokens", self.settings.session_token_budget),
                budgets.get("cost_budget", self.settings.session_cost_budget),
                # A ceiling for a named role, which is also a floor nobody else can
                # spend. Design runs once every 24 ticks with the most expensive turn
                # in the company; support runs every 3. One shared pool means support
                # spends it first and design arrives at a closed till.
                budgets.get("role_tokens") or {},
            )
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
                # Read alongside the text, once per tick and not once per agent.
                # Said when something is left behind: a picture over the size cap
                # or past the per-call limit is named in the log rather than
                # vanishing between the folder and the prompt.
                allowed = max(0, int(getattr(self.settings, "image_max_per_call", llm.MAX_IMAGES)))
                if allowed:
                    tick_images, tick_skipped = llm.read_images(
                        documents.images(slug), limit=allowed
                    )
                else:
                    # The operator said never. Not read, not encoded, not counted
                    # as skipped-for-size: refused on purpose, and said once.
                    tick_images, tick_skipped = [], []
                    if documents.images(slug):
                        log.info("tick %d: pictures on file but CORP_IMAGE_MAX_PER_CALL is 0", tick)
                for reason in tick_skipped:
                    log.info("tick %d image not sent — %s", tick, reason)
                # Read fresh every tick, like the cadence and pause directives:
                # pinning a role's model in the CEO chat takes effect on the next
                # tick rather than on a restart.
                pins = model_overrides(self.store, slug)
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
                    memory_top_k=memory_top_k,
                    # Read once per tick rather than per agent: extraction
                    # touches the disk, and every agent in a tick sees the
                    # same files.
                    documents=documents.context(slug),
                    images=tick_images,
                    images_skipped=tick_skipped,
                )
                for spec in due_roles(
                    tick,
                    enabled,
                    paused_roles(self.store, slug),
                    cadence_overrides(self.store, slug),
                    #  counts turns already taken in this session, so this is true
                    # exactly once per launch.
                    session_start=(ran == 0 and offset == 0),
                ):
                    # A pinned model replaces the tier's, for this role only. The
                    # roster spec is shared, so it is copied rather than mutated —
                    # writing to it would pin the model for every company in the
                    # process, which the console runs several of.
                    pinned = pins.get(spec.role.value)
                    if pinned and pinned != spec.model:
                        spec = replace(spec, model=pinned)
                        log.info("tick %d [%s] pinned to %s", tick, spec.role.value, pinned)
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
                        # A run that stops itself has to say so somewhere the
                        # operator looks. One row in the action log is not that.
                        inbox.notify(
                            self.store,
                            slug,
                            "system",
                            "The run stopped: no model could be reached",
                            f"{exc}. Run `corparius doctor` to see which tier is unreachable.",
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
                        inbox.notify(
                            self.store,
                            slug,
                            "system",
                            "The session froze: token velocity hit the ceiling",
                            "The circuit breaker reached SECURISE and stopped the day. The "
                            "ceiling that tripped is this company's own "
                            "`budgets.tokens_per_minute` in company.yaml — raise that, not "
                            "CORP_TOKENS_PER_MINUTE_LIMIT, which only applies when the "
                            "company sets none. Or open the spend breakdown and find what "
                            "is spending.",
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
            memory_top_k = _memory_top_k(self.settings)
            executor = Executor(self.router, gate, self.store, self.settings)
            time.sleep(1)
        # A rule granted "for this run" that outlived the run would be a standing
        # authorisation the operator never gave.
        self.store.clear_run_rules(slug)
        repo = self._autocommit(slug, ran)
        # `ran`, not ticks * days: a run stopped mid-day did not play a full day,
        # and reporting that it did would be the console lying about its own work.
        return {
            "ticks_run": ran,
            "next_tick": start,
            "days": days,
            "stopped": stopped,
            "repo": repo,
            **last,
        }

    def _autocommit(self, slug: str, ran: int) -> dict:
        """Commit the company folder once the run is over, when the operator
        asked for it. Once per run and not once per tick: an agent changes
        company.yaml or skills/ rarely, and a commit per tick would bury the
        real edits under dozens of empty ones.

        Never raises. A repository that cannot be reached is not a reason to
        lose a run that already happened.
        """
        from . import companyrepo

        if not companyrepo.autocommit_enabled():
            return {"enabled": False}
        try:
            res = companyrepo.sync(slug, f"{slug}: automatic commit after {ran} tick(s)")
        except Exception as exc:  # defensive: sync already swallows its own
            return {"enabled": True, "ok": False, "error": str(exc)}
        return {"enabled": True, **res}
