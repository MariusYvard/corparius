"""Where a drafted answer came from, kept next to the action it produced.

`structured.ask` has always returned `ok`, `fell_back`, `attempts`, `source` and `errors`.
Counted across the package before schema 18: **12 callers read `.data`, 3 read `.ok`, 1 reads
`.source`, 1 reads `.fell_back`, and none read `.errors` or `.attempts`.** `record_action` took
six columns, one of them a boolean, so once a turn ended none of it existed anywhere.

`_empty_draft`'s docstring already carried the bill: an operator read "Nothing usable drafted"
as a broken site generator while groq and cerebras were both answering 429, **365 026 tokens
in**. That helper was the fix, and it is *optional* — which is how it came to be "the fourth
caller to read only one field". NVIDIA's NOOA lists the answer as a property rather than a
helper: all model calls traced, automatically (docs/reverse-engineering/nooa.md).

So the last test in this file is the one that matters most. Four columns nothing reads would be
the same defect wearing the other face, and this project has a name for that too.
"""

from types import SimpleNamespace

import pytest

from corparius.kernel.records import Trace
from corparius.store import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path / "data"))
    yield s
    s.close()


class _Harness:
    """Whatever the harness returned. `Trace.of` is duck-typed because a rank-0 record may not
    import `structured`, and every test that fakes a result fakes a different shape."""

    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)


# --- reading a harness result -------------------------------------------------


def test_a_trace_carries_the_five_fields_that_were_being_dropped():
    got = Trace.of(_Harness(source="groq:llama", attempts=3, fell_back=True, errors=["429", "429"]))
    assert got.source == "groq:llama"
    assert got.attempts == 3
    assert got.fell_back is True
    assert got.errors == "429; 429"


def test_no_result_is_an_empty_trace_not_a_crash():
    """The paths that call no model — a skipped tool, a raised exception, a deterministic
    write — pass None and mean it."""
    assert Trace.of(None) == Trace()


def test_a_result_missing_fields_is_read_as_far_as_it_goes():
    """Duck-typed, so a fake or an older harness that carries three of the five still traces
    those three rather than raising in the middle of journalling a turn."""
    got = Trace.of(_Harness(source="ovh:x"))
    assert got.source == "ovh:x" and got.attempts == 0 and got.fell_back is False


def test_the_error_text_is_bounded():
    """It goes in a row that an operator reads in a list. A provider that returns a page of
    HTML on an error would otherwise put the page in the journal."""
    got = Trace.of(_Harness(errors=["x" * 1000]))
    assert len(got.errors) == 400


# --- the round trip -----------------------------------------------------------


def test_the_trace_survives_the_turn(store):
    """The whole point: after the action is journalled, which provider answered is still there.
    Before this, `record_action` was handed `result.ok` and the rest was gone."""
    store.record_action(
        "acme", "ceo", "decide", {}, "done", True, Trace("cerebras:gpt-oss", 2, True, "429")
    )
    row = store.recent_actions("acme")[0]
    assert row["source"] == "cerebras:gpt-oss"
    assert row["attempts"] == 2
    assert row["fell_back"] == 1
    assert row["errors"] == "429"


def test_a_turn_that_called_no_model_leaves_it_null(store):
    """NULL is a third state and the columns keep it: **not recorded** is not the same answer
    as "no provider answered". Same reasoning as `vision_ok` in migration 16 — collapsing the
    two would make the console tell an operator their history says something it does not."""
    store.record_action("acme", "ceo", "produce_mockup", {}, "written", True)
    row = store.recent_actions("acme")[0]
    assert row["source"] is None
    assert row["fell_back"] is None


# --- the aggregate ------------------------------------------------------------


def test_routing_health_says_who_answered(store):
    for source in ("groq:a", "groq:a", "cerebras:b"):
        store.record_action("acme", "ceo", "decide", {}, "o", True, Trace(source, 1, False, ""))
    health = store.routing_health("acme")
    assert health["drafted"] == 3
    assert health["answered_by"] == {"groq:a": 2, "cerebras:b": 1}
    assert list(health["answered_by"])[0] == "groq:a", "most frequent first"


def test_turns_that_called_no_model_are_excluded_not_counted_as_failures(store):
    """A quiet day would otherwise look like an outage."""
    store.record_action("acme", "ceo", "skipped", {}, "nothing to do", True)
    store.record_action("acme", "ceo", "decide", {}, "o", True, Trace("groq:a", 1, False, ""))
    health = store.routing_health("acme")
    assert health["drafted"] == 1 and health["fell_back"] == 0


def test_repair_rounds_are_counted_as_retries_not_as_attempts(store):
    """One attempt is a call that worked. `retries` is what a provider cost above the first
    try, which is the number that means something to a token budget."""
    store.record_action("acme", "ceo", "decide", {}, "o", True, Trace("groq:a", 1, False, ""))
    store.record_action("acme", "ceo", "decide", {}, "o", True, Trace("groq:a", 4, False, ""))
    assert store.routing_health("acme")["retries"] == 3


# --- and something reads it ---------------------------------------------------


def test_the_journal_is_actually_read_by_a_diagnostic(store, tmp_path, monkeypatch):
    """The mirror test, and the reason this feature is not the defect it was written to fix.

    Four columns nothing consumes would be "produced and never consumed" with a migration
    docstring attached. `_check_routing_history` is the consumer, and unlike every other
    provider check in the doctor it reads what *happened* rather than what would.
    """
    from corparius.config.settings import Settings
    from corparius.doctor import _check_routing_history
    from corparius.kernel import paths

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    folder = paths.companies_dir() / "acme"
    folder.mkdir(parents=True)
    (folder / "company.yaml").write_text("name: Acme\n", encoding="utf-8")
    for _ in range(4):
        store.record_action("acme", "ceo", "decide", {}, "o", True, Trace("groq:a", 1, True, "429"))
    level, name, message = _check_routing_history(Settings(), store)
    assert name == "history"
    assert level == "warn", "four of four falling back is a tier pointed at the wrong thing"
    assert "groq:a" in message and "4 of 4 fell back" in message


def test_a_chain_that_mostly_holds_is_not_a_warning(store, tmp_path, monkeypatch):
    """A fall-back is the product working — the chain exists to be walked. Only a majority
    means the tier a role asks for is not the one answering."""
    from corparius.config.settings import Settings
    from corparius.doctor import _check_routing_history
    from corparius.kernel import paths

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    folder = paths.companies_dir() / "acme"
    folder.mkdir(parents=True)
    (folder / "company.yaml").write_text("name: Acme\n", encoding="utf-8")
    for i in range(5):
        store.record_action("acme", "ceo", "decide", {}, "o", True, Trace("groq:a", 1, i == 0, ""))
    level, _, message = _check_routing_history(Settings(), store)
    assert level == "ok" and "1 fell back" in message


def test_a_store_from_before_schema_18_says_so_rather_than_blaming_providers(store):
    """No drafted turn with a source is not a verdict about the providers. On an upgraded store
    every existing row is NULL, and reporting that as "nothing answers" would send an operator
    to fix something that is not broken."""
    from corparius.config.settings import Settings
    from corparius.doctor import _check_routing_history

    level, _, message = _check_routing_history(Settings(), store)
    assert level == "ok" and "no drafted turn recorded yet" in message


def test_the_executor_is_what_puts_the_trace_in_the_journal(tmp_path):
    """The gap the rest of this file left open, and it was real: every test above records a
    trace *itself*, so `Executor._invoke` could stop passing one and all of them would still
    pass. Proved by replacing `Trace.of(ctx.structured)` with `None` — nothing failed.

    So this drives a real drafting turn through the executor and reads the row it wrote. It is
    the only test here that covers the wiring rather than the parts.
    """
    from corparius.agents import Executor
    from corparius.config.permissions import PermissionEngine
    from corparius.hitl import ApprovalGate
    from corparius.kernel.records import AgentRole, LLMResult, Usage
    from corparius.roster import ROSTER
    from corparius.safety import CircuitBreaker, TokenBudget

    store = Store(str(tmp_path / "e2e"))

    class _Router:
        def generate(self, messages, *a, **kw):
            return LLMResult(
                text='{"headline": "h", "body": "b"}',
                usage=Usage(2, 2, 0.0),
                model="llama-3.3",
                provider="groq",
            )

        def embed(self, text):
            return [0.0, 1.0]

    class _Settings:
        loop_similarity_threshold = 0.95
        max_identical_tool_calls = 99

    ctx = SimpleNamespace(
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

    drafted = [r for r in store.recent_actions("t") if r["source"]]
    assert drafted, "a real drafting turn journalled no source at all"
    assert "groq" in drafted[0]["source"], f"got {drafted[0]['source']!r}"
    assert store.routing_health("t")["drafted"] >= 1
    store.close()
