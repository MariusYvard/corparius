"""The safety firewall must actually stop a runaway agent, not just look like it."""
import pytest

from app.safety import (
    TokenBudget, BudgetExceeded, LoopGuard, CircuitBreaker, cosine, hash_embed,
)


def test_budget_raises_once_ceiling_is_reached():
    b = TokenBudget(100)
    b.record_usage(60, 30)   # 90 used
    b.check_before()         # still under, must not raise
    b.record_usage(5, 5)     # 100 used
    with pytest.raises(BudgetExceeded):
        b.check_before()


def test_budget_reports_remaining():
    b = TokenBudget(100)
    b.record_usage(40, 10)
    assert b.remaining == 50


def test_cosine_of_identical_vectors_is_one():
    v = hash_embed("hello world")
    assert cosine(v, v) == pytest.approx(1.0)


def test_loop_guard_flags_semantic_stutter():
    g = LoopGuard(similarity_threshold=0.95, window=3)
    e = hash_embed("the same repeated output")
    assert g.observe_output(e) is False   # 1
    assert g.observe_output(e) is False   # 2
    assert g.observe_output(e) is True    # 3 identical -> loop


def test_loop_guard_flags_repeated_identical_tool_calls():
    g = LoopGuard(max_identical_calls=2)
    assert g.observe_tool_call("send", {"a": 1}) is False
    assert g.observe_tool_call("send", {"a": 1}) is False
    assert g.observe_tool_call("send", {"a": 1}) is True   # third > 2


def test_circuit_breaker_escalates_then_recovers():
    cb = CircuitBreaker(tokens_per_minute_limit=1000)
    assert cb.record(500, now=0.0) == CircuitBreaker.NORMAL
    assert cb.record(600, now=1.0) == CircuitBreaker.CONSERVATIVE   # 1100 > 1000
    assert cb.record(600, now=2.0) == CircuitBreaker.SAFE           # still hot
    # Old spend ages out of the 60s window -> back to normal.
    assert cb.record(10, now=120.0) == CircuitBreaker.NORMAL
