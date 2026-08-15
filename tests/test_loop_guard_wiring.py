"""The three places a turn is allowed to stop itself, tested for themselves.

`LoopGuard` already has its own tests in `test_safety.py`: given embeddings it says "too similar",
given a repeated call it says "seen this". What was never tested directly is the other half, the
three lines in `agents.Executor._invoke` that **act** on that answer and halt the turn.

They were covered, and only by accident. A full turn on a real role happened to draft enough times
for the guard to trip; changing which roles run per tick made those turns stop doing that, and the
per-file coverage ratchet caught three pairs of lines going dark. Nothing about the guard broke, and
that is the point: incidental coverage of a safety mechanism reports green until whatever
incidentally reached it moves, and then it reports nothing at all and no test fails.

Two things this had to be measured to get right, both of which the first draft of this file got
wrong:

  * **the window is three, not two.** `observe_output` keeps a deque of three and answers only when
    it is full and every consecutive pair is similar past the threshold. Two identical drafts are
    not a stutter, which is correct (a tool naming the same sections twice is a tool working) and
    means a test that drafts twice reaches the guard and learns nothing.
  * **the guard fires after the draft, not before it.** The tokens for the stuttering answer are
    already spent when it is caught, necessarily: you cannot know a paragraph repeats itself without
    generating it. So what the guard saves is the *effect* and everything after it, and that is what
    these tests assert. Counting router calls would assert the opposite of how it works.

And the schema branch and the prose branch are separate call sites, so `draft_social_post` (schema)
and `draft_design_brief` (no schema) both appear below. One rule, two paths, and a test that used
only one would leave the other exactly as unprotected as it was.
"""

import types

import pytest

from corparius.agents import Executor
from corparius.config.permissions import PermissionEngine
from corparius.hitl import ApprovalGate
from corparius.kernel.records import AgentRole, LLMResult, Usage
from corparius.roster import ROSTER, AgentSpec
from corparius.safety import CircuitBreaker, TokenBudget
from corparius.store import Store

# The guard needs its window full before it will answer, so a playbook has to reach the same tool
# this many times for the stutter branch to be reachable at all.
WINDOW = 3


class _Router:
    """Answers every call the same way, which is the condition the guards exist to notice."""

    def __init__(self):
        self.calls = 0

    def generate(self, messages, *a, **kw):
        self.calls += 1
        return LLMResult(
            text='{"headline": "h", "body": "b"}', usage=Usage(2, 2), model="m", provider="test"
        )

    def embed(self, text):
        return [1.0, 0.0]


class _Settings:
    def __init__(self, similarity=0.95, identical=99):
        self.loop_similarity_threshold = similarity
        self.max_identical_tool_calls = identical


def _bench(tmp_path, settings):
    store = Store(str(tmp_path))
    ctx = types.SimpleNamespace(
        company={"slug": "t", "name": "T", "offer": {}},
        tick=0,
        budget=TokenBudget(1_000_000),
        breaker=CircuitBreaker(1_000_000),
        data_path=str(tmp_path),
        memory=[],
        leads=[],
        store=store,
        role="",
        structured=None,
    )
    gate = ApprovalGate(store, PermissionEngine(store=store))
    router = _Router()
    return router, store, ctx, Executor(router, gate, store, settings)


def _repeating(role, tool, times):
    """A spec whose playbook asks for one tool several times over. The shortest route to a repeated
    call inside a single turn, and not a contrived one: a playbook is a list of names, and an agent
    that has been told to write a rule down and then writes the same rule down is this shape."""
    base = ROSTER[role]
    return AgentSpec(
        role=base.role,
        cadence_hours=base.cadence_hours,
        difficulty=base.difficulty,
        system_prompt=base.system_prompt,
        playbook=[tool] * times,
    )


def _ran(store) -> int:
    """How many effects actually executed. `style_violation` rows are excluded because they are the
    charter's observation about a draft, not a tool that ran, and counting them would make this
    assertion depend on whether the fixture's prose happens to trip a style rule."""
    return store.db.execute(
        "select count(*) from actions where tool != ?", ("style_violation",)
    ).fetchone()[0]


# --- the stutter guard, at both of its call sites ---------------------------------


@pytest.mark.parametrize(
    ("role", "tool"),
    [
        (AgentRole.SOCIAL, "draft_social_post"),  # has a schema: the structured branch
        (AgentRole.DESIGN, "draft_design_brief"),  # no schema: the prose branch
    ],
)
def test_an_agent_that_keeps_saying_the_same_thing_is_stopped(tmp_path, role, tool):
    """Threshold at zero, so identical embeddings are unmistakably identical and the assertion is
    about the wiring rather than about cosine arithmetic.

    Asked for the tool one more time than the window holds. The guard answers on the last draft, so
    the effects that ran are the ones before it: the turn stops instead of going round again."""
    router, store, ctx, executor = _bench(tmp_path, _Settings(similarity=0.0))
    done = executor.run_turn("t", _repeating(role, tool, WINDOW + 1), ctx)

    assert router.calls == WINDOW, "the turn drafted again after the guard had stopped it"
    assert _ran(store) == WINDOW - 1, "the stuttering draft still reached its effect"
    assert len(done) == WINDOW - 1, f"work was recorded past the stop: {done}"


def test_the_same_call_repeated_is_stopped_before_it_runs(tmp_path):
    """The other guard, which does not need a window: one repeat past the limit is enough.

    The similarity threshold is left impossible so this cannot pass for the wrong reason. It has to
    be the call-identity check that fires, and unlike the stutter guard this one can stop the effect
    on the *first* repetition, because a call with identical parameters is knowable in advance."""
    router, store, ctx, executor = _bench(tmp_path, _Settings(similarity=1.1, identical=1))
    done = executor.run_turn("t", _repeating(AgentRole.SOCIAL, "draft_social_post", 3), ctx)

    assert _ran(store) == 1, "the repeated call ran anyway"
    assert len(done) == 1, f"work was recorded past the stop: {done}"
    assert router.calls == 2, "the turn kept drafting after the stop"


# --- the other end of the thread --------------------------------------------------


def test_a_permissive_guard_lets_the_whole_playbook_through(tmp_path):
    """Why the three above are not vacuous. With both guards set so they cannot fire, the same
    playbook runs to the end — so those tests are measuring the guards and not some unrelated reason
    a turn stops early."""
    router, store, ctx, executor = _bench(tmp_path, _Settings(similarity=1.1, identical=99))
    done = executor.run_turn(
        "t", _repeating(AgentRole.SOCIAL, "draft_social_post", WINDOW + 1), ctx
    )

    assert router.calls == WINDOW + 1
    assert _ran(store) == WINDOW + 1 and len(done) == WINDOW + 1


@pytest.mark.parametrize("settings", [_Settings(similarity=0.0), _Settings(identical=1)])
def test_a_guard_halts_a_turn_without_failing_it(tmp_path, settings):
    """The orchestrator calls `run_turn` in a loop over ten roles. A stop that propagated as an
    exception would take the rest of the day down with it, so a tripped guard returns the work done
    so far and nothing raises."""
    _router, _store, ctx, executor = _bench(tmp_path, settings)
    done = executor.run_turn("t", _repeating(AgentRole.SOCIAL, "draft_social_post", 5), ctx)
    assert isinstance(done, list)
