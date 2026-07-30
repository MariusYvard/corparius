"""An agent that produces what nobody consumes should stop, not accelerate.

Measured on one operator's real day: the social agent was the largest line in
the company's spend — 29 065 tokens, more than the CEO and support together —
and `schedule_post`'s entire effect was returning the string "Post scheduled
for +2h". Nothing was stored. Every post it wrote was gone before the next tick
wrote another, and the next tick came every two hours.

Two things were wrong and both are here: the drafts are kept, and the agent
stands down once they pile up.
"""

import pytest

from corparius import agents, cfg
from corparius.models import AgentRole
from corparius.store import Store
from corparius.tools import TOOLS


def _ctx(store, slug="t", channel="linkedin", structured=None):
    return type(
        "Ctx",
        (),
        {
            "store": store,
            "company": {"slug": slug, "icp": {"channels": [channel]}},
            "structured": structured,
        },
    )()


def _drafted(text="Vigil: 90s pour voir venir", tags=("a", "b")):
    return type(
        "R",
        (),
        {"data": {"headline": text, "body": text, "hashtags": list(tags)}, "fell_back": False},
    )()


# --- the draft is kept ------------------------------------------------------


def test_a_drafted_post_is_written_down(tmp_path):
    """It is `draft_social_post` that holds the text: ctx.structured is reset
    between tools, so a draft not stored here is not stored at all — which is
    exactly what used to happen."""
    store = Store(str(tmp_path))
    TOOLS["draft_social_post"].run(_ctx(store, structured=_drafted()), draft="{}")
    rows = store.list_drafts("t")
    assert len(rows) == 1
    assert "90s pour voir venir" in rows[0]["body"]
    assert "#a" in rows[0]["body"] and rows[0]["channel"] == "linkedin"
    store.close()


def test_two_turns_do_not_lose_the_first_post(tmp_path):
    """The whole defect in one assertion."""
    store = Store(str(tmp_path))
    TOOLS["draft_social_post"].run(_ctx(store, structured=_drafted("first")), draft="{}")
    TOOLS["draft_social_post"].run(_ctx(store, structured=_drafted("second")), draft="{}")
    bodies = [r["body"] for r in store.list_drafts("t")]
    assert any("first" in b for b in bodies) and any("second" in b for b in bodies)
    store.close()


def test_scheduling_promotes_everything_waiting(tmp_path):
    """A draft written by a backlog task runs draft_social_post on its own,
    with no schedule_post after it. Promoting only the newest stranded those in
    `draft` for ever — counted by nothing, published by nothing."""
    store = Store(str(tmp_path))
    for n in range(3):
        TOOLS["draft_social_post"].run(_ctx(store, structured=_drafted(f"post {n}")), draft="{}")
    out = TOOLS["schedule_post"].run(_ctx(store), draft="")
    assert store.count_drafts("t", "draft") == 0
    assert store.count_drafts("t", "queued") == 3
    assert "3 post(s) waiting" in out.output
    store.close()


def test_scheduling_says_plainly_that_nothing_publishes_them(tmp_path):
    """ "Scheduled for +2h" was true of nothing. An operator reading the log
    should learn that these are waiting on them, not on a clock."""
    store = Store(str(tmp_path))
    TOOLS["draft_social_post"].run(_ctx(store, structured=_drafted()), draft="{}")
    out = TOOLS["schedule_post"].run(_ctx(store), draft="")
    assert "Nothing publishes them yet" in out.output
    assert "+2h" not in out.output
    store.close()


def test_scheduling_nothing_says_so(tmp_path):
    store = Store(str(tmp_path))
    assert "Nothing drafted" in TOOLS["schedule_post"].run(_ctx(store), draft="").output
    store.close()


# --- and the agent stops ----------------------------------------------------


class _Exec(agents.Executor):
    def __init__(self, store):
        super().__init__(router=None, gate=None, store=store, settings=None)


def test_the_social_agent_stands_down_once_the_queue_is_full(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_SOCIAL_QUEUE_MAX", "3")
    cfg.invalidate()
    store = Store(str(tmp_path))
    for n in range(3):
        store.add_draft("t", "social", "linkedin", f"post {n}", state="queued")
    done: list[str] = []
    assert _Exec(store)._stood_down("t", agents.ROSTER[AgentRole.SOCIAL], done) is True
    assert "stood down" in done[0] and "3 post(s)" in done[0]
    store.close()


def test_it_keeps_working_while_the_queue_is_shallow(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_SOCIAL_QUEUE_MAX", "5")
    cfg.invalidate()
    store = Store(str(tmp_path))
    store.add_draft("t", "social", "linkedin", "one", state="queued")
    assert _Exec(store)._stood_down("t", agents.ROSTER[AgentRole.SOCIAL], []) is False
    store.close()


def test_the_operator_is_told_once_not_once_per_tick(tmp_path, monkeypatch):
    """A warning repeated every two hours is a warning nobody reads. notify() is
    idempotent on the title, so the count lives in the body."""
    monkeypatch.setenv("CORP_SOCIAL_QUEUE_MAX", "2")
    cfg.invalidate()
    store = Store(str(tmp_path))
    for n in range(4):
        store.add_draft("t", "social", "linkedin", f"p{n}", state="queued")
    ex = _Exec(store)
    for _ in range(5):
        ex._stood_down("t", agents.ROSTER[AgentRole.SOCIAL], [])
    notices = [i for i in store.list_inbox("t") if "piling up" in i["title"]]
    assert len(notices) == 1, "one notice, however many turns stood down"
    assert "4 posts are written" in notices[0]["body"]
    store.close()


@pytest.mark.parametrize("role", [AgentRole.CEO, AgentRole.SUPPORT, AgentRole.FINANCE])
def test_no_other_role_stands_down_on_social_drafts(tmp_path, monkeypatch, role):
    """The queue is the social agent's own output. Stopping finance because
    posts piled up would be a different bug."""
    monkeypatch.setenv("CORP_SOCIAL_QUEUE_MAX", "1")
    cfg.invalidate()
    store = Store(str(tmp_path))
    store.add_draft("t", "social", "linkedin", "p", state="queued")
    assert _Exec(store)._stood_down("t", agents.ROSTER[role], []) is False
    store.close()


# --- the ceiling that froze every session ----------------------------------


def test_a_new_company_can_run_a_real_quarter_day_without_freezing():
    """A tenth of the session budget was calibrated against mock runs. Against
    real providers one agent's turn is three or four calls of a thousand tokens,
    and several agents land in the same wall-clock minute — six SECURISE freezes
    in one measured session."""
    from corparius.company import validate

    cfg_out, _errors, _warnings = validate(
        {"slug": "t", "name": "T", "budgets": {"session_tokens": 120_000}}
    )
    assert cfg_out["budgets"]["tokens_per_minute"] >= 20_000


def test_a_ceiling_too_low_to_work_is_named_as_such():
    """vigil declared 8000 and froze six times. Accepting it silently is what
    made that look like corparius misbehaving rather than a setting."""
    from corparius.company import validate

    _cfg, _errors, warnings = validate(
        {
            "slug": "t",
            "name": "T",
            "budgets": {"session_tokens": 120_000, "tokens_per_minute": 8000},
        }
    )
    assert any("circuit breaker will freeze" in w for w in warnings)


def test_the_freeze_notice_names_the_setting_that_actually_tripped():
    """It said "Raise CORP_TOKENS_PER_MINUTE_LIMIT", which a company that sets
    its own budget does not read at all."""
    import inspect

    from corparius import orchestrator

    source = inspect.getsource(orchestrator)
    assert "budgets.tokens_per_minute" in source
