"""Where a task came from, on the card the operator reads.

`plan_from_documents` turns what the company's own agents wrote into work, and until now a queued
task arrived with a title, a role, a tool — and nothing at all about its origin. Measured on a real
run:

```text
    plan_from_documents: Queued 1 from the documents:
      coder/generate_code: Implémenter l'analyse prosodique via openSMILE
```

Four documents were read. Which one produced that? The operator could not tell, so the one person
who has to decide whether to reject it was the one who could not find the paragraph behind it.

**Taken from docling-graph**, where every extracted node carries a `__provenance__` back to its
chunk and page — and it is a rule this codebase already applies everywhere else it publishes.
`sitegen.proof_html` drops a claim that has no source rather than print it; every number an agent
reports is Measured, Given or Estimated. A task drawn out of a document was the one thing arriving
with no origin at all.

Two halves, because writing it down is only worth anything if it is shown:

  * the tool asks the model for the heading it was shown, and records it on the task;
  * the console renders `task.why`, which the store has carried on every row for a long time and
    the Svelte board never drew — so `propose_task` has been writing a reason nobody could read.
"""

import os
import pathlib
import tempfile
import types

import pytest

from corparius.config import cfg
from corparius.store import Store
from corparius.tools.registry import TOOLS


@pytest.fixture
def bench(monkeypatch):
    home = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setenv("CORP_HOME", str(home))
    cfg.invalidate()
    from corparius import documents

    documents.write("acme", "design-brief.md", "Le fond doit être anthracite, la couleur réservée.")
    store = Store(str(home / "data"))
    yield store
    store.close()
    cfg.invalidate()


def _run(store, entries):
    ctx = types.SimpleNamespace(
        company={"slug": "acme", "name": "Acme", "agents": {"design": True}},
        store=store,
        structured=types.SimpleNamespace(data={"tasks": entries}),
    )
    return TOOLS["plan_from_documents"].run(ctx)


def _seen(store) -> list:
    from corparius.tools.effects import PLAN_FROM_DOCS_COUNT, _agent_documents

    return [d.label for d in _agent_documents("acme")[:PLAN_FROM_DOCS_COUNT]]


def test_a_task_names_the_document_it_came_from(bench):
    """The whole point, and the label is the one the model was shown: the prompt heads each chunk
    `--- {doc.label} ---`, so asking for "the name of the document above" is asking for a string it
    can actually produce."""
    source = _seen(bench)[0]
    _run(bench, [f"design|draft_design_brief|Passer le fond en anthracite|{source}"])

    task = bench.list_tasks("acme")[0]
    assert source in task["why"]


def test_a_task_with_no_source_is_queued_and_says_so(bench):
    """Three fields or four. The source arrived after the format did, and refusing every
    three-field answer would throw a whole round away because a weaker tier omitted the newest
    field — a tool that stops working the day it is answered by a cheaper model.

    A task with no origin is a worse task, not a lost one, and the row says which it is.
    """
    result = _run(bench, ["design|draft_design_brief|Une tâche sans source"])
    assert "Queued 1" in result.output

    why = bench.list_tasks("acme")[0]["why"]
    assert "not named" in why, why


def test_an_invented_source_is_recorded_and_flagged(bench):
    """The one that matters most. A model that names a document it was never shown must not have
    that laundered into a fact on a card an operator then trusts — this codebase refuses an
    unsourced claim on a public page for exactly the same reason."""
    _run(bench, ["design|draft_design_brief|Une source inventée|notes-secretes.md"])

    why = bench.list_tasks("acme")[0]["why"]
    assert "notes-secretes.md" in why, "the claim was dropped instead of shown"
    assert "not one of the documents read" in why


def test_a_malformed_entry_is_still_refused_with_the_format_named(bench):
    """Two fields is not a shortened four, it is an answer nothing can act on. The refusal names the
    shape so the next round has something to correct against."""
    result = _run(bench, ["design|draft_design_brief"])
    assert "Queued" not in result.output
    assert "role|tool|title|source" in result.output


def test_the_prompt_asks_for_the_source(bench):
    """Both ends. A reader that accepted a fourth field nothing ever asked for would record "not
    named" forever and look like it was working."""
    ctx = types.SimpleNamespace(
        company={"slug": "acme", "name": "Acme", "agents": {"design": True}}, store=bench
    )
    asked = TOOLS["plan_from_documents"].draft_prompt(ctx)
    assert "role|tool|title|source" in asked
    assert "trace" in asked or "came from" in asked


def test_the_board_draws_it():
    """The other half, and the reason it is a test rather than a glance: the store has carried
    `why` on every task row for a long time and this console never rendered it, so `propose_task`
    was writing a reason no operator could read. Writing provenance into the same void would have
    been the same defect with better prose."""
    board = pathlib.Path("web/src/Operations.svelte").read_text(encoding="utf-8")
    assert "task.why" in board, "a task's origin is stored and never drawn"


def test_the_store_carries_it_to_the_console_at_all():
    """One layer below the board. `why` has to survive `list_tasks` or the component above is
    rendering a field that never arrives."""
    home = pathlib.Path(tempfile.mkdtemp())
    os.environ["CORP_HOME"] = str(home)
    cfg.invalidate()
    store = Store(str(home / "data"))
    store.add_task("a", "T", "design", why="From written/design-brief.md")
    assert store.list_tasks("a")[0]["why"] == "From written/design-brief.md"
    store.close()
