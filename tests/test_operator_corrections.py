"""The small deliberate acts an operator does by hand, and the one of them that grants power.

The last three gaps the stage-7 coverage ratchet named: `cli/configure.py` at 53.9% and
`cli/backlog.py` at 66.4% were `cmd_memory`, `cmd_rules`, `cmd_inbox` and — the one that matters
most — the `--always` branch of `approve`, which is how a tool stops asking for permission at
all. None of the four had a single test.

`approve --always` is a **grant**, and it is guarded by name: a tool the company lists in
`hitl_tools` keeps asking however many times it is approved. That guard is one `if` and it was
untested, so nothing would have failed if it had been inverted or deleted — and what it protects
is the standing-rule table, whose survival past a company delete was one of the three live bugs
this restructuring found (`purge_company` cleared 6 of 13 tables, and `rules` was among the 7
that stayed, so a company recreated on the same slug inherited its authorisations).
"""

import types

import pytest

from corparius.cli import backlog, configure
from corparius.kernel.records import ApprovalRequest

COMPANY = """
slug: t
name: T
offer: {product: p, price_eur: 9}
icp: {segment: seg, channels: [linkedin], pains: [pain]}
agents: {ceo: true, social: true, finance: true, ads: false, coder: false}
budgets: {session_tokens: 20000, tokens_per_minute: 20000}
hitl_tools: [send_financial_transaction]
"""


@pytest.fixture()
def company(tmp_path, monkeypatch):
    """A company file and a private store, the environment way. See `tests/test_cli.py`."""
    from corparius.config import cfg

    path = tmp_path / "company.yaml"
    path.write_text(COMPANY, encoding="utf-8")
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    cfg.invalidate()
    return str(path)


def _store(company):
    from corparius.app.support import open_store

    return open_store()


def _args(company, **kw):
    kw["company"] = company
    return types.SimpleNamespace(**kw)


# --- the grant ------------------------------------------------------------------


def _an_approval(store, tool):
    store.add_approval(
        ApprovalRequest(id="ap1", company="t", agent="finance", tool=tool, parameters={"x": 1})
    )


def test_approving_with_always_adds_the_standing_rule(company, capsys):
    """ "Yes, and stop asking" is one decision, so it is one command. Splitting it in two, as the
    code comment says, "invites the half that never runs"."""
    store = _store(company)
    _an_approval(store, "draft_social_post")
    backlog.cmd_decide(_args(company, id="ap1", note="", always=True), "approved")
    out = capsys.readouterr().out
    assert "ap1 -> approved" in out
    assert "no longer asks" in out
    assert [r["tool"] for r in store.list_rules("t")] == ["draft_social_post"]


def test_a_tool_gated_by_name_keeps_asking_however_often_it_is_approved(company, capsys):
    """The guard, and the reason it is by name: `hitl_tools` in the company file is the
    operator's own list of things they want to see every time. A standing rule would silently
    overrule the file they wrote it in.

    `send_financial_transaction` is in this company's `hitl_tools`, which is what makes this a
    real case rather than a constructed one.
    """
    store = _store(company)
    _an_approval(store, "send_financial_transaction")
    backlog.cmd_decide(_args(company, id="ap1", note="", always=True), "approved")
    out = capsys.readouterr().out
    assert "gated by name; it keeps asking" in out
    assert store.list_rules("t") == [], "a named HITL tool must not gain a standing rule"


def test_rejecting_with_always_grants_nothing(company):
    """`--always` only belongs to `approve`, but the flag reaches `cmd_decide` either way and the
    status is what decides. A rejection that granted a standing rule would be the worst possible
    reading of "always"."""
    store = _store(company)
    _an_approval(store, "draft_social_post")
    backlog.cmd_decide(_args(company, id="ap1", note="", always=True), "rejected")
    assert store.list_rules("t") == []


def test_an_unknown_approval_id_says_so_and_changes_nothing(company, capsys):
    store = _store(company)
    backlog.cmd_decide(_args(company, id="nope", note="", always=True), "approved")
    assert "approval id not found" in capsys.readouterr().out
    assert store.list_rules("t") == []


def test_deciding_an_approval_releases_the_tasks_parked_on_it(company, capsys):
    """Whatever decided it, work waiting on that answer can move. Reported, because a count of
    zero and a count of three are different things to an operator watching a stuck board."""
    store = _store(company)
    _an_approval(store, "draft_social_post")
    task = store.add_task("t", "blocked work", "social")
    # `park_task` is what links the two, and the link is the task's own note. Setting
    # `status="waiting"` by hand is not enough — measured: `release_waiting_tasks` reads
    # `note` for `approval:<id>` and skips anything else, so a hand-set status releases
    # nothing and this test would have passed on an empty count.
    store.park_task(task, "ap1", "approval")
    backlog.cmd_decide(_args(company, id="ap1", note="", always=False), "approved")
    out = capsys.readouterr().out
    assert "unblocked 1 task(s)" in out
    assert store.list_tasks("t")[0]["status"] != "waiting"


# --- standing rules, seen and revoked -------------------------------------------


def test_rules_lists_what_is_standing(company, capsys):
    store = _store(company)
    store.add_rule("t", "draft_social_post", "always", "granted in a test")
    configure.cmd_rules(_args(company, revoke=""))
    out = capsys.readouterr().out
    assert "standing rules: T" in out and "draft_social_post" in out and "always" in out


def test_rules_says_plainly_when_every_tool_still_asks(company, capsys):
    configure.cmd_rules(_args(company, revoke=""))
    assert "none; every gated tool still asks" in capsys.readouterr().out


def test_revoking_a_rule_removes_it(company, capsys):
    store = _store(company)
    store.add_rule("t", "deploy_site", "always", "granted in a test")
    configure.cmd_rules(_args(company, revoke="deploy_site"))
    assert "revoked deploy_site" in capsys.readouterr().out
    assert store.list_rules("t") == []


def test_revoking_a_rule_that_was_never_granted_says_so(company, capsys):
    configure.cmd_rules(_args(company, revoke="deploy_site"))
    assert "no standing rule for that tool" in capsys.readouterr().out


# --- memory ---------------------------------------------------------------------


def test_memory_lists_what_the_agents_learned(company, capsys):
    store = _store(company)
    store.remember("t", "ceo", "the segment answers on Tuesdays", why="two campaigns")
    configure.cmd_memory(_args(company, pin=0, forget=0))
    out = capsys.readouterr().out
    assert "memory: T" in out
    assert "the segment answers on Tuesdays" in out
    assert "(two campaigns)" in out, "the justification is half the fact"


def test_memory_says_where_facts_come_from_when_there_are_none(company, capsys):
    configure.cmd_memory(_args(company, pin=0, forget=0))
    assert "nothing learned yet" in capsys.readouterr().out


def test_pinning_marks_the_fact_and_forgetting_removes_it(company, capsys):
    store = _store(company)
    fact_id = store.remember("t", "ceo", "keep this one")
    configure.cmd_memory(_args(company, pin=fact_id, forget=0))
    assert "pinned" in capsys.readouterr().out
    configure.cmd_memory(_args(company, pin=0, forget=0))
    assert "*#" in capsys.readouterr().out, "a pinned fact has to be visibly pinned"
    configure.cmd_memory(_args(company, pin=0, forget=fact_id))
    assert "forgotten" in capsys.readouterr().out
    assert store.list_memory("t") == []


def test_pinning_or_forgetting_an_id_that_is_not_there_says_so(company, capsys):
    configure.cmd_memory(_args(company, pin=9999, forget=0))
    assert "no such memory" in capsys.readouterr().out
    configure.cmd_memory(_args(company, pin=0, forget=9999))
    assert "no such memory" in capsys.readouterr().out


# --- inbox ----------------------------------------------------------------------


def test_inbox_lists_what_is_waiting_on_a_person(company, capsys):
    store = _store(company)
    store.add_inbox("t", "design", "question", "Which price?", "the page needs one")
    backlog.cmd_inbox(_args(company, answer_to="", answer=""))
    out = capsys.readouterr().out
    assert "inbox: T" in out and "Which price?" in out and "the page needs one" in out


def test_an_empty_inbox_says_nothing_is_waiting(company, capsys):
    backlog.cmd_inbox(_args(company, answer_to="", answer=""))
    assert "nothing waiting on you" in capsys.readouterr().out


def test_answering_an_item_unblocks_the_work_that_waited_for_it(company, capsys):
    store = _store(company)
    item = store.add_inbox("t", "design", "question", "Which price?")
    task = store.add_task("t", "waiting work", "social")
    store.park_task(task, item, "question")
    backlog.cmd_inbox(_args(company, answer_to=item, answer="49 EUR"))
    out = capsys.readouterr().out
    assert f"answered {item}" in out and "unblocked 1 task(s)" in out


def test_answering_twice_says_it_was_already_answered(company, capsys):
    store = _store(company)
    item = store.add_inbox("t", "design", "question", "Which price?")
    backlog.cmd_inbox(_args(company, answer_to=item, answer="49 EUR"))
    capsys.readouterr()
    backlog.cmd_inbox(_args(company, answer_to=item, answer="49 EUR"))
    assert "already answered, or no such item" in capsys.readouterr().out
