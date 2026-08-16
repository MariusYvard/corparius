"""The turn executor.

Control flow is deterministic: code decides which tools run, and in what order. The LLM only
drafts content. Routing stays out of the model.

The roster itself — who the ten agents are, their cadences, their playbooks — is
`corparius/roster.py`. It used to be the first 150 lines of this file, and that is why the
tool effects, which read the roster, ended up importing the module that imports the tools.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import housestyle, structured
from .config import cfg
from .config.permissions import risk_of
from .config.provider_table import split_target
from .kernel import paths
from .kernel.records import AgentRole, ToolResult, Trace
from .roster import AgentSpec
from .safety import BudgetExceeded, LoopGuard
from .tools.registry import TOOLS

log = logging.getLogger("corparius.agents")


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
    # The company's own files. Bounded in documents.context, because this
    # rides on every prompt and an unscoped block already cost this project
    # 3 815 characters a turn.
    files = _files(ctx, tool)
    if files:
        system = f"{system}\n\n{files}"
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
    # How this company writes, beside the language it writes in. One block: the half a model has to
    # apply (neutral, no promotion, vary how many things you list) plus a line naming the mechanical
    # rules, which are also checked after the fact.
    #
    # Saying them as well as checking them is not duplication. The check catches what a model does;
    # the sentence is what stops it doing it, and the cheapest violation is the one that never
    # happened. `ctx.style` is the company's own charter when it has one, read once per tick.
    charter = housestyle.instruction(getattr(ctx, "style", None))
    if charter:
        system = f"{system}\n\nHow this company writes:\n{charter}"
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


def _files(ctx, tool) -> str:
    """The company's own documents, ranked against the prompt about to be sent.

    The same shape as `_recall` directly below, and that is the point: memory has been ranked against
    `tool.draft_prompt(ctx)` for a long time while the document block four lines away ignored it
    entirely. One function held both, so the inconsistency was visible on one screen and still went
    unnoticed — a design agent building a sales page and a finance agent reviewing spend received the
    same 6 000 characters, picked by modification time.

    Falls back to `ctx.documents`, the pre-rendered recency block, whenever there are no files to rank
    or no prompt to rank them against. Every context that never carried `doc_files` — the console's
    one-off calls, a plugin's, the tests that build a minimal ctx — keeps exactly what it had.
    """
    files = getattr(ctx, "doc_files", None)
    if not files:
        return getattr(ctx, "documents", "") or ""
    try:
        query = tool.draft_prompt(ctx)
    except Exception:
        # A tool whose prompt needs something this context lacks still gets its documents. The block
        # is worth more than the ranking, and an exception here would take down a turn over the
        # ordering of a paragraph.
        query = ""
    from . import documents as documents_mod

    return documents_mod.context(
        ctx.company.get("slug", ""),
        query=query,
        docs=files,
    ) or (getattr(ctx, "documents", "") or "")


def _styled(data, style):
    """Every string in a structured answer, through the charter. Returns (data, what is left).

    Walks nested lists and mappings because a tool's schema does: `tasks` is a list of strings and
    `findings` a list of mappings, and a charter that only reached the top level would leave the
    part a visitor actually reads untouched.
    """
    left: list[dict] = []

    def walk(value):
        if isinstance(value, str):
            fixed, hits = housestyle.apply(value, style)
            left.extend(hits)
            return fixed
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    return walk(data), left


def _site_pages_for(ctx) -> list:
    """The pages worth rendering for this company: its own site, or the generated one.

    The same precedence `app/publish.py` uses, and for the reason the *second* live divergence in
    this project was about: a company that maintains its own `site/public` publishes that, and a
    review that rendered the generated page instead would be criticising a file nobody visits.

    Home page first. `_owned_pages` learned that by measurement — sorting by size put a 7 674-
    character `tech.html` ahead of `index.html` and the home page was never reviewed at all — and a
    capture budget of four pages would repeat the mistake exactly.
    """
    slug = str((ctx.company or {}).get("slug") or "")
    own = paths.owned_site(slug) if slug else None
    if own is not None:
        pages = sorted(
            own.rglob("*.html"), key=lambda p: (p.name != "index.html", p.stat().st_size)
        )
        if pages:
            return pages
    generated = paths.site_index(getattr(ctx, "data_path", "") or ".", slug)
    return [generated] if generated.is_file() else []


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
        """Run a backlog task's tool for real. Returns True if a guard tripped.

        `ctx.task` is set for the whole of this method and cleared on the way out.
        `by_task_only` tools exist to serve a task, and `ask_operator`'s prompt has
        always said "this task" while nothing put the task anywhere a prompt could
        read it. Clearing it matters as much as setting it: the context is shared
        across the whole turn, so a task left behind would be read by every playbook
        tool that ran afterwards.

        Set around everything rather than around the call, so the invariant — no task
        on the context after this returns — holds on every path out, including the
        early one where nothing can run the task at all. A test asserted the
        invariant and found that path.
        """
        ctx.task = task
        try:
            return self._work_task_inner(company, spec, ctx, task, loop, done)
        finally:
            ctx.task = None

    def _work_task_inner(self, company, spec, ctx, task, loop, done) -> bool:
        tool_name = (task.get("tool") or "").strip()
        if tool_name not in TOOLS:
            self._hold_untooled(company, task, done)
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

    def _hold_untooled(self, company, task, done) -> None:
        """A task nothing can run is held for the operator, not closed as done.

        It used to be completed with the note "done (no tool mapped)". Measured in
        a real store: **22 tasks closed that way**, every one of them having done
        nothing — and because nothing was done, the condition that produced the
        task was still there on the next turn, so the agent proposed it again. Six
        near-identical proposals about one badge on one landing page, each approved,
        each closed, none of it happening. A board of green rows and no work.

        `waiting` rather than left approved: `claim_next_task` orders by priority
        then age, so a task that can never run and stays in the queue would be
        picked first for that role forever and starve everything behind it.
        `release_waiting_tasks` ignores a note that names no blocker, so it stays
        put until somebody decides — which is the honest state.
        """
        from . import inbox

        self.store.set_task_status(
            task["id"], "waiting", "no tool: needs an owner or a tool before it can run"
        )
        done.append(
            f"backlog #{task['id']} held, nothing can run it: {task['title'][:60]} "
            f"(target {task.get('target') or '?'} has no tool for this)"
        )
        inbox.notify(
            self.store,
            company,
            task.get("target") or "ceo",
            # The id is in the title on purpose. `inbox.notify` is idempotent on the
            # title, so one notice per *task* rather than one for all of them — two
            # held tasks used to collapse into a single notice, and settling one left
            # the other invisible.
            f"Task #{task['id']} is waiting for an owner",
            f"“{task['title'][:90]}” was approved, but no tool on {task.get('target') or 'that role'} "
            "can carry it out, so nothing would happen if it ran. Open the backlog, set the "
            "agent and the tool that should do it — or reject it. It used to be marked done "
            "instead, which is why the same idea kept coming back.",
            fix="backlog",
            # What the console needs to settle it without leaving the page.
            options=(f"task:{task['id']}",),
        )

    def _pictures_for(self, tool, spec, ctx) -> list:
        """The company's images, for the turns where they are worth their price.

        Three conditions, all required, cheapest to check first:

        1. the tool asked (`sees_images`) — a capture helps a design brief and does
           nothing for reconciling Stripe;
        2. the company has one on file;
        3. the model can read one. **Measured first, declared second**: a preflight
           verdict outranks the catalogue, because this project already knows what
           a capability claim is worth. With neither, nothing is sent — a picture
           mailed to a text-only model is paid for and thrown away by the provider.
        """
        if not getattr(tool, "sees_images", False):
            return []
        on_file = list(getattr(ctx, "images", []) or [])
        shoots = bool(getattr(tool, "shoots_site", False))
        if not on_file and not shoots:
            return []
        # Asked of the router, not read off the settings: `spec.model` is None for
        # nine of the ten roles and the tier decides, so reading the tier here is
        # how this would come to disagree with the call it reasons about.
        model = self.router.resolve_model(spec.difficulty, spec.model)
        if not self._model_reads_images(model, ctx):
            log.info(
                "[%s] %s: %s reads no images, %d not sent",
                spec.role.value,
                tool.name,
                model,
                len(on_file),
            )
            return []
        # **Taken here, after the model has been established as able to read one.** A capture costs
        # a couple of seconds of browser per page, and spending that to send a picture the provider
        # will drop is the same waste `sees_images` was written to avoid — one step later in the
        # same function.
        return (self._site_shots(ctx, spec, tool) if shoots else []) + on_file

    def _site_shots(self, ctx, spec, tool) -> list:
        """Pictures of the company's own pages, rendered now.

        The design agent has always reviewed sites it had never seen: `_site_text` strips the tags
        and sends the prose, which is the right input for wording and says nothing about contrast,
        hierarchy, or whether the first screen names what is being sold. The text still goes; this
        is the other half.

        Never fatal, at every step. No browser on the machine, a page that would not render, a file
        too large to send — each of those costs this turn its picture and nothing else, and the
        review carries on with exactly what it had before.
        """
        from .providers import llm as llm_mod
        from .providers import screenshot

        pages = _site_pages_for(ctx)
        if not pages or not screenshot.available():
            if pages:
                log.info(
                    "[%s] %s: no browser on this machine, so the review is text only",
                    spec.role.value,
                    tool.name,
                )
            return []
        # Under the company's own folder rather than a temporary directory, and deliberately not in
        # `documents/`: an operator's document list must not fill up with machine-made screenshots,
        # and `documents/written/` is synced to the company repository, where a new PNG per run
        # would be a commit per run of a file nobody reads.
        into = paths.companies_dir() / (ctx.company.get("slug", "") or "company") / ".shots"
        made = screenshot.capture_all([str(p) for p in pages], into)
        if not made:
            return []
        # `Path`, not `str`. `read_images` decides the media type from `path.suffix` and a string has
        # none, so every capture came back as "not an image format a provider accepts" — a picture
        # taken, paid for in browser time, and dropped one line before it would have been sent. It
        # failed silently into the skipped list, which is exactly where an end-to-end test earns its
        # place over one that stops at `capture_all`.
        shots, skipped = llm_mod.read_images([Path(p) for p in made])
        if skipped:
            log.info(
                "[%s] %s: %d capture(s) too large to send", spec.role.value, tool.name, len(skipped)
            )
        log.info("[%s] %s: %d page(s) rendered and sent", spec.role.value, tool.name, len(shots))
        return shots

    def _model_reads_images(self, model: str, ctx) -> bool:
        """Measured verdict if there is one, the catalogue's claim otherwise."""
        # Mock mode has no model to be wrong about, and the mock reports what it
        # was handed — letting pictures through is what makes an offline run
        # exercise this path instead of skipping it.
        if getattr(self.router.settings, "llm_mock", False):
            return True
        _, name = split_target(model)
        store = getattr(ctx, "store", None)
        if store is None:
            return False
        try:
            for row in store.known_probes():
                if row["model"] == name and row.get("vision_ok") is not None:
                    return bool(row["vision_ok"])
        except Exception:  # noqa: BLE001 - a probe table that cannot be read is not a verdict
            pass
        try:
            from .providers import modelinfo

            return bool(modelinfo.describe(model, modelinfo.cached(store))["vision_declared"])
        except Exception:  # noqa: BLE001 - no catalogue means no claim, not a crash
            return False

    def _invoke(self, company, spec, ctx, tool_name, loop):
        """Run one tool through budget, draft, loop guards and the HITL gate.
        Returns (result, stop); stop=True means a guard tripped, halt the turn."""
        tool = TOOLS[tool_name]
        try:
            ctx.budget.check_before(role=spec.role.value)
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
        pictures = self._pictures_for(tool, spec, ctx)
        # Omitted rather than passed empty, for the reason HybridRouter._carry
        # spells out: a router or provider written before images existed — a test
        # double, a plugin — must keep working, and "no keyword" says "no images"
        # exactly as well as an empty list.
        carry = {"images": pictures} if pictures else {}
        if tool.needs_draft and tool.schema:
            # Same shape out, whatever model answered. The harness may spend more
            # than one call (a repair round), but it accounts for every one.
            result = structured.ask(
                self.router,
                _messages(spec, ctx, tool),
                tool.schema,
                difficulty=spec.difficulty,
                # The pin, which this path used to drop on the floor. `spec.model`
                # carries a per-role model set by a `model` directive; the raw-draft
                # branch below has always passed it, and this one never did — so a
                # pin was honoured for prose and silently ignored for every tool
                # with a schema, which is most of the ones worth pinning.
                #
                # Measured on a real run: design pinned to `claudecode:opus`, the
                # log said so, and `review_site` was answered by
                # `cerebras:gpt-oss-120b`, which cannot produce JSON — so the tool
                # reported "no model returned usable structure" and did nothing.
                model=spec.model,
                **carry,
            )

            def _bill(answer) -> None:
                for used in answer.usages:  # a repair round is a real call; bill it
                    ctx.budget.record_usage(
                        used.input_tokens, used.output_tokens, used.cost, spec.role.value
                    )
                    ctx.breaker.record(used.total)
                    self.store.record_usage(
                        company, spec.role.value, used.input_tokens, used.output_tokens, used.cost
                    )

            _bill(result)

            # **One extra round, when the tool asks for one.** The first answer says what it needs;
            # this puts that in front of the model and asks again. `Behaviour.refine` carries why it
            # is bounded at one and why the capability lives here rather than in the tool: the
            # executor owns routing, the budget, the breaker, the usage log and the per-role model
            # pin, and a tool reaching a model itself would escape all five.
            #
            # Same router, same schema, same pin, and billed through the same `_bill` — which is the
            # whole point of it being an executor capability. A second call that did not reach
            # `ctx.budget` would be spend the operator's ceiling never sees.
            more = tool.refine_prompt(ctx, result)
            if more:
                second = structured.ask(
                    self.router,
                    [*_messages(spec, ctx, tool), {"role": "user", "content": more}],
                    tool.schema,
                    difficulty=spec.difficulty,
                    model=spec.model,
                    **carry,
                )
                _bill(second)
                # Only if it answered. A refused or empty second round leaves the first answer
                # standing rather than replacing something usable with nothing — the tool asked for
                # more context, it did not stake the turn on getting it.
                if second.ok and second.data:
                    result = second

            # **The charter, applied to the answer rather than asked for.** Straight quotation
            # marks replace curly ones by substitution, with no reading required; everything else
            # (an em dash, a banned word) is reported and left alone, because replacing one needs
            # the sentence and a checker that guessed would quietly change what the agent meant.
            #
            # On `result.data` and not on the JSON around it: the effect reads the fields, so this
            # is the last point where the text is still text.
            result.data, left = _styled(result.data, getattr(ctx, "style", None))
            if left:
                # Recorded beside the action rather than raised. The draft is usable and the
                # violation is a fact about it, and a turn that failed over punctuation would be
                # the charter costing more than it saves.
                rules = sorted({v["rule"] for v in left})
                log.info(
                    "[%s] %s: %d style violation(s): %s",
                    spec.role.value,
                    tool_name,
                    len(left),
                    ", ".join(rules),
                )
                ctx.style_violations = left
                # **Recorded, not only logged.** A log line is invisible to the product: the operator
                # does not read it and no agent can. The action log is the history this codebase
                # already uses to notice a pattern (`_repeated_failure` reads it to decide there is a
                # procedure worth writing down), so a wording corrected on three different days is
                # visible to `write_style_rule` through exactly the same door.
                #
                # `ok=True`, and the distinction matters: the draft is usable and a violation is an
                # observation about it. Recording it as a failure would feed `_repeated_failure` and
                # have the company writing a skill about how to fail at punctuation.
                #
                # One row per turn rather than one per hit, so a paragraph with nine curly quotes is
                # one line in a log a person reads.
                self.store.record_action(
                    company,
                    spec.role.value,
                    "style_violation",
                    {"rules": rules, "wording": sorted({v["text"] for v in left})[:8]},
                    f"{tool_name}: " + ", ".join(rules),
                    True,
                )

            ctx.structured = result
            # The loop guard sees the **final** draft only. The first answer is scaffolding — a tool
            # naming the same three sections on two consecutive turns is not a stutter, it is a tool
            # working, and counting it would stop a company for being consistent.
            draft = json.dumps(result.data, ensure_ascii=False)
            if loop.observe_output(self.router.embed(draft)):
                log.warning("[%s] loop stop: semantic stutter", spec.role.value)
                return None, True
        elif tool.needs_draft:
            res = self.router.generate(
                _messages(spec, ctx, tool),
                difficulty=spec.difficulty,
                model=spec.model,
                **carry,
            )
            ctx.budget.record_usage(
                res.usage.input_tokens, res.usage.output_tokens, res.usage.cost, spec.role.value
            )
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
            # The routing detail, from the harness result set above. Recorded here because
            # this is the one caller that has it — twelve tool effects read `.data` off the
            # same object and eleven of them read nothing else.
            Trace.of(ctx.structured),
        )
        if result.pending:
            log.info("[%s] paused for human approval on %s", spec.role.value, tool_name)
        return result, False
