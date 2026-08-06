"""An unanswered approval must not idle the company.

Before this, a held tool broke the agent's turn: one unanswered question about a
payment stopped the same agent from doing the nine other things in its playbook,
and the backlog task behind it went back to `approved` only to be claimed again
next turn and re-file the same request. So the company spent its budget asking
the same question and did nothing else until a human came back.

The contract now: a guard tripping halts the turn, a human being asked does not.
"""

import types

from corparius.agents import ROSTER, Executor
from corparius.config.permissions import MONEY, PermissionEngine
from corparius.hitl import ApprovalGate
from corparius.kernel.records import AgentRole, ToolResult
from corparius.safety import CircuitBreaker, TokenBudget
from corparius.store import Store
from corparius.tools import TOOLS, Tool


class _Router:
    def generate(self, messages, **kw):
        return types.SimpleNamespace(
            text="draft",
            usage=types.SimpleNamespace(input_tokens=1, output_tokens=1, total=2, cost=0.0),
        )

    def embed(self, text):
        return [0.0, 1.0]


def _ctx(store, company="t"):
    return types.SimpleNamespace(
        company={"slug": company, "name": "T", "offer": {}},
        tick=0,
        budget=TokenBudget(100000),
        breaker=CircuitBreaker(100000),
        data_path=".",
        memory=[],
        leads=[],
        store=store,
        role="",
        structured=None,
    )


def _executor(store, settings=None):
    gate = ApprovalGate(store, PermissionEngine(["send_financial_transaction"], store=store))
    return Executor(_Router(), gate, store, settings or _Settings())


class _Settings:
    loop_similarity_threshold = 0.95
    max_identical_tool_calls = 2


def test_a_held_tool_does_not_stop_the_rest_of_the_playbook(tmp_path):
    """Finance's playbook is reconcile_stripe then send_financial_transaction.
    Order matters here: put the gated one first and the old code never reached
    the second."""
    store = Store(str(tmp_path))
    spec = ROSTER[AgentRole.FINANCE]
    held_first = type(spec)(
        spec.role,
        spec.cadence_hours,
        spec.difficulty,
        spec.system_prompt,
        ["send_financial_transaction", "reconcile_stripe"],
    )
    done = _executor(store).run_turn("t", held_first, _ctx(store))
    assert any("send_financial_transaction" in line for line in done)
    assert any("reconcile_stripe" in line for line in done), (
        "the agent stopped at the approval instead of carrying on"
    )


def test_a_guard_still_halts_the_turn(tmp_path):
    """The counterpart. Relaxing the approval stop must not relax the budget
    stop: the firewall is the reason the product is safe to leave running."""
    store = Store(str(tmp_path))
    ctx = _ctx(store)
    ctx.budget = TokenBudget(0)
    done = _executor(store).run_turn("t", ROSTER[AgentRole.FINANCE], ctx)
    assert done == []


def test_a_blocked_task_is_parked_not_returned_to_the_queue(tmp_path):
    store = Store(str(tmp_path))
    tid = store.add_task(
        "t", "Pay the invoice", "finance", 2, "approved", "ceo", tool="send_financial_transaction"
    )
    _executor(store).run_turn("t", ROSTER[AgentRole.FINANCE], _ctx(store))
    task = next(x for x in store.list_tasks("t") if x["id"] == tid)
    assert task["status"] == "waiting"
    assert task["note"].startswith("approval:")
    assert store.claim_next_task("t", "finance") is None, "a parked task must not be re-claimed"


def test_a_parked_task_does_not_re_ask_every_turn(tmp_path):
    """The failure this prevents is a budget leak: re-drafting a request the
    operator is already looking at costs a model call and produces a duplicate."""
    store = Store(str(tmp_path))
    store.add_task("t", "Pay", "finance", 2, "approved", "ceo", tool="send_financial_transaction")
    ex = _executor(store)
    for _ in range(4):
        ex.run_turn("t", ROSTER[AgentRole.FINANCE], _ctx(store))
    assert len(store.list_approvals("t", "pending")) == 1


def test_approving_puts_the_task_back_in_the_queue(tmp_path):
    store = Store(str(tmp_path))
    tid = store.add_task(
        "t", "Pay", "finance", 2, "approved", "ceo", tool="send_financial_transaction"
    )
    _executor(store).run_turn("t", ROSTER[AgentRole.FINANCE], _ctx(store))
    store.set_approval_status(store.list_approvals("t")[0]["id"], "approved")
    assert store.release_waiting_tasks("t") == {"released": 1, "refused": 0}
    assert store.claim_next_task("t", "finance")["id"] == tid


def test_rejecting_closes_the_task_rather_than_leaving_it_hanging(tmp_path):
    store = Store(str(tmp_path))
    store.add_task("t", "Pay", "finance", 2, "approved", "ceo", tool="send_financial_transaction")
    _executor(store).run_turn("t", ROSTER[AgentRole.FINANCE], _ctx(store))
    store.set_approval_status(store.list_approvals("t")[0]["id"], "rejected")
    assert store.release_waiting_tasks("t") == {"released": 0, "refused": 1}
    assert store.list_tasks("t", "rejected")


def test_an_undecided_approval_leaves_the_task_parked(tmp_path):
    store = Store(str(tmp_path))
    store.add_task("t", "Pay", "finance", 2, "approved", "ceo", tool="send_financial_transaction")
    _executor(store).run_turn("t", ROSTER[AgentRole.FINANCE], _ctx(store))
    assert store.release_waiting_tasks("t") == {"released": 0, "refused": 0}
    assert store.list_tasks("t", "waiting")


def test_blocked_work_is_reported_apart_from_wip(tmp_path):
    """Counted, so the board does not flatter itself; but not charged against
    the pull limit, or four unanswered questions would stop the company from
    starting anything else."""
    store = Store(str(tmp_path))
    store.add_task("t", "Pay", "finance", 2, "approved", "ceo", tool="send_financial_transaction")
    _executor(store).run_turn("t", ROSTER[AgentRole.FINANCE], _ctx(store))
    assert store.flow_metrics("t")["blocked"] == 1
    assert store.flow_metrics("t")["wip"] == 0
    assert store.wip_count("t", "finance") == 0


def test_a_second_tool_on_the_same_gate_is_skipped_without_a_model_call(tmp_path, monkeypatch):
    """A drafting tool would mint a fresh approval id per draft, so without the
    pre-draft check a tightened threshold would pile up one request per turn."""
    store = Store(str(tmp_path))
    calls = []
    router = _Router()
    original = router.generate
    monkeypatch.setattr(
        router, "generate", lambda *a, **k: (calls.append(1), original(*a, **k))[1], raising=False
    )
    tool = Tool(
        "drafty",
        "d",
        risk=MONEY,
        needs_draft=True,
        prompt=lambda c: "x",
        effect=lambda c, d: ToolResult(ok=True, output="done"),
    )
    monkeypatch.setitem(TOOLS, "drafty", tool)
    spec = ROSTER[AgentRole.FINANCE]
    only_drafty = type(spec)(
        spec.role, spec.cadence_hours, spec.difficulty, spec.system_prompt, ["drafty"]
    )
    gate = ApprovalGate(store, PermissionEngine(store=store))
    ex = Executor(router, gate, store, _Settings())
    for _ in range(3):
        ex.run_turn("t", only_drafty, _ctx(store))
    assert len(store.list_approvals("t", "pending")) == 1
    assert len(calls) == 1, "the agent kept re-drafting a request already on the operator's desk"
