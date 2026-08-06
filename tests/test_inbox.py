"""Everything that needs a human, other than an approval.

Approvals answer "may I". They left two things with nowhere to go: an agent that
lacks a fact could not ask for it, and a session that froze itself could not say
so. Both used to end as one row in the action log, which is the same as not
being said at all.
"""

import types

from corparius import inbox
from corparius.store import Store


def _ctx(store, role="outreach", slug="t"):
    return types.SimpleNamespace(company={"slug": slug, "name": "T"}, store=store, role=role)


def test_a_question_waits_and_then_carries_the_answer(tmp_path):
    store = Store(str(tmp_path))
    ctx = _ctx(store)
    ident = inbox.ask(ctx, "Which mailbox should I send from?", "No SMTP is configured.")
    assert ident and inbox.answer_to(ctx, "Which mailbox should I send from?") == ""
    store.resolve_inbox(ident, "hello@cvboost.fr")
    assert inbox.answer_to(ctx, "Which mailbox should I send from?") == "hello@cvboost.fr"


def test_asking_twice_files_one_item(tmp_path):
    """A re-run of the same tick must find the question it already asked. The id
    is a hash of what is being asked, not a fresh one per attempt."""
    store = Store(str(tmp_path))
    ctx = _ctx(store)
    first = inbox.ask(ctx, "Which mailbox?")
    second = inbox.ask(ctx, "Which mailbox?")
    assert first == second
    assert len(store.list_inbox("t", "pending")) == 1


def test_an_answered_question_is_not_asked_again(tmp_path):
    store = Store(str(tmp_path))
    ctx = _ctx(store)
    ident = inbox.ask(ctx, "Which mailbox?")
    store.resolve_inbox(ident, "hello@cvboost.fr")
    assert inbox.ask(ctx, "Which mailbox?") == ""
    assert store.list_inbox("t", "pending") == []


def test_an_answer_reaches_every_role_that_asks(tmp_path):
    """The id folds in the agent, so outreach and support raise different items.
    Matching the answer on the title is what stops the operator being asked the
    same thing once per role."""
    store = Store(str(tmp_path))
    ident = inbox.ask(_ctx(store, "outreach"), "Which mailbox?")
    store.resolve_inbox(ident, "hello@cvboost.fr")
    assert inbox.answer_to(_ctx(store, "support"), "Which mailbox?") == "hello@cvboost.fr"


def test_first_responder_wins(tmp_path):
    """The work that was waiting has already moved on the first answer;
    rewriting the record would leave the store disagreeing with what happened."""
    store = Store(str(tmp_path))
    ident = inbox.ask(_ctx(store), "Which mailbox?")
    assert store.resolve_inbox(ident, "first") is True
    assert store.resolve_inbox(ident, "second") is False
    assert store.list_inbox("t")[0]["resolution"] == "first"


def test_a_notification_blocks_nothing_and_is_idempotent(tmp_path):
    """A breaker that trips three days running should leave one live notice, not
    a wall of them."""
    store = Store(str(tmp_path))
    for _ in range(3):
        inbox.notify(store, "t", "system", "The session froze", "velocity ceiling")
    notices = store.list_inbox("t", "pending", inbox.NOTIFICATION)
    assert len(notices) == 1


def test_the_inbox_is_scoped_to_one_company(tmp_path):
    store = Store(str(tmp_path))
    inbox.ask(_ctx(store, slug="a"), "Which mailbox?")
    assert store.list_inbox("b") == []


def test_asking_with_no_store_is_survivable(tmp_path):
    ctx = types.SimpleNamespace(company={"slug": "t"}, store=None, role="outreach")
    assert inbox.ask(ctx, "Which mailbox?") == ""
    assert inbox.answer_to(ctx, "Which mailbox?") == ""


def test_answering_a_question_releases_the_task_it_held(tmp_path):
    """A question parks work exactly as an approval does, so it has to release
    it too — otherwise an answered question leaves its task parked for good."""
    store = Store(str(tmp_path))
    tid = store.add_task(
        "t", "Publish the site", "design", 2, "approved", "ceo", tool="deploy_site"
    )
    ident = inbox.ask(_ctx(store, "design"), "Where should the site be published?")
    store.park_task(tid, ident, "question")
    assert store.release_waiting_tasks("t") == {"released": 0, "refused": 0}
    store.resolve_inbox(ident, "netlify")
    assert store.release_waiting_tasks("t") == {"released": 1, "refused": 0}
    assert store.claim_next_task("t", "design")["id"] == tid


def test_a_parked_question_is_not_claimed_meanwhile(tmp_path):
    store = Store(str(tmp_path))
    tid = store.add_task("t", "Publish", "design", 2, "approved", "ceo", tool="deploy_site")
    store.park_task(tid, inbox.ask(_ctx(store, "design"), "Where?"), "question")
    assert store.claim_next_task("t", "design") is None


def test_the_ask_operator_tool_asks_then_reports_the_answer(tmp_path):
    from corparius.tools.registry import TOOLS

    store = Store(str(tmp_path))
    ctx = _ctx(store, "support")
    ctx.structured = types.SimpleNamespace(
        data={"question": "What refund policy should I quote?", "why": "a ticket asks"}
    )
    held = TOOLS["ask_operator"].run(ctx, "")
    assert held.pending and held.question_id and not held.ok
    store.resolve_inbox(held.question_id, "Full refund within 14 days.")
    answered = TOOLS["ask_operator"].run(ctx, "")
    assert answered.ok and "Full refund" in answered.output


def test_a_frozen_session_leaves_a_notice(tmp_path):
    """Before this, a circuit-breaker freeze was one row in the action log. A
    company could sit dead for a day unless the operator thought to look."""
    from corparius.config.settings import Settings
    from corparius.orchestrator import Runtime

    s = Settings()
    s.llm_mock = True
    s.data_path = str(tmp_path)
    store = Store(str(tmp_path))
    cfg = {
        "slug": "t",
        "name": "T",
        "offer": {"product": "p"},
        "agents": {"ceo": True},
        "budgets": {"session_tokens": 100000, "tokens_per_minute": 1},
        "hitl_tools": [],
    }
    assert Runtime(s, store).run(cfg, ticks=6)["frozen"] is True
    notices = store.list_inbox("t", "pending", inbox.NOTIFICATION)
    assert notices and "froze" in notices[0]["title"]
