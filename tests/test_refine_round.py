"""The executor's second round: what it costs, what bounds it, and who owns it.

A tool effect reaches `company`, `data_path`, `leads`, `store` and `structured` — deliberately **not**
a model handle, because the executor owns routing, the token budget, the breaker, the usage log and
the per-role model pin. That is why `review_generated_site` was built as a second tool on another
role rather than as a loop inside the first one, and why a tool that wants to read something before
answering could not simply ask.

`Behaviour.refine` is that capability, granted by the executor and bounded by it. Given the first
structured answer it returns text to put in front of the model for **one** more call, or "" when one
round was enough.

Four properties, and the last two are the ones that make it safe rather than merely useful:

  * a tool without `refine` is unaffected — that is every tool that existed before this;
  * the extra round actually reaches the model, with the same schema and the same pin;
  * **both calls are billed.** A second call that missed `ctx.budget` would be spend the operator's
    ceiling never sees, which is the failure mode this project has already paid 365 026 tokens for;
  * **exactly one.** Not a loop. PageIndex's agentic retrieval spends 2–4 calls per question and an
    open loop is a token bill with no ceiling; two rounds is where structure-then-content lands.
"""

import pytest

from corparius.tools.effects import Behaviour
from corparius.tools.registry import Tool
from corparius.tools.spec import ToolSpec


class Recorded:
    """A structured.Result double: what the harness hands back."""

    def __init__(self, data, usages=(), ok=True, source="test"):
        self.data = data
        self.usages = list(usages)
        self.ok = ok
        self.source = source
        self.fell_back = False
        self.attempts = 1
        self.errors = []


class Usage:
    def __init__(self, total=100):
        self.input_tokens = total // 2
        self.output_tokens = total - total // 2
        self.cost = 0.0
        self.total = total


# --- the hook itself --------------------------------------------------------------


def test_a_tool_without_refine_is_asked_once_and_says_nothing():
    """Every tool that existed before this. The default has to be silence rather than an error, or
    adding a capability would mean touching forty declarations that do not want it."""
    tool = Tool.from_parts(
        ToolSpec("t", "d", needs_draft=True, schema={"x": {"type": "str", "default": ""}}),
        Behaviour(effect=lambda c, d: None, prompt=lambda c: "go"),
    )
    assert tool.refine_prompt(object(), Recorded({"x": "1"})) == ""


def test_refine_sees_the_first_answer():
    """The whole point: the second prompt is built *from* the first result. A hook that could not
    read it would be a fixed second prompt, which is one prompt in two calls."""
    seen = {}

    def refine(ctx, result):
        seen["data"] = result.data
        return "now the rest"

    tool = Tool.from_parts(
        ToolSpec("t", "d", needs_draft=True, schema={"x": {"type": "str", "default": ""}}),
        Behaviour(effect=lambda c, d: None, prompt=lambda c: "go", refine=refine),
    )
    assert tool.refine_prompt(object(), Recorded({"x": "asked"})) == "now the rest"
    assert seen["data"] == {"x": "asked"}


# --- the first user ---------------------------------------------------------------


def _ctx(tmp_path, store=None):
    class Ctx:
        company = {"slug": "acme", "name": "Acme"}
        data_path = str(tmp_path)

    ctx = Ctx()
    ctx.store = store
    return ctx


def _written(tmp_path, name, body):
    from corparius import documents

    folder = tmp_path / "companies" / "acme" / "documents" / documents.WRITTEN
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(body, encoding="utf-8")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    from corparius.config import cfg

    cfg.invalidate()
    return tmp_path


def _long_review(home, name="review.md"):
    """A document that does not fit — which is the only situation where a map is worth a call.

    Padded past `PLAN_FROM_DOCS_BUDGET` on purpose: the two sentences that matter are the ones the
    assertions look for, and the filler is what makes leaving something out unavoidable.
    """
    filler = ("The reviewer went on at length about margins and whitespace. " * 40) + "\n"
    _written(
        home,
        name,
        "# Pricing\nThe annual toggle lowered conversion by a third.\n" + filler + "\n"
        "# Hosting\nThe bucket is static so a deploy cannot break the checkout.\n" + filler,
    )


def test_the_first_round_sends_headings_and_not_bodies(home):
    """The defect it replaces: the prompt divided one budget evenly across the newest four documents
    and sent the first N characters of each, so a two-page note and a thirty-page review got the same
    room and the useful half of the long one was never reached."""
    from corparius.tools import effects

    _long_review(home)
    prompt = effects._plan_from_docs_prompt(_ctx(home))
    assert "Pricing" in prompt and "Hosting" in prompt, "the headings are the map"
    assert "lowered conversion" not in prompt, "no body in round one — that is the saving"
    assert "`sections`" in prompt


def test_a_corpus_that_fits_is_sent_whole(home):
    """Headings are not enough on their own, and this is the half that was missing.

    A document that opens with `# site-review` and holds one line *has* a heading, so the map fired
    on sixty characters: one call spent choosing the only option on offer, then a second sending text
    the first call had room for. Two calls to do one call's work — the same waste the no-headings
    branch avoids, through a different door. The map is worth a round only when something has to be
    left out.
    """
    from corparius.tools import effects

    _written(home, "review.md", "# site-review\n\nindex.html: replace 'we detect burnout'\n")
    prompt = effects._plan_from_docs_prompt(_ctx(home))
    assert "we detect burnout" in prompt, "it fits, so it goes in round one"
    assert "`sections`" not in prompt, "nothing to choose between"


def test_a_corpus_with_no_headings_keeps_the_even_slice(home):
    """There is nothing to descend, and a young company's notes are exactly this. Sending a map of
    one entry and then asking for it back would be two calls to do one call's work."""
    from corparius.tools import effects

    _written(home, "note.md", "Just a paragraph the design agent wrote, with no headings at all.")
    prompt = effects._plan_from_docs_prompt(_ctx(home))
    assert "Just a paragraph" in prompt, "the body is sent directly"
    assert "`sections`" not in prompt


def test_the_second_round_carries_the_sections_that_were_asked_for(home):
    """And only those. The saving is real only if what comes back is narrower than what would have
    been sent unasked."""
    from corparius.tools import effects

    _written(
        home,
        "review.md",
        "# Pricing\nThe annual toggle lowered conversion by a third.\n\n"
        "# Hosting\nThe bucket is static so a deploy cannot break the checkout.\n",
    )
    more = effects._plan_from_docs_refine(_ctx(home), Recorded({"sections": ["Pricing"]}))
    assert "lowered conversion" in more
    assert "cannot break the checkout" not in more, "Hosting was not asked for"
    assert "`tasks`" in more, "round two asks for the work"


def test_naming_nothing_asks_for_nothing(home):
    """A model that read the map and wanted none of it must not be charged for a second call to say
    so again. The executor leaves the first answer standing."""
    from corparius.tools import effects

    _written(home, "review.md", "# Pricing\nSomething about prices.\n")
    assert effects._plan_from_docs_refine(_ctx(home), Recorded({"sections": []})) == ""


def test_a_heading_that_does_not_exist_is_dropped_rather_than_obeyed(home):
    """A model naming a section it invented would otherwise produce an empty second round — two calls
    spent to do nothing. What it got right is still worth reading; the rest goes quietly, because the
    map was in front of it."""
    from corparius.tools import effects

    _written(home, "review.md", "# Pricing\nThe annual toggle lowered conversion.\n")
    more = effects._plan_from_docs_refine(
        _ctx(home), Recorded({"sections": ["Pricing", "Invented Heading"]})
    )
    assert "lowered conversion" in more
    assert "Invented Heading" not in more

    only_wrong = effects._plan_from_docs_refine(_ctx(home), Recorded({"sections": ["Nope"]}))
    assert only_wrong == "", "nothing matched, so nothing is worth a second call"


def test_the_tool_declares_the_field_the_first_round_fills(home):
    """Both ends. Round one is asked for `sections`; if the schema does not carry it, the harness
    drops the answer and the second round is built from nothing."""
    from corparius.tools.spec import SPEC

    assert "sections" in SPEC["plan_from_documents"].schema
    assert "tasks" in SPEC["plan_from_documents"].schema


# --- what makes it safe rather than merely useful ---------------------------------


def _turn(tmp_path, refine, calls):
    """One real turn through the real executor, with a router that counts and a tool that refines.

    A real `Executor`, a real `TokenBudget`, `CircuitBreaker` and `Store` — only the router is a
    double, and only because the assertions are about what reaches it. Billing that is asserted
    against a mock of the thing doing the billing asserts nothing.

    Each call is recorded as its **whole** message list rather than its last entry: `structured.ask`
    appends the schema instruction after the user turn, so the refine text is second from the end.
    Asserting on `[-1]` passed for the wrong reason until it did not.
    """
    import types

    from corparius.agents import Executor
    from corparius.config.permissions import PermissionEngine
    from corparius.hitl import ApprovalGate
    from corparius.kernel.records import AgentRole, LLMResult
    from corparius.kernel.records import Usage as LLMUsage
    from corparius.roster import ROSTER
    from corparius.safety import CircuitBreaker, TokenBudget
    from corparius.store import Store
    from corparius.tools.registry import TOOLS

    store = Store(str(tmp_path / "data"))

    class Router:
        def generate(self, messages, *a, **kw):
            calls.append([m["content"] for m in messages])
            return LLMResult(
                text='{"headline": "h", "body": "b"}',
                usage=LLMUsage(10, 10, 0.25),
                model="m",
                provider="openrouter",
            )

        def embed(self, text):
            return [0.0, 1.0]

    class Settings:
        loop_similarity_threshold = 0.95
        max_identical_tool_calls = 99

    spec = ROSTER[AgentRole.SOCIAL]
    name = spec.playbook[0]
    original = TOOLS[name].behaviour
    TOOLS[name].behaviour = type(original)(
        effect=original.effect, prompt=original.prompt, skip_when=None, refine=refine
    )
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
    try:
        gate = ApprovalGate(store, PermissionEngine(store=store))
        Executor(Router(), gate, store, Settings()).run_turn("t", spec, ctx)
    finally:
        TOOLS[name].behaviour = original
        store.close()
    return ctx


def _asking(calls, text):
    """How many calls carried this prompt."""
    return sum(1 for messages in calls if text in messages)


def test_the_second_call_is_billed_like_the_first(home):
    """The property that makes this an executor capability rather than a tool calling a model.

    A tool that reached the router itself would escape the budget, the breaker, the usage log and the
    per-role pin — all five live here. A second call that missed `ctx.budget` would be spend the
    operator's ceiling never sees, which is the failure mode this project has already paid 365 026
    tokens for once: an operator read "Nothing usable drafted" as a broken generator while two
    providers were answering 429.

    Two turns, differing in one thing — whether the tool declares `refine`. The first is the control,
    and it is what makes the second number mean something.
    """
    control: list[list[str]] = []
    once = _turn(home, None, control)
    spent_once = once.budget.used
    assert spent_once > 0, "the control turn has to have spent something to be a control"

    refined: list[list[str]] = []
    twice = _turn(home, lambda ctx, result: "read this as well", refined)

    assert len(refined) == len(control) + 1, "the refine round has to reach the model"
    assert _asking(refined, "read this as well") == 1
    assert twice.budget.used == spent_once * 2, "both calls billed, at the same rate"
    # The breaker watches **velocity**, so a call it never saw is not a smaller number — it is a
    # burst it cannot see at all. Reading `_events` because there is no public rate, and the count
    # is the whole assertion: two calls, two events.
    assert len(twice.breaker._events) == len(once.breaker._events) * 2


def test_the_usage_log_carries_the_second_call_too(home):
    """The budget is the ceiling for this process; the usage log is the bill an operator reads next
    week. Both are written by `_bill`, three lines apart, and could still come apart — so the one
    that outlives the run gets its own assertion."""
    from corparius.store import Store

    def spent():
        store = Store(str(home / "data"))
        try:
            return sum(row["t"] for row in store.spend_by_agent("t"))
        finally:
            store.close()

    start = spent()
    _turn(home, None, [])
    one_call = spent() - start

    mark = spent()
    _turn(home, lambda ctx, result: "read this as well", [])
    two_calls = spent() - mark

    assert one_call > 0, "the control has to log something"
    assert two_calls == one_call * 2, f"{one_call} tokens logged for one call, {two_calls} for two"


def test_it_is_one_extra_round_and_not_a_loop(home):
    """Bounded by the executor, not by the tool's restraint. A `refine` that always asks for more —
    which is what a naive agentic loop is — gets exactly one more call and then stops.

    PageIndex's agentic retrieval spends 2–4 calls per question; an open loop is a token bill with no
    ceiling, and this codebase's own history says which of those it can afford. Note that the bound
    is not the tool being well behaved: this `refine` is deliberately the worst one that could be
    written, and the executor never asks it a second time.
    """
    calls: list[list[str]] = []
    _turn(home, lambda ctx, result: "and again", calls)
    assert _asking(calls, "and again") == 1, f"asked {_asking(calls, 'and again')} times, not once"
