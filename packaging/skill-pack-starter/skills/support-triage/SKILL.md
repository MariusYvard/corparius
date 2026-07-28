---
name: support-triage
description: How to read a ticket before answering it, and when to stop and ask.
allowed-tools: triage_inbox, draft_support_reply, propose_task
source: adapted from anthropics/knowledge-work-plugins, customer-support/skills/{ticket-triage,draft-response}
licence: Apache-2.0
---

Read the ticket for five things before writing a word: the problem they actually
have (not the one they named), what they saw, who they are, whether they are
blocked right now, and how they sound. The last two set the priority; the first
three set the answer.

Blocked in production beats confused about a feature, every time. A customer who
is calm and stuck outranks one who is angry and merely inconvenienced.

Then answer in this order: what you will do, by when, and only then why. An
apology first buries the commitment under it. Match their register — someone who
wrote three terse lines does not want six paragraphs.

Never invent a date, a cause or a refund. If the answer depends on something you
cannot see — an account state, a deploy, a policy nobody wrote down — ask the
operator instead of guessing. A confident wrong answer to a customer costs more
than a day's delay, and asking is one tool call.

If the ticket names a defect rather than a misunderstanding, propose the task.
A reply that soothes and leaves the bug in place is a reply you will write again
next week.
