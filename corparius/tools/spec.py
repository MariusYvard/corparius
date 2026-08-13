"""What every tool *is*, with no idea what any of them does. Rank 4, and free to import.

Forty tools, as data: the name, the sentence the console shows, the risk class permissions
weighs, whether a human gate is declared by name, whether the model has to draft first, the
structured-output schema, and two flags about how a tool is reached.

**No callable appears in this file**, and that is the whole point. The registry it was cut out
of imported `deploy`, `documents`, `enrich`, `integrations`, `leadsource`, `mailbox`, `signals`,
`sitecheck` and `sitegen` at module scope, because that is where the effects live. So did every
consumer that only ever wanted a *name*: `company` validating an operator's `hitl_tools`,
`doctor` checking a skill's `allowed-tools`, `skills` doing the same, the console rendering a
catalogue. Reading a list of forty names loaded an SMTP client and an IMAP client.

`permissions` reads a tool through `getattr` — `name`, `risk`, `hitl` — so a `ToolSpec` is
weighed exactly like a `Tool` and the console can answer "would this ask?" without the
adapters. `tools/registry.py` is the other half: it imports the effects and binds them by name.

The comments on individual fields moved with the fields they explain. Several of them carry
measurements taken on a real store, and they are the reason a flag is set the way it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import permissions


@dataclass(frozen=True)
class ToolSpec:
    """Frozen because this is a declaration, not state. A plugin adds a tool by registering a
    `Tool` in the registry; nothing mutates a spec in place."""

    name: str
    description: str
    # A gate declared by name. Separate from `risk` and stronger than it: no threshold and no
    # standing rule can lower this one.
    hitl: bool = False
    # What this tool does to the world outside the process, which is what
    # corparius/config/permissions.py weighs against the operator's threshold.
    risk: str = permissions.READ
    needs_draft: bool = False
    # Opt-in structured output: when a tool declares a schema, the executor drives the router
    # through corparius/structured so the effect receives a validated dict
    # (ctx.structured.data) that is the same shape whatever model, tier or provider answered.
    # Tools without a schema are unchanged.
    schema: dict | None = None
    # Whether the company's own pictures are worth sending to this tool. Opt in, per tool, for
    # the same reason `skip_when` exists: an image is the most expensive thing a turn can
    # carry, and a screenshot of a competitor's page helps a design brief and does nothing at
    # all for reconciling Stripe. Declared here so it is greppable, rather than inferred from
    # the role.
    sees_images: bool = False
    # This tool runs only when a task names it, never from a playbook. Its prompt is written
    # for a task ("what *this task* cannot proceed without"), so a playbook turn would ask it
    # with no task to be about.
    #
    # Declared rather than deduced, because "on no playbook" is exactly what a forgotten tool
    # looks like too: `ask_operator` and `set_roster` sat there for months, one by design and
    # one by omission, and nothing could tell them apart. `tests/test_tool_reach.py` now
    # demands that every tool have a path, and this flag is how a tool says its path is a task.
    by_task_only: bool = False


SPEC: dict[str, ToolSpec] = {
    "set_daily_plan": ToolSpec(
        "set_daily_plan",
        "Set the day's 1-3 priorities",
        needs_draft=True,
    ),
    "write_eod_summary": ToolSpec(
        "write_eod_summary",
        "Summarise the day",
        needs_draft=True,
    ),
    "remember": ToolSpec(
        "remember",
        "Write down one thing the company learned",
        needs_draft=True,
        schema={
            "fact": {"type": "str", "required": True, "max_len": 200},
            "why": {"type": "str", "default": "", "max_len": 200},
        },
    ),
    "write_skill": ToolSpec(
        "write_skill",
        "Write down the procedure that avoids a repeated failure",
        needs_draft=True,
        # WRITE_LOCAL, not READ: this puts a file in the company's folder, and that file goes
        # into a prompt on the next turn of the tool it names. `remember` writes a row in the
        # store and is weighed the same way.
        risk=permissions.WRITE_LOCAL,
        schema={
            # No `allowed_tools` field, on purpose. The scope is the tool that actually failed
            # and the effect sets it — a model choosing its own scope could choose "all", and
            # an unscoped skill rides on every prompt of every turn.
            "name": {"type": "str", "default": "", "max_len": 60},
            "description": {"type": "str", "default": "", "max_len": 120},
            "instructions": {"type": "str", "required": True, "max_len": 2000},
        },
    ),
    "write_note": ToolSpec(
        "write_note",
        "Write the internal document a task asks for",
        needs_draft=True,
        risk=permissions.WRITE_LOCAL,
        # A task, never a playbook: on a playbook this writes a note about nothing,
        # every turn. Five tools already write documents under fixed names; this is
        # the one that writes the document a *task* asked for, which is what
        # "rédiger une note de cadrage pour le contrat de licence" needed and had
        # nowhere to go.
        by_task_only=True,
        schema={
            "title": {"type": "str", "default": "", "max_len": 80},
            "body": {"type": "str", "default": "", "max_len": 4000},
        },
    ),
    "ask_operator": ToolSpec(
        "ask_operator",
        "Ask the operator for something only they can supply",
        needs_draft=True,
        by_task_only=True,
        schema={
            "question": {"type": "str", "required": True, "max_len": 160},
            "why": {"type": "str", "default": "", "max_len": 300},
        },
    ),
    "plan_from_documents": ToolSpec(
        "plan_from_documents",
        "Turn what the agents wrote into work",
        needs_draft=True,
        risk=permissions.WRITE_LOCAL,
        schema={
            "tasks": {"type": "list", "default": []},
            "note": {"type": "str", "default": "", "max_len": 200},
        },
    ),
    "create_tasks": ToolSpec(
        "create_tasks",
        "CEO adds tasks to the backlog",
    ),
    "assign_held_tasks": ToolSpec(
        "assign_held_tasks",
        "Give a held task the role and tool that can actually do it",
        needs_draft=True,
        risk=permissions.WRITE_LOCAL,
        schema={
            "assignments": {"type": "list", "default": []},
            "note": {"type": "str", "default": "", "max_len": 200},
        },
    ),
    "review_proposals": ToolSpec(
        "review_proposals",
        "CEO validates or refuses proposed tasks",
    ),
    "propose_task": ToolSpec(
        "propose_task",
        "Suggest a task to the CEO for review",
        needs_draft=True,
        schema={
            "idea": {"type": "str", "default": "", "max_len": 90},
            "why": {"type": "str", "default": "", "max_len": 200},
            # Which role does the work. Measured: support proposed "remove the
            # unverified badge from the landing page" six times over; every one was
            # targeted at support, because the target was the proposer, and support's
            # tool drafts a support reply. So the site kept the badge, a support
            # reply about something else was written instead, and the task was
            # marked done. An idea about the site belongs to design.
            "owner": {"type": "str", "default": "", "max_len": 20},
        },
    ),
    "kaizen": ToolSpec(
        "kaizen",
        "Continuous improvement: find the bottleneck, propose a fix",
    ),
    "draft_social_post": ToolSpec(
        "draft_social_post",
        "Draft a post for X or LinkedIn",
        needs_draft=True,
        schema={
            "headline": {"type": "str", "required": True, "max_len": 120},
            "body": {"type": "str", "required": True, "max_len": 500},
            "hashtags": {"type": "list", "default": []},
        },
    ),
    "schedule_post": ToolSpec(
        "schedule_post",
        "Queue the drafted post so it can be published",
        risk=permissions.EXTERNAL,
    ),
    "find_targets": ToolSpec(
        "find_targets",
        "Find ICP-matching prospects",
        risk=permissions.EXTERNAL,
    ),
    "send_outreach": ToolSpec(
        "send_outreach",
        "Send a cold email sequence",
        risk=permissions.EXTERNAL,
        needs_draft=True,
    ),
    "triage_inbox": ToolSpec(
        "triage_inbox",
        "Triage the support inbox",
        risk=permissions.EXTERNAL,
    ),
    "scan_replies": ToolSpec(
        "scan_replies",
        "Check the inbox for prospect replies",
        risk=permissions.EXTERNAL,
    ),
    "draft_support_reply": ToolSpec(
        "draft_support_reply",
        "Draft a reply to the top ticket",
        needs_draft=True,
    ),
    "review_ad_budget": ToolSpec(
        "review_ad_budget",
        "Review ad spend and pacing",
    ),
    "adjust_bids": ToolSpec(
        "adjust_bids",
        "Write ad variants and adjust bids",
        risk=permissions.EXTERNAL,
        needs_draft=True,
    ),
    "reconcile_stripe": ToolSpec(
        "reconcile_stripe",
        "Reconcile Stripe cashflow",
        risk=permissions.EXTERNAL,
    ),
    "send_financial_transaction": ToolSpec(
        "send_financial_transaction",
        "Pay an invoice / move money",
        risk=permissions.MONEY,
        hitl=True,
    ),
    "review_commitments": ToolSpec(
        "review_commitments",
        "Check the last plan against what actually happened",
    ),
    "stop_useless_work": ToolSpec(
        "stop_useless_work",
        "Stand down any role producing into a void",
    ),
    "check_providers": ToolSpec(
        "check_providers",
        "Notice a failing model tier and say what to do",
    ),
    "set_roster": ToolSpec(
        "set_roster",
        "Turn a role on or off",
        needs_draft=True,
    ),
    "weekly_review": ToolSpec(
        "weekly_review",
        "Seven days: spent against produced",
    ),
    "decide": ToolSpec(
        "decide",
        "Record a decision that binds what comes next",
        needs_draft=True,
    ),
    "review_site": ToolSpec(
        "review_site",
        "Read the company's own site and write down what to change",
        needs_draft=True,
        risk=permissions.WRITE_LOCAL,
        schema={
            "findings": {"type": "list", "default": []},
            "worst": {"type": "str", "default": "", "max_len": 200},
        },
    ),
    "write_site_content": ToolSpec(
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
    ),
    "review_kpis": ToolSpec(
        "review_kpis",
        "Review KPIs against targets",
    ),
    "update_pricing": ToolSpec(
        "update_pricing",
        "Draft a pricing adjustment",
        needs_draft=True,
    ),
    "scan_competitors": ToolSpec(
        "scan_competitors",
        "Scan and summarise competitors",
        risk=permissions.EXTERNAL,
        needs_draft=True,
        # The operator drops a capture of a rival's page precisely so this job can
        # read it.
        sees_images=True,
    ),
    "scan_signals": ToolSpec(
        "scan_signals",
        "Watch configured sources for buying signals",
        risk=permissions.EXTERNAL,
    ),
    "generate_code": ToolSpec(
        "generate_code",
        "Draft a feature or fix",
        needs_draft=True,
    ),
    "publish_production_code": ToolSpec(
        "publish_production_code",
        "Merge a PR to production",
        risk=permissions.CODE,
        hitl=True,
    ),
    "draft_design_brief": ToolSpec(
        "draft_design_brief",
        "Draft a visual direction or brief",
        needs_draft=True,
        # A screenshot in the company's folder is the whole input to this job: a
        # visual direction argued from a description of a picture is worth less
        # than one argued from the picture.
        sees_images=True,
    ),
    "produce_mockup": ToolSpec(
        "produce_mockup",
        "Produce a landing or ad mockup",
    ),
    # The other half of the site loop, and a **separate tool on a different role** rather than a second
    # model call inside the build. Two reasons, and neither is style. A tool effect reaches `company`,
    # `data_path`, `leads`, `store` and `structured` — deliberately not a model handle, because the
    # executor owns routing, the token budget and the accounting; so a critique round inside the build
    # would have to be a new executor capability. And the judge should not be the writer: roles carry
    # their own model pin, so design writing and strategy reviewing is how a different model gets to
    # judge, using machinery the product already has. `_review_generated_site` reads `source` off both
    # actions and says when they were the same, because a second opinion from the same model is one
    # opinion twice.
    "review_generated_site": ToolSpec(
        "review_generated_site",
        "Review the generated sales page and say what to change",
        needs_draft=True,
        risk=permissions.READ,
        schema={
            "findings": {"type": "list", "default": []},
            "worst": {"type": "str", "default": "", "max_len": 200},
        },
    ),
    "build_sales_site": ToolSpec(
        "build_sales_site",
        "Generate the sales landing page",
        risk=permissions.WRITE_LOCAL,
        needs_draft=True,
    ),
    "deploy_site": ToolSpec(
        "deploy_site",
        "Publish the sales site to the configured hosts",
        risk=permissions.EXTERNAL,
        hitl=True,
        # Publishing is a decision, not a cadence. It waits for a task that says
        # to publish, so no daily design turn ever pushes a site on its own.
        by_task_only=True,
    ),
}


ROLE_TOOL = {
    "outreach": "send_outreach",
    "social": "draft_social_post",
    "support": "draft_support_reply",
    # Strategy's work product is a written document. Without this, a strategy task
    # reached an agent with no tool that could carry it and was held for the
    # operator — measured, twice, on one real company.
    "strategy": "write_note",
    # The tool that can change what the site says, not the one that renders it.
    # `build_sales_site` reads the copy out of company.yaml and writes HTML, so a
    # task like "remove the unverified badge from the landing page" completed
    # through it rebuilds the same page, byte for byte, and reports success.
    # Rendering happens anyway: it is the last step of the design playbook every
    # turn. What a backlog task needs is the step that changes something.
    "design": "write_site_content",
    # The five that had no entry, which meant an approved task for any of them
    # completed "done (no tool mapped)" — the 22-of-24 defect above, still live for
    # half the roster. Not derived from the playbook: three of the five existing
    # entries **disagree** with their role's first playbook step, and the reason is
    # the rule this table is really written to. `find_targets`, `review_kpis` and
    # `triage_inbox` come first in their playbooks and all three only *look*; a task
    # approved onto one of them finishes having produced nothing, which is the same
    # nothing as no tool at all. **The default is a tool that produces.**
    #
    # And each is the producing tool its role can run *without* a gate: `adjust_bids`
    # is external, `send_financial_transaction` is money and `publish_production_code`
    # is code — all three would park an approved task on the human gate the moment the
    # CEO approved it, which is not approval, it is a queue.
    "ads": "review_ad_budget",
    "coder": "generate_code",
    "competitor": "scan_competitors",
    "finance": "reconcile_stripe",
    # No entry for `ceo`, on purpose, and the guard below is what makes that
    # honest rather than an omission: the CEO arbitrates the backlog, it does not
    # work it. A task owned by the CEO is a proposal nobody will execute, so
    # `unrunnable_reason` refuses it out loud instead of approving it to die quietly.
}


def unrunnable_reason(task: dict) -> str:
    """Why this task would finish having done nothing, or "" when it will run.

    The measured defect: **24 tasks for one role with no tool, 22 closed "done (no
    tool mapped)"**. `executable_fields` fixes the case where a default exists; this
    is the other half — the case where none does, which was silently approved and
    silently completed. Half the roster had no default until the entries above.

    A sentence rather than a boolean, because both callers put it in front of a
    person: the CEO's review writes it into the rejection, and the console's approve
    button shows it. "Rejected" with no cause is how the condition that produced the
    proposal survives to produce it again.
    """
    if task.get("tool"):
        return ""
    target = (task.get("target") or "").strip()
    if not target:
        return "no role owns it, so nothing would pick it up"
    if target in ROLE_TOOL:
        return ""
    if target == "ceo":
        return "the CEO arbitrates the backlog rather than working it, so no tool would run this"
    return f"no tool is mapped to '{target[:24]}', so it would complete having done nothing"


def executable_fields(task: dict) -> dict:
    """What has to be set on an approved task for it to actually run.

    Two paths approve a proposal — the CEO's `review_proposals` and the operator's
    own button in the console — and only the CEO's reached this registry. Measured
    in a real store: **24 tasks for one role with no tool, 22 of them closed
    "done (no tool mapped)"** having done nothing at all. The condition that
    produced them therefore survived, so the agent proposed it again, and again;
    six near-identical proposals about one badge on one landing page.

    So it lives in one function that both ends call. `test_registries` asserts the
    keys and values are real; this is the other half of the same rule.
    """
    if task.get("tool"):
        return {}
    target = (task.get("target") or "").strip()
    return {"tool": ROLE_TOOL[target]} if target in ROLE_TOOL else {}
