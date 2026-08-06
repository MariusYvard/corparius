"""The permission engine decides what runs without a human, and says why.

The properties that matter here are the ones an operator would be furious to
discover were false: that a tool they gated by name cannot be un-gated by any
other setting, that the shipped defaults gate exactly what they gated before
risk classes existed, and that a dry run really is dry.
"""

import pytest

from corparius import permissions as perm
from corparius.hitl import BLOCKED_MESSAGE, ApprovalGate
from corparius.kernel.records import ToolResult
from corparius.permissions import Decision, PermissionEngine
from corparius.store import Store
from corparius.tools import TOOLS


class _Recorder:
    def __init__(self, name="thing", hitl=False, risk=perm.READ):
        self.name = name
        self.hitl = hitl
        self.risk = risk
        self.ran = 0

    def run(self, ctx, draft=""):
        self.ran += 1
        return ToolResult(ok=True, output="did the thing")


def test_read_tools_never_ask():
    d = PermissionEngine().evaluate(_Recorder(risk=perm.READ))
    assert d.allowed and not d.needs_user


def test_money_asks_under_the_default_threshold():
    d = PermissionEngine().evaluate(_Recorder(risk=perm.MONEY))
    assert not d.allowed and d.needs_user and d.rule == "risk"


def test_external_does_not_ask_under_the_default_threshold():
    """The default is `ask above external`, which is what reproduces the
    behaviour corparius had before risk classes. An upgrade that suddenly
    queued every cold email would be a regression dressed as a feature."""
    assert PermissionEngine().evaluate(_Recorder(risk=perm.EXTERNAL)).allowed


def test_tightening_the_threshold_gates_external():
    engine = PermissionEngine(ask_above=perm.READ)
    assert engine.evaluate(_Recorder(risk=perm.EXTERNAL)).needs_user


def test_auto_mode_still_obeys_a_tool_gated_by_name():
    engine = PermissionEngine(["thing"], mode=perm.AUTO)
    assert engine.evaluate(_Recorder(name="thing", risk=perm.READ)).needs_user


def test_auto_mode_allows_everything_else():
    assert PermissionEngine(mode=perm.AUTO).evaluate(_Recorder(risk=perm.MONEY)).allowed


def test_discuss_mode_refuses_rather_than_queues():
    """A dry run must not leave a pile of approvals behind: the operator asked
    what the roster would do, not to be asked about it."""
    d = PermissionEngine(mode=perm.DISCUSS).evaluate(_Recorder(risk=perm.MONEY))
    assert not d.allowed and not d.needs_user


def test_discuss_mode_still_runs_read_tools():
    assert PermissionEngine(mode=perm.DISCUSS).evaluate(_Recorder(risk=perm.READ)).allowed


def test_auto_allow_is_ignored_outside_custom_mode():
    engine = PermissionEngine(mode=perm.INTERACTIVE, auto_allow=["thing"], ask_above=perm.READ)
    assert engine.evaluate(_Recorder(name="thing", risk=perm.MONEY)).needs_user


def test_auto_allow_applies_in_custom_mode():
    engine = PermissionEngine(mode=perm.CUSTOM, auto_allow=["thing"], ask_above=perm.READ)
    d = engine.evaluate(_Recorder(name="thing", risk=perm.MONEY))
    assert d.allowed and d.rule == "auto_allow"


def test_auto_allow_cannot_reach_a_tool_gated_by_name():
    engine = PermissionEngine(["thing"], mode=perm.CUSTOM, auto_allow=["thing"])
    assert engine.evaluate(_Recorder(name="thing")).rule == "hitl"


def test_a_standing_rule_lets_a_risky_tool_through(tmp_path):
    store = Store(str(tmp_path))
    store.add_rule("t", "thing", "always")
    engine = PermissionEngine(ask_above=perm.READ, store=store)
    d = engine.evaluate(_Recorder(name="thing", risk=perm.EXTERNAL), "t")
    assert d.allowed and d.rule == "rule:always"


def test_a_standing_rule_cannot_silence_a_tool_gated_by_name(tmp_path):
    """The one guarantee the product makes is that money and production ask.
    If a rule could override that, the guarantee would depend on the order the
    operator happened to click in."""
    store = Store(str(tmp_path))
    store.add_rule("t", "thing", "always")
    engine = PermissionEngine(["thing"], store=store)
    assert engine.evaluate(_Recorder(name="thing", risk=perm.MONEY), "t").needs_user


def test_a_standing_rule_is_scoped_to_one_company(tmp_path):
    store = Store(str(tmp_path))
    store.add_rule("t", "thing", "always")
    engine = PermissionEngine(ask_above=perm.READ, store=store)
    assert engine.evaluate(_Recorder(name="thing", risk=perm.EXTERNAL), "other").needs_user


def test_run_scoped_rules_are_cleared_and_always_rules_are_not(tmp_path):
    store = Store(str(tmp_path))
    store.add_rule("t", "for_now", "run")
    store.add_rule("t", "for_good", "always")
    assert store.clear_run_rules("t") == 1
    assert store.find_rule("t", "for_now") == ""
    assert store.find_rule("t", "for_good") == "always"


def test_an_unannotated_tool_is_treated_as_harmless():
    """Plugins predate risk classes and register tools through PluginAPI. A
    plugin tool must not be blocked for a field its author never heard of."""

    class Legacy:
        name = "legacy"
        hitl = False

    assert perm.risk_of(Legacy()) == perm.READ
    assert PermissionEngine().evaluate(Legacy()).allowed


def test_an_unknown_risk_string_falls_back_to_read():
    assert perm.risk_of(_Recorder(risk="catastrophic")) == perm.READ


@pytest.mark.parametrize(
    "name,risk",
    [
        ("send_financial_transaction", perm.MONEY),
        ("publish_production_code", perm.CODE),
        ("deploy_site", perm.EXTERNAL),
        ("build_sales_site", perm.WRITE_LOCAL),
        ("review_kpis", perm.READ),
    ],
)
def test_the_shipped_toolbox_is_annotated(name, risk):
    assert TOOLS[name].risk == risk


def test_the_shipped_defaults_gate_exactly_what_they_used_to(tmp_path):
    """Pinned deliberately. This is the assertion that fails if a later change
    to the default threshold or to a risk class quietly widens or narrows what
    an existing company has to approve."""
    from corparius.config.settings import Settings

    engine = PermissionEngine.from_settings(Settings(), {}, Store(str(tmp_path)))
    gated = {name for name, tool in TOOLS.items() if engine.evaluate(tool, "t").needs_user}
    assert gated == {"send_financial_transaction", "publish_production_code", "deploy_site"}


def test_the_gate_reports_a_refusal_as_a_recoverable_error(tmp_path):
    gate = ApprovalGate(Store(str(tmp_path)), PermissionEngine(mode=perm.DISCUSS))
    tool = _Recorder(risk=perm.MONEY)
    result = gate.execute("t", "finance", tool, None, "", {})
    assert tool.ran == 0 and result.denied and not result.pending
    assert result.output == BLOCKED_MESSAGE.format(reason="discuss mode: thing is money")
    assert gate.store.list_approvals("t", "pending") == []


def test_the_gate_still_accepts_a_bare_list_of_names(tmp_path):
    """Callers that only care about which tools are gated predate the engine."""
    gate = ApprovalGate(Store(str(tmp_path)), ["thing"])
    assert gate.requires_approval(_Recorder(name="thing")) is True


def test_a_decision_carries_its_motive():
    d = PermissionEngine().evaluate(_Recorder(name="pay", risk=perm.MONEY))
    assert isinstance(d, Decision)
    assert "pay is money" in d.reason and "external" in d.reason
