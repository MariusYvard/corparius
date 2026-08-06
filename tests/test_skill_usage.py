"""When a skill was last actually used — the prerequisite for ever archiving one.

A skill reaches a prompt when the tool about to run is named in its `allowed-tools`, and until
schema 17 that left no trace. Fine while an operator writes every skill by hand and can see
the folder; not fine at all once an agent can write one. Hermes Agent's curator names the
failure mode in its own docstring — "hundreds of narrow skills where each one captures one
session's specific bug" — and here it is worse than clutter, because an unscoped skill rides
on **every prompt of every turn** and `always_on_chars()` already measures that tax.

The distinction this file defends is the one that makes the counter mean anything: **rendering
a skill on a page is not using it.** The console builds loaders to draw a catalogue and to warn
about unscoped skills. If those counted, the curator would be told everything is in service
and would archive nothing.
"""

import time

import pytest

from corparius.skills import SkillLoader
from corparius.store import Store

SKILL = """---
name: outreach-tone
description: How this company words a first email.
allowed-tools: send_outreach
---
Short sentences. Name the problem before the product.
"""


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path / "data"))
    yield s
    s.close()


def _loader(tmp_path, store=None, slug="acme", body=SKILL):
    folder = tmp_path / "skills" / "outreach-tone"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(body, encoding="utf-8")
    return SkillLoader([(tmp_path / "skills", slug)], store=store, slug=slug)


def test_a_skill_that_reaches_a_prompt_is_counted(tmp_path, store):
    loader = _loader(tmp_path, store)
    assert loader.context_for("send_outreach"), "the skill should be in scope"
    usage = store.skill_usage("acme")
    assert usage["outreach-tone"]["uses"] == 1
    assert usage["outreach-tone"]["last_used"] > 0


def test_the_count_accumulates(tmp_path, store):
    loader = _loader(tmp_path, store)
    for _ in range(3):
        loader.context_for("send_outreach")
    assert store.skill_usage("acme")["outreach-tone"]["uses"] == 3


def test_a_tool_out_of_scope_counts_nothing(tmp_path, store):
    """`for_tool` answers "would this apply". Only `context_for` answers "did it go"."""
    loader = _loader(tmp_path, store)
    assert loader.context_for("reconcile_stripe") == ""
    assert store.skill_usage("acme") == {}


def test_asking_whether_it_applies_is_not_using_it(tmp_path, store):
    """The console asks this to render a catalogue, and a page view is not a prompt."""
    loader = _loader(tmp_path, store)
    assert loader.for_tool("send_outreach"), "in scope"
    assert loader.catalog(), "and listed"
    assert store.skill_usage("acme") == {}, "neither of those is use"


def test_a_loader_with_no_store_still_works(tmp_path):
    """Every read-only caller builds one this way — `skillcli`, the doctor, the console. A
    counter is not a reason for them to open a database."""
    loader = _loader(tmp_path, store=None)
    assert loader.context_for("send_outreach")


def test_a_failing_counter_does_not_cost_the_turn(tmp_path, store, monkeypatch):
    """Best-effort, and deliberately. What depends on the count is a curator's judgement of
    what to archive, and a curator that archives nothing is a folder that grows — recoverable.
    A turn that dies because a bookkeeping write failed is not."""

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "record_skill_use", boom)
    loader = _loader(tmp_path, store)
    assert loader.context_for("send_outreach"), "the prompt still gets its skill"


def test_the_timestamp_can_be_stated_so_age_is_testable(store):
    """The only thing that reads `last_used` is a decision about age. A test of that decision
    has to be able to say when, rather than wait thirty days."""
    long_ago = time.time() - 40 * 86400
    store.record_skill_use("acme", ["stale-one"], now=long_ago)
    assert store.skill_usage("acme")["stale-one"]["last_used"] == pytest.approx(long_ago)


def test_two_companies_keep_separate_counts(tmp_path, store):
    """Keyed by (company, skill): a company skill of the same name replaces a global one on
    purpose, and one company's use says nothing about another's."""
    _loader(tmp_path / "a", store, slug="acme").context_for("send_outreach")
    _loader(tmp_path / "b", store, slug="other").context_for("send_outreach")
    _loader(tmp_path / "b", store, slug="other").context_for("send_outreach")
    assert store.skill_usage("acme")["outreach-tone"]["uses"] == 1
    assert store.skill_usage("other")["outreach-tone"]["uses"] == 2


def test_a_truncated_skill_still_counts(tmp_path, store):
    """It was cut to fit the budget, not dropped — its opening still shaped the prompt, and a
    skill that keeps getting truncated is exactly what a curator should be able to see."""
    long_body = SKILL + "\n" + ("filler. " * 2000)
    folder = tmp_path / "skills" / "outreach-tone"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(long_body, encoding="utf-8")
    loader = SkillLoader([(tmp_path / "skills", "acme")], max_chars=200, store=store, slug="acme")
    out = loader.context_for("send_outreach")
    assert "[truncated]" in out
    assert store.skill_usage("acme")["outreach-tone"]["uses"] == 1
