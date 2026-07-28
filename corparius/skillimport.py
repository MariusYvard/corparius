"""Importing a skill written for another host.

There is a lot of good prose about knowledge work in the open — Anthropic's
`knowledge-work-plugins` alone publishes 141 SKILL.md files under Apache-2.0 —
and none of it drops into corparius. Three reasons, each measurable on the real
files rather than on a blog post about them:

  * No `allowed-tools`. Their frontmatter is `name`, `description` and
    `argument-hint`, because their host lets the model ask for a skill by
    description. Corparius decides by code (skills.py), so a file with no tool
    list is `unscoped`: injected into every prompt of every agent, forever.
  * Size. Their median SKILL.md is around 12 KB and the largest is 26 KB, against
    a 4000-character cap for corparius' whole injected block. The three skills
    this repo ships are about 1.1 KB each.
  * They are slash commands for a human who is present. "Gather the following
    from the user. If not provided, ask before proceeding" is a reasonable
    instruction there and impossible here, where agents run unattended on a
    cadence.

So this module does not convert. It copies the body verbatim, fills in the
frontmatter corparius needs, and says — in numbers — how much of it the loader
will actually cut. Importing is not fitting, and a command that swallows 14 KB
without saying so would recreate the silent failure the loader was hardened
against in the first place.
"""

from __future__ import annotations

from pathlib import Path

from . import skills

# What a foreign skill's name means in corparius' vocabulary.
#
# Only names whose job an existing tool already does. Half of the 141 are for
# work this roster has never done — bio-research pipelines, Zoom SDKs, contract
# redlines, PDF signing — and inventing a mapping for those would be inventing
# a job. Unknown names get no tools at all, which the caller must then report.
TOOL_HINTS: dict[str, list[str]] = {
    # customer support
    "draft-response": ["draft_support_reply"],
    "ticket-triage": ["triage_inbox", "propose_task"],
    "customer-escalation": ["triage_inbox", "draft_support_reply"],
    "kb-article": ["draft_support_reply"],
    "customer-research": ["find_targets", "scan_signals"],
    # sales and outreach
    "draft-outreach": ["send_outreach"],
    "account-research": ["find_targets", "scan_signals"],
    "call-prep": ["send_outreach"],
    "call-summary": ["scan_replies"],
    "pipeline-review": ["scan_replies", "review_kpis"],
    "daily-briefing": ["set_daily_plan"],
    "forecast": ["review_kpis"],
    # marketing, social and ads
    "content-creation": ["draft_social_post", "schedule_post"],
    "draft-content": ["draft_social_post"],
    "campaign-plan": ["draft_social_post", "schedule_post", "review_ad_budget"],
    "email-sequence": ["send_outreach"],
    "performance-report": ["review_ad_budget", "adjust_bids", "review_kpis"],
    "brand-review": ["draft_social_post", "draft_design_brief"],
    "seo-audit": ["build_sales_site"],
    # competition
    "competitive-brief": ["scan_competitors"],
    "competitive-intelligence": ["scan_competitors"],
    # money
    "reconciliation": ["reconcile_stripe"],
    "close-management": ["reconcile_stripe"],
    "journal-entry": ["reconcile_stripe"],
    "journal-entry-prep": ["reconcile_stripe"],
    "financial-statements": ["review_kpis"],
    "variance-analysis": ["review_kpis", "update_pricing"],
    # design
    "design-critique": ["produce_mockup"],
    "design-handoff": ["draft_design_brief", "produce_mockup"],
    "design-system": ["draft_design_brief"],
    "ux-copy": ["produce_mockup", "build_sales_site"],
    "accessibility-review": ["produce_mockup", "build_sales_site"],
    # engineering
    "code-review": ["generate_code"],
    "deploy-checklist": ["publish_production_code", "deploy_site"],
    "testing-strategy": ["generate_code"],
    "tech-debt": ["propose_task", "kaizen"],
    "documentation": ["generate_code"],
    # planning
    "write-spec": ["create_tasks"],
    "roadmap-update": ["create_tasks", "set_daily_plan"],
    "metrics-review": ["review_kpis"],
    "stakeholder-update": ["write_eod_summary"],
    "sprint-planning": ["create_tasks", "set_daily_plan"],
}

# Attribution goes in the frontmatter, not in the body.
#
# `skills.parse` ignores keys it does not know, so these cost nothing at run
# time — and a comment in the body would be paid for on every prompt the skill
# applies to, and would make the announced cut wrong by its own length. A human
# opening the file still sees where it came from, which is the point.
EXTRA_KEYS = ("source", "licence")


def suggest_tools(name: str) -> list[str]:
    """The tools a foreign skill's name maps to, or [] when nothing here does
    that job. Never a guess: an invented scope is worse than none, because it
    silently points prose at the wrong agent."""
    return list(TOOL_HINTS.get(name.strip().lower(), []))


def inspect(path: Path | str, max_chars: int = skills.DEFAULT_MAX_CHARS) -> dict:
    """Read a foreign SKILL.md and report what importing it would cost.

    Reads only. `ok` qualifies the read, as everywhere else in this codebase —
    a skill that will be truncated to a fifth is still a successful read, and
    conflating the two would hide the number that matters.
    """
    p = Path(path)
    if p.is_dir():
        p = p / "SKILL.md"
    skill = skills.parse(p)
    if skill is None:
        return {"ok": False, "detail": f"{p} is not a readable SKILL.md", "path": str(p)}
    chars = len(skill.instructions)
    over = max(0, chars - max_chars)
    return {
        "ok": True,
        "path": str(p),
        "name": skill.name,
        "description": skill.description,
        "chars": chars,
        "cap": max_chars,
        "over_cap": chars > max_chars,
        # What the loader will actually drop. The whole point of this module is
        # that this number is shown before the import, not discovered later in
        # a warning nobody was looking at.
        "cut_pct": round(100.0 * over / chars, 1) if chars else 0.0,
        # Their own tools, if the file happens to carry them; otherwise ours,
        # guessed from the name; otherwise nothing.
        "declared_tools": list(skill.allowed_tools),
        "suggested_tools": list(skill.allowed_tools) or suggest_tools(skill.name),
        "unscoped": not skill.allowed_tools and not suggest_tools(skill.name),
        "body": skill.instructions,
    }


def render(result: dict, tools: list[str], source: str, licence: str = "Apache-2.0") -> str:
    """The corparius-shaped file, as text. Separate from writing it so
    `--dry-run` shows exactly what would land."""
    described = result["description"] or "Imported. Write one line saying when it applies."
    front = [
        "---",
        f"name: {result['name']}",
        f"description: {described}",
        f"allowed-tools: {', '.join(tools)}" if tools else "allowed-tools:",
        f"source: {source}",
        f"licence: {licence}",
        "---",
        "",
    ]
    return "\n".join(front) + result["body"].strip() + "\n"


def write(
    result: dict,
    dest: Path | str,
    tools: list[str],
    source: str = "",
    licence: str = "Apache-2.0",
) -> Path:
    """Write `<dest>/<name>/SKILL.md`. Refuses to overwrite.

    A skill is something its author edited; replacing one with an import would
    throw away the trimming that makes an import usable at all.
    """
    folder = Path(dest) / result["name"]
    target = folder / "SKILL.md"
    if target.exists():
        raise FileExistsError(target)
    folder.mkdir(parents=True, exist_ok=True)
    target.write_text(render(result, tools, source or result["path"], licence), encoding="utf-8")
    return target
