"""What the operator should do next, and whether the button goes anywhere.

The CEO tab could answer questions and could not answer *the* question. Somebody who does not know
what to do has nothing to type, and "ask the agent that holds the plan" only helps a person who
already knows what to ask it. So `app.guidance` reads the answer off the store and names a
destination for each step — a thing to press, not a sentence to act on.

Three properties, and the third is the one that decides whether any of this is trustworthy:

  * **it is derived, never generated.** Every step is a fact about the store. A model asked "what
    should I do?" produces a plausible list, and plausible is the worst possible answer here: it can
    name a tab that does not apply, or miss the two approvals actually holding the company up;
  * **it is ordered by what blocks the company**, not by what is easy;
  * **every destination exists and every step can be rendered.** A button that goes nowhere, or one
    labelled with a raw i18n key, is worse than no button — it teaches an operator that this list is
    decoration.
"""

import json
import pathlib

import pytest

from corparius.app import guidance
from corparius.config.settings import Settings
from corparius.store import Store

COMPANY = "acme"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    from corparius.config import cfg

    cfg.invalidate()
    made = Store(str(tmp_path))
    yield made
    made.close()


def _keys(steps) -> list[str]:
    return [s["key"] for s in steps]


def _pending(store, tool="send_outreach", agent="outreach"):
    import time

    from corparius.hitl import ApprovalRequest

    store.add_approval(
        ApprovalRequest(
            id=f"{tool}-1",
            company=COMPANY,
            agent=agent,
            tool=tool,
            parameters={},
            status="pending",
            ts=time.time(),
            detail={},
        )
    )


# --- what it finds ----------------------------------------------------------------


def test_an_empty_company_is_told_to_connect_a_model(store):
    """The install thread leads while it is unfinished, and `onboarding` already decides which of its
    three steps is next — so this takes that answer rather than forming a second one."""
    steps = guidance.next_steps(store, Settings(), COMPANY)
    assert steps and steps[0]["key"].startswith("ob."), _keys(steps)
    assert steps[0]["tab"] or steps[0]["act"], "the lead step must go somewhere"


def test_a_human_blocking_the_company_outranks_everything_unfinished(store):
    """Nothing moves while a person is the blocker. A missing Stripe key is merely unfinished; two
    approvals are the company standing still."""
    _pending(store)
    store.add_draft(COMPANY, "post", "linkedin", "a body somebody has to send or bin")
    steps = guidance.next_steps(store, Settings(), COMPANY)
    keys = _keys(steps)
    assert "approvals" in keys and "drafts" in keys
    assert keys.index("approvals") < keys.index("drafts"), "the gate blocks; a draft merely waits"


def test_the_approvals_step_names_what_is_waiting(store):
    """ "Decide what the gate is holding" with no idea what it is holding is half a step. The tools
    are named so an operator can tell a read from a spend before they even arrive."""
    _pending(store, tool="update_pricing", agent="strategy")
    _pending(store, tool="send_outreach", agent="outreach")
    step = next(
        s for s in guidance.next_steps(store, Settings(), COMPANY) if s["key"] == "approvals"
    )
    assert "update_pricing" in step["detail"] and "send_outreach" in step["detail"]


def test_a_company_with_nothing_waiting_gets_no_busywork(store):
    """An empty list is a real answer and the console renders it as "nothing is waiting on you".
    Inventing a step to fill the space is how a guidance list becomes noise nobody reads."""
    store.record_action(COMPANY, "ceo", "write_note", {}, "wrote something", True)
    store.set_approval_status("nothing", "approved")  # no such row; the count stays 0
    steps = guidance.next_steps(store, Settings(), COMPANY)
    assert all(s["key"] != "approvals" for s in steps)


def test_the_list_is_bounded(store):
    """Four. Handing somebody a backlog when they asked what to do is the same as handing them
    nothing — which is why `onboarding` reduces three steps to one lead rather than showing three."""
    _pending(store)
    for n in range(6):
        store.add_draft(COMPANY, "post", "linkedin", f"draft number {n} that somebody has to send")
    assert len(guidance.next_steps(store, Settings(), COMPANY)) <= 4


def test_go_live_waits_until_the_company_has_actually_run(store):
    """Telling somebody to wire Stripe before they have run a day answers a question they have not
    reached. It is also why `golive` is a parameter: `api.adapters.golive_status` already computes it,
    and a second implementation here would be two answers to "is the checkout wired"."""
    gaps = {"payment": {"wired": False}, "mail": {"wired": False}, "hosting": {"published": False}}
    assert all(
        not s["key"].startswith("golive.")
        for s in guidance.next_steps(store, Settings(), COMPANY, golive=gaps)
    )
    store.record_action(COMPANY, "ceo", "write_note", {}, "the company did something", True)
    later = guidance.next_steps(store, Settings(), COMPANY, golive=gaps)
    assert any(s["key"] == "golive.payment" for s in later), _keys(later)


# --- every button goes somewhere --------------------------------------------------


def test_every_destination_is_a_real_tab_or_action(store):
    """The property that makes this a redirect rather than advice. A `tab` that the console does not
    have is a button that does nothing, and an operator only has to meet one of those to stop trusting
    the list."""
    _pending(store)
    store.add_draft(COMPANY, "post", "linkedin", "a body somebody has to send or bin")
    store.record_action(COMPANY, "ceo", "write_note", {}, "ran", True)
    gaps = {"payment": {"wired": False}, "mail": {"wired": False}, "hosting": {"published": False}}
    for step in guidance.next_steps(store, Settings(), COMPANY, golive=gaps):
        assert step["tab"] or step["act"], f"{step['key']} goes nowhere"
        if step["tab"]:
            assert step["tab"] in guidance.TABS, f"{step['key']} names tab {step['tab']!r}"
        if step["act"]:
            assert step["act"] in guidance.ACTS, f"{step['key']} names act {step['act']!r}"


def test_every_step_key_has_a_string_in_both_languages(store):
    """The other end of the wire. A step the console renders as `next.drafts` is a raw key where a
    sentence belongs, and only a screenshot would find it — the same failure `test_i18n` exists for,
    reached through a code path that builds its key at runtime.

    The `ob.*` steps borrow the onboarding thread's own labels rather than getting a second set: two
    vocabularies for the same three steps would be two answers wearing one name.
    """
    strings = {
        lang: json.loads(pathlib.Path(f"web/i18n/{lang}.json").read_text(encoding="utf-8"))
        for lang in ("en", "fr")
    }
    from corparius.app import onboarding

    reachable = ["approvals", "inbox", "drafts", "golive.payment", "golive.email", "golive.hosting"]
    for lang, table in strings.items():
        for key in reachable:
            assert f"next.{key}" in table, f"{lang} cannot render next.{key}"
        for key in onboarding.STEPS:
            assert f"ob.{key}" in table, f"{lang} cannot render the onboarding step ob.{key}"
        for key in ("next.title", "next.desc", "next.none"):
            assert key in table, f"{lang} is missing {key}"


def test_the_reachable_list_is_the_whole_list(store):
    """The guard on the guard: the test above checks a hand-written list of keys, so a rule added to
    `next_steps` with no string would pass it. This reads the module instead."""
    source = pathlib.Path("corparius/app/guidance.py").read_text(encoding="utf-8")
    emitted = set(__import__("re").findall(r'_step\(\s*(?:f?)"([a-z.]+)', source))
    # `ob.` and `golive.` are f-string prefixes completed at runtime; the rest are literal keys.
    literal = {k for k in emitted if not k.endswith(".")}
    assert literal == {"approvals", "inbox", "drafts"}, sorted(literal)
