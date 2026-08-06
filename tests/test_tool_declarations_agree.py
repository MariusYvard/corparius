"""A tool declares itself in three places, and the three have to agree.

`needs_draft` says a model is called before the effect runs. `schema` says the reply must
validate against a shape. `prompt` says what to ask. They are separate fields because they are
separate concerns — the schema is machine-checked, the prompt is composed from company data at
run time, the description is what a person reads. NVIDIA's NOOA collapses all three into a
method signature plus its docstring (docs/reverse-engineering/nooa.md); corparius cannot,
because its prompts interpolate the company. What it can do is refuse a combination that means
nothing.

Every pairing below holds today. This file is the guard, not a repair — and one of the three
was already guarded, in `test_images.py`, for exactly this reason:

    "`sees_images` is only ever read on the drafting path, so setting it on a tool with
     needs_draft=False does nothing — silently. A dead flag reads as a feature to the next
     person who greps for it."

That is the same sentence four times over, so it belongs in one place with the other three.
"""

import pytest

from corparius.tools.registry import TOOLS


def test_a_schema_without_a_draft_would_never_be_validated():
    """The silent one, and the worst of the three.

    A schema tool gets its validated dict from `ctx.structured`, which the executor sets only
    on the drafting path (agents.py). With `needs_draft=False` the effect reads `None`, falls
    into `_empty_draft`, and reports "no model returned usable structure" — when no model was
    ever asked. The operator is sent to check their providers over a declaration mistake.
    """
    orphans = sorted(name for name, t in TOOLS.items() if t.schema and not t.needs_draft)
    assert not orphans, (
        f"these declare a schema and call no model, so ctx.structured is never set: {orphans}. "
        "Add needs_draft=True, or drop the schema."
    )


def test_a_prompt_without_a_draft_is_never_asked():
    """The mirror. `draft_prompt` is called from the drafting path and nowhere else, so a
    prompt on a tool that calls no model is prose nobody reads — and it looks wired."""
    unused = sorted(name for name, t in TOOLS.items() if t.behaviour.prompt and not t.needs_draft)
    assert not unused, f"these carry a prompt no model is ever shown: {unused}"


def test_a_draft_with_no_prompt_asks_for_nothing():
    """The third direction, and the one that reaches a provider: `needs_draft` spends a real
    call, and with no prompt it spends it on an empty request."""
    empty = sorted(name for name, t in TOOLS.items() if t.needs_draft and not t.behaviour.prompt)
    assert not empty, f"these call a model with nothing to ask: {empty}"


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_every_tool_has_a_description_a_person_could_read(name):
    """The third declaration, the one for humans. It is the row the console shows next to an
    approval, so an empty one makes the operator decide on a tool name alone."""
    tool = TOOLS[name]
    assert tool.description.strip(), f"{name} has no description"
    assert len(tool.description) <= 120, f"{name}'s description is a paragraph, not a row"
    assert not tool.description.endswith("."), (
        f"{name}'s description ends with a period; these are labels, not sentences, and the "
        "console renders them in a list"
    )


def test_the_guard_is_not_vacuous():
    """Four assertions over forty tools, and all four pass — so the risk is that they are
    checking nothing. Each one is re-run against a deliberately broken tool."""
    from corparius.tools.effects import Behaviour
    from corparius.tools.registry import Tool
    from corparius.tools.spec import ToolSpec

    broken = Tool.from_parts(
        ToolSpec("bad", "does the wrong thing", schema={"x": {"type": "str"}}, needs_draft=False),
        Behaviour(effect=lambda c, d: None, prompt=lambda c: "asked but never shown"),
    )
    assert broken.schema and not broken.needs_draft, "the first assertion would catch this"
    assert broken.behaviour.prompt and not broken.needs_draft, "and so would the second"

    silent = Tool.from_parts(
        ToolSpec("quiet", "", needs_draft=True), Behaviour(effect=lambda c, d: None)
    )
    assert silent.needs_draft and not silent.behaviour.prompt, "the third would catch this"
    assert not silent.description, "and the fourth"
