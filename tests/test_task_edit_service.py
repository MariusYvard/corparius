"""One service for the backlog, and the live bug that having two produced.

Two callers reached the backlog and were repaired in opposite directions, each blind to the
other. The console grew validation — the agent has to be a real role, the tool has to be in the
registry — and it grew the `executable_fields` call on approval. `cli.cmd_task` kept calling
`store.update_task(id, **fields)` directly, so it had none of either.

Measured on a real store before this file existed: the command line accepted
`--target not-a-real-agent` and `--tool not-a-real-tool` and wrote both. And the approval path
is the one that cost something — from `executable_fields`' own docstring, **24 tasks for one
role carried no tool and 22 closed "done (no tool mapped)" having done nothing**, so the
condition survived and the agent proposed the same work again.

The first four tests below are the reproduction, now inverted into a guard.
"""

import pytest

from corparius.app import tasks as app_tasks
from corparius.app.errors import Refused
from corparius.store import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path / "data"))
    yield s
    s.close()


def _task(store, target="social", tool=""):
    return store.add_task("acme", "Publier un post", target, 3, created_by="ceo")


# --- the validation the command line did not have ------------------------------


def test_an_agent_that_does_not_exist_is_refused(store):
    ident = _task(store)
    with pytest.raises(Refused, match="unknown agent 'not-a-real-agent'"):
        app_tasks.edit(store, ident, target="not-a-real-agent")
    assert store.get_task(ident)["target"] == "social", "and nothing was written"


def test_a_tool_that_does_not_exist_is_refused(store):
    ident = _task(store)
    with pytest.raises(Refused, match="unknown tool 'not-a-real-tool'"):
        app_tasks.edit(store, ident, tool="not-a-real-tool")


def test_an_empty_tool_clears_it_rather_than_being_refused(store):
    """A real thing an operator asks for, and the reason the check is `if clean and ...`
    rather than `if clean`."""
    ident = _task(store)
    app_tasks.edit(store, ident, tool="draft_social_post")
    assert store.get_task(ident)["tool"] == "draft_social_post"
    app_tasks.edit(store, ident, tool="")
    assert store.get_task(ident)["tool"] == ""


def test_an_empty_title_is_refused(store):
    ident = _task(store)
    with pytest.raises(Refused, match="title cannot be empty"):
        app_tasks.edit(store, ident, title="   ")


def test_priority_is_clamped_not_refused(store):
    """A number out of range is a slider that went too far, not a mistake worth stopping for."""
    ident = _task(store)
    app_tasks.edit(store, ident, priority=99)
    assert store.get_task(ident)["priority"] == app_tasks.MAX_PRIORITY
    app_tasks.edit(store, ident, priority=-5)
    assert store.get_task(ident)["priority"] == 0


def test_a_priority_that_is_not_a_number_is_refused(store):
    ident = _task(store)
    with pytest.raises(Refused, match="whole number"):
        app_tasks.edit(store, ident, priority="soon")


def test_a_missing_id_is_refused_before_anything_is_read(store):
    with pytest.raises(Refused, match="a task id is required"):
        app_tasks.edit(store, None, title="x")


def test_a_decision_that_is_not_one_is_refused(store):
    ident = _task(store)
    with pytest.raises(Refused, match="approved, rejected"):
        app_tasks.edit(store, ident, decision="maybe")


def test_changing_nothing_is_refused_rather_than_reported_as_a_change(store):
    ident = _task(store)
    with pytest.raises(Refused, match="nothing to change"):
        app_tasks.edit(store, ident)


# --- the approval path, which is where the cost was ----------------------------


def test_approving_maps_the_tool_the_role_needs(store):
    """The end of the wire the command line was never attached to. Without this the task
    closes "done (no tool mapped)" having done nothing, the condition survives, and the agent
    proposes the same work again."""
    ident = _task(store)
    changed = app_tasks.edit(store, ident, decision="approved")
    row = store.get_task(ident)
    assert row["tool"] == "draft_social_post", "approval must leave it executable"
    assert row["status"] == "approved"
    assert "tool" in changed["changed"]


def test_an_explicit_tool_wins_over_the_mapping(store):
    """The operator chose. `executable_fields` fills a gap; it does not overrule."""
    ident = _task(store)
    app_tasks.edit(store, ident, tool="write_note", decision="approved")
    assert store.get_task(ident)["tool"] == "write_note"


def test_approving_a_task_that_is_not_there_is_refused(store):
    with pytest.raises(Refused, match="no task 9999"):
        app_tasks.edit(store, 9999, decision="approved")


def test_a_role_with_no_mapped_tool_still_approves(store):
    """`ROLE_TOOL` does not cover every role, on purpose. A task for one of those is approved
    and held for the operator rather than refused — which is what the backlog is for."""
    ident = store.add_task("acme", "Regarder les chiffres", "finance", 3, created_by="ceo")
    app_tasks.edit(store, ident, decision="approved")
    assert store.get_task(ident)["status"] == "approved"


# --- the two callers agree ------------------------------------------------------


def test_the_service_carries_no_status_code(store):
    """The rule that makes it shareable. The console maps `Refused` to 400; a terminal prints
    it. A service returning `(400, {...})` — which the console's handler used to — can only be
    called by something that speaks HTTP.

    Read from the AST, not from the source text: the first version of this grepped for "400"
    and matched its own docstring explaining what 400 means. A test that can be satisfied by
    prose is not checking the code.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(app_tasks))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }
    http_codes = {c for c in literals if 200 <= c <= 599}
    assert not http_codes, f"these read as status codes: {sorted(http_codes)}"


@pytest.mark.parametrize("handler", ["tasks_post", "v1_tasks_post"])
def test_the_console_handler_only_unpacks_and_translates(handler):
    """Both spellings should be unpacking a body and mapping one exception. If either grows logic,
    the callers start to differ again — which is the whole history here.

    This read `adapters.edit_task` until the endpoint got a v1 twin. The adapter went, and the hop
    it saved is real: `tests/test_api_version.py` requires both handler bodies to contain the same
    service call, and a handler that delegates to an adapter that calls the service does not satisfy
    that by reading — it satisfies it by trust. One less indirection, one more thing asserted.
    """
    import inspect

    from corparius.api import handlers

    source = inspect.getsource(getattr(handlers, handler))
    assert "app_tasks.edit(" in source
    assert "Refused" in source and "400" in source
    # No validation left behind: those words belong to the service now.
    assert "unknown agent" not in source and "unknown tool" not in source
