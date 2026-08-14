"""What the memory payload says about its own size, and why the console needed it said.

The card rendered every fact a company had ever learned as one flat list, and on the real company that
is **55 facts, 13 933 characters, 16 pinned, written over 6.9 days** — about eight a day, mean fact 253
characters. Two things were invisible in that list and both are the operator's business:

**The cost.** These facts are pasted into prompts by `store.recall`, so their *length* is what gets
paid for, not their count. Same reasoning as `skills.always_on_chars()`, which already counts the tax
an unscoped skill puts on every turn.

**The ceiling.** `store.remember` caps *unpinned* rows at `CORP_MEMORY_MAX` and deletes the oldest past
it. At eight facts a day the default of 200 arrives in about three weeks, and the company then starts
forgetting with nothing on screen to say so. A pin is the operator saying "this one stays" — neither
counted against the cap nor dropped by it — which is why `unpinned` is reported rather than the total.

The number that would organise this list best is not here: **how often each fact actually reached a
prompt.** `skill_usage` has `uses` and `last_used`; `memory` has neither, and `store.recall` is the one
place that knows. That is a migration and a write on a hot read path, so it is named here rather than
smuggled in — grouping by `agent` needed no schema change and answers the question that was asked.
"""

import pytest

from corparius.app import overview as app_overview
from corparius.store import Store

COMPANY = "example"


class Settings:
    """The two fields `app_overview.memory` reads. `memory_max` mirrors `config.settings.Settings`,
    which resolves `CORP_MEMORY_MAX` once for the whole process — the cap is read from there rather
    than re-read from `cfg` here, so the console cannot draw a ceiling the store does not enforce."""

    def __init__(self, enabled=True, memory_max=200):
        self.memory_enabled = enabled
        self.memory_max = memory_max


@pytest.fixture
def store(tmp_path):
    made = Store(str(tmp_path))
    yield made
    made.close()


# Genuinely different sentences, not a numbered template. `remember` deduplicates on a cosine over
# `hash_embed` at 0.95, and "The 3 pricing experiment..." against "The 4 pricing experiment..." differs
# by a single token — the first version of this fixture asked for ten rows and got nine, which is the
# dedup working correctly and the fixture being wrong about what it wrote.
SENTENCES = [
    "The payment link belongs to the merchant account and the old one is abandoned",
    "Nobody has replied to a cold email sent before nine in the morning",
    "Two of the three leads came from a referral rather than the site",
    "The pricing page converts better without the annual toggle on it",
    "Support tickets peak on Monday and almost none arrive at the weekend",
    "The database holds no real customer rows, only seeded test identifiers",
    "A generated headline naming the buyer outperforms one naming the product",
    "Hosting is on a static bucket, so a deploy cannot break the checkout",
    "The founder signs emails personally and the reply rate doubles when he does",
    "Every enrichment call is billed even when it returns nothing usable",
    "The competitor raised prices in June and said so on their changelog",
    "Invoices go out on the first, and chasing them before the tenth annoys people",
]


def _fill(store, count, *, pinned=0, why="because it stays true"):
    assert count <= len(SENTENCES), "add more sentences rather than numbering a template"
    for index in range(count):
        store.remember(COMPANY, "ceo", SENTENCES[index], why, pinned=index < pinned)


# --- the cost -------------------------------------------------------------------


def test_the_payload_carries_the_characters_not_just_the_count(store):
    """Length is the unit because length is what a prompt pays."""
    _fill(store, 3)
    said = app_overview.memory(store, Settings(), COMPANY)
    expected = sum(len(row["fact"]) + len(row["why"]) for row in store.list_memory(COMPANY))
    assert said["chars"] == expected
    assert said["chars"] > len(said["memory"]), "characters cannot be a row count"


def test_a_switched_off_memory_reports_nothing_rather_than_stale_numbers(store):
    """`memory_enabled` off means the list is empty, and the budget has to agree — a card reading
    "0 facts, 13 933 characters" is worse than one that says the feature is off."""
    _fill(store, 3)
    said = app_overview.memory(store, Settings(enabled=False), COMPANY)
    assert said["memory"] == [] and said["chars"] == 0 and said["unpinned"] == 0
    assert said["memory_enabled"] is False


# --- the ceiling ----------------------------------------------------------------


def test_the_cap_reported_is_the_settings_cap_and_not_a_second_reading(store, monkeypatch):
    """The whole point of sending `cap`. Two surfaces claiming one number is the failure this
    repository keeps finding, and here it would draw a ceiling the store does not have — so the
    payload has to follow `settings.memory_max` wherever it goes, including somewhere unusual."""
    assert app_overview.memory(store, Settings(memory_max=12), COMPANY)["cap"] == 12
    assert app_overview.memory(store, Settings(memory_max=7), COMPANY)["cap"] == 7

    # And the settings field is really the resolved `CORP_MEMORY_MAX`, or the line above is pinning a
    # stub to itself.
    monkeypatch.setenv("CORP_MEMORY_MAX", "31")
    from corparius.config import cfg
    from corparius.config import settings as settings_mod

    cfg.invalidate()
    assert settings_mod.Settings().memory_max == 31


def test_pinned_facts_are_not_counted_against_the_cap(store):
    """`store.remember` excludes pinned rows from the cap, so counting them here would tell an
    operator they are sixteen facts nearer a limit they are not."""
    _fill(store, 10, pinned=4)
    said = app_overview.memory(store, Settings(), COMPANY)
    assert len(said["memory"]) == 10
    assert said["unpinned"] == 6, "unpinned must exclude what the operator chose to keep"


def test_the_cap_is_real_and_drops_the_oldest_unpinned(store):
    """Not a claim about the payload but about the thing it reports: at the cap the company starts
    forgetting. Proved rather than trusted, because the whole warning rests on it."""
    for sentence in SENTENCES[:8]:
        store.remember(COMPANY, "ceo", sentence, max_rows=5)
    kept = [row["fact"] for row in store.list_memory(COMPANY)]
    assert len(kept) == 5, f"the cap did not hold: {len(kept)} rows"
    assert SENTENCES[7] in kept, "the newest has to survive"
    assert SENTENCES[0] not in kept, "the oldest goes first"


def test_a_pinned_fact_survives_the_cap(store):
    """The other half, and the reason the console tells an operator to pin what must stay."""
    store.remember(COMPANY, "ceo", SENTENCES[0], pinned=True)
    for sentence in SENTENCES[1:8]:
        store.remember(COMPANY, "ceo", sentence, max_rows=3)
    facts = [row["fact"] for row in store.list_memory(COMPANY)]
    assert any("payment link" in fact for fact in facts), "a pin must outlive the cap"


# --- what the console groups by --------------------------------------------------


def test_every_fact_carries_the_agent_that_wrote_it(store):
    """The axis the card groups by, and it has to be present on every row or a group appears named
    after nothing. Measured on the real company: ceo 33, strategy 12, outreach 6, design 2,
    finance 2 — five genuinely different kinds of fact."""
    for role in ("ceo", "strategy", "outreach"):
        store.remember(COMPANY, role, f"What {role} found out about the {role} channel this week")
    rows = app_overview.memory(store, Settings(), COMPANY)["memory"]
    assert {row["agent"] for row in rows} == {"ceo", "strategy", "outreach"}
    assert all(row.get("ts") for row in rows), "every fact needs a time or the order is arbitrary"
