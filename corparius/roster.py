"""Who the ten agents are, what they run and how often. Rank 4, and free to import.

Data, entirely: a role, a cadence, a difficulty tier, a system prompt, and a playbook that
names tools as **strings**. Nothing here imports a tool, calls a model or touches the host.

It was the first 150 lines of `agents.py`, above the executor, and that adjacency cost more
than it looked. `tools/effects.py` reads the roster twice — `_assign_held` and `_set_roster`
both need to know which role can honour what — so `effects` imported `agents`, `agents`
imported the tool registry, and the registry imported `effects`. A three-module cycle held
together by the fact that a data table and the machine that consumes it lived in one file.

Splitting them makes the direction obvious: **the executor reads the roster, and so do the
effects; the roster reads nothing.** Which is also why every playbook entry is a string. A
playbook holding tool *objects* would put this file back above the registry, and the cycle
with it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .kernel.records import AgentRole, Difficulty


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
            # The deliberate counterpart to stop_useless_work, which is the
            # automatic one. It was built, described as the most CEO decision
            # there is, and left on no playbook — so no CEO could ever take it.
            "set_roster",
            "set_daily_plan",
            # Before reviewing new proposals: a task already approved and then held
            # is work the CEO has already said yes to, and leaving it for the
            # operator while arbitrating fresh ideas is the wrong order.
            "assign_held_tasks",
            "review_proposals",
            "create_tasks",
            # After the baseline, because this reads what the agents actually found
            # and the baseline is what fills a quiet day. A design review naming
            # sixteen changes is worth more than "Publish a post today", and it
            # should not be competing with it for the work-in-progress limit.
            "plan_from_documents",
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
            # For a company that ships its own site, the one above skips itself and
            # this one has the say. Both are on the playbook because which applies
            # is a fact about the company, not a setting: exactly one of them ever
            # runs, and each says why when it is the other's turn.
            "review_site",
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
