"""Spend measured in money, not only in tokens.

OpenRouter reports what a call cost, in the same `usage` block corparius was
already parsing for token counts, on the endpoint it was already calling. It was
being read for tokens and thrown away for money — and money is what an operator
running a company budgets in.

The property that matters most here is the one that is easy to get wrong: a
provider that reports nothing must read as "not reported", never as "free".
"""

import types

from corparius.kernel.records import Usage
from corparius.llm import OpenAICompatProvider
from corparius.safety import BudgetExceeded, TokenBudget
from corparius.store import Store


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _reply(usage: dict):
    return {"choices": [{"message": {"content": "hi"}}], "usage": usage}


def _provider(monkeypatch, usage: dict) -> OpenAICompatProvider:
    from corparius import llm

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _Response(_reply(usage)))
    return OpenAICompatProvider("openrouter", "https://openrouter.ai/api/v1", "k")


def test_a_reported_cost_reaches_the_usage(monkeypatch):
    p = _provider(monkeypatch, {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.00042})
    res = p.generate([{"role": "user", "content": "x"}], "m")
    assert res.usage.input_tokens == 10 and res.usage.output_tokens == 5
    assert res.usage.cost == 0.00042


def test_a_provider_that_reports_nothing_stays_at_zero(monkeypatch):
    p = _provider(monkeypatch, {"prompt_tokens": 10, "completion_tokens": 5})
    assert _provider is not None
    assert p.generate([{"role": "user", "content": "x"}], "m").usage.cost == 0.0


def test_a_cost_sent_as_a_string_is_not_fatal(monkeypatch):
    """Providers send it as a JSON number or a decimal string depending on the
    day. A run must not die over which."""
    p = _provider(monkeypatch, {"prompt_tokens": 1, "completion_tokens": 1, "cost": "0.0009"})
    assert p.generate([{"role": "user", "content": "x"}], "m").usage.cost == 0.0009


def test_a_nonsense_cost_is_worth_nothing_not_a_crash(monkeypatch):
    p = _provider(monkeypatch, {"prompt_tokens": 1, "completion_tokens": 1, "cost": "n/a"})
    assert p.generate([{"role": "user", "content": "x"}], "m").usage.cost == 0.0


def test_a_negative_cost_is_floored(monkeypatch):
    p = _provider(monkeypatch, {"prompt_tokens": 1, "completion_tokens": 1, "cost": -3})
    assert p.generate([{"role": "user", "content": "x"}], "m").usage.cost == 0.0


def test_the_budget_accumulates_money_alongside_tokens():
    b = TokenBudget(1000)
    b.record_usage(10, 10, 0.5)
    b.record_usage(10, 10, 0.25)
    assert b.used == 40 and b.spent == 0.75


def test_no_cost_ceiling_by_default_changes_nothing():
    """A second way for a run to stop has to be asked for."""
    b = TokenBudget(1000)
    b.record_usage(1, 1, 9_999.0)
    b.check_before()  # must not raise


def test_a_cost_ceiling_stops_the_turn_when_crossed():
    b = TokenBudget(1_000_000, max_cost=1.0)
    b.record_usage(1, 1, 1.5)
    try:
        b.check_before()
    except BudgetExceeded as exc:
        assert "cost budget" in str(exc)
    else:
        raise AssertionError("the cost ceiling did not stop the turn")


def test_the_token_ceiling_still_applies_under_a_cost_ceiling():
    b = TokenBudget(10, max_cost=1000.0)
    b.record_usage(20, 0, 0.0)
    try:
        b.check_before()
    except BudgetExceeded as exc:
        assert "token budget" in str(exc)
    else:
        raise AssertionError("the token ceiling stopped applying")


def test_the_store_records_and_sums_cost(tmp_path):
    store = Store(str(tmp_path))
    store.record_usage("t", "ceo", 10, 5, 0.001)
    store.record_usage("t", "ceo", 10, 5, 0.002)
    store.record_usage("t", "social", 4, 2, 0.0)
    by_agent = {r["agent"]: r for r in store.spend_by_agent("t")}
    assert round(by_agent["ceo"]["cost"], 6) == 0.003
    assert by_agent["social"]["cost"] == 0.0


def test_a_run_with_no_reported_cost_is_not_called_free(tmp_path):
    """0.00 and "nobody told us" are different facts. The console decides what
    to print from this, so conflating them here would put "0.00 EUR" in front of
    an operator on a paid key."""
    store = Store(str(tmp_path))
    store.record_usage("t", "ceo", 10, 5)
    assert store.cost_reported("t") is False
    store.record_usage("t", "ceo", 10, 5, 0.001)
    assert store.cost_reported("t") is True


def test_cost_reported_is_scoped_to_one_company(tmp_path):
    store = Store(str(tmp_path))
    store.record_usage("a", "ceo", 1, 1, 0.5)
    assert store.cost_reported("b") is False


def test_usage_defaults_keep_every_existing_construction_valid():
    """Usage is built positionally in five places in llm.py. A field with a
    default is what keeps those calls, and every provider that reports no cost,
    working unchanged."""
    u = Usage(3, 4)
    assert u.total == 7 and u.cost == 0.0


def test_a_repair_round_is_billed_in_money_too(tmp_path, monkeypatch):
    """structured.ask may spend more than one call. Every one is already billed
    in tokens; the same has to be true of money, or a schema tool would under-
    report exactly when it costs most."""
    from corparius.agents import ROSTER, Executor
    from corparius.config.permissions import PermissionEngine
    from corparius.hitl import ApprovalGate
    from corparius.kernel.records import AgentRole
    from corparius.safety import CircuitBreaker

    store = Store(str(tmp_path))

    from corparius.kernel.records import LLMResult

    class _Router:
        def generate(self, messages, *a, **kw):
            return LLMResult(
                text='{"headline": "h", "body": "b"}',
                usage=Usage(2, 2, 0.01),
                model="m",
                provider="openrouter",
            )

        def embed(self, text):
            return [0.0, 1.0]

    class _Settings:
        loop_similarity_threshold = 0.95
        max_identical_tool_calls = 99

    ctx = types.SimpleNamespace(
        company={"slug": "t", "name": "T", "offer": {}},
        tick=0,
        budget=TokenBudget(1_000_000),
        breaker=CircuitBreaker(1_000_000),
        data_path=".",
        memory=[],
        leads=[],
        store=store,
        role="",
        structured=None,
    )
    gate = ApprovalGate(store, PermissionEngine(store=store))
    Executor(_Router(), gate, store, _Settings()).run_turn("t", ROSTER[AgentRole.SOCIAL], ctx)
    assert ctx.budget.spent > 0, "a drafting turn recorded no money"
    assert store.cost_reported("t") is True
