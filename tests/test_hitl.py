"""The approval gate is the only thing standing between an agent and the
operator's money. It had no direct test: coverage came through a full run, which
exercises the pending path and nothing else.

The rejection path in particular is untested territory that matters — a rejected
tool must come back as a recoverable error the agent can carry on from, not as a
silent success or a crash.
"""

from app.hitl import REJECTION_MESSAGE, ApprovalGate, _approval_id
from app.models import ToolResult
from app.store import Store
from app.tools import TOOLS


class _Recorder:
    """A tool whose only job is to say whether it was allowed to run."""

    def __init__(self, name="paid_thing", hitl=False):
        self.name = name
        self.hitl = hitl
        self.ran = 0

    def run(self, ctx, draft=""):
        self.ran += 1
        return ToolResult(ok=True, output="did the thing")


def _gate(tmp_path, hitl_tools=()):
    return ApprovalGate(Store(str(tmp_path / "data")), hitl_tools)


def test_ungated_tool_runs_immediately(tmp_path):
    gate = _gate(tmp_path)
    tool = _Recorder()
    result = gate.execute("t", "finance", tool, None, "", {})
    assert result.ok and tool.ran == 1


def test_gated_tool_is_held_and_records_an_approval(tmp_path):
    gate = _gate(tmp_path)
    tool = _Recorder(hitl=True)
    result = gate.execute("t", "finance", tool, None, "", {"amount": 12})
    assert tool.ran == 0, "a gated tool must not run before a human says so"
    assert result.pending is True and result.ok is False
    pending = gate.store.list_approvals("t", "pending")
    assert len(pending) == 1 and pending[0]["tool"] == "paid_thing"


def test_a_tool_named_in_hitl_tools_is_gated_even_when_not_flagged(tmp_path):
    """company.yaml can widen the gate; that per-company list is the operator's
    lever and must outrank the tool's own default."""
    gate = _gate(tmp_path, hitl_tools=["paid_thing"])
    tool = _Recorder(hitl=False)
    assert gate.execute("t", "finance", tool, None, "", {}).pending is True
    assert tool.ran == 0


def test_approval_lets_the_tool_run(tmp_path):
    gate = _gate(tmp_path)
    tool = _Recorder(hitl=True)
    gate.execute("t", "finance", tool, None, "", {"amount": 12})
    gate.store.set_approval_status(gate.store.list_approvals("t")[0]["id"], "approved")
    result = gate.execute("t", "finance", tool, None, "", {"amount": 12})
    assert result.ok and tool.ran == 1


def test_rejection_comes_back_as_a_recoverable_error(tmp_path):
    gate = _gate(tmp_path)
    tool = _Recorder(hitl=True)
    gate.execute("t", "finance", tool, None, "", {"amount": 12})
    gate.store.set_approval_status(gate.store.list_approvals("t")[0]["id"], "rejected")
    result = gate.execute("t", "finance", tool, None, "", {"amount": 12})
    assert tool.ran == 0
    assert result.denied is True and result.ok is False
    assert result.output == REJECTION_MESSAGE


def test_approval_does_not_carry_to_different_parameters(tmp_path):
    """An approved 12 EUR payment must not authorise a 12000 EUR one. The store
    looks approvals up by exact parameters, so this is the property that keeps a
    single click from becoming a standing authorisation."""
    gate = _gate(tmp_path)
    tool = _Recorder(hitl=True)
    gate.execute("t", "finance", tool, None, "", {"amount": 12})
    gate.store.set_approval_status(gate.store.list_approvals("t")[0]["id"], "approved")
    assert gate.execute("t", "finance", tool, None, "", {"amount": 12000}).pending is True
    assert tool.ran == 0


def test_approval_id_ignores_parameter_order():
    """_approval_id sorts parameters before hashing. Without that, the same
    request built from a differently-ordered dict would mint a second approval
    and ask the operator to authorise work they already authorised."""
    a = _approval_id("t", "pay", {"amount": 12, "to": "acme"})
    b = _approval_id("t", "pay", {"to": "acme", "amount": 12})
    assert a == b


def test_approval_id_separates_companies_and_tools():
    base = _approval_id("t", "pay", {"amount": 12})
    assert base != _approval_id("other", "pay", {"amount": 12})
    assert base != _approval_id("t", "refund", {"amount": 12})


def test_the_shipped_money_tool_is_gated(tmp_path):
    """Ties the gate to the real toolbox rather than a stand-in."""
    gate = _gate(tmp_path)
    assert gate.requires_approval(TOOLS["send_financial_transaction"]) is True
    assert gate.requires_approval(TOOLS["review_kpis"]) is False
