"""`docs/reverse-engineering/` is a registry, and it had no test at either end.

Six studies of competing products sit in that folder, and `comparatif.md` is supposed to be
the index: one row per product, a sentence in "Ce que corparius prend à chacun", and the
source it was read from. Nothing checked that.

Both failure directions are silent and both have already happened in this project's other
registries. A new study with no row is work nobody can find — the reason the folder exists is
that these findings turn into code, and `test_assign_held`, `test_blocked_outreach` and
`test_owned_site` all cite `nanocorp.md` by name in their docstrings. A row for a study that
was renamed or removed sends a reader to a file that is not there.

The rule this file applies is the project's uniform one (see test_registries.py): every entry
is reached, and everything reached is registered.
"""

import re
from pathlib import Path

import pytest

FOLDER = Path("docs/reverse-engineering")
INDEX = FOLDER / "comparatif.md"

# The index is not a study of itself.
STUDIES = sorted(p.stem for p in FOLDER.glob("*.md") if p.name != INDEX.name)


def _index() -> str:
    return INDEX.read_text(encoding="utf-8")


def _table_rows() -> set[str]:
    """The first cell of each row of the positioning table, lowercased.

    Matched on the leading `| ` of a line rather than by product name, so a study whose title
    differs from its filename still has to appear — the check is "is it in the table", not "is
    the string somewhere in the file", which a passing mention in prose would satisfy.
    """
    rows = re.findall(r"^\| ([^|]+?) \|", _index(), re.M)
    skip = {"solution", "---"}
    return {r.strip().lower() for r in rows if r.strip().lower() not in skip}


def test_there_is_something_to_check():
    """The guard on the guard. An empty `STUDIES` would make every assertion below pass."""
    assert len(STUDIES) >= 6, f"only {len(STUDIES)} studies found; the glob stopped matching"
    assert INDEX.is_file(), "the index is gone, so nothing below means anything"


@pytest.mark.parametrize("study", STUDIES)
def test_every_study_has_a_row_in_the_comparison(study):
    """A study with no row is a study nobody finds. `corparius` is itself a row, and the
    filenames are hyphenated where the product names are not, so the comparison is on the
    words rather than on the slug."""
    words = [w for w in study.split("-") if len(w) > 3]
    rows = " ".join(_table_rows())
    assert any(w in rows for w in words), (
        f"{study}.md has no row in comparatif.md. Add one, or say in the file why it is not "
        "a product being positioned against."
    )


@pytest.mark.parametrize("study", STUDIES)
def test_every_study_says_what_corparius_takes_from_it(study):
    """The section that turns a study into work. A fiche that describes a competitor and
    concludes nothing is the "just observed it" failure — the folder exists because these
    findings become code."""
    body = (FOLDER / f"{study}.md").read_text(encoding="utf-8")
    assert re.search(r"^#+ .*(en tire|prend|retient|Ce que corparius)", body, re.M | re.I), (
        f"{study}.md has no section saying what corparius takes from it. A study that "
        "concludes nothing is a study that changed nothing."
    )


@pytest.mark.parametrize("study", STUDIES)
def test_every_study_names_at_least_one_source(study):
    """Prove it, do not ask to be believed. These documents make claims about somebody else's
    code, and a claim with no URL cannot be re-checked when their code moves."""
    body = (FOLDER / f"{study}.md").read_text(encoding="utf-8")
    assert "http" in body or "https" in _index(), (
        f"{study}.md cites no source, and comparatif.md has no URL either"
    )


def test_the_comparison_names_no_study_that_does_not_exist():
    """The mirror. A row pointing at a renamed or deleted file sends a reader nowhere, and
    the index is the only place that would have said so."""
    linked = set(re.findall(r"\]\(([a-z0-9-]+)\.md\)", _index()))
    ghosts = sorted(linked - set(STUDIES))
    assert not ghosts, f"comparatif.md links to studies that do not exist: {ghosts}"


def test_every_source_url_is_listed_once():
    """Sources accumulate as products are studied, and a duplicate reads as two sources
    supporting a claim when there is one."""
    urls = re.findall(r"^- (https?://\S+)$", _index(), re.M)
    duplicated = sorted({u for u in urls if urls.count(u) > 1})
    assert not duplicated, f"the same source is listed twice: {duplicated}"
    assert len(urls) >= len(STUDIES) - 1, (
        f"{len(urls)} sources for {len(STUDIES)} studies. One study may legitimately have no "
        "public URL; two suggests a source was not written down."
    )
