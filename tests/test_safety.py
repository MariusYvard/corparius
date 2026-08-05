"""The safety firewall must actually stop a runaway agent, not just look like it."""

import pytest

from corparius.kernel.vectors import hash_embed
from corparius.safety import BudgetExceeded, CircuitBreaker, LoopGuard, TokenBudget


def test_budget_raises_once_ceiling_is_reached():
    b = TokenBudget(100)
    b.record_usage(60, 30)  # 90 used
    b.check_before()  # still under, must not raise
    b.record_usage(5, 5)  # 100 used
    with pytest.raises(BudgetExceeded):
        b.check_before()


def test_budget_reports_remaining():
    b = TokenBudget(100)
    b.record_usage(40, 10)
    assert b.remaining == 50


def test_loop_guard_flags_semantic_stutter():
    g = LoopGuard(similarity_threshold=0.95, window=3)
    e = hash_embed("the same repeated output")
    assert g.observe_output(e) is False  # 1
    assert g.observe_output(e) is False  # 2
    assert g.observe_output(e) is True  # 3 identical -> loop


def test_loop_guard_flags_repeated_identical_tool_calls():
    g = LoopGuard(max_identical_calls=2)
    assert g.observe_tool_call("send", {"a": 1}) is False
    assert g.observe_tool_call("send", {"a": 1}) is False
    assert g.observe_tool_call("send", {"a": 1}) is True  # third > 2


def test_circuit_breaker_escalates_then_recovers():
    cb = CircuitBreaker(tokens_per_minute_limit=1000)
    assert cb.record(500, now=0.0) == CircuitBreaker.NORMAL
    assert cb.record(600, now=1.0) == CircuitBreaker.CONSERVATIVE  # 1100 > 1000
    assert cb.record(600, now=2.0) == CircuitBreaker.SAFE  # still hot
    # Old spend ages out of the 60s window -> back to normal.
    assert cb.record(10, now=120.0) == CircuitBreaker.NORMAL


def test_a_hot_breaker_cannot_talk_itself_down():
    """It used to. `SAFE if mode == CONSERVATIVE else CONSERVATIVE` flipped SAFE
    back to CONSERVATEUR on the very next call, so the mode a session ended a
    turn in depended on whether it had spent an odd or an even number of times,
    and a runaway day could spend its way out of the freeze it had earned.
    Adding one tool to a playbook was enough to move that parity."""
    cb = CircuitBreaker(tokens_per_minute_limit=1)
    modes = [cb.record(100, now=float(i)) for i in range(6)]
    assert modes[0] == CircuitBreaker.CONSERVATIVE
    assert set(modes[1:]) == {CircuitBreaker.SAFE}, f"the breaker de-escalated: {modes}"


def test_recovery_still_works_after_the_freeze_sticks():
    """Sticky while hot, not sticky forever: the rolling window is the whole
    point, and a breaker that never came back would turn one spike into a
    permanently dead company."""
    cb = CircuitBreaker(tokens_per_minute_limit=1000)
    cb.record(2000, now=0.0)
    assert cb.record(2000, now=1.0) == CircuitBreaker.SAFE
    assert cb.record(10, now=200.0) == CircuitBreaker.NORMAL
