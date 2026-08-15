"""How a company writes, and the half of it a machine can hold to.

An editorial charter splits into two halves that behave differently, and the split is the whole
design. One half is judgment: neutral rather than promotional, no closing paragraph about impact,
vary how many things you list. Only a model can apply those, so they go in the prompt. The other half
is mechanical: a character that must not appear, a banned phrase, a comma before the final "and".

Asking a model to obey the mechanical half makes it advisory. A model that emits an em dash once in
ten generations is caught by nobody and the violation reaches a published page. That is the shape
this codebase calls a guard that does not run, so the mechanical half is checked in code.

**And most of it still cannot be fixed automatically**, which is the part worth being careful about.
Curly quotation marks become straight ones by substitution and nothing is lost. An em dash becomes a
comma, a colon or a pair of brackets depending on the sentence, and a banned adjective needs the
sentence rewritten rather than a synonym dropped in. Those are reported. A checker that guessed would
quietly change what an agent meant, which is worse than the violation it was correcting.
"""

import pathlib

import pytest

from corparius import housestyle as hs

BAD = (
    "Notre solution incontournable se présente comme un tournant — elle témoigne de notre "
    "vision. Nous livrons A, B, and C, avec des “guillemets” courbes."
)


# --- what it catches --------------------------------------------------------------


def test_it_catches_each_class_of_rule_it_ships():
    """One sentence breaking every shipped rule, so a rule that stops matching is visible here
    rather than on a published page."""
    caught = {v["rule"] for v in hs.check(BAD)}
    assert caught == {
        "puffery",
        "presents-itself-as",
        "em-dash",
        "landscape",
        "oxford-comma",
        "curly-quote",
    }, caught


def test_clean_prose_is_left_entirely_alone():
    """The other end of the thread. A checker that flags correct writing is one an operator turns
    off, and then it protects nothing."""
    good = "The annual toggle lowered conversion by a third. Hosting is static, so a deploy cannot break the checkout."
    fixed, left = hs.apply(good)
    assert fixed == good and left == []


def test_only_the_substitution_is_fixed_and_the_judgment_is_reported():
    """The line this module refuses to cross.

    Curly to straight is a character swap with nothing to decide. Everything else needs the sentence:
    an em dash becomes a comma, a colon or brackets depending on what follows, and `incontournable`
    needs the claim rewritten rather than a synonym. Guessing would change what the agent meant.
    """
    fixed, left = hs.apply(BAD)
    assert "“" not in fixed and "”" not in fixed and '"guillemets"' in fixed
    assert "—" in fixed, "the dash was replaced by something this module cannot know"
    assert "incontournable" in fixed
    assert {v["rule"] for v in left} == {
        "puffery",
        "presents-itself-as",
        "em-dash",
        "landscape",
        "oxford-comma",
    }
    assert all(v["fixable"] is False for v in left)


def test_a_violation_says_where_and_why():
    """Data rather than a sentence, because two callers want it: one records it beside the action
    and one puts it in front of a model. A formatted string would make the second parse prose."""
    hit = next(v for v in hs.check("Une solution incontournable.") if v["rule"] == "puffery")
    assert hit["text"] == "incontournable"
    assert hit["at"] == "Une solution incontournable.".index("incontournable")
    assert "promotional" in hit["why"]


# --- whose rules ------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    from corparius.config import cfg

    cfg.invalidate()
    return tmp_path


def _write(home, body: str) -> pathlib.Path:
    path = home / "companies" / "acme" / hs.STYLE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_a_company_with_no_charter_gets_the_shipped_one(home):
    assert hs.load("acme").rules == hs.DEFAULT_RULES


def test_an_operators_rules_are_added_to_the_shipped_ones_and_come_first(home):
    """Adding is what somebody who wrote three lines about tone almost always means. Theirs lead the
    report, because a violation of the rule they cared enough to write down is the one they want to
    read first."""
    _write(
        home,
        "voice: Tutoyer le lecteur.\nrules:\n  - name: no-solution\n    find: solution\n    why: le mot ne dit rien\n",
    )
    style = hs.load("acme")
    assert len(style.rules) == len(hs.DEFAULT_RULES) + 1
    assert style.rules[0].name == "no-solution"
    assert style.voice.startswith("Tutoyer le lecteur.")
    assert [v["rule"] for v in hs.check("Notre solution.", style)] == ["no-solution"]


def test_replace_gives_them_exactly_what_they_wrote(home):
    """The one flag that changes shape rather than content. A company writing for a market that
    wants warmth should be able to drop `crucial` from the banned list without editing the product,
    and this is how they say so."""
    _write(home, "replace: true\nvoice: Ecris comme tu parles.\nrules: []\n")
    style = hs.load("acme")
    assert style.rules == []
    assert style.voice == "Ecris comme tu parles."
    assert hs.check(BAD, style) == [], "the shipped rules survived a replacement"


def test_a_charter_that_will_not_parse_falls_back_and_says_so(home, caplog):
    """A preference must not take a run down, and falling back in silence is its own defect: the
    operator watches the agents ignore what they wrote with nothing anywhere to explain it.

    Found while writing these tests. A file holding one stray escape parsed to nothing and looked
    exactly like a charter that was being obeyed.
    """
    _write(home, "rules: [this is not\n  yaml: [\n")
    with caplog.at_level("WARNING"):
        style = hs.load("acme")
    assert style.rules == hs.DEFAULT_RULES
    # `getMessage()`, not `.message`: a LogRecord has no such attribute, and the first version of
    # this line was an expression that evaluated to something truthy without ever looking at a log.
    assert any("style.yaml" in r.getMessage() for r in caplog.records), (
        "it fell back without a word, which is the half of this that is a defect"
    )


def test_a_rule_with_a_broken_pattern_is_dropped_not_fatal(home):
    """One bad line in a hand-edited file must not cost the other nine. The rest of the charter
    still applies, which is the difference between a typo and an outage."""
    _write(
        home, "rules:\n  - name: broken\n    find: '[unclosed'\n  - name: fine\n    find: widget\n"
    )
    style = hs.load("acme")
    assert [r.name for r in style.rules][:1] == ["fine"]
    assert [v["rule"] for v in hs.check("a widget", style)] == ["fine"]


# --- an agent writing one down ----------------------------------------------------


def test_an_agent_can_write_a_rule_and_writing_it_twice_changes_nothing(home):
    """The counterpart to `write_skill`, and the same idea one step further.

    Prose tells the next model what to avoid and is re-read from scratch every turn. A rule is
    checked, for nothing, on every draft forever. An agent that has seen the same wording corrected
    three times has learned something a sentence cannot hold.

    Idempotent on the pattern, because an agent filing the same rule every day turns a charter into
    a log.
    """
    _write(home, "rules: []\n")
    rule = hs.Rule("no-leverage", r"\bleverage\b", "jargon seen three times")
    assert hs.add_rule("acme", rule) is True
    assert hs.add_rule("acme", rule) is False, "the second filing wrote a duplicate"
    names = [r.name for r in hs.load("acme").rules]
    assert names[0] == "no-leverage" and len(names) == len(hs.DEFAULT_RULES) + 1


def test_writing_a_rule_keeps_what_the_operator_already_wrote(home):
    """Their file is theirs. A tool that reformats it while adding a line is a tool they stop
    trusting with it."""
    _write(
        home, "voice: Ecris court.\nrules:\n  - name: mine\n    find: widget\n    why: parce que\n"
    )
    assert hs.add_rule("acme", hs.Rule("theirs", "gadget", "added by an agent")) is True
    style = hs.load("acme")
    assert style.voice.startswith("Ecris court.")
    assert [r.name for r in style.rules][:2] == ["mine", "theirs"]


# --- through a real turn ----------------------------------------------------------


def test_the_charter_reaches_the_prompt_and_the_answer(home):
    """Both ends, through the executor, because a charter that only exists in a unit test is a
    charter no agent has ever seen.

    The prompt half and the checking half are deliberately both here. Saying the rules is what stops
    a model breaking them; checking is what catches it when the saying did not work. Neither alone
    is the feature: a prompt-only charter is advisory and a check-only charter spends a model call
    producing text it then has to reject.
    """
    import types

    from corparius.agents import Executor, _messages
    from corparius.config.permissions import PermissionEngine
    from corparius.hitl import ApprovalGate
    from corparius.kernel.records import AgentRole, LLMResult
    from corparius.kernel.records import Usage as LLMUsage
    from corparius.roster import ROSTER
    from corparius.safety import CircuitBreaker, TokenBudget
    from corparius.store import Store
    from corparius.tools.registry import TOOLS

    _write(
        home,
        "rules:\n  - name: no-widget\n    find: widget\n    why: this company sells no widgets\n",
    )
    spec = ROSTER[AgentRole.SOCIAL]
    tool = TOOLS[spec.playbook[0]]
    ctx = types.SimpleNamespace(
        company={"slug": "acme", "name": "Acme", "offer": {}},
        tick=0,
        budget=TokenBudget(1_000_000),
        breaker=CircuitBreaker(1_000_000),
        data_path=str(home),
        memory=[],
        leads=[],
        store=None,
        role="",
        structured=None,
        style=hs.load("acme"),
    )

    # One: the rules are in front of the model.
    system = _messages(spec, ctx, tool)[0]["content"]
    assert "How this company writes:" in system
    assert "no widgets" in system, "the operator's own rule never reached the prompt"
    assert "promotional" in system, "and neither did the shipped ones"

    # Two: what comes back is corrected where it can be, and the rest is recorded.
    store = Store(str(home / "data"))
    ctx.store = store

    class Router:
        def generate(self, messages, *a, **kw):
            return LLMResult(
                text='{"headline": "Un widget \u201cincontournable\u201d", "body": "b"}',
                usage=LLMUsage(10, 10, 0.0),
                model="m",
                provider="openrouter",
            )

        def embed(self, text):
            return [0.0, 1.0]

    class Settings:
        loop_similarity_threshold = 0.95
        max_identical_tool_calls = 99

    try:
        gate = ApprovalGate(store, PermissionEngine(store=store))
        done = Executor(Router(), gate, store, Settings()).run_turn("acme", spec, ctx)
    finally:
        store.close()

    # On what the turn reported, not on `ctx.structured`: the executor clears that for each tool in
    # the playbook, so by the end it belongs to `schedule_post`. The line the effect wrote is where
    # the corrected text actually went.
    said = " ".join(done or [])
    assert "“" not in said and '"incontournable"' in said, said
    rules = {v["rule"] for v in ctx.style_violations}
    assert "puffery" in rules and "no-widget" in rules, rules
    assert "curly-quote" not in rules, "a fixed violation is not one that is left"
