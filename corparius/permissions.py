"""What may run without asking a human, and why.

The gate used to be a boolean: a tool was flagged, or it was not. That answers
"does this stop" but never "why did that one go through", which is exactly what
an operator reading the audit trail wants to know, and it gives no dial between
"ask about the three money tools" and "ask about everything".

So a decision is made of three things. A tool carries a *risk class* describing
what it does to the world outside this process. The operator picks a *mode* and
a *threshold*: how consequential a tool has to be before it needs a human. And
either of them can be overridden by name, upward through `hitl_tools` (which
always wins, so a declared gate can never be argued away) or downward through
standing rules the operator grants from the console.

`evaluate` returns a Decision carrying the verdict *and* its motive, and the
motive is written to the action log. Modelled on OpenWorker's permissions.py;
see docs/reverse-engineering/openworker.md.
"""

from __future__ import annotations

from dataclasses import dataclass

# Risk classes, ordered by how much of the outside world a tool touches. The
# class describes the *effect*, not the subject: drafting a pricing note is
# READ because nothing leaves the process, while sending one cold email is
# EXTERNAL because a stranger receives it.
READ = "read"  # reads, drafts, computes; nothing leaves the process
WRITE_LOCAL = "write_local"  # writes files under the operator's data dir
EXTERNAL = "external"  # calls a third party, or someone receives something
CODE = "code"  # ships code to a place that runs it
MONEY = "money"  # moves the operator's money

ORDER: dict[str, int] = {READ: 0, WRITE_LOCAL: 1, EXTERNAL: 2, CODE: 3, MONEY: 4}
RISK_CLASSES: tuple[str, ...] = tuple(ORDER)

# Modes.
DISCUSS = "discuss"  # dry run: nothing above the threshold executes at all
INTERACTIVE = "interactive"  # default: anything above the threshold asks
AUTO = "auto"  # nothing asks, except tools gated by name
CUSTOM = "custom"  # interactive, plus the auto_allow list
MODES: tuple[str, ...] = (DISCUSS, INTERACTIVE, AUTO, CUSTOM)

# Default threshold: ask above EXTERNAL, i.e. for CODE and MONEY. Combined with
# the shipped `hitl_tools`, that reproduces exactly the behaviour corparius had
# before risk classes existed, so an existing company upgrades without suddenly
# stalling on approvals it never had to give. Tighten it to `read` for a posture
# where every side effect is confirmed.
DEFAULT_ASK_ABOVE = EXTERNAL


def risk_of(tool) -> str:
    """A tool with no declared class is treated as harmless. Plugins predate
    this module and register tools through PluginAPI.register_tool, so refusing
    to run an unannotated tool would break them; over-gating them would be worse
    than useless, since the operator cannot annotate someone else's tool."""
    risk = getattr(tool, "risk", READ)
    return risk if risk in ORDER else READ


@dataclass(frozen=True)
class Decision:
    """The verdict and its motive. `needs_user` distinguishes the two ways of
    not being allowed: held for a human (the normal gate) versus refused
    outright (discuss mode), which the caller reports differently."""

    allowed: bool
    needs_user: bool = False
    reason: str = ""
    rule: str = ""  # what decided it, for the audit trail


class PermissionEngine:
    """Pure with respect to its inputs except for the standing-rule lookup,
    which is re-read on every check rather than cached: a rule granted from the
    console must take effect on the next tool call, not on the next run."""

    def __init__(
        self,
        hitl_tools=(),
        *,
        mode: str = INTERACTIVE,
        ask_above: str = DEFAULT_ASK_ABOVE,
        auto_allow=(),
        store=None,
    ):
        self.hitl_tools = set(hitl_tools)
        self.mode = mode if mode in MODES else INTERACTIVE
        self.ask_above = ask_above if ask_above in ORDER else DEFAULT_ASK_ABOVE
        self.auto_allow = set(auto_allow)
        self.store = store

    @classmethod
    def from_settings(cls, settings, company: dict | None = None, store=None) -> PermissionEngine:
        """company.yaml overrides the global setting, key by key, the same way
        hitl_tools already did."""
        company = company or {}
        return cls(
            company.get("hitl_tools", settings.hitl_tools),
            mode=company.get("permission_mode", settings.permission_mode),
            ask_above=company.get("ask_above", settings.ask_above),
            auto_allow=company.get("auto_allow", settings.auto_allow),
            store=store,
        )

    def _standing_rule(self, company: str, tool_name: str) -> str:
        if self.store is None or not company:
            return ""
        find = getattr(self.store, "find_rule", None)
        return find(company, tool_name) if find else ""

    def evaluate(self, tool, company: str = "") -> Decision:
        name = getattr(tool, "name", "")
        risk = risk_of(tool)
        above = ORDER[risk] > ORDER[self.ask_above]

        # 1. A declared gate wins over everything, including auto mode and any
        #    standing rule. Otherwise "never ask me again" on some other tool
        #    could quietly widen into the money tools, and the one guarantee the
        #    product makes would depend on the order the operator clicked in.
        if getattr(tool, "hitl", False) or name in self.hitl_tools:
            return Decision(False, True, f"{name} is gated by name", "hitl")

        if self.mode == AUTO:
            return Decision(True, reason="auto mode", rule="mode")

        # 2. Discuss mode refuses rather than queues: the point of a dry run is
        #    to see what the roster would do without leaving a pile of
        #    approvals behind.
        if self.mode == DISCUSS and above:
            return Decision(False, False, f"discuss mode: {name} is {risk}", "mode")

        if self.mode == CUSTOM and name in self.auto_allow:
            return Decision(True, reason=f"{name} is auto-allowed", rule="auto_allow")

        scope = self._standing_rule(company, name)
        if scope:
            return Decision(True, reason=f"standing rule ({scope})", rule=f"rule:{scope}")

        if above:
            return Decision(False, True, f"{name} is {risk}, above {self.ask_above}", "risk")
        return Decision(True, reason=f"{name} is {risk}", rule="risk")
