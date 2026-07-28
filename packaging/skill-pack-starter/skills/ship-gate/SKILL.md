---
name: ship-gate
description: What to look for in code before proposing it, and what must be true before it goes to production.
allowed-tools: generate_code, publish_production_code
source: adapted from anthropics/knowledge-work-plugins, engineering/skills/{code-review,deploy-checklist}
licence: Apache-2.0
---

Review in one order, because the cheap checks make the expensive ones easier to
read: correctness, then security, then maintainability, then performance.

- **Correctness.** What happens on the empty input, the duplicate, the second
  call? Most defects live in the case nobody named.
- **Security.** Anything that concatenates a query, trusts a path, or logs a
  secret. A credential in a log is a credential that has leaked.
- **Maintainability.** Would the next person guess what this does from its name?
  If the answer needs the comment, the comment is doing the name's work.
- **Performance.** Only where the data grows. A loop over five items is not a
  problem, and calling it one is how a review loses its authority.

Separate what is wrong from what you would have done differently, and say which
is which. A review that mixes them gets read as opinion and dismissed whole.

Publishing to production is gated on a human by design. Before proposing it,
state what changed, what could break, and how it is undone. "Revert the commit"
is only an answer if nothing has migrated behind it — if something has, say so
in the same sentence.
