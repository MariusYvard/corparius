"""The business toolbox. Each tool carries a mock `effect` for the MVP; swap the
effect for a real integration (Stripe, Lemlist, GitHub, Meta Ads, ...) to go
live. Tools flagged `hitl` never execute until a human approves them.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from . import (
    cfg,
    deploy,
    documents,
    enrich,
    inbox,
    integrations,
    leadsource,
    mailbox,
    paths,
    permissions,
    signals,
    sitegen,
)
from . import (
    company as company_mod,
)
from .models import ToolResult

log = logging.getLogger("corparius.tools")


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        effect: Callable,
        *,
        hitl: bool = False,
        risk: str = permissions.READ,
        needs_draft: bool = False,
        prompt: Callable | None = None,
        schema: dict | None = None,
        skip_when: Callable | None = None,
        sees_images: bool = False,
        by_task_only: bool = False,
    ):
        self.name = name
        self.description = description
        self.hitl = hitl
        # Whether the company's own pictures are worth sending to this tool. Opt
        # in, per tool, for the same reason `skip_when` exists: an image is the
        # most expensive thing a turn can carry, and a screenshot of a competitor's
        # page helps a design brief and does nothing at all for reconciling Stripe.
        # Declared here so it is greppable, rather than inferred from the role.
        self.sees_images = sees_images
        # This tool runs only when a task names it, never from a playbook. Its
        # prompt is written for a task ("what *this task* cannot proceed without"),
        # so a playbook turn would ask it with no task to be about.
        #
        # Declared rather than deduced, because "on no playbook" is exactly what a
        # forgotten tool looks like too: `ask_operator` and `set_roster` sat there
        # for months, one by design and one by omission, and nothing could tell
        # them apart. `tests/test_tool_reach.py` now demands that every tool have a
        # path, and this flag is how a tool says its path is a task.
        self.by_task_only = by_task_only
        # What this tool does to the world outside the process, which is what
        # corparius/permissions.py weighs against the operator's threshold.
        # `hitl` stays separate and stronger: it is a gate declared by name,
        # not a class, and no threshold or standing rule can lower it.
        self.risk = risk
        self.needs_draft = needs_draft
        # Opt-in structured output: when a tool declares a schema, the executor
        # drives the router through corparius/structured so the effect receives a
        # validated dict (ctx.structured.data) that is the same shape whatever
        # model, tier or provider answered. Tools without a schema are unchanged.
        self.schema = schema
        self._prompt = prompt
        self._effect = effect
        # Checked before the model is called, and it returns the reason rather
        # than a boolean so the log says why nothing happened. Without it, a
        # needs_draft tool spends a real call before its effect can discover
        # there was nothing to do: `draft_support_reply` wrote a reply to
        # nobody every three hours on a company with no mailbox connected.
        self._skip_when = skip_when

    def skip_reason(self, ctx) -> str:
        return self._skip_when(ctx) if self._skip_when else ""

    def draft_prompt(self, ctx) -> str:
        return self._prompt(ctx) if self._prompt else ""

    def run(self, ctx, draft: str = "") -> ToolResult:
        return self._effect(ctx, draft)


def _name(ctx) -> str:
    return ctx.company.get("name", "the company")


def _ok(text: str) -> ToolResult:
    return ToolResult(ok=True, output=text)


def _fail(text: str) -> ToolResult:
    return ToolResult(ok=False, output=text)


def _channel(ctx) -> str:
    """The company's first configured channel. icp.channels was written by the
    example and the wizard but read by nobody, so every post claimed LinkedIn
    whatever the config said."""
    channels = (ctx.company.get("icp", {}) or {}).get("channels") or []
    return str(channels[0]) if channels else "linkedin"


def _social_post(ctx) -> str:
    """Reads the validated draft (same shape whatever model wrote it) instead of
    slicing raw text. ctx.structured is set by the executor for schema tools."""
    r = getattr(ctx, "structured", None)
    data = r.data if r else {}
    headline = data.get("headline", "").strip() or "post"
    tags = " ".join(f"#{h.lstrip('#')}" for h in data.get("hashtags", [])[:3])
    note = " (structure recovered)" if r and r.fell_back else ""
    tail = f" {tags}" if tags else ""
    # Write it down. This is the tool that holds the text — schedule_post runs
    # after ctx.structured has been reset, so if the draft is not stored here it
    # is not stored at all, which is exactly what used to happen.
    store = getattr(ctx, "store", None)
    if store is not None:
        body = (data.get("body") or headline).strip()
        store.add_draft(
            ctx.company.get("slug", "company"),
            "social",
            _channel(ctx),
            body + (f"\n\n{tags}" if tags else ""),
        )
    return f"Post drafted for {_channel(ctx)}: {headline[:100]}{tail}{note}"


def _schedule_post(ctx) -> str:
    """Promote the newest draft to the publishing queue, and say how deep it is.

    `draft_social_post` writes the text — it is the tool that has it, and
    ctx.structured is reset between tools, so this one never sees it. Here the
    draft becomes something a publisher can pick up, and the depth of the queue
    is the number that tells an operator whether any of this is reaching anyone.

    Before this, the effect was `f"Post scheduled for +2h on {channel}"` and
    nothing else. Measured on one operator's day, the social agent was the
    largest line in the company's spend — 29 065 tokens — and every post it
    wrote was gone before the next tick wrote another. "Scheduled" was true of
    nothing.
    """
    store = getattr(ctx, "store", None)
    if store is None:
        return "Draft queue unavailable"
    slug = ctx.company.get("slug", "company")
    # Everything waiting, not just the newest. A draft written by a backlog task
    # runs `draft_social_post` on its own, without the playbook's schedule_post
    # after it — so promoting only the last one leaves those stranded in `draft`
    # for ever, counted by nothing and published by nothing.
    pending = store.list_drafts(slug, state="draft", limit=50)
    if not pending:
        return "Nothing drafted to queue"
    for row in pending:
        store.set_draft_state(row["id"], "queued")
    waiting = store.count_drafts(slug, "queued")
    return (
        f"Queued for {_channel(ctx)}: {waiting} post(s) waiting. "
        "Nothing publishes them yet — read or export them from the console."
    )


def _remember(ctx) -> str:
    """Reads the validated draft, so what gets stored is a fact and a reason
    rather than whatever prose the model happened to produce. The store refuses
    a fact it already holds in other words, so an agent asked this every day
    does not fill the memory with paraphrases of one observation."""
    store = getattr(ctx, "store", None)
    if store is None:
        return "Memory unavailable"
    r = getattr(ctx, "structured", None)
    data = r.data if r else {}
    fact = str(data.get("fact", "")).strip()
    if not fact:
        return "Nothing worth remembering today"
    slug = ctx.company.get("slug", "company")
    kept = store.remember(
        slug,
        getattr(ctx, "role", "") or "ceo",
        fact,
        str(data.get("why", "")).strip(),
        max_rows=cfg.get_int("CORP_MEMORY_MAX", 200),
    )
    if not kept:
        return f"Already known, not stored again: {fact[:90]}"
    return f"Remembered: {fact[:110]}"


def _ask_operator(ctx) -> ToolResult:
    """A backlog task the CEO could only describe, not do. Mapped through
    ROLE_TOOL like any other, so "ask about X" is queued, parked and released by
    the machinery that already exists rather than by a second mechanism."""
    r = getattr(ctx, "structured", None)
    data = r.data if r else {}
    question = str(data.get("question", "")).strip()
    if not question:
        return _fail("Nothing to ask")
    answered = inbox.answer_to(ctx, question)
    if answered:
        return _ok(f"Operator answered: {answered[:120]}")
    ident = inbox.ask(ctx, question, str(data.get("why", "")).strip())
    if not ident:
        return _fail("Cannot reach the inbox")
    return ToolResult(ok=False, output=f"asked: {question}", pending=True, question_id=ident)


def _review_ad_budget(ctx) -> str:
    """budgets.daily_ad_spend_eur was the other write-only field: the log said
    '0 EUR/day, within cap' no matter what the operator had budgeted."""
    cap = (ctx.company.get("budgets", {}) or {}).get("daily_ad_spend_eur", 0)
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        cap = 0
    if cap <= 0:
        return "Ad budget reviewed: no daily cap set, ads stay off"
    return f"Ad budget reviewed: {cap} EUR/day cap, within cap"


def _build_site(ctx, draft: str) -> str:
    company = ctx.company
    out_dir = paths.site_dir(ctx.data_path, company.get("slug", "company"))
    # A mock draft is the echoed prompt, not a headline. Offline is the default
    # first run, so feeding it as the site's H1 makes the product look broken;
    # fall back to the company's own tagline instead.
    headline: str | None = draft.strip()
    if not headline or headline.startswith("[mock:"):
        headline = None
    path = sitegen.build_site(company, str(out_dir), headline=headline, store=ctx.store)
    return f"Sales site built at {path}"


def _deploy_site(ctx) -> ToolResult:
    """Returns a ToolResult, not a string: a deploy that published nothing used
    to be wrapped in _ok() and recorded in the action log as a success."""
    company = ctx.company
    slug = company.get("slug", "company")
    out_dir = paths.site_dir(ctx.data_path, slug)
    if not paths.site_index(ctx.data_path, slug).exists():
        sitegen.build_site(company, str(out_dir), store=ctx.store)
    res = deploy.deploy_result(str(out_dir))
    if res["ok"]:
        return _ok(f"Site published: {res['provider']} -> {res['result']}")
    if res["errors"]:
        return _fail("Site not published, every provider failed: " + "; ".join(res["errors"]))
    # Not a failure of the agent: it did its part and is missing something only
    # a human has. Recording that as a failed action buried it in the log, and
    # the backlog task behind it churned forever against a wall nobody was told
    # about. So it asks, and the work parks until the operator answers.
    title = "Where should the sales site be published?"
    question = inbox.ask(
        ctx,
        title,
        "No deploy provider is configured. Set one in the console (Providers), then answer "
        "here with its name — netlify, vercel, github-pages — to release this task."
        + (" Skipped: " + "; ".join(res["skipped"]) if res["skipped"] else ""),
    )
    if not question:
        answered = inbox.answer_to(ctx, title)
        return _fail(
            f"Site not published: still no provider after '{answered}'."
            if answered
            else "Site not published: no provider is configured."
        )
    return ToolResult(
        ok=False, output=f"asked the operator: {title}", pending=True, question_id=question
    )


def _find_targets(ctx) -> str:
    company = ctx.company
    icp = company.get("icp", {}) or {}
    query = icp.get("segment", "") or company.get("name", "")
    leads = enrich.enrich_all(leadsource.find_leads(query, 5))
    ctx.leads = leads
    if leads:
        return f"Found {len(leads)} leads via {leads[0].source}: " + ", ".join(
            lead.label() for lead in leads[:5]
        )
    # No source, no leads, no number. This used to answer "Found 5 ICP-matching
    # targets from enriched data (mock)" — five people who do not exist, written
    # into the action log every tick, where the flow metrics read it and the
    # outreach agent then drafted letters to them. It is the same fabrication
    # `triage_inbox` was already caught doing, and the repo's own rule is that
    # every number is Measured, Given or Estimated. That one was none.
    ctx.leads = []
    configured = ", ".join(leadsource.configured_sources()) or "none"
    return (
        "No lead found. Sources configured: "
        f"{configured}. Set CORP_LEADS_CSV for a list you own, or CORP_LEAD_SEARCH_URL "
        "to let corparius search the web itself (Settings, Leads)."
    )


def _no_lead_to_write_to(ctx) -> str:
    """Why there is nothing to draft, or "" when there is somebody to write to.

    `find_targets` runs first in the outreach playbook and puts what it found on
    `ctx.leads`. When it found nobody, the next tool used to draft anyway: a real
    model call, every three hours, producing a letter addressed to `[Nom]` that was
    then queued for the operator's approval as if it were ready to send.

    Two costs in one. The tokens, which is the same waste `draft_support_reply`
    stopped paying on a company with no mailbox. And the letter itself — asked to
    write a cold email to nobody in particular, a placeholder is the honest thing a
    model can produce. The prompt forbids it, and a prompt is a request; not
    drafting is the version that cannot be ignored.
    """
    leads = [lead for lead in (getattr(ctx, "leads", None) or []) if getattr(lead, "email", "")]
    if leads:
        return ""
    configured = ", ".join(leadsource.configured_sources()) or "none"
    return (
        "No lead with an email address, so there is nobody to write to and nothing "
        f"to draft. Sources configured: {configured}. Set CORP_LEADS_CSV for a list "
        "you own, or CORP_LEAD_SEARCH_URL to let corparius search (Settings, Leads)."
    )


def _outreach_prompt(ctx) -> str:
    """Name the person, or say plainly that there is nobody to name.

    The prompt was `Draft a 2-line cold email opener for {company}.` — which
    never mentions a recipient. So every draft came back addressed to
    `Bonjour [nom]`, and that was the model behaving correctly: asked to write
    a cold email to nobody in particular, a placeholder is the only honest
    thing it can produce. Meanwhile `find_targets` had just put five real
    people on `ctx.leads`, and nothing passed them along.

    Naming the lead is what turns a template into a letter, and the
    instruction against placeholders only means something once there is a name
    to use instead.
    """
    name = _name(ctx)
    leads = list(getattr(ctx, "leads", []) or [])
    if not leads:
        # No lead: say so rather than inviting a placeholder. A generic opener
        # the operator will personalise by hand is a usable thing; a letter to
        # `[nom]` presented as ready to send is not.
        return (
            f"Draft a 2-line cold email opener for {name}. No specific recipient is known, "
            "so write it so that it reads correctly with no name at all — never leave a "
            "bracket, a placeholder or a blank to fill in."
        )
    lead = leads[0]
    who = getattr(lead, "label", lambda: "")() or getattr(lead, "name", "") or ""
    role = getattr(lead, "role", "") or getattr(lead, "title", "")
    org = getattr(lead, "company", "") or getattr(lead, "org", "")
    about = ", ".join(part for part in (who, role, org) if part)
    return (
        f"Draft a 2-line cold email opener for {name}, addressed to: {about}. "
        "Use their actual name. Never write a placeholder, a bracket or a blank "
        "to fill in — this is sent as written."
    )


def _scan_signals(ctx) -> str:
    company = ctx.company
    icp = company.get("icp", {}) or {}
    keywords = [k for k in (icp.get("pains", []) + [icp.get("segment", "")]) if k]
    hits = signals.find_signals(keywords or [company.get("name", "")], 5)
    if hits:
        return f"Signals detected ({len(hits)}): " + " | ".join(hits[:3])
    return "No buying signals in configured sources (mock)"


# A bracketed blank a model left for someone to fill in: [Nom], [thème], {{name}}.
# Deliberately narrow — a real sentence rarely carries one, and a false positive
# here refuses a good email.
_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,40}\]|\{\{[^}\n]{1,40}\}\}")


def unfilled_blanks(text: str) -> list[str]:
    """Placeholders a draft still carries, in order, deduplicated.

    The prompt already tells the model never to leave one. That is a request, and
    the draft is sent verbatim — so the instruction was the only thing between a
    prospect and `Bonjour Dr [Nom]`. Measured beats declared here as everywhere:
    this reads the text that is actually about to go out.
    """
    seen: list[str] = []
    for found in _PLACEHOLDER.findall(str(text or "")):
        if found not in seen:
            seen.append(found)
    return seen


def _send_outreach(ctx, draft: str) -> str:
    company = ctx.company
    store = getattr(ctx, "store", None)
    # Never send a letter with a blank in it. `skip_when` stops the common case —
    # no lead, no draft — and this stops the rest: a model given a real name can
    # still leave `[thème de publication]` behind, and nothing else looks at the
    # text before it reaches somebody's inbox.
    blanks = unfilled_blanks(draft)
    if blanks:
        return (
            f"Not sent: the draft still has {len(blanks)} blank(s) to fill in "
            f"({', '.join(blanks[:3])}). It would have gone out as written."
        )
    leads = [lead for lead in getattr(ctx, "leads", []) if lead.email]
    if leads:
        cap = cfg.get_int("CORP_OUTREACH_MAX_PER_RUN", 20)
        subject = f"{company.get('name', 'corparius')} outreach"
        sent, skipped = [], []
        for lead in leads[:cap]:
            res, message_id = integrations.send_email_tracked(lead.email, subject, draft)
            if res is None:
                break  # SMTP not configured, fall back below
            if res == "sent":
                sent.append(lead.email)
                if store is not None:
                    # Remember who we wrote to, or a reply is just another
                    # unread message nobody connects to anything.
                    store.record_outreach(
                        company.get("slug", "company"), lead.email, message_id, subject
                    )
            else:
                skipped.append(lead.email)
        if sent or skipped:
            return f"Outreach: {len(sent)} sent, {len(skipped)} skipped. {', '.join(sent[:3])}"
    return (
        integrations.send_outreach_email(company, draft)
        or f"Cold email sent to 5 targets. Opener: {draft[:90]}"
    )


def _no_mailbox(ctx, consequence: str) -> str:
    """Say it once, where it can be acted on, instead of every tick forever.

    Three tools reached this state and each returned its own sentence to the
    action log. Correct, repeated on every run, and pointing at nothing the
    operator could click — the log line was the whole remedy. `add_inbox` is
    idempotent on a deterministic id, so filing it from a tick that runs every
    three hours leaves exactly one item, and the console renders `fix` as a
    button that opens the mail settings.
    """
    store = getattr(ctx, "store", None)
    if store is not None:
        inbox.notify(
            store,
            ctx.company.get("slug", "company"),
            getattr(ctx, "role", "") or "system",
            "No mailbox connected",
            "Outreach replies, inbox triage and support drafts all need one. "
            "Settings, then Mail: pick your provider and follow the steps.",
            fix="mail",
        )
    return f"No mailbox connected, so {consequence} (filed in the inbox)"


def _scan_replies(ctx) -> str:
    """Match unread mail against the addresses this company wrote to. This is
    the return leg of prospecting: without it the company emails people and
    never learns whether anyone answered."""
    store = getattr(ctx, "store", None)
    if store is None:
        return "Reply tracking unavailable"
    slug = ctx.company.get("slug", "company")
    if not mailbox.configured():
        return _no_mailbox(ctx, "replies cannot be seen")
    pending = store.pending_outreach(slug)
    if not pending:
        return "No outreach awaiting a reply"
    messages = mailbox.fetch(limit=40)
    if not messages:
        stats = store.outreach_stats(slug)
        return (
            f"Inbox read: nothing new. {stats['replied']}/{stats['sent']} outreach answered so far"
        )
    replied = []
    for msg in messages:
        if msg.sender in pending and store.mark_replied(slug, msg.sender, msg.body[:400]):
            replied.append(msg)
    if not replied:
        return f"Inbox read: {len(messages)} unread, none from the {len(pending)} prospects waiting"
    stats = store.outreach_stats(slug)
    who = ", ".join(m.sender for m in replied[:3])
    return (
        f"{len(replied)} prospect(s) replied: {who}. "
        f"Reply rate now {stats['replied']}/{stats['sent']}"
    )


def _triage_inbox(ctx) -> str:
    """Read the real inbox when one is connected, and say nothing when not.

    Half of this was fixed once: the old fixed string claimed '3 support, 1
    sales, 0 urgent' for every company. The replacement kept the numbers and
    called them "sample counts", which is the same three fabricated figures with
    a label on them — and they went into the action log every three hours, where
    the flow metrics read the log. The repo's own rule is to label every number
    Measured, Given or Estimated; these were none of the three.
    """
    if not mailbox.configured():
        return _no_mailbox(ctx, "there is nothing to triage")
    messages = mailbox.fetch(limit=40)
    if not messages:
        return "Inbox read: nothing unread"
    urgent = [
        m
        for m in messages
        if any(
            w in (m.subject + " " + m.body[:200]).lower()
            for w in ("urgent", "asap", "refund", "remboursement", "cancel", "broken")
        )
    ]
    top = messages[0]
    return f"Inbox read: {len(messages)} unread, {len(urgent)} look urgent. Top: {top.label()}"


# --------------------------------------------------------------------------
# What makes a CEO rather than a task generator
# --------------------------------------------------------------------------


def _record_decision(ctx, draft: str) -> str:
    """Write a decision down, or decline to invent one.

    "Nothing decided" is a real answer and has to stay cheap to give: a CEO
    that must produce a decision every turn produces noise, which is how three
    contradicting priorities landed in one afternoon.
    """
    text = " ".join((draft or "").split())
    if not text or text.lower().startswith("nothing decided"):
        return "No decision this turn"
    store = getattr(ctx, "store", None)
    if store is None:
        return "No store, so nothing recorded"
    store.add_decision(ctx.company.get("slug", "company"), text)
    return f"Decided: {text[:120]}"


def _keep(ctx, name: str, text: str, line: str) -> str:
    """Log the line, keep the document.

    The agent wrote several hundred words; the action log holds a hundred and
    twenty characters of them. Everything past that was thrown away at the
    moment of writing — including by the agent that would want it next turn.
    """
    slug = ctx.company.get("slug", "company")
    try:
        documents.write(slug, name, text)
    except OSError as exc:  # a full disk must not fail the turn
        log.warning("could not keep %s for %s: %s", name, slug, exc)
    return line


def _empty_draft(ctx, consequence: str) -> str:
    """Why a schema tool got nothing: the model said nothing, or none answered.

    Two very different facts, reported as one. `structured.ask` returns the schema
    defaults when no reply validates — empty lists, empty strings — so a tool that
    reads only `.data` cannot tell "it had nothing to add" from "every provider
    refused". Measured on a real run: groq and cerebras both answered 429, the
    harness fell back, and `write_site_content` reported "Nothing usable drafted".
    The operator read that as a bad site generator and had spent 365 026 tokens
    getting there.

    The harness has always carried the answer — `ok`, `fell_back`, `attempts`,
    `source`, `errors` — and this is the fourth caller to read only one field of it.
    """
    result = getattr(ctx, "structured", None)
    if result is not None and (getattr(result, "fell_back", False) or not result.ok):
        why = "; ".join(getattr(result, "errors", []) or []) or "no valid structure came back"
        where = getattr(result, "source", "") or "no provider"
        attempts = getattr(result, "attempts", 0)
        return (
            f"No model returned usable structure after {attempts} attempt(s) "
            f"({where}): {why}. {consequence}. This is a routing problem, not an "
            "empty answer — prove your models in the console (Providers)."
        )
    return f"Nothing to add, so {consequence}"


def _write_site_content(ctx, draft: str) -> str:
    """Turn a drafted plan into the site blocks, in company.yaml.

    The renderer gained `how_it_works`, `privacy` and `pages`, and I filled them
    in by hand to show them working — which is exactly the wrong way round. An
    operator hand-writing YAML is the friction this project exists to remove,
    and a capability nothing can reach is not a capability.

    **What it will write, and what it refuses to.** A company can describe its
    own protocol and its own data handling: those are facts it owns, and drafting
    them is honest work. It cannot invent a customer quote or a study — so
    `proof` and `testimonials` are never written here, and the tool says so
    rather than leaving the operator to wonder why those sections stayed empty.
    That is the same line the renderer already draws, one step earlier.
    """
    store = getattr(ctx, "store", None)
    slug = ctx.company.get("slug", "company")
    data = getattr(ctx, "structured", None)
    fields = data.data if data else {}

    steps = [str(s).strip() for s in (fields.get("steps") or []) if str(s).strip()][:5]
    privacy = [str(s).strip() for s in (fields.get("privacy") or []) if str(s).strip()][:5]
    page_title = str(fields.get("page_title", "")).strip()
    page_body = str(fields.get("page_body", "")).strip()

    if not (steps or privacy or page_body):
        return _empty_draft(ctx, "company.yaml is unchanged")

    path = company_mod.path_for(slug)
    try:
        raw = company_mod.load(path, slug)
    except (FileNotFoundError, ValueError) as exc:
        return f"Cannot read {slug}: {exc}"

    site = dict(raw.get("site") or {})
    wrote = []
    if steps:
        site["how_it_works"] = steps
        wrote.append(f"{len(steps)} step(s)")
    if privacy:
        site["privacy"] = privacy
        wrote.append(f"{len(privacy)} privacy point(s)")
    if page_title and page_body:
        pages = [p for p in (site.get("pages") or []) if isinstance(p, dict)]
        slug_new = company_mod._slugify(page_title) or "more"
        pages = [p for p in pages if p.get("slug") != slug_new]
        pages.append({"slug": slug_new, "title": page_title, "body": page_body})
        site["pages"] = pages[:6]
        wrote.append(f"a page ({slug_new})")
    raw["site"] = site

    cfg_out, errors, warnings = company_mod.validate(raw)
    if errors:
        # Refuse rather than persist: a company.yaml that stops loading takes the
        # whole company down, and this tool runs unattended.
        return f"Refused, the result would not validate: {'; '.join(errors)}"
    company_mod.dump(cfg_out, path)
    if store is not None:
        store.record_action(slug, "design", "write_site_content", {}, "; ".join(wrote), True)
    note = "Wrote " + ", ".join(wrote) + " into company.yaml"
    if not (cfg_out.get("site") or {}).get("proof"):
        note += (
            ". Proof and testimonials are left empty on purpose: a claim needs a source "
            "and a quote needs a name, and neither can be drafted"
        )
    return note


def _review_commitments(ctx) -> str:
    """Did the last plan happen? Compare what was promised to what was done.

    The CEO wrote "the absolute priority is to finish and deploy the new site"
    and then never looked again — three different "absolute priorities" in three
    hours in one real run, two of them contradicting each other. A CEO who never
    rereads their own plan is a plan generator.
    """
    store = getattr(ctx, "store", None)
    if store is None:
        return "No store, so nothing to hold anyone to"
    slug = ctx.company.get("slug", "company")
    plans = store.recent_outputs(slug, "set_daily_plan", 1)
    if not plans:
        return "No plan on record yet, so there is nothing to check against"
    done = [t for t in store.list_tasks(slug) if t["status"] == "done"]
    still_open = [t for t in store.list_tasks(slug) if t["status"] in ("approved", "in_progress")]
    plan = plans[0].replace("Daily plan set: ", "")[:110]
    if not done:
        return (
            f"Last plan: {plan}. Nothing has been completed since. Either it was not "
            f"actionable or the company is blocked ({len(still_open)} task(s) open)."
        )
    return (
        f"Last plan: {plan}. {len(done)} task(s) done since, {len(still_open)} open. "
        f"Most recent: {done[-1]['title'][:60]}."
    )


def _review_kpis(ctx) -> str:
    """The real numbers, or the honest absence of them.

    This returned "KPIs reviewed: signups flat, conversion 2.1%" for every
    company on every run — two fabricated figures that then fed the CEO's own
    decisions, while `reconcile_stripe` read a live balance three lines below in
    the same log. The rule this repo set itself is that every number is
    Measured, Given or Estimated, and those were none.
    """
    store = getattr(ctx, "store", None)
    if store is None:
        return "No store, so no numbers"
    slug = ctx.company.get("slug", "company")
    stats = store.outreach_stats(slug)
    flow = store.flow_metrics(slug)
    spend = sum(int(row.get("tokens", 0) or 0) for row in store.spend_by_agent(slug))
    revenue = store.recent_outputs(slug, "reconcile_stripe", 1)
    parts = [f"{flow['throughput']} task(s) completed, {flow['wip']} in progress"]
    if stats.get("sent"):
        parts.append(f"outreach {stats['replied']}/{stats['sent']} answered")
    else:
        parts.append("no outreach sent, so there is no reply rate to report")
    parts.append(f"{spend} tokens spent")
    parts.append(
        revenue[0].replace("Stripe reconciled: ", "revenue ") if revenue else "no revenue reading"
    )
    return "KPIs: " + "; ".join(parts)


def _stop_useless_work(ctx) -> str:
    """Stand down whatever produces into a void, and say so once.

    A real run drafted ten LinkedIn posts nobody could publish while the agent
    stood itself down and the CEO kept queueing "Publish a post today" for it.
    The stand-down was a patch on the agent; deciding what is worth producing is
    the CEO's job, and the CEO can now act on it.
    """
    store = getattr(ctx, "store", None)
    if store is None:
        return "No store, so nothing to weigh"
    slug = ctx.company.get("slug", "company")
    already = {d["target"] for d in store.directives(slug, "pause")}
    stopped, restarted = [], []

    unpublished = store.count_unpublished(slug)
    cap = cfg.get_int("CORP_SOCIAL_QUEUE_MAX", 5)
    if unpublished >= cap and "social" not in already:
        store.add_directive(
            slug, "pause", "social", f"{unpublished} drafts and nothing publishes them"
        )
        stopped.append(f"social ({unpublished} unpublished)")
    elif unpublished < cap:
        for d in store.directives(slug, "pause"):
            if d["target"] == "social" and "publishes them" in (d.get("note") or ""):
                store.clear_directive(d["id"])
                restarted.append("social, its queue drained")

    if not mailbox.configured() and "support" not in already:
        store.add_directive(slug, "pause", "support", "no mailbox connected")
        stopped.append("support (no mailbox)")

    if stopped:
        return "Stood down: " + ", ".join(stopped) + ". Nothing consumes what they produce."
    if restarted:
        return "Restarted: " + ", ".join(restarted)
    return "Every role still has somewhere for its work to go"


def _check_providers(ctx) -> str:
    """React when a tier keeps failing, instead of watching it fail.

    One run logged twenty-odd `429 Too Many Requests` from one provider and two
    `claude CLI exited 1`, and nothing anywhere reacted. The preflight knows how
    to answer this; what was missing was anybody asking.
    """
    store = getattr(ctx, "store", None)
    if store is None:
        return "No store, so no history to read"
    slug = ctx.company.get("slug", "company")
    failures = [o for o in store.recent_failures(slug, 40) if o]
    if not failures:
        return "No provider failure in the recent log"
    limited = [o for o in failures if "429" in o or "Too Many Requests" in o]
    # The measured fact, and only that. The remedy used to be spelled out here as
    # "run `corparius preflight`" — a terminal command told to somebody reading a
    # web console, in English, on a page that may be in French, while the console
    # has had a button doing exactly that all along. What to press is the console's
    # sentence to write, in the operator's own language; what happened is this
    # function's. `fix` is the seam between the two.
    note = f"{len(failures)} failed call(s) recently"
    if limited:
        note += f", {len(limited)} of them rate limits"
    note += "."
    inbox.notify(store, slug, "ceo", "Providers are failing", note, fix="preflight")
    return note


# What `_set_roster` writes when it stands a role down, and the only note it is
# allowed to clear. The operator's own stand-down, set in the CEO chat, carries a
# different one — and the whole reason this project grew standing directives was
# that a role the operator stood down kept being re-armed.
CEO_STAND_DOWN = "stood down by the CEO"


def _set_roster(ctx, draft: str = "") -> str:
    """Hire and fire. The most CEO decision there is, and it lived in a YAML file.

    `design -social` turns design on and social off. A role nobody has is
    dropped rather than promised.

    **It cannot undo the operator.** Turning a role back on clears only the
    stand-downs this tool wrote. Left as it was, putting this on the CEO's playbook
    would have had the CEO clearing the operator's own pauses twice a day — the
    exact failure standing directives were introduced to end, arriving through the
    tool meant to respect them.
    """
    store = getattr(ctx, "store", None)
    slug = ctx.company.get("slug", "company")
    words = [w.strip().lower() for w in re.split(r"[,\s]+", draft or "") if w.strip()]
    roles = set(company_mod.ROLES)
    off = [w.lstrip("-") for w in words if w.startswith("-") and w.lstrip("-") in roles]
    on = [w for w in words if not w.startswith("-") and w in roles]
    if not on and not off:
        return "No role named, so the roster is unchanged"
    kept: list[str] = []
    if store is not None:
        for role in off:
            store.add_directive(slug, "pause", role, CEO_STAND_DOWN)
        for role in list(on):
            paused = [d for d in store.directives(slug, "pause") if d["target"] == role]
            mine = [d for d in paused if (d.get("note") or "") == CEO_STAND_DOWN]
            theirs = [d for d in paused if (d.get("note") or "") != CEO_STAND_DOWN]
            if theirs:
                # Said, not silently ignored: a CEO that reports turning a role
                # back on while it stays off is the empty promise again.
                on.remove(role)
                kept.append(role)
                continue
            if not mine:
                # Already running. Reporting "on: coder" for a role that was never
                # off is a change that did not happen — measured on a real run, the
                # CEO announced exactly that on four consecutive turns.
                on.remove(role)
                continue
            for d in mine:
                store.clear_directive(d["id"])
    parts = []
    if on:
        parts.append("on: " + ", ".join(on))
    if off:
        parts.append("off: " + ", ".join(off))
    if kept:
        parts.append("left off, you stood them down: " + ", ".join(kept))
    if not parts:
        return "Roster unchanged"
    return "Roster changed — " + "; ".join(parts)


def _weekly_review(ctx) -> str:
    """Spent against produced, promised against delivered, over seven days.

    The end-of-day summary is a paragraph a model wrote. This is arithmetic: it
    can be wrong, but it cannot flatter.
    """
    store = getattr(ctx, "store", None)
    if store is None:
        return "No store, so no account to give"
    slug = ctx.company.get("slug", "company")
    week = store.week_summary(slug)
    if not week["actions"]:
        return "Nothing happened this week"
    line = (
        f"Seven days: {week['actions']} actions, {week['done']} task(s) finished, "
        f"{week['tokens']} tokens, {week['failed']} failed call(s)."
    )
    if not week["done"]:
        return line + " Nothing was finished, so every token this week bought nothing."
    return line + f" {week['tokens'] // max(1, week['done'])} tokens per finished task."


ROLE_TOOL = {
    "outreach": "send_outreach",
    "social": "draft_social_post",
    "support": "draft_support_reply",
    "design": "build_sales_site",
}


def _create_tasks(ctx) -> str:
    """Data-driven: the CEO reads what the company observed (buying signals,
    leads, KPIs) from the action log and queues targeted tasks, deduped against
    what is already open, plus a light baseline."""
    store = getattr(ctx, "store", None)
    if store is None:
        return "Backlog unavailable"
    slug = ctx.company.get("slug", "company")
    enabled = ctx.company.get("agents", {}) or {}
    open_pairs = {
        (t["target"], t.get("tool") or "")
        for t in store.list_tasks(slug)
        if t["status"] in ("approved", "in_progress")
    }
    created: list[str] = []
    wip_limit = cfg.get_int("CORP_WIP_LIMIT", 4)

    # What the operator told the CEO. A paused role must not be re-armed by the
    # CEO's own baseline: the run log shows `social stood down: 9 post(s)
    # queued` and, three lines later, the CEO queueing "Publish a post today"
    # for that same role. Standing a role down has to mean the whole company
    # stops asking it for work, not only that the agent skips its turn.
    paused = {d["target"] for d in store.directives(slug, "pause") if d.get("target")}
    focus = next((d["note"] for d in store.directives(slug, "focus") if d.get("note")), "")

    def queue(title, target, tool, priority):
        if target in paused:
            return
        if not enabled.get(target) or (target, tool) in open_pairs:
            return
        if store.wip_count(slug, target) >= wip_limit:
            return  # pull system: do not overproduce past the WIP limit
        store.add_task(slug, title, target, priority, "approved", "ceo", tool=tool)
        open_pairs.add((target, tool))
        created.append(target)

    signals = [o for o in store.recent_outputs(slug, "scan_signals", 3) if "detected" in o.lower()]
    if signals:
        queue(f"Act on buying signal: {signals[0][:60]}", "outreach", "send_outreach", 3)
    leads = store.recent_outputs(slug, "find_targets", 1)
    if leads and "found" in leads[0].lower() and "mock" not in leads[0].lower():
        queue("Contact the freshly found leads", "outreach", "send_outreach", 2)
    kpis = store.recent_outputs(slug, "review_kpis", 1)
    if kpis and ("flat" in kpis[0].lower() or "conversion" in kpis[0].lower()):
        queue("Refresh the landing page to lift conversion", "design", "build_sales_site", 2)
    # The baseline is what fills a quiet day. Under a stated priority it is the
    # wrong thing to fill it with: an operator who said "focus on the prototype"
    # does not want two housekeeping tasks queued on top of it every cycle.
    if focus:
        queue(f"Priority: {focus[:70]}", "ceo", "set_daily_plan", 3)
    else:
        queue("Publish a post today", "social", "draft_social_post", 1)
        queue("Clear the support inbox", "support", "draft_support_reply", 1)

    if not created:
        return "CEO backlog review: nothing new to queue"
    return f"CEO queued {len(created)} data-driven task(s): {', '.join(created)}"


def _review_proposals(ctx) -> str:
    store = getattr(ctx, "store", None)
    if store is None:
        return "Backlog unavailable"
    slug = ctx.company.get("slug", "company")
    proposals = store.list_tasks(slug, "proposed")
    cap = cfg.get_int("CORP_CEO_APPROVE_CAP", 3)
    approved = rejected = modified = 0
    for i, task in enumerate(proposals):
        if i < cap:
            fields: dict[str, object] = {}  # priority is int, tool is str
            if task["priority"] < 2:
                fields["priority"] = 2  # CEO re-prioritises the suggestion
            if not task.get("tool") and task["target"] in ROLE_TOOL:
                fields["tool"] = ROLE_TOOL[task["target"]]  # make it executable
            if fields:
                store.update_task(task["id"], **fields)
                modified += 1
            store.set_task_status(task["id"], "approved", "validated by CEO")
            approved += 1
        else:
            store.set_task_status(task["id"], "rejected", "declined by CEO")
            rejected += 1
    return f"CEO reviewed {len(proposals)}: {approved} approved ({modified} modified), {rejected} rejected"


def _already_proposing(ctx) -> str:
    store = getattr(ctx, "store", None)
    if store is None:
        return ""
    role = getattr(ctx, "role", "agent")
    open_ones = [
        t
        for t in store.list_tasks(ctx.company.get("slug", "company"), "proposed")
        if t["created_by"] == role
    ]
    return f"{role} already has an idea waiting with the CEO" if open_ones else ""


def _propose_task(ctx) -> str:
    """One open idea per role, and the idea has to say what it is.

    Support runs every three hours and filed "Idea from support" each time —
    five identical rows in one measured session, none carrying a tool, all
    completed "(symbolic)". Capping it at one per role stopped the pile from
    growing, which left one unreadable row instead of five: the title was
    generated from the role, so the proposal never contained the proposal. The
    CEO approved it blind and the operator could not tell one from another.

    So the agent writes it: a title that names the work, a sentence of why, and
    the tool that would do it. A backlog row that does not say what it is has
    nothing to review.
    """
    store = getattr(ctx, "store", None)
    if store is None:
        return "Backlog unavailable"
    slug = ctx.company.get("slug", "company")
    role = getattr(ctx, "role", "agent")
    result = getattr(ctx, "structured", None)
    fields = result.data if result else {}
    title = " ".join(str(fields.get("idea", "")).split())[:90]
    if not title:
        # Better nothing than a row that says "Idea from support": an empty
        # backlog is readable, a backlog of placeholders is not.
        return f"{role} had nothing specific to propose"
    why = " ".join(str(fields.get("why", "")).split())[:200]

    existing = store.list_tasks(slug)
    if any(t["created_by"] == role and t["status"] == "proposed" for t in existing):
        return f"{role} already has an idea waiting with the CEO"
    if any(t["title"].lower() == title.lower() for t in existing):
        # Already proposed once, whatever the CEO did with it. Re-filing it is
        # how five identical rows happened in the first place.
        return f"{role} already proposed that: {title}"

    store.add_task(
        slug,
        title,
        role,
        priority=1,
        status="proposed",
        created_by=role,
        why=why,
        # No tool, deliberately. The title is now model-written text, and an idea
        # is not an instruction: `_review_proposals` attaches the tool when the
        # CEO approves it, so nothing an agent writes arrives executable.
    )
    return f"{role} proposed to the CEO: {title}"


def _kaizen(ctx) -> str:
    store = getattr(ctx, "store", None)
    if store is None:
        return "Backlog unavailable"
    slug = ctx.company.get("slug", "company")
    fm = store.flow_metrics(slug)
    bottleneck = fm.get("bottleneck")
    if bottleneck and fm["by_target"].get(bottleneck, 0) >= 2:
        store.add_task(
            slug,
            f"Kaizen: unblock {bottleneck} ({fm['by_target'][bottleneck]} open)",
            bottleneck,
            priority=2,
            status="proposed",
            created_by="strategy",
            tool=ROLE_TOOL.get(bottleneck, ""),
        )
        return f"Kaizen: bottleneck {bottleneck}, proposed an improvement to the CEO"
    return (
        f"Kaizen: flow healthy (throughput {fm['throughput']}, wip {fm['wip']}, "
        f"{fm['tokens_per_completed_task']} tokens/task)"
    )


# Risk classes below describe the effect, not the subject. Drafting a pricing
# note is READ because nothing leaves the process; sending one cold email is
# EXTERNAL because a stranger receives it. Tools whose mock effect will become a
# real integration are classed for the integration, not for the mock, so
# swapping the effect does not silently widen what runs unattended.
_ALL = [
    Tool(
        "set_daily_plan",
        "Set the day's 1-3 priorities",
        needs_draft=True,
        prompt=lambda c: (
            f"Yesterday: {c.memory[0] if getattr(c, 'memory', None) else 'no prior summary'}. "
            f"In one sentence, set today's top priority for {_name(c)}."
        ),
        effect=lambda c, d: _ok(f"Daily plan set: {d[:140]}"),
    ),
    Tool(
        "write_eod_summary",
        "Summarise the day",
        needs_draft=True,
        prompt=lambda c: f"In one sentence, summarise the day for {_name(c)}.",
        effect=lambda c, d: _ok(_keep(c, "End of day", d, f"EOD summary: {d[:140]}")),
    ),
    Tool(
        "remember",
        "Write down one thing the company learned",
        needs_draft=True,
        prompt=lambda c: (
            f"What did {_name(c)} learn today that is still true next month? "
            "One fact about the market, the offer or the customers — not today's numbers."
        ),
        schema={
            "fact": {"type": "str", "required": True, "max_len": 200},
            "why": {"type": "str", "default": "", "max_len": 200},
        },
        effect=lambda c, d: _ok(_remember(c)),
    ),
    Tool(
        "ask_operator",
        "Ask the operator for something only they can supply",
        needs_draft=True,
        by_task_only=True,
        prompt=lambda c: (
            f"In one sentence, ask the operator of {_name(c)} for the one piece of "
            "information or access this task cannot proceed without."
        ),
        schema={
            "question": {"type": "str", "required": True, "max_len": 160},
            "why": {"type": "str", "default": "", "max_len": 300},
        },
        effect=lambda c, d: _ask_operator(c),
    ),
    Tool(
        "create_tasks", "CEO adds tasks to the backlog", effect=lambda c, d: _ok(_create_tasks(c))
    ),
    Tool(
        "review_proposals",
        "CEO validates or refuses proposed tasks",
        effect=lambda c, d: _ok(_review_proposals(c)),
    ),
    Tool(
        "propose_task",
        "Suggest a task to the CEO for review",
        needs_draft=True,
        # Checked before the call, not after: the cap is one open idea per role,
        # and support reaches this tool every three hours. Without this the model
        # writes a proposal that the effect then throws away, every time.
        skip_when=lambda c: _already_proposing(c),
        prompt=lambda c: (
            f"Propose one concrete task for {_name(c)}, drawn from what you have just seen "
            "in your own work. `idea`: the task itself, as an instruction someone could act "
            "on — name the thing, not the category. `why`: one sentence on what prompted it. "
            "If nothing in this turn warrants a task, leave `idea` empty rather than "
            "inventing something to file."
        ),
        schema={
            "idea": {"type": "str", "default": "", "max_len": 90},
            "why": {"type": "str", "default": "", "max_len": 200},
        },
        effect=lambda c, d: _ok(_propose_task(c)),
    ),
    Tool(
        "kaizen",
        "Continuous improvement: find the bottleneck, propose a fix",
        effect=lambda c, d: _ok(_kaizen(c)),
    ),
    Tool(
        "draft_social_post",
        "Draft a post for X or LinkedIn",
        needs_draft=True,
        prompt=lambda c: f"Draft one short {_channel(c)} post for {_name(c)}.",
        schema={
            "headline": {"type": "str", "required": True, "max_len": 120},
            "body": {"type": "str", "required": True, "max_len": 500},
            "hashtags": {"type": "list", "default": []},
        },
        effect=lambda c, d: _ok(_social_post(c)),
    ),
    Tool(
        "schedule_post",
        "Queue the drafted post so it can be published",
        risk=permissions.EXTERNAL,
        effect=lambda c, d: _ok(_schedule_post(c)),
    ),
    Tool(
        "find_targets",
        "Find ICP-matching prospects",
        risk=permissions.EXTERNAL,
        effect=lambda c, d: _ok(_find_targets(c)),
    ),
    Tool(
        "send_outreach",
        "Send a cold email sequence",
        risk=permissions.EXTERNAL,
        needs_draft=True,
        # Checked before the draft, like draft_support_reply with no mailbox. With
        # nobody to write to there is nothing to write, and paying a model call to
        # find that out is the exact waste that check was added for — on the tool
        # next to it, three hours apart.
        #
        # It also removes the letter to `[Nom]` at the root. Asked to write a cold
        # email to nobody, a model produces a placeholder; the prompt forbids it and
        # a prompt is a request. Not drafting at all is the only version that cannot
        # be ignored.
        skip_when=lambda c: _no_lead_to_write_to(c),
        prompt=lambda c: _outreach_prompt(c),
        effect=lambda c, d: _ok(_send_outreach(c, d)),
    ),
    Tool(
        "triage_inbox",
        "Triage the support inbox",
        risk=permissions.EXTERNAL,
        effect=lambda c, d: _ok(_triage_inbox(c)),
    ),
    Tool(
        "scan_replies",
        "Check the inbox for prospect replies",
        risk=permissions.EXTERNAL,
        effect=lambda c, d: _ok(_scan_replies(c)),
    ),
    Tool(
        "draft_support_reply",
        "Draft a reply to the top ticket",
        needs_draft=True,
        prompt=lambda c: f"Draft a one-line support reply for a {_name(c)} user.",
        skip_when=lambda c: (
            "" if mailbox.configured() else _no_mailbox(c, "there is no ticket to reply to")
        ),
        effect=lambda c, d: _ok(f"Reply drafted: {d[:110]}"),
    ),
    Tool(
        "review_ad_budget",
        "Review ad spend and pacing",
        effect=lambda c, d: _ok(_review_ad_budget(c)),
    ),
    Tool(
        "adjust_bids",
        "Write ad variants and adjust bids",
        risk=permissions.EXTERNAL,
        needs_draft=True,
        prompt=lambda c: f"Write one ad headline for {_name(c)}.",
        effect=lambda c, d: _ok(f"Bid variant written: {d[:90]}"),
    ),
    Tool(
        "reconcile_stripe",
        "Reconcile Stripe cashflow",
        risk=permissions.EXTERNAL,
        effect=lambda c, d: _ok(
            integrations.stripe_reconcile() or "Stripe reconciled: MRR 27 EUR, 3 active subs (mock)"
        ),
    ),
    Tool(
        "send_financial_transaction",
        "Pay an invoice / move money",
        risk=permissions.MONEY,
        hitl=True,
        effect=lambda c, d: _ok("Paid infrastructure invoice 12 EUR (mock)"),
    ),
    Tool(
        "review_commitments",
        "Check the last plan against what actually happened",
        effect=lambda c, d: _ok(_review_commitments(c)),
    ),
    Tool(
        "stop_useless_work",
        "Stand down any role producing into a void",
        effect=lambda c, d: _ok(_stop_useless_work(c)),
    ),
    Tool(
        "check_providers",
        "Notice a failing model tier and say what to do",
        effect=lambda c, d: _ok(_check_providers(c)),
    ),
    Tool(
        "set_roster",
        "Turn a role on or off",
        needs_draft=True,
        prompt=lambda c: (
            "Name only the roles that should change, prefixing with - the ones to "
            "stand down, e.g. `coder -social`. Answer with role names only, and "
            "answer with nothing at all if the roster is right as it is — naming "
            "every role every turn is how a decision becomes noise."
        ),
        effect=lambda c, d: _ok(_set_roster(c, d)),
    ),
    Tool(
        "weekly_review",
        "Seven days: spent against produced",
        effect=lambda c, d: _ok(_weekly_review(c)),
    ),
    Tool(
        "decide",
        "Record a decision that binds what comes next",
        needs_draft=True,
        prompt=lambda c: (
            "State one decision the company is taking now, in a sentence, and why. "
            "A decision binds the future; an observation does not. If nothing has "
            "been decided, answer exactly: nothing decided."
        ),
        effect=lambda c, d: _ok(_record_decision(c, d)),
    ),
    Tool(
        "write_site_content",
        "Draft the site sections and write them into company.yaml",
        needs_draft=True,
        risk=permissions.WRITE_LOCAL,
        schema={
            "steps": {"type": "list", "default": []},
            "privacy": {"type": "list", "default": []},
            "page_title": {"type": "str", "default": "", "max_len": 60},
            "page_body": {"type": "str", "default": "", "max_len": 1200},
        },
        prompt=lambda c: (
            f"Write the sales-site content for {_name(c)}, which sells: "
            f"{(c.company.get('offer') or {}).get('product', '')[:200]}. "
            "`steps`: three to five short steps describing how it actually works, in order. "
            "`privacy`: up to four sentences on what happens to the customer's data, only "
            "what is true of this product. "
            "`page_title` and `page_body`: one secondary page the buyer would want — the "
            "method, the architecture, who it is for — two or three paragraphs separated "
            "by a blank line. "
            "Never invent a customer quote, a statistic or a study; those are not yours to "
            "write. Leave a field empty rather than filling it with something you do not know."
        ),
        effect=lambda c, d: _ok(_write_site_content(c, d)),
    ),
    Tool(
        "review_kpis",
        "Review KPIs against targets",
        effect=lambda c, d: _ok(_review_kpis(c)),
    ),
    Tool(
        "update_pricing",
        "Draft a pricing adjustment",
        needs_draft=True,
        prompt=lambda c: f"Suggest one pricing tweak for {_name(c)} in a sentence.",
        effect=lambda c, d: _ok(_keep(c, "Pricing note", d, f"Pricing note: {d[:120]}")),
    ),
    Tool(
        "scan_competitors",
        "Scan and summarise competitors",
        risk=permissions.EXTERNAL,
        needs_draft=True,
        # The operator drops a capture of a rival's page precisely so this job can
        # read it.
        sees_images=True,
        prompt=lambda c: f"Name one competitor risk for {_name(c)} in a sentence.",
        effect=lambda c, d: _ok(_keep(c, "Competitor scan", d, f"Competitor scan: {d[:120]}")),
    ),
    Tool(
        "scan_signals",
        "Watch configured sources for buying signals",
        risk=permissions.EXTERNAL,
        effect=lambda c, d: _ok(_scan_signals(c)),
    ),
    Tool(
        "generate_code",
        "Draft a feature or fix",
        needs_draft=True,
        prompt=lambda c: f"Describe a small feature for {_name(c)} in one sentence.",
        effect=lambda c, d: _ok(f"Feature branch drafted: {d[:110]}"),
    ),
    Tool(
        "publish_production_code",
        "Merge a PR to production",
        risk=permissions.CODE,
        hitl=True,
        effect=lambda c, d: _ok("Merged PR #42 to production (mock)"),
    ),
    Tool(
        "draft_design_brief",
        "Draft a visual direction or brief",
        needs_draft=True,
        # A screenshot in the company's folder is the whole input to this job: a
        # visual direction argued from a description of a picture is worth less
        # than one argued from the picture.
        sees_images=True,
        prompt=lambda c: f"Describe a visual direction for {_name(c)} in one sentence.",
        effect=lambda c, d: _ok(_keep(c, "Design brief", d, f"Design brief drafted: {d[:120]}")),
    ),
    Tool(
        "produce_mockup",
        "Produce a landing or ad mockup",
        effect=lambda c, d: _ok("Mockup produced: landing hero and one ad variant (mock)"),
    ),
    Tool(
        "build_sales_site",
        "Generate the sales landing page",
        risk=permissions.WRITE_LOCAL,
        needs_draft=True,
        prompt=lambda c: f"Write one punchy sales headline, under 10 words, for {_name(c)}.",
        effect=lambda c, d: _ok(_build_site(c, d)),
    ),
    Tool(
        "deploy_site",
        "Publish the sales site to the configured hosts",
        risk=permissions.EXTERNAL,
        hitl=True,
        # Publishing is a decision, not a cadence. It waits for a task that says
        # to publish, so no daily design turn ever pushes a site on its own.
        by_task_only=True,
        effect=lambda c, d: _deploy_site(c),
    ),
]

TOOLS: dict[str, Tool] = {t.name: t for t in _ALL}
