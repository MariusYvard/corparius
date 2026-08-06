"""Durable memory: what a company learned, kept past the third day.

corparius already re-read the last three end-of-day summaries, which is what
stops a --loop company planning each morning as if it had just been born. But a
three-day horizon erases everything it learns about its market, and that is what
this adds. The two are kept apart deliberately: ctx.memory is still yesterday,
read positionally by set_daily_plan.
"""

import types

from corparius.agents import _messages, language_line
from corparius.kernel.records import AgentRole
from corparius.roster import ROSTER
from corparius.store import Store
from corparius.tools.registry import TOOLS


def test_a_fact_survives_and_comes_back(tmp_path):
    store = Store(str(tmp_path))
    store.remember("t", "ceo", "Career coaches buy, job seekers churn.", "three months of data")
    facts = [r["fact"] for r in store.recall("t")]
    assert facts == ["Career coaches buy, job seekers churn."]


def test_the_same_fact_restated_is_not_stored_twice(tmp_path):
    """An agent asked the same question every day restates one observation with
    different word order, casing and punctuation. That is what the deduplicator
    catches, and it is the shape the failure actually takes."""
    store = Store(str(tmp_path))
    assert store.remember("t", "ceo", "Career coaches buy, job seekers churn.")
    assert store.remember("t", "ceo", "job seekers churn -- career coaches BUY") == 0
    assert len(store.list_memory("t")) == 1


def test_a_true_paraphrase_is_not_caught_and_that_is_deliberate(tmp_path):
    """The comparison is a bag of tokens, not a language model. Loosening it
    until it caught this would start merging facts that only sound alike, which
    loses information instead of saving space."""
    store = Store(str(tmp_path))
    store.remember("t", "ceo", "Career coaches buy, job seekers churn.")
    assert store.remember("t", "ceo", "Our coaching customers stay; individuals leave.")
    assert len(store.list_memory("t")) == 2


def test_a_genuinely_different_fact_is_kept(tmp_path):
    store = Store(str(tmp_path))
    store.remember("t", "ceo", "Career coaches buy, job seekers churn.")
    store.remember("t", "strategy", "ATS parsing breaks on two-column layouts.")
    assert len(store.list_memory("t")) == 2


def test_recall_ranks_by_relevance_to_the_prompt(tmp_path):
    store = Store(str(tmp_path))
    store.remember("t", "ceo", "Career coaches buy, job seekers churn.")
    store.remember("t", "ceo", "ATS parsing breaks on two-column layouts.")
    top = store.recall("t", query="what breaks in ATS parsing", limit=1)
    assert "ATS parsing" in top[0]["fact"]


def test_a_pinned_fact_outranks_a_more_relevant_one(tmp_path):
    """Pinning is the operator saying "this one always goes in front of the
    model". Relevance must not outvote them."""
    store = Store(str(tmp_path))
    store.remember("t", "ceo", "ATS parsing breaks on two-column layouts.")
    pid = store.remember("t", "ceo", "Never claim a callback rate.")
    store.pin_memory(pid)
    assert store.recall("t", query="ATS parsing", limit=1)[0]["id"] == pid


def test_the_cap_drops_the_oldest_unpinned_and_never_a_pinned_one(tmp_path):
    """max_rows caps unpinned facts. Counting pinned ones against it would mean
    that pinning enough facts silently stops the company from learning."""
    store = Store(str(tmp_path))
    pid = store.remember("t", "ceo", "keep me forever")
    store.pin_memory(pid)
    for i in range(10):
        store.remember("t", "ceo", f"disposable observation number {i}", max_rows=3)
    kept = store.list_memory("t")
    unpinned = [r for r in kept if not r["pinned"]]
    assert len(unpinned) == 3
    assert pid in [r["id"] for r in kept], "the cap discarded a pinned fact"
    assert "number 9" in unpinned[0]["fact"], "the cap dropped the newest instead of the oldest"


def test_the_operator_can_forget_something_the_agent_got_wrong(tmp_path):
    store = Store(str(tmp_path))
    mid = store.remember("t", "ceo", "Everyone loves us.")
    assert store.forget(mid) is True
    assert store.list_memory("t") == []
    assert store.forget(mid) is False


def test_memory_is_scoped_to_one_company(tmp_path):
    store = Store(str(tmp_path))
    store.remember("a", "ceo", "A learned something.")
    assert store.recall("b") == []


def test_an_empty_fact_is_not_stored(tmp_path):
    store = Store(str(tmp_path))
    assert store.remember("t", "ceo", "   ") == 0
    assert store.list_memory("t") == []


def test_recalled_facts_reach_the_system_prompt(tmp_path):
    store = Store(str(tmp_path))
    store.remember("t", "ceo", "Never claim a callback rate.")
    ctx = types.SimpleNamespace(
        company={"slug": "t", "name": "T", "offer": {}},
        memory=[],
        leads=[],
        store=store,
        memory_top_k=5,
    )
    spec = ROSTER[AgentRole.OUTREACH]
    system = _messages(spec, ctx, TOOLS["send_outreach"])[0]["content"]
    assert "Never claim a callback rate." in system


def test_recall_off_costs_nothing(tmp_path):
    """memory_top_k is 0 when the setting is off, and 0 by default on a context
    built by hand — every existing caller."""
    store = Store(str(tmp_path))
    store.remember("t", "ceo", "Never claim a callback rate.")
    ctx = types.SimpleNamespace(
        company={"slug": "t", "name": "T", "offer": {}}, memory=[], leads=[], store=store
    )
    spec = ROSTER[AgentRole.OUTREACH]
    # Still exact equality, against a baseline that now includes the one
    # unconditional line every prompt carries: the company's language. The
    # property under test is that nothing *else* is added, so weakening this
    # to a substring check would have retired the test rather than updated it.
    assert _messages(spec, ctx, TOOLS["send_outreach"])[0]["content"] == (
        f"{spec.system_prompt}\n\n{language_line(ctx.company)}"
    )


def test_daily_plan_still_reads_yesterday_not_a_recalled_fact(tmp_path):
    """set_daily_plan reads ctx.memory[0] positionally. Merging durable facts
    into that list would have made memory[0] a fact instead of yesterday, and
    broken the tool without breaking a test."""
    store = Store(str(tmp_path))
    store.remember("t", "ceo", "A durable fact about the market.")
    ctx = types.SimpleNamespace(
        company={"slug": "t", "name": "T", "offer": {}},
        memory=["Yesterday we shipped the pricing page."],
        store=store,
        memory_top_k=5,
    )
    prompt = TOOLS["set_daily_plan"].draft_prompt(ctx)
    assert "Yesterday we shipped the pricing page." in prompt
    assert "durable fact" not in prompt


def test_the_remember_tool_writes_what_the_schema_validated(tmp_path):
    store = Store(str(tmp_path))
    ctx = types.SimpleNamespace(
        company={"slug": "t", "name": "T"},
        store=store,
        role="ceo",
        structured=types.SimpleNamespace(
            data={"fact": "Coaches renew, seekers do not.", "why": "cohort data"}
        ),
    )
    out = TOOLS["remember"].run(ctx, "")
    assert out.ok and "Coaches renew" in out.output
    row = store.list_memory("t")[0]
    assert row["fact"] == "Coaches renew, seekers do not." and row["why"] == "cohort data"


def test_the_remember_tool_says_so_when_it_already_knew(tmp_path):
    store = Store(str(tmp_path))
    store.remember("t", "ceo", "Coaches renew, seekers do not.")
    ctx = types.SimpleNamespace(
        company={"slug": "t", "name": "T"},
        store=store,
        role="ceo",
        structured=types.SimpleNamespace(data={"fact": "seekers do not, coaches renew!"}),
    )
    assert "Already known" in TOOLS["remember"].run(ctx, "").output


def test_the_remember_tool_is_harmless_and_ungated(tmp_path):
    """It writes to the operator's own store and nothing leaves the process."""
    from corparius.config.permissions import READ, PermissionEngine

    assert TOOLS["remember"].risk == READ
    assert not PermissionEngine().evaluate(TOOLS["remember"], "t").needs_user
