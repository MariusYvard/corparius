"""The three steps out of an empty install, and the three judgements they encode.

This lived in the shipped page's JavaScript, which is why it was the last Overview card with no resource
behind it. Moving it to `app/onboarding.py` is not tidying: each of the three judgements below is one a
second client would otherwise reimplement, and two of them are easy to get backwards in a way that
produces a card which nags someone who has already finished.
"""

import pytest

from corparius.app import onboarding
from corparius.store import Store


class _Mock:
    llm_mock = True


class _Live:
    llm_mock = False


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path))
    yield s
    s.close()


def _approval(store, slug="c", ident="ap1"):
    from corparius.kernel.records import ApprovalRequest

    store.add_approval(
        ApprovalRequest(
            id=ident, company=slug, agent="social", tool="draft_social_post", parameters={}
        )
    )
    return ident


def _steps(store, settings=None, slug="c", run=None):
    return onboarding.steps(store, settings or _Mock(), slug, run=run)


def _by_key(rows):
    return {row["key"]: row for row in rows}


# --- the shape a client renders from ----------------------------------------------


def test_the_three_steps_come_back_in_order_with_an_action_each(store):
    rows = _steps(store)
    assert [row["key"] for row in rows] == ["model", "run", "decide"]
    # The keys are the i18n prefixes too, so a client renders each from its key with no table of its
    # own: `ob.model`, `ob.modelHint`, `ob.modelCta`.
    import json
    import pathlib

    en = json.loads(pathlib.Path("web/i18n/en.json").read_text(encoding="utf-8"))
    for row in rows:
        for suffix in ("", "Hint", "Cta"):
            assert f"ob.{row['key']}{suffix}" in en, f"ob.{row['key']}{suffix}"
    # An action each: a tab to open, or the one button that is the whole step.
    assert _by_key(rows)["run"]["act"] == "run"
    assert _by_key(rows)["model"]["tab"] == "providers"
    assert _by_key(rows)["decide"]["tab"] == "operations"


def test_only_one_step_leads_at_a_time(store):
    """`lead` is the single next thing to do, so a client renders one call to action rather than three
    competing ones — which is how a guided thread stops guiding."""
    rows = _steps(store)
    assert [row["lead"] for row in rows] == [True, False, False]
    assert sum(row["lead"] for row in rows) == 1


def test_the_lead_moves_to_the_first_unfinished_step(store):
    """Walked in order rather than expressed as three conditions naming each other, which is how the
    page said it and how a fourth step would have got the sequence wrong."""
    rows = _steps(store, _Live())  # step one done by a real provider
    assert _by_key(rows)["model"]["done"] is True
    assert _by_key(rows)["run"]["lead"] is True
    assert _by_key(rows)["decide"]["lead"] is False


def test_nothing_leads_once_everything_is_done(store):
    store.record_action("c", "social", "draft_social_post", {}, "ok", True)
    _approval(store)
    store.set_approval_status("ap1", "approved", "")
    rows = _steps(store, _Live())
    assert onboarding.finished(rows) is True
    assert not any(row["lead"] for row in rows)


# --- judgement one: staying in mock is a finished choice --------------------------


def test_mock_mode_alone_leaves_the_first_step_open(store):
    """Nothing has happened yet, so the thread starts at the beginning."""
    assert _by_key(_steps(store))["model"]["done"] is False


def test_a_real_provider_finishes_the_first_step(store):
    assert _by_key(_steps(store, _Live()))["model"]["done"] is True


def test_having_run_once_in_mock_also_finishes_it(store):
    """The judgement, and it matters: running once means the operator either wired a model or accepted
    the mock **deliberately**. Treating mock as unfinished would nag somebody who has already decided,
    forever, because there is nothing left for them to do about it."""
    store.record_action("c", "social", "draft_social_post", {}, "ok", True)
    rows = _by_key(_steps(store, _Mock()))
    assert rows["model"]["done"] is True, "staying in mock is a choice, not an unfinished step"
    assert rows["run"]["done"] is True


# --- judgement two: a failed run is not a run you watched work -------------------


def test_a_run_that_ended_in_an_error_does_not_count(store):
    """Ticking the step off on the strength of a failure is the opposite of the reassurance it exists
    to give: the operator would be told they had watched the agents work when they had watched a
    traceback."""
    rows = _by_key(_steps(store, run={"result": {"error": "the run stopped on an error"}}))
    assert rows["run"]["done"] is False
    assert rows["model"]["done"] is False, "and it must not finish step one either"


def test_a_run_that_finished_counts_even_with_no_actions_logged(store):
    """A run of a company with every role paused logs nothing and still happened. The operator advanced
    the clock and watched, which is what the step asks."""
    rows = _by_key(_steps(store, run={"result": {"ticks_run": 24}}))
    assert rows["run"]["done"] is True


# --- judgement three: the company working is not the human deciding --------------


def test_a_completed_task_does_not_tick_off_the_decision_step(store):
    """The page had this right and the reason is worth keeping: the company completing its own work is
    not a person having decided anything. A done task ticking this off would retire the card before the
    operator had ever used the gate the product is built around."""
    task = store.add_task("c", "write the landing page", "design")
    store.set_task_status(task, "done", "done by the design agent")
    store.record_action("c", "design", "write_site_content", {}, "ok", True)
    rows = _by_key(_steps(store, _Live()))
    assert rows["run"]["done"] is True, "work happened"
    assert rows["decide"]["done"] is False, "but nobody decided anything"


def test_a_pending_approval_is_not_a_decision(store):
    """One waiting is the *reason* for the step, not its completion."""
    _approval(store)
    assert _by_key(_steps(store))["decide"]["done"] is False


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_either_answer_counts_because_deciding_is_the_point(store, decision):
    """Rejecting is deciding. A step that only accepted approval would be teaching the operator that
    the gate has one correct answer, which is the opposite of what a human gate is for."""
    _approval(store)
    store.set_approval_status("ap1", decision, "")
    assert _by_key(_steps(store))["decide"]["done"] is True


def test_the_signal_is_durable_and_not_the_browser_s(store):
    """What the move actually bought. The page kept this in `localStorage`, so it was lost on a new
    browser and invisible to a phone — and a phone reading the thread is the premise of the whole v1
    contract.

    `set_approval_status` has exactly two callers and both are the operator: one pressing the button,
    one asking the CEO to in the chat. Asserted from the source, because "nothing automatic moves an
    approval off pending" is the claim the durable answer rests on.
    """
    import pathlib
    import re

    callers = []
    for path in sorted(pathlib.Path("corparius").rglob("*.py")):
        if path.match("store/*"):
            continue
        if re.search(r"set_approval_status\(", path.read_text(encoding="utf-8")):
            callers.append(path.as_posix())
    assert callers == [
        "corparius/app/approvals.py",
        "corparius/app/directives.py",
    ], f"a third caller can move an approval off pending: {callers}"


def test_deciding_is_counted_per_company(store):
    """Two companies are two threads. One company's decision must not retire another's card."""
    _approval(store, "one", "a1")
    store.set_approval_status("a1", "approved", "")
    assert store.decided_approvals("one") == 1
    assert store.decided_approvals("two") == 0
    assert _by_key(_steps(store, slug="two"))["decide"]["done"] is False


# --- what is deliberately not here ------------------------------------------------


def test_dismissing_is_not_a_server_field():
    """Per-browser by choice, and stated so nobody adds a settings row for it.

    The card retires itself once the three are done, so the worst a new browser costs is seeing a thread
    that is nearly finished. That is a different trade from the theme, which is server-side precisely
    because an operator wants it to follow them.
    """
    import inspect

    source = inspect.getsource(onboarding)
    # The module docstring explains the choice in prose; the check is that no *field* carries it, so
    # `dismissing` (the word in that explanation) is removed before looking for `dismiss`.
    assert "dismiss" not in source.lower().replace("dismissing", "")
    assert "hidden" not in {key for row in onboarding.ACTIONS.values() for key in row}


def test_the_card_reads_the_thread_and_does_not_recompute_it():
    """Which step leads is the whole content of an onboarding card. A client deriving it independently
    would be a second implementation of the only thing this service does."""
    import pathlib

    card = pathlib.Path("web/src/Overview.svelte").read_text(encoding="utf-8")
    assert "summary?.onboarding" in card
    # No local recomputation of the sequence: `lead` and `done` come from the payload.
    assert "step.lead" in card and "step.done" in card
    assert "llm_mock" not in card.split("let onboarding")[1][:2000], (
        "the card is deciding step one for itself"
    )
