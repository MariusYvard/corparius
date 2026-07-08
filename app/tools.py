"""The business toolbox. Each tool carries a mock `effect` for the MVP; swap the
effect for a real integration (Stripe, Lemlist, GitHub, Meta Ads, ...) to go
live. Tools flagged `hitl` never execute until a human approves them.
"""
from __future__ import annotations
from typing import Callable
import os

from .models import ToolResult
from . import integrations, sitegen, deploy, leadsource, enrich, signals


class Tool:
    def __init__(self, name: str, description: str, effect: Callable,
                 *, hitl: bool = False, needs_draft: bool = False,
                 prompt: Callable | None = None):
        self.name = name
        self.description = description
        self.hitl = hitl
        self.needs_draft = needs_draft
        self._prompt = prompt
        self._effect = effect

    def draft_prompt(self, ctx) -> str:
        return self._prompt(ctx) if self._prompt else ""

    def run(self, ctx, draft: str = "") -> ToolResult:
        return self._effect(ctx, draft)


def _name(ctx) -> str:
    return ctx.company.get("name", "the company")


def _ok(text: str) -> ToolResult:
    return ToolResult(ok=True, output=text)


def _build_site(ctx, draft: str) -> str:
    company = ctx.company
    out_dir = os.path.join(ctx.data_path, "sites", company.get("slug", "company"))
    path = sitegen.build_site(company, out_dir, headline=(draft.strip() or None))
    return f"Sales site built at {path}"


def _deploy_site(ctx) -> str:
    company = ctx.company
    out_dir = os.path.join(ctx.data_path, "sites", company.get("slug", "company"))
    if not os.path.exists(os.path.join(out_dir, "index.html")):
        sitegen.build_site(company, out_dir)
    return "Site published: " + deploy.deploy_site(out_dir)


def _find_targets(ctx) -> str:
    company = ctx.company
    icp = company.get("icp", {}) or {}
    query = icp.get("segment", "") or company.get("name", "")
    leads = enrich.enrich_all(leadsource.find_leads(query, 5))
    ctx.leads = leads
    if leads:
        return f"Found {len(leads)} leads via {leads[0].source}: " + ", ".join(
            lead.label() for lead in leads[:5])
    return "Found 5 ICP-matching targets from enriched data (mock)"


def _scan_signals(ctx) -> str:
    company = ctx.company
    icp = company.get("icp", {}) or {}
    keywords = [k for k in (icp.get("pains", []) + [icp.get("segment", "")]) if k]
    hits = signals.find_signals(keywords or [company.get("name", "")], 5)
    if hits:
        return f"Signals detected ({len(hits)}): " + " | ".join(hits[:3])
    return "No buying signals in configured sources (mock)"


def _send_outreach(ctx, draft: str) -> str:
    company = ctx.company
    leads = [lead for lead in getattr(ctx, "leads", []) if lead.email]
    if leads:
        cap = int(os.environ.get("CORP_OUTREACH_MAX_PER_RUN", "20") or 20)
        sent, skipped = [], []
        for lead in leads[:cap]:
            res = integrations.send_email(
                lead.email, f"{company.get('name', 'corparius')} outreach", draft)
            if res is None:
                break   # SMTP not configured, fall back below
            (sent if res == "sent" else skipped).append(lead.email)
        if sent or skipped:
            return f"Outreach: {len(sent)} sent, {len(skipped)} skipped. {', '.join(sent[:3])}"
    return integrations.send_outreach_email(company, draft) or \
        f"Cold email sent to 5 targets. Opener: {draft[:90]}"


ROLE_TOOL = {"outreach": "send_outreach", "social": "draft_social_post",
             "support": "draft_support_reply", "design": "build_sales_site"}


def _create_tasks(ctx) -> str:
    """Data-driven: the CEO reads what the company observed (buying signals,
    leads, KPIs) from the action log and queues targeted tasks, deduped against
    what is already open, plus a light baseline."""
    store = getattr(ctx, "store", None)
    if store is None:
        return "Backlog unavailable"
    slug = ctx.company.get("slug", "company")
    enabled = ctx.company.get("agents", {}) or {}
    open_pairs = {(t["target"], t.get("tool") or "") for t in store.list_tasks(slug)
                  if t["status"] in ("approved", "in_progress")}
    created: list[str] = []

    def queue(title, target, tool, priority):
        if not enabled.get(target) or (target, tool) in open_pairs:
            return
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
    cap = int(os.environ.get("CORP_CEO_APPROVE_CAP", "3") or 3)
    approved = rejected = modified = 0
    for i, task in enumerate(proposals):
        if i < cap:
            fields = {}
            if task["priority"] < 2:
                fields["priority"] = 2   # CEO re-prioritises the suggestion
            if not task.get("tool") and task["target"] in ROLE_TOOL:
                fields["tool"] = ROLE_TOOL[task["target"]]   # make it executable
            if fields:
                store.update_task(task["id"], **fields)
                modified += 1
            store.set_task_status(task["id"], "approved", "validated by CEO")
            approved += 1
        else:
            store.set_task_status(task["id"], "rejected", "declined by CEO")
            rejected += 1
    return f"CEO reviewed {len(proposals)}: {approved} approved ({modified} modified), {rejected} rejected"


def _propose_task(ctx) -> str:
    store = getattr(ctx, "store", None)
    if store is None:
        return "Backlog unavailable"
    slug = ctx.company.get("slug", "company")
    role = getattr(ctx, "role", "agent")
    store.add_task(slug, f"Idea from {role}", role, priority=1,
                   status="proposed", created_by=role)
    return f"{role} proposed a task to the CEO"


_ALL = [
    Tool("set_daily_plan", "Set the day's 1-3 priorities", needs_draft=True,
         prompt=lambda c: (f"Yesterday: {c.memory[0] if getattr(c, 'memory', None) else 'no prior summary'}. "
                           f"In one sentence, set today's top priority for {_name(c)}."),
         effect=lambda c, d: _ok(f"Daily plan set: {d[:140]}")),
    Tool("write_eod_summary", "Summarise the day", needs_draft=True,
         prompt=lambda c: f"In one sentence, summarise the day for {_name(c)}.",
         effect=lambda c, d: _ok(f"EOD summary: {d[:140]}")),
    Tool("create_tasks", "CEO adds tasks to the backlog",
         effect=lambda c, d: _ok(_create_tasks(c))),
    Tool("review_proposals", "CEO validates or refuses proposed tasks",
         effect=lambda c, d: _ok(_review_proposals(c))),
    Tool("propose_task", "Suggest a task to the CEO for review",
         effect=lambda c, d: _ok(_propose_task(c))),
    Tool("draft_social_post", "Draft a post for X or LinkedIn", needs_draft=True,
         prompt=lambda c: f"Draft one short LinkedIn post for {_name(c)}.",
         effect=lambda c, d: _ok(f"Post drafted: {d[:120]}")),
    Tool("schedule_post", "Schedule the drafted post",
         effect=lambda c, d: _ok("Post scheduled for +2h on linkedin")),
    Tool("find_targets", "Find ICP-matching prospects",
         effect=lambda c, d: _ok(_find_targets(c))),
    Tool("send_outreach", "Send a cold email sequence", needs_draft=True,
         prompt=lambda c: f"Draft a 2-line cold email opener for {_name(c)}.",
         effect=lambda c, d: _ok(_send_outreach(c, d))),
    Tool("triage_inbox", "Triage the support inbox",
         effect=lambda c, d: _ok("Inbox triaged: 3 support, 1 sales, 0 urgent")),
    Tool("draft_support_reply", "Draft a reply to the top ticket", needs_draft=True,
         prompt=lambda c: f"Draft a one-line support reply for a {_name(c)} user.",
         effect=lambda c, d: _ok(f"Reply drafted: {d[:110]}")),
    Tool("review_ad_budget", "Review ad spend and pacing",
         effect=lambda c, d: _ok("Ad budget reviewed: 0 EUR/day, within cap")),
    Tool("adjust_bids", "Write ad variants and adjust bids", needs_draft=True,
         prompt=lambda c: f"Write one ad headline for {_name(c)}.",
         effect=lambda c, d: _ok(f"Bid variant written: {d[:90]}")),
    Tool("reconcile_stripe", "Reconcile Stripe cashflow",
         effect=lambda c, d: _ok(integrations.stripe_reconcile()
                                 or "Stripe reconciled: MRR 27 EUR, 3 active subs (mock)")),
    Tool("send_financial_transaction", "Pay an invoice / move money", hitl=True,
         effect=lambda c, d: _ok("Paid infrastructure invoice 12 EUR (mock)")),
    Tool("review_kpis", "Review KPIs against targets",
         effect=lambda c, d: _ok("KPIs reviewed: signups flat, conversion 2.1%")),
    Tool("update_pricing", "Draft a pricing adjustment", needs_draft=True,
         prompt=lambda c: f"Suggest one pricing tweak for {_name(c)} in a sentence.",
         effect=lambda c, d: _ok(f"Pricing note: {d[:120]}")),
    Tool("scan_competitors", "Scan and summarise competitors", needs_draft=True,
         prompt=lambda c: f"Name one competitor risk for {_name(c)} in a sentence.",
         effect=lambda c, d: _ok(f"Competitor scan: {d[:120]}")),
    Tool("scan_signals", "Watch configured sources for buying signals",
         effect=lambda c, d: _ok(_scan_signals(c))),
    Tool("generate_code", "Draft a feature or fix", needs_draft=True,
         prompt=lambda c: f"Describe a small feature for {_name(c)} in one sentence.",
         effect=lambda c, d: _ok(f"Feature branch drafted: {d[:110]}")),
    Tool("publish_production_code", "Merge a PR to production", hitl=True,
         effect=lambda c, d: _ok("Merged PR #42 to production (mock)")),
    Tool("draft_design_brief", "Draft a visual direction or brief", needs_draft=True,
         prompt=lambda c: f"Describe a visual direction for {_name(c)} in one sentence.",
         effect=lambda c, d: _ok(f"Design brief drafted: {d[:120]}")),
    Tool("produce_mockup", "Produce a landing or ad mockup",
         effect=lambda c, d: _ok("Mockup produced: landing hero and one ad variant (mock)")),
    Tool("build_sales_site", "Generate the sales landing page", needs_draft=True,
         prompt=lambda c: f"Write one punchy sales headline, under 10 words, for {_name(c)}.",
         effect=lambda c, d: _ok(_build_site(c, d))),
    Tool("deploy_site", "Publish the sales site to the configured hosts", hitl=True,
         effect=lambda c, d: _ok(_deploy_site(c))),
]

TOOLS: dict[str, Tool] = {t.name: t for t in _ALL}
