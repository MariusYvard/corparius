---
name: books-hygiene
description: How to read a reconciliation difference, and what never moves money without a human.
allowed-tools: reconcile_stripe, send_financial_transaction
source: adapted from anthropics/knowledge-work-plugins, finance/skills/{reconciliation,close-management}
licence: Apache-2.0
---

A difference between the books and the processor is one of three things, and
they are not equally urgent.

**Timing.** A payout in flight, a charge captured today and settled tomorrow. It
clears itself; note it and move on. Chasing timing differences is the most
common way to waste a finance turn.

**An entry that is missing.** Money moved and nothing recorded it, or the other
way round. This is the one worth the turn: find what moved, record it, say what
it was.

**An error.** Right amount, wrong account; or a duplicate. Say which, and never
correct it by adding a second entry that happens to cancel the first — the books
then balance and describe something that did not happen.

Report the difference in currency and as a share of the period. "€12 on €4 200"
and "€12 on €40" are the same twelve euros and not the same problem.

Moving money is gated on a human by design, and that gate exists because a wrong
transfer is not reversible by a retry. Prepare it fully — amount, recipient,
reason — so the person approving reads a decision, not a puzzle.
