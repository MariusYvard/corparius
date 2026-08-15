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
    # **What must be true of the company before this role is worth a turn.** Names from
    # `readiness.FACTS`, and empty for every role that *creates* those facts rather than consuming
    # them — a design agent held until there is a site would be held forever.
    #
    # Cadence answers "has enough time passed" and `paused` answers "the operator said stop". Neither
    # could answer "is there anything here to do yet", and the gap was visible in the shipped example
    # config: `ads: false  # off until there is budget to spend`, written by hand, because the
    # runtime had no way to know. This is that comment, as data.
    needs: tuple[str, ...] = ()
    # **Which hour of the day this role starts from.** `tick % cadence == 0` put every role on hour
    # 0: a daily role and a six-hourly one both fired at midnight, together, every day. The roster's
    # own docstring promised staggering and the arithmetic could not deliver it — the README's
    # cadence figure shows the stampede as a column of dots down the 00h line.
    #
    # With an offset the day has a shape: the CEO opens it alone, design and social land between its
    # reviews, and the two daily readers sit in the afternoon where nothing else is.
    offset_hours: int = 0


ROSTER: dict[AgentRole, AgentSpec] = {
    AgentRole.CEO: AgentSpec(
        AgentRole.CEO,
        # 12h was two turns a day, and the operator could not get a decision out of the company
        # when a decision was what they wanted. Six is four: it opens the day, checks in around
        # midday and again mid-afternoon, and closes it. This is the most expensive turn in the
        # roster (fifteen tools), which is the argument for six rather than four.
        6,
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
            # After `remember`, and for the same reason it is here: this is the day boundary,
            # the one moment the company looks back. `remember` writes a fact; this writes a
            # procedure, when something has failed twice and a procedure would have helped.
            # It skips itself otherwise — see `_nothing_to_learn`.
            "write_skill",
            "write_eod_summary",
        ],
        # Hour 0, alone: the day opens with the one role that decides what the others are for.
        offset_hours=0,
    ),
    AgentRole.SOCIAL: AgentSpec(
        AgentRole.SOCIAL,
        # 2h was **twelve drafts a day**, into a queue nothing publishes and somebody reads. No
        # company posts twelve times a day, and the pile was the operator's problem rather than
        # the agent's. Three is already generous.
        8,
        Difficulty.TRIVIAL,
        "You run social media for the company.",
        ["draft_social_post", "schedule_post"],
        # 3, 11, 19: after the CEO has set the plan, not before it.
        offset_hours=3,
    ),
    AgentRole.OUTREACH: AgentSpec(
        AgentRole.OUTREACH,
        # Cold email with no public page is a link to nothing, so this is held until there is a
        # site. Once there is one, four sends a day is the cadence a warmup schedule wants.
        6,
        Difficulty.EASY,
        "You run cold outbound to the ICP, and you follow up on who answered.",
        ["find_targets", "send_outreach", "scan_replies"],
        needs=("site",),
        offset_hours=4,
    ),
    AgentRole.SUPPORT: AgentSpec(
        AgentRole.SUPPORT,
        # Unchanged, and gated instead: support has to be *responsive*, so three hours is right
        # the day a mailbox exists. What was wrong was running it every three hours on a company
        # with no mailbox at all, which drafted a reply to nobody.
        3,
        Difficulty.EASY,
        "You handle customer support.",
        ["triage_inbox", "draft_support_reply", "propose_task"],
        needs=("mail",),
        offset_hours=2,
    ),
    AgentRole.ADS: AgentSpec(
        AgentRole.ADS,
        # Four turns a day adjusting bids on a campaign that does not exist. Daily, and only once
        # there is a page to send traffic to *and* a way to be paid for it: buying visits to a
        # page that cannot sell is the purest waste in the roster.
        24,
        Difficulty.TRIVIAL,
        "You manage paid acquisition.",
        ["review_ad_budget", "adjust_bids"],
        needs=("site", "payment"),
        offset_hours=9,
    ),
    AgentRole.FINANCE: AgentSpec(
        AgentRole.FINANCE,
        # Twice a day, and only once the company can be paid. Reconciling Stripe four times a day
        # against a week with one charge is noise that costs a turn each time.
        12,
        Difficulty.TRIVIAL,
        "You keep the books and the cashflow.",
        ["reconcile_stripe", "send_financial_transaction"],
        needs=("payment",),
        offset_hours=5,
    ),
    AgentRole.STRATEGY: AgentSpec(
        AgentRole.STRATEGY,
        24,
        Difficulty.HARD,
        "You own strategy, pricing, the roadmap and continuous improvement (kaizen).",
        # `review_generated_site` is on strategy and not on design **on purpose**: design writes the
        # sales page, and a writer reviewing their own work is one opinion twice. Roles carry their own
        # model pin, so this is also how a different model gets to judge — pin strategy to something
        # other than design's tier and the separation is real rather than hoped for. The tool itself
        # reads `source` off both actions and says when they were the same.
        ["review_kpis", "update_pricing", "kaizen", "review_generated_site", "remember"],
        # Hour 7, on its own: the most expensive tier in the roster should not share a tick.
        offset_hours=7,
    ),
    AgentRole.COMPETITOR: AgentSpec(
        AgentRole.COMPETITOR,
        24,
        Difficulty.TRIVIAL,
        "You track the competitive landscape and buying signals.",
        ["scan_competitors", "scan_signals"],
        offset_hours=13,
    ),
    AgentRole.DESIGN: AgentSpec(
        AgentRole.DESIGN,
        # The role that builds the thing everything else points at, and it ran **once a day**. Early
        # in a company's life the sales site is the whole product surface; this is the one cadence
        # that goes up rather than down.
        8,
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
        # 1, 9, 17: right after each CEO turn, so a decision reaches the page the same day.
        offset_hours=1,
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
