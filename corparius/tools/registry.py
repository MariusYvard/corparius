"""The forty tools, effects bound. Rank 4.

`spec.py` says what a tool is; `effects.py` says what it does; this file zips them by name and
is the only one of the three that costs anything to import. Six of the eight consumers of the
old flat registry never needed it.

`TOOLS` is mutated in place at run time — `plugins.PluginAPI.register_tool` inserts a plugin's
tool here, which is why it is a plain dict and not frozen. A plugin tool inherits the HITL gate
and the permission engine at dispatch like any other.
"""

from __future__ import annotations

from collections.abc import Callable

from ..config import permissions
from ..kernel.records import ToolResult
from .effects import BEHAVIOUR, Behaviour
from .spec import SPEC, ToolSpec


class Tool:
    """A declaration paired with its behaviour.

    **The constructor is unchanged, on purpose.** Splitting the registry was an internal
    move; `Tool` is part of the plugin API, which carries an `api_version`, and a plugin
    written for version 1 calls `Tool("name", "description", effect=...)`. Changing that
    signature would break every third-party plugin silently — and `permissions.risk_of`
    already documents this project's position on that: plugins predate later additions and
    are not broken by them. So the eleven keyword arguments still work, and the two halves
    are assembled here rather than by the caller.

    `from_parts` is the path `_build` takes, where the halves already exist separately.

    Attributes are forwarded rather than the spec exposed, because `permissions` reads
    `name`, `risk` and `hitl` off whatever it is handed and forty call sites spell
    `tool.name`.
    """

    def __init__(
        self,
        name: str,
        description: str,
        effect: Callable,
        *,
        hitl: bool = False,
        risk: str = permissions.READ,
        needs_draft: bool = False,
        prompt: Callable | None = None,
        schema: dict | None = None,
        skip_when: Callable | None = None,
        sees_images: bool = False,
        by_task_only: bool = False,
    ):
        self.spec = ToolSpec(
            name=name,
            description=description,
            hitl=hitl,
            risk=risk,
            needs_draft=needs_draft,
            schema=schema,
            sees_images=sees_images,
            by_task_only=by_task_only,
        )
        self.behaviour = Behaviour(effect=effect, prompt=prompt, skip_when=skip_when)

    @classmethod
    def from_parts(cls, spec: ToolSpec, behaviour: Behaviour) -> Tool:
        """Assemble from halves that already exist, without re-listing eleven fields.

        `__new__` rather than `__init__` because passing a `ToolSpec` back through the
        keyword constructor would mean spelling every field twice — and the next field added
        to `ToolSpec` would be silently dropped here, which is the whole class of bug this
        file's assertions exist to catch.
        """
        tool = cls.__new__(cls)
        tool.spec = spec
        tool.behaviour = behaviour
        return tool

    def __getattr__(self, item: str):
        # Only reached for names not found normally, so `spec` and `behaviour` never recurse.
        try:
            return getattr(self.spec, item)
        except AttributeError:
            raise AttributeError(f"{type(self).__name__!r} has no attribute {item!r}") from None

    def __repr__(self) -> str:
        return f"Tool({self.spec.name!r})"

    def skip_reason(self, ctx) -> str:
        return self.behaviour.skip_when(ctx) if self.behaviour.skip_when else ""

    def draft_prompt(self, ctx) -> str:
        return self.behaviour.prompt(ctx) if self.behaviour.prompt else ""

    def run(self, ctx, draft: str = "") -> ToolResult:
        return self.behaviour.effect(ctx, draft)


def _build() -> dict[str, Tool]:
    """One tool per spec, and a spec for every behaviour.

    The two assertions are this file's whole job. A spec with no behaviour is a tool the
    console offers and nothing can execute — the exact shape that put `ask_operator` and
    `set_roster` in the registry with no path for months. A behaviour with no spec is an
    effect nothing can reach. Both used to be impossible to state, because the two halves
    were the same literal.
    """
    orphan_specs = sorted(set(SPEC) - set(BEHAVIOUR))
    orphan_effects = sorted(set(BEHAVIOUR) - set(SPEC))
    assert not orphan_specs, f"tools declared with no effect: {orphan_specs}"
    assert not orphan_effects, f"effects with no declaration: {orphan_effects}"
    return {name: Tool.from_parts(SPEC[name], BEHAVIOUR[name]) for name in SPEC}


TOOLS: dict[str, Tool] = _build()
