"""The business toolbox. Each tool carries a mock `effect` for the MVP; swap the
effect for a real integration (Stripe, Lemlist, GitHub, Meta Ads, ...) to go
live. Tools flagged `hitl` never execute until a human approves them.
"""
from __future__ import annotations
from typing import Callable

from .models import ToolResult


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


_ALL = [
    Tool("set_daily_plan", "Set the day's 1-3 priorities", needs_draft=True,
         prompt=lambda c: f"In one sentence, set today's top priority for {_name(c)}.",
         effect=lambda c, d: _ok(f"Daily plan set: {d[:140]}")),
    Tool("write_eod_summary", "Summarise the day", needs_draft=True,
         prompt=lambda c: f"In one sentence, summarise the day for {_name(c)}.",
         effect=lambda c, d: _ok(f"EOD summary: {d[:140]}")),
    Tool("draft_social_post", "Draft a post for X or LinkedIn", needs_draft=True,
         prompt=lambda c: f"Draft one short LinkedIn post for {_name(c)}.",
         effect=lambda c, d: _ok(f"Post drafted: {d[:120]}")),
    Tool("schedule_post", "Schedule the drafted post",
         effect=lambda c, d: _ok("Post scheduled for +2h on linkedin")),
    Tool("find_targets", "Find ICP-matching prospects",
         effect=lambda c, d: _ok("Found 5 ICP-matching targets from enriched data")),
    Tool("send_outreach", "Send a cold email sequence", needs_draft=True,
         prompt=lambda c: f"Draft a 2-line cold email opener for {_name(c)}.",
         effect=lambda c, d: _ok(f"Cold email sent to 5 targets. Opener: {d[:90]}")),
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
         effect=lambda c, d: _ok("Stripe reconciled: MRR 27 EUR, 3 active subs (mock)")),
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
    Tool("generate_code", "Draft a feature or fix", needs_draft=True,
         prompt=lambda c: f"Describe a small feature for {_name(c)} in one sentence.",
         effect=lambda c, d: _ok(f"Feature branch drafted: {d[:110]}")),
    Tool("publish_production_code", "Merge a PR to production", hitl=True,
         effect=lambda c, d: _ok("Merged PR #42 to production (mock)")),
]

TOOLS: dict[str, Tool] = {t.name: t for t in _ALL}
