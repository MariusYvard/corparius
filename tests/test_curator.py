"""The maintenance half of the learning loop, and mostly a file about restraint.

`write_skill` lets the company write down what failed twice. Without a curator that becomes the
failure mode Hermes Agent's own docstring names — "hundreds of narrow skills where each one
captures one session's specific bug" — and here it is worse than a cluttered folder, because a
skill goes into a prompt. An unread one is not clutter, it is spend.

So most of these tests are about what the sweep leaves alone: the operator's skills, a skill
still in use, and a skill that has never run yet because the tool it is scoped to has not come
round. Archiving that last one would delete the answer before the question was asked again.
"""

import time

import pytest

from corparius import curator
from corparius.kernel import paths
from corparius.skills import SkillLoader
from corparius.store import Store
from corparius.tools.effects import AGENT_AUTHOR

DAY = 86400.0


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture()
def store(home):
    s = Store(str(home / "data"))
    yield s
    s.close()


def _skill(name, *, mine=True, age_days=0.0, tool="draft_social_post"):
    """A skill folder. `mine` means the company wrote it; otherwise the operator did."""
    folder = paths.company_skills_dir("acme") / name
    folder.mkdir(parents=True, exist_ok=True)
    author = f"author: {AGENT_AUTHOR}\n" if mine else ""
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\nallowed-tools: {tool}\n{author}---\nbody\n",
        encoding="utf-8",
    )
    if age_days:
        old = time.time() - age_days * DAY
        import os

        os.utime(folder, (old, old))
    return folder


def _live():
    folder = paths.company_skills_dir("acme")
    return sorted(p.parent.name for p in folder.glob("*/SKILL.md"))


def _archived():
    folder = paths.company_skills_dir("acme") / curator.ARCHIVE
    return sorted(p.parent.name for p in folder.glob("*/SKILL.md")) if folder.is_dir() else []


# --- what it leaves alone ----------------------------------------------------


def test_the_operators_own_skills_are_never_touched(store):
    """The promise `EXTRA_DIRS` already makes, extended to the curator: the person running the
    business keeps the last word. Not stale, not archived, not even counted as a candidate."""
    _skill("theirs", mine=False, age_days=400)
    report = curator.sweep(store, "acme")
    assert _live() == ["theirs"]
    assert report["archived"] == [] and report["theirs"] == 1


def test_a_skill_in_use_stays(store):
    _skill("busy")
    store.record_skill_use("acme", ["busy"])
    report = curator.sweep(store, "acme")
    assert _live() == ["busy"] and report["kept"] == ["busy"]


def test_a_skill_that_has_never_run_gets_a_grace_period(store):
    """`write_skill` scopes a skill to the tool that failed, and that tool may not come round
    for weeks. Archiving it for never having been used would delete the answer before the
    question was asked again."""
    _skill("not-yet", age_days=5)
    report = curator.sweep(store, "acme")
    assert _live() == ["not-yet"] and report["waiting"] == ["not-yet"]


def test_a_sweep_that_cannot_read_usage_archives_nothing(store, monkeypatch):
    """The safe direction. Not knowing what has been used is not evidence that nothing has."""
    _skill("old", age_days=400)

    def boom(*a, **k):
        raise RuntimeError("locked")

    monkeypatch.setattr(store, "skill_usage", boom)
    assert curator.sweep(store, "acme")["archived"] == []
    assert _live() == ["old"]


def test_a_company_with_no_skills_folder_is_not_an_error(store):
    assert curator.sweep(store, "brand-new") == {
        "archived": [],
        "kept": [],
        "waiting": [],
        "theirs": 0,
    }


# --- what it archives --------------------------------------------------------


def test_a_skill_nothing_has_read_in_a_month_is_archived(store):
    _skill("stale")
    store.record_skill_use("acme", ["stale"], now=time.time() - 40 * DAY)
    report = curator.sweep(store, "acme")
    assert _live() == []
    assert _archived() == ["stale"]
    assert report["archived"][0]["name"] == "stale"
    assert "unread for 40 days" in report["archived"][0]["why"]


def test_a_skill_never_used_past_the_grace_period_is_archived(store):
    _skill("never", age_days=60)
    report = curator.sweep(store, "acme")
    assert _archived() == ["never"]
    assert "never used in 60 days" in report["archived"][0]["why"]


def test_nothing_is_ever_deleted(store):
    """Archived means moved. The archive is the operator's record of what their company
    decided, and a curator that deletes is one an operator cannot audit."""
    _skill("gone", age_days=100)
    curator.sweep(store, "acme")
    body = (paths.company_skills_dir("acme") / curator.ARCHIVE / "gone" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "body" in body


def test_the_archive_is_invisible_to_the_loader(store):
    """The reason the archive is a folder rather than a flag: `_discover` globs `*/SKILL.md`,
    one level, so `.archive/x/SKILL.md` is structurally out of reach. Nothing has to remember
    to filter it."""
    _skill("stale", age_days=100)
    curator.sweep(store, "acme")
    loader = SkillLoader.for_company("acme")
    assert loader.skills == []
    assert loader.context_for("draft_social_post") == ""


def test_archiving_the_same_name_twice_keeps_both(store):
    """Two versions of one skill are both part of the record."""
    _skill("twice", age_days=100)
    curator.sweep(store, "acme")
    _skill("twice", age_days=100)
    curator.sweep(store, "acme")
    kept = _archived()
    assert len(kept) == 2 and "twice" in kept


def test_the_usage_row_goes_with_the_skill(store):
    """Otherwise a skill written again under the same name inherits a `last_used` from before
    it was archived, and the next sweep archives it immediately — the company keeps answering
    a question and keeps having the answer taken away."""
    _skill("recurring")
    store.record_skill_use("acme", ["recurring"], now=time.time() - 40 * DAY)
    curator.sweep(store, "acme")
    assert store.skill_usage("acme") == {}
    # Written again today: it must now get the grace period, not instant archival.
    _skill("recurring")
    assert curator.sweep(store, "acme")["waiting"] == ["recurring"]
    assert _live() == ["recurring"]


# --- what it tells the operator ---------------------------------------------


def test_the_operator_is_told_once_not_once_per_skill(store):
    """Same lesson as `Executor._stood_down`: a warning repeated every day is a warning nobody
    reads. One notice naming all of them."""
    for name in ("a-one", "b-two", "c-three"):
        _skill(name, age_days=100)
    curator.sweep(store, "acme")
    notices = [n for n in store.list_inbox("acme") if n["agent"] == "curator"]
    assert len(notices) == 1
    body = notices[0]["body"]
    assert "a-one" in body and "b-two" in body and "c-three" in body
    assert "Nothing was deleted" in body


def test_a_quiet_sweep_says_nothing(store):
    """Nothing archived, nothing to report. A notice per sweep would be a daily message saying
    the company is fine."""
    _skill("busy")
    store.record_skill_use("acme", ["busy"])
    curator.sweep(store, "acme")
    assert [n for n in store.list_inbox("acme") if n["agent"] == "curator"] == []


def test_no_model_is_called(store, monkeypatch):
    """Deterministic by construction. Hermes ships its LLM consolidation pass disabled by
    default; this does not have the pass at all, because merging two skills is the one
    operation here that can lose meaning."""
    import corparius.llm as llm_mod

    monkeypatch.setattr(
        llm_mod.HybridRouter,
        "generate",
        lambda *a, **k: pytest.fail("the curator called a model"),
    )
    _skill("stale", age_days=100)
    assert curator.sweep(store, "acme")["archived"]
