"""The CEO's powers, and the promise each one keeps.

Before these, the chat read the store and wrote nothing. The operator's own
session: "too early for cold emailing, I want a working prototype first" — the
CEO answered "I will pause the campaigns" — the next tick drafted another one.
A conversation held over a machine that could not hear it.
"""

import tempfile
import types

import pytest

from corparius.app import directives as app_directives
from corparius.kernel.records import AgentRole
from corparius.orchestrator import cadence_overrides, due_roles, paused_roles
from corparius.store import Store
from corparius.tools.registry import TOOLS

SLUG = "vigil"
ENABLED = {r.value: True for r in AgentRole}


@pytest.fixture
def store():
    s = Store(tempfile.mkdtemp())
    yield s
    s.close()


def _due(store, tick=None):
    """Which roles run: over a whole day by default, or at one named hour.

    A day rather than an hour, because these tests are about **pausing and cadence overrides**, not
    about the clock. They asked for hour 0 back when hour 0 was a stampede that fired every role at
    once; each role now starts from its own hour, so "social runs" is a question about the day.
    """
    hours = range(24) if tick is None else [tick]
    return sorted(
        {
            s.role.value
            for hour in hours
            for s in due_roles(
                hour, ENABLED, paused_roles(store, SLUG), cadence_overrides(store, SLUG)
            )
        }
    )


def test_pausing_a_role_stops_it_on_the_next_tick(store):
    assert "social" in _due(store)
    app_directives.apply(store, SLUG, {"pause": ["social", "outreach"]}, "en")
    due = _due(store)
    assert "social" not in due and "outreach" not in due
    assert "ceo" in due, "pausing one role must not stop the company"


def test_resuming_brings_it_back(store):
    app_directives.apply(store, SLUG, {"pause": ["social"]}, "en")
    app_directives.apply(store, SLUG, {"resume": ["social"]}, "en")
    assert "social" in _due(store)


def test_a_role_the_model_invented_is_dropped_not_promised(store):
    """Promising to pause `marketing` — which is not a role — would be exactly
    the empty promise this mechanism replaces."""
    said = app_directives.apply(store, SLUG, {"pause": ["marketing", "social"]}, "en")
    assert "marketing" not in said and "social" in said
    assert {d["target"] for d in store.directives(SLUG, "pause")} == {"social"}


def test_a_priority_replaces_the_housekeeping_backlog(store):
    """The bug in the run log: `social stood down: 9 post(s) queued` and, three
    lines later, the CEO queueing "Publish a post today" for that same role.
    Standing a role down has to stop the whole company asking it for work."""
    app_directives.apply(store, SLUG, {"pause": ["social"], "focus": "finish the prototype"}, "en")
    ctx = types.SimpleNamespace(store=store, company={"slug": SLUG, "name": "V", "agents": ENABLED})
    TOOLS["create_tasks"].run(ctx)
    queued = [t["target"] for t in store.list_tasks(SLUG) if t["created_by"] == "ceo"]
    assert "social" not in queued, "the CEO re-armed a role the operator had paused"
    assert queued, "a stated priority should still produce work"


def test_clearing_the_priority_brings_the_baseline_back(store):
    app_directives.apply(store, SLUG, {"focus": "one thing"}, "en")
    assert store.directives(SLUG, "focus")
    app_directives.apply(store, SLUG, {"focus": ""}, "en")
    assert store.directives(SLUG, "focus") == []


def test_a_cadence_is_a_sentence_not_a_yaml_edit(store):
    app_directives.apply(store, SLUG, {"cadence": {"support": 24}}, "en")
    assert cadence_overrides(store, SLUG) == {"support": 24}
    # Support starts from hour 2 and the operator asked for once a day, so 2 and 26 are its hours.
    # The roster default of every three hours would also put it on 5, which is the assertion that
    # says the override actually replaced it rather than joining it.
    assert "support" in _due(store, 2)
    assert "support" not in _due(store, 5), "the roster default still applied"
    assert "support" in _due(store, 26)


@pytest.mark.parametrize("hours", [0, -1, 10_000, "soon", None])
def test_a_cadence_that_means_nothing_is_refused(store, hours):
    """Zero would busy-loop a role and a year is indistinguishable from off.
    Neither is what anybody means, so neither is silently clamped."""
    app_directives.apply(store, SLUG, {"cadence": {"social": hours}}, "en")
    assert cadence_overrides(store, SLUG) == {}


def test_saying_the_same_thing_twice_leaves_one_directive(store):
    app_directives.apply(store, SLUG, {"pause": ["social"]}, "en")
    app_directives.apply(store, SLUG, {"pause": ["social"]}, "en")
    assert len([d for d in store.directives(SLUG, "pause") if d["target"] == "social"]) == 1


def test_approving_in_words_resolves_the_request_that_exists(store):
    """Bonus, and narrow on purpose: it approves a request already raised and
    already shown. The console button is untouched."""
    from corparius.config.permissions import PermissionEngine
    from corparius.hitl import ApprovalGate

    gate = ApprovalGate(store, PermissionEngine(["send_outreach"]))
    ctx = types.SimpleNamespace(store=store, company={"slug": SLUG, "name": "V"}, leads=[])
    gate.execute(SLUG, "outreach", TOOLS["send_outreach"], ctx, "Bonjour…", {"draft": "x"})
    assert store.pending_approval_for(SLUG, "send_outreach")

    said = app_directives.apply(store, SLUG, {"approve": ["send_outreach"]}, "en")
    assert "send_outreach" in said
    assert store.pending_approval_for(SLUG, "send_outreach") is None


def test_approving_something_nobody_asked_for_does_nothing(store):
    said = app_directives.apply(store, SLUG, {"approve": ["deploy_site"]}, "en")
    assert "deploy_site" not in said


def test_an_ordinary_answer_changes_nothing(store):
    """Most messages are conversation. Empty fields must stay empty."""
    assert app_directives.apply(store, SLUG, {"reply": "hello"}, "en") == ""
    assert store.directives(SLUG) == []


def test_the_reply_reports_what_happened_not_what_was_intended(store):
    said = app_directives.apply(
        store, SLUG, {"pause": ["social"], "focus": "ship the prototype"}, "en"
    )
    assert "social" in said and "ship the prototype" in said


# --------------------------------------------------------------------------
# A power the model is never told about is a power nothing can reach
# --------------------------------------------------------------------------
#
# `model` was added to _CEO_SCHEMA and to `_apply_directives`, and the CEO was
# asked in a real console to put the design role on claudecode:opus. It answered
# "J'approuve l'utilisation de Claudecode Opus pour le design" and wrote nothing —
# the empty promise, arriving through the very field meant to end it.
#
# The cause was not the paragraph. `render_hint` had no rendering for a `dict`, so
# every dict field was described to the model as `string`: it was asked for a
# string where the code expected an object. `cadence` survived only because its
# prose happened to carry an example. These tests hold both ends.


# The two halves of the CEO's powers live in `app/`, not in the console: the prompt that
# *describes* them in `app/chat.py`, the code that *reads* them in `app/directives.py`. They
# were both in `webui.py` when these tests were written, and a path-shaped read is exactly what
# a move breaks — the same trap the flat glob in test_registries.py set for the whole
# restructuring. Read by inspecting the functions rather than by slicing a file at a marker, so
# the next move does not silently make these assertions read nothing.
def _chat_prompt() -> str:
    """The system prompt the chat sends. Read from the source because building it for real needs
    a store, a company and a live router, and what matters here is whether the field is
    described at all."""
    import inspect

    from corparius.app import chat as app_chat

    return inspect.getsource(app_chat.once)


# `reply` is the answer itself; `intent` and `ticks` drive the console's buttons,
# not a standing directive.
_NOT_A_DIRECTIVE = {"reply", "intent", "ticks"}
_POWERS = sorted(set(app_directives.CEO_SCHEMA) - _NOT_A_DIRECTIVE)


@pytest.mark.parametrize("field", _POWERS)
def test_every_power_is_named_in_the_prompt(field):
    assert f"`{field}`" in _chat_prompt(), (
        f"the chat acts on `{field}` and never tells the CEO it exists, so it "
        "answers in prose and records nothing"
    )


@pytest.mark.parametrize("field", _POWERS)
def test_every_power_is_read_when_it_arrives(field):
    """The mirror direction: a field offered to the model and read by nobody is a
    promise the console makes and drops."""
    import inspect

    from corparius.app import directives

    applied = inspect.getsource(directives.apply)
    assert f'"{field}"' in applied, f"`{field}` is offered to the CEO and never read"


def test_no_dict_field_is_described_to_a_model_as_a_string():
    """The root cause, guarded once for every schema in the project rather than
    once per field: `render_hint` fell through to "string" for a dict, so the model
    was asked for the wrong type and had no way to know the shape."""
    from corparius import structured

    rendered = structured.render_hint({"d": {"type": "dict", "default": {}}})
    assert "string" not in rendered, "a dict is still described as a string"
    assert "{" in rendered.split('"d":')[1]


@pytest.mark.parametrize("field", _POWERS)
def test_a_dict_power_carries_its_own_shape(field):
    """An example in a paragraph has to be remembered; one on the field cannot be
    forgotten, because `render_hint` reads it."""
    spec = app_directives.CEO_SCHEMA[field]
    if spec.get("type") != "dict":
        pytest.skip("not a dict field")
    assert spec.get("shape"), f"`{field}` is a dict with no shape for the model to copy"


# --- a pin has to reach the tools worth pinning -------------------------------


def test_the_pin_reaches_a_tool_with_a_schema(monkeypatch, tmp_path):
    """A `model` directive was honoured for prose and dropped for every structured
    tool — which is most of the ones worth pinning.

    Measured on a real run: design pinned to `claudecode:opus`, the log said
    `[design] pinned to claudecode:opus`, and `review_site` was answered by
    `cerebras:gpt-oss-120b`, which cannot produce JSON. The tool reported "no model
    returned usable structure" and did nothing, twice over, and nothing anywhere
    said the pin had been ignored.
    """
    import json as _json

    from corparius import structured
    from corparius.kernel.records import LLMResult, Usage

    seen: list = []

    class Router:
        def generate(self, messages, difficulty=None, model=None, max_tokens=512, images=None):
            seen.append(model)
            return LLMResult(_json.dumps({"findings": ["a"], "worst": "b"}), "p", "m", Usage(1, 1))

        def embed(self, text):
            return [0.0]

    structured.ask(
        Router(),
        [{"role": "user", "content": "x"}],
        {"findings": {"type": "list", "default": []}, "worst": {"type": "str", "default": ""}},
        model="claudecode:opus",
    )
    assert seen == ["claudecode:opus"], f"structured.ask dropped the pin: {seen}"


def test_the_agent_hands_the_pin_to_the_structured_path():
    """The other end of the same wire: the branch in agents.py that calls
    structured.ask must pass spec.model, exactly as the raw-draft branch beside it
    has always done."""
    import inspect

    from corparius import agents

    src = inspect.getsource(agents.Executor._invoke)
    structured_call = src[src.index("structured.ask(") : src.index("elif tool.needs_draft")]
    assert "model=spec.model" in structured_call, (
        "the structured branch does not pass the pin, so a pinned role with a "
        "schema tool silently gets its tier model"
    )
