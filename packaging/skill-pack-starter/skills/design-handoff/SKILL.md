---
name: design-handoff
description: What a brief or a mockup has to state so that the thing built from it is the thing asked for.
allowed-tools: draft_design_brief, produce_mockup
source: adapted from anthropics/knowledge-work-plugins, design/skills/design-handoff
licence: Apache-2.0
---

A design that only shows the happy path is not finished; it is a screenshot of
the best case. State four things every time, because these are what gets
improvised otherwise:

- **Empty.** What is on screen before there is any data. This is the state a new
  user sees first and the one most often left undesigned.
- **Loading.** What moves, and what does not move, while waiting.
- **Too long.** The name that does not fit, the list with two hundred rows.
- **Wrong.** What the error says, where it appears, and what it offers to do
  next.

Name spacing, size and colour as tokens the site already has, not as pixel
values. A value copied into a mockup is a value that will drift from the one in
the code by the second iteration.

Say what the user is trying to do, in one sentence, before any layout. A brief
that opens with a layout has already chosen the answer and hidden the question.

Accessibility is a specification, not a review step: state the contrast, the
focus order, and what a screen reader announces. Adding it afterwards means
rebuilding.
