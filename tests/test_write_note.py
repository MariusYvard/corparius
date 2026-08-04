"""A tool that writes the document a task asks for.

Five tools already write documents — `draft_design_brief`, `update_pricing`,
`scan_competitors`, `write_eod_summary`, `review_site` — each under a fixed name.
None of them writes *the* document a particular task asked for, so "rédiger une note
de cadrage pour le contrat de licence institutionnelle" had nowhere to go: strategy
had no tool that could carry it, the task was held, and when the CEO placed it
anyway it landed on `write_site_content`, which would have produced site copy for a
licence contract. The operator asked for the tool directly.

Building it turned up a second defect. `ask_operator`'s prompt says "the one piece of
information **this task** cannot proceed without" — and nothing had ever put the task
on the context, so the model was being asked about a task it could not see. Declared
and unreachable, in a prompt rather than in code.
"""

import pytest

from corparius import documents, tools
from corparius.store import Store
from corparius.tools import ROLE_TOOL, TOOLS


class _Ctx:
    def __init__(self, task=None, structured=None, slug="c"):
        self.company = {"slug": slug, "name": "C"}
        self.task = task
        self.structured = structured
        self.store = None
        self.data_path = "unused"


class _Result:
    def __init__(self, data, ok=True, fell_back=False):
        self.data = data
        self.ok = ok
        self.fell_back = fell_back


@pytest.fixture(autouse=True)
def _own_home(tmp_path, monkeypatch):
    monkeypatch.setattr(documents.paths, "companies_dir", lambda: tmp_path)
    (tmp_path / "c").mkdir()


# --- the task reaches the prompt ----------------------------------------------


def test_the_prompt_carries_the_task_and_its_reason():
    ctx = _Ctx(task={"id": 1, "title": "Note de cadrage licence", "why": "Le pricing l'exige"})
    prompt = tools._write_note_prompt(ctx)
    assert "Note de cadrage licence" in prompt and "Le pricing l'exige" in prompt


def test_a_task_with_no_reason_still_works():
    prompt = tools._write_note_prompt(_Ctx(task={"id": 1, "title": "Just this"}))
    assert "Just this" in prompt and "why it was asked for" not in prompt


def test_the_prompt_is_never_empty_even_with_no_task():
    """`skip_when` is not what guards this one — `by_task_only` is — but a prompt
    that can come back empty is a tool that can call a model with nothing in it."""
    assert tools._write_note_prompt(_Ctx()).strip()


def test_it_asks_for_labelled_figures():
    """The house rule, in the prompt of a tool whose whole output is prose that may
    contain numbers."""
    prompt = tools._write_note_prompt(_Ctx(task={"id": 1, "title": "Pricing note"}))
    assert "Measured, Given or Estimated" in prompt
    assert "rather than inventing" in prompt


# --- what it writes -----------------------------------------------------------


def test_it_keeps_the_document_where_every_agent_reads_it():
    ctx = _Ctx(
        task={"id": 1, "title": "Note de cadrage"},
        structured=_Result({"title": "Note de cadrage licence", "body": "Le contrat couvre..."}),
    )
    out = tools._write_note(ctx)
    assert "Note written" in out and "Note de cadrage licence" in out
    written = list((documents.folder("c") / "written").glob("*.md"))
    assert [p.name for p in written] == ["note-de-cadrage-licence.md"]
    assert "Le contrat couvre" in written[0].read_text(encoding="utf-8")


def test_the_length_is_reported_so_a_stub_is_visible():
    """A log line saying "note written" over four words is the same lie as a deploy
    that published nothing."""
    ctx = _Ctx(task={"id": 1, "title": "T"}, structured=_Result({"title": "T", "body": "x" * 500}))
    assert "(500 chars)" in tools._write_note(ctx)


def test_the_task_title_names_the_file_when_the_model_gives_none():
    ctx = _Ctx(
        task={"id": 1, "title": "Fallback name"}, structured=_Result({"title": "", "body": "text"})
    )
    tools._write_note(ctx)
    assert (documents.folder("c") / "written" / "fallback-name.md").is_file()


def test_an_empty_body_writes_nothing():
    ctx = _Ctx(task={"id": 1, "title": "T"}, structured=_Result({"title": "T", "body": "   "}))
    out = tools._write_note(ctx)
    assert "no note was written" in out
    assert not list((documents.folder("c") / "written").glob("*.md"))


def test_no_provider_answering_is_not_an_empty_note():
    """`_empty_draft` distinguishes "nothing to add" from "every provider refused" —
    the operator read the second as a bad generator once already."""
    ctx = _Ctx(task={"id": 1, "title": "T"}, structured=_Result({"body": ""}, ok=False))
    out = tools._write_note(ctx)
    assert "no note was written" in out
    assert "routing" in out.lower() or "provider" in out.lower()


# --- and it is reachable exactly one way --------------------------------------


def test_it_runs_from_a_task_and_never_from_a_cadence():
    """On a playbook it would write a note about nothing every turn, which is the
    queue of drafts nobody reads in another costume."""
    assert TOOLS["write_note"].by_task_only is True
    from corparius.agents import ROSTER

    on_a_playbook = {n for spec in ROSTER.values() for n in spec.playbook}
    assert "write_note" not in on_a_playbook


def test_a_strategy_task_is_now_executable():
    """The case that started this: strategy's work product is a written document,
    and it had no tool that could produce one."""
    assert ROLE_TOOL["strategy"] == "write_note"
    assert tools.executable_fields({"target": "strategy", "tool": ""}) == {"tool": "write_note"}


def test_ask_operator_can_finally_name_its_task():
    ctx = _Ctx(task={"id": 1, "title": "Get the Netlify token"})
    prompt = TOOLS["ask_operator"].draft_prompt(ctx)
    assert "Get the Netlify token" in prompt


def test_a_playbook_turn_sees_no_task():
    """The context is shared across a whole turn. A task left on it would be read by
    every tool that ran afterwards."""
    assert tools._task_subject(_Ctx()) == ""
    assert tools._task_subject(_Ctx(task={})) == ""


def test_the_task_is_cleared_after_the_call(tmp_path):
    """Set for one call, cleared in a finally. Proven through `_work_task` rather
    than by reading it: a tool later in the same turn must not inherit it."""
    from corparius.agents import Executor

    store = Store(str(tmp_path / "data"))
    try:
        task_id = store.add_task("c", "A held one", "finance", status="approved")
        agent = Executor.__new__(Executor)
        agent.store = store
        ctx = _Ctx()
        ctx.task = "sentinel"
        agent._work_task("c", None, ctx, store.claim_next_task("c", "finance"), None, [])
        assert ctx.task is None, "the task outlived its call"
        assert store.get_task(task_id)["status"] == "waiting"
    finally:
        store.close()
