"""A per-role token purse, so a cheap frequent role cannot starve an expensive rare one.

The operator asked for it in plain terms: the agent that builds the site should have
a much higher ceiling. The reason it needs one is arithmetic. Design runs once every
24 ticks and its turn is the most expensive in the company — it reads four real
pages and reviews them. Support runs every 3 ticks. Measured on one real week:
830 069 tokens spent against a `session_tokens` of 120 000, with support's turns
landing first. One shared pool means the frequent role spends it and the rare one
arrives at a closed till.
"""

import pytest

from corparius.company import validate
from corparius.safety import BudgetExceeded, TokenBudget


def _cfg(**budgets):
    raw = {
        "slug": "c",
        "name": "C",
        "offer": {"product": "p"},
        "icp": {"segment": "s", "pains": ["x"]},
        "budgets": {"session_tokens": 120_000, **budgets},
    }
    return validate(raw)


# --- the arithmetic -----------------------------------------------------------


def test_a_reserve_is_a_purse_in_addition_to_the_shared_budget():
    """The first version subtracted, and a 400 000 reserve against a 120 000 session
    left the shared pool at zero — every other role starved instantly, which is the
    opposite of what asking for one role to have more can possibly mean. Measured
    the moment it ran."""
    b = TokenBudget(120_000, reserves={"design": 400_000})
    assert b.shared_max == 120_000, "the other roles must keep what they had"
    assert b.reserves["design"] == 400_000
    assert b.max_tokens == 520_000, "and the total is what actually stops a runaway"


def test_a_frequent_role_cannot_touch_the_reserve():
    b = TokenBudget(120_000, reserves={"design": 400_000})
    b.record_usage(119_999, 0, 0.0, "support")
    with pytest.raises(BudgetExceeded) as exc:
        b.check_before(1, "support")
    assert "token budget" in str(exc.value)
    b.check_before(1, "design")  # untouched
    assert b.remaining_for("design") == 400_000


def test_a_reserved_role_is_stopped_by_its_own_ceiling():
    b = TokenBudget(120_000, reserves={"design": 10_000})
    b.record_usage(10_000, 0, 0.0, "design")
    with pytest.raises(BudgetExceeded) as exc:
        b.check_before(1, "design")
    assert "design budget" in str(exc.value), "the message must name whose ceiling it is"


def test_a_reserved_role_spending_does_not_charge_the_shared_pool():
    """Otherwise its spending would count twice and the reserve would be a fiction."""
    b = TokenBudget(120_000, reserves={"design": 400_000})
    b.record_usage(300_000, 0, 0.0, "design")
    assert b.remaining_for("support") == 120_000


def test_the_total_still_stops_a_runaway():
    b = TokenBudget(1_000, reserves={"design": 1_000})
    b.record_usage(2_000, 0, 0.0, "design")
    with pytest.raises(BudgetExceeded) as exc:
        b.check_before(1, "design")
    assert "token budget spent: 2000/2000" in str(exc.value)


def test_no_reserves_behaves_exactly_as_before():
    """Every company that has not asked for this must be unchanged."""
    b = TokenBudget(1_000)
    assert b.max_tokens == 1_000 and b.shared_max == 1_000 and b.reserves == {}
    b.record_usage(999, 0)
    with pytest.raises(BudgetExceeded):
        b.check_before(1)
    b2 = TokenBudget(1_000)
    b2.record_usage(999, 0, 0.0, "design")
    with pytest.raises(BudgetExceeded):
        b2.check_before(1, "design")


def test_a_zero_or_negative_reserve_is_no_reserve():
    b = TokenBudget(1_000, reserves={"design": 0, "support": -5})
    assert b.reserves == {} and b.max_tokens == 1_000


# --- what company.yaml accepts ------------------------------------------------


def test_a_role_reserve_survives_validation():
    cfg, errors, warnings = _cfg(role_tokens={"design": 400_000})
    assert not errors
    assert cfg["budgets"]["role_tokens"] == {"design": 400_000}
    assert any("520000 tokens in total" in w for w in warnings), warnings


def test_nothing_is_emitted_when_nothing_is_reserved():
    """Like cost_budget: writing an empty mapping into every company would pin them
    all to whatever this file meant today."""
    cfg, _, _ = _cfg()
    assert "role_tokens" not in cfg["budgets"]


def test_a_name_that_is_not_a_role_is_named_not_swallowed():
    cfg, _, warnings = _cfg(role_tokens={"webmaster": 100})
    assert cfg["budgets"].get("role_tokens") is None
    assert any("webmaster is not a role" in w for w in warnings), warnings


def test_a_reserve_for_a_disabled_agent_is_flagged():
    raw = {
        "slug": "c",
        "name": "C",
        "offer": {"product": "p"},
        "icp": {"segment": "s", "pains": ["x"]},
        "agents": {"design": False},
        "budgets": {"session_tokens": 120_000, "role_tokens": {"design": 1_000}},
    }
    _, _, warnings = validate(raw)
    assert any("that agent is off" in w for w in warnings), warnings


def test_a_reserve_is_clamped_like_the_session_budget():
    from corparius.company import TOKENS_MAX

    cfg, _, warnings = _cfg(role_tokens={"design": TOKENS_MAX * 10})
    assert cfg["budgets"]["role_tokens"]["design"] == TOKENS_MAX
    assert any("clamped" in w for w in warnings)


def test_a_mapping_is_required():
    cfg, _, warnings = _cfg(role_tokens=["design"])
    assert "role_tokens" not in cfg["budgets"]
    assert any("not a mapping" in w for w in warnings)


# --- and the wire from the config to the agent --------------------------------
#
# Behaviour, not source text. An earlier version of these two sliced
# `inspect.getsource` and broke on a reformat, which tests nothing about whether
# the reserve reaches the ledger.


def test_the_orchestrator_hands_the_reserves_to_the_ledger(tmp_path, monkeypatch):
    """A reserve nothing reads is a reserve that does nothing."""
    from corparius import orchestrator
    from corparius.config import Settings
    from corparius.store import Store

    seen: list = []
    real = orchestrator.TokenBudget

    def capture(max_tokens, max_cost=0.0, reserves=None):
        seen.append(reserves)
        return real(max_tokens, max_cost, reserves)

    monkeypatch.setattr(orchestrator, "TokenBudget", capture)
    s = Settings()
    s.llm_mock = True
    s.data_path = str(tmp_path)
    store = Store(s.data_path)
    try:
        orchestrator.Runtime(s, store).run(
            {
                "slug": "t",
                "name": "T",
                "offer": {"product": "p"},
                "icp": {"segment": "s", "pains": ["x"]},
                "agents": {
                    "design": True,
                    "ceo": False,
                    "social": False,
                    "support": False,
                    "outreach": False,
                    "finance": False,
                    "strategy": False,
                    "competitor": False,
                    "ads": False,
                    "coder": False,
                },
                "budgets": {"session_tokens": 50_000, "role_tokens": {"design": 400_000}},
                "hitl_tools": [],
            },
            ticks=1,
        )
    finally:
        store.close()
    assert seen and seen[0] == {"design": 400_000}, f"the reserve never arrived: {seen}"


def test_the_agent_checks_and_records_against_its_own_ledger():
    """Both ends. Checking the reserve while charging the shared pool would let a
    role spend its purse twice over."""
    from corparius.agents import ROSTER, Executor
    from corparius.kernel.records import AgentRole

    calls: list = []

    class Ledger:
        def check_before(self, estimate=0, role=""):
            calls.append(("check", role))

        def record_usage(self, i, o, cost=0.0, role=""):
            calls.append(("record", role))

    class Breaker:
        def record(self, total):
            pass

    class Ctx:
        budget = Ledger()
        breaker = Breaker()
        company = {"slug": "t", "name": "T", "offer": {"product": "p"}}
        structured = None
        skills = None
        memory: list = []
        memory_top_k = 0
        documents = ""
        images: list = []
        images_skipped: list = []
        role = "design"

    class Router:
        def generate(self, messages, difficulty=None, model=None, max_tokens=512, images=None):
            from corparius.kernel.records import LLMResult, Usage

            return LLMResult("a headline", Usage(3, 4), "m", "mock")

        def embed(self, text):
            return [0.0]

        def resolve_model(self, difficulty, model=None):
            return model or "mock:m"

    class Store:
        def record_usage(self, *a, **k):
            pass

        def record_action(self, *a, **k):
            pass

    class Gate:
        """The two methods the executor calls on it. Stubbed rather than built,
        because what is under test is which ledger the spend lands in."""

        def decide(self, tool, company):
            from corparius.permissions import Decision

            return Decision(allowed=True, needs_user=False, reason="test", rule="test")

        def execute(self, company, role, tool, ctx, draft, params):
            return tool.run(ctx, draft)

    agent = Executor.__new__(Executor)
    agent.router = Router()
    agent.store = Store()
    agent.gate = Gate()
    from corparius.safety import LoopGuard

    agent._invoke("t", ROSTER[AgentRole.DESIGN], Ctx(), "draft_design_brief", LoopGuard())
    assert ("check", "design") in calls, f"the check did not name the role: {calls}"
    assert ("record", "design") in calls, f"the spend was not booked to the role: {calls}"
