---
name: skill-template
description: One line. What this skill knows, and when it is worth reading.
allowed-tools: send_outreach, draft_support_reply
---

# What this file is

A skill is what your company knows about a job, written for the agent that does
that job. It is prose, not code: no Python, no dependency, nothing executed.

Copy this folder into one of:

- `companies/<slug>/skills/<your-skill>/SKILL.md` — applies to that company only
- `skills/<your-skill>/SKILL.md` — applies to every company on this machine

A company skill with the same `name` replaces the shared one rather than
stacking with it. Two sets of instructions for the same job, both in context, is
how a model gets told to do opposite things.

## The frontmatter

`name` identifies the skill; it defaults to the folder name. `description` is
what the console shows. `allowed-tools` is the part that matters: this file is
read into the prompt only when the tool about to run is named there. Omit it and
the skill applies to every tool, which is right for background knowledge about
the company and wrong for instructions about one job.

The tool names are the ones in the action log — `send_outreach`,
`draft_social_post`, `draft_support_reply`, `update_pricing`, and so on. A name
that matches no tool is reported by `corparius doctor`; it does not fail the run,
it just never applies.

## Writing the body

Everything after the frontmatter goes into the agent's system prompt, so write
what you would tell a new hire on their first day, not what you would put in a
brochure.

Be specific and be short. `CORP_SKILL_MAX_CHARS` caps what one prompt carries
(4000 characters by default); past it a skill is truncated and marked as
truncated, so the opening paragraphs are the ones that survive. Put the rule
that matters first.

Prefer things that are true about *your* market:

- the objection you actually get, and the answer that actually works
- the price you never discount below, and why
- the two words your founder refuses to see in a post
- the customer segment to leave alone

Avoid restating what the agent already knows from `company.yaml` — its name, its
offer, its price and its channels are already in every prompt.

## Label every number

The one rule worth writing into every skill that touches figures: **say where a
number came from, and never present a guess as a fact.**

```
Label each figure Measured, Given or Estimated.
- Measured: it came from the store, the mailbox or a connected account.
- Given: the operator wrote it in company.yaml or answered it in the inbox.
- Estimated: you worked it out. Say so, and say from what.
Never state a number with no label. If you do not have one, say you do not.
```

This is the same discipline corparius applies to itself: a deploy that published
nothing is not logged as a success, a day stopped at noon is not counted whole.
An agent that reports "conversion is 4%" with nothing behind it costs the
operator a decision, which is worse than reporting nothing.

Borrowed from `aaron-he-zhu/aaron-marketing-skills`, whose skills carry this rule
throughout; see `docs/reverse-engineering/openworker.md` for what else that
library does and does not transfer here.

## Two things not to copy from other skill libraries

Public `SKILL.md` collections are written for hosts with slash commands and
skill-to-skill handoffs. Two of their habits break here:

- **A "next skill" or "handoff" section does nothing.** Corparius decides which
  skill applies from `allowed-tools`, in code. A skill cannot call another one.
- **Omitting `allowed-tools`** makes the skill apply to every tool of every
  agent. `corparius doctor` warns about it, but write the list.
