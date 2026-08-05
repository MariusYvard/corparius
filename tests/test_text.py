"""The two slug spellings, and the gap between them held open on purpose.

Three functions did this job across two modules. Two were identical to the byte, docstring
included. The third had no accent folding and no length cap, and its only caller was the
line that derives a company's directory name — so the one spelling that reached the file
system was the broken one.

These tests are not here to say the behaviour is right. They are here so that changing it
has to be a decision: `slugify_loose` is wrong, is named, and the fix costs a rename
migration for every installed company whose name carries an accent.
"""

from corparius.kernel.text import slugify, slugify_loose


def test_a_slug_survives_an_accent():
    """`[^a-z0-9-]+` turned "Méthode et architecture" into `m-thode-et-architecture` — the
    accent became a hyphen and the word lost a letter. A French company got a broken URL
    for every page it wrote, and nobody notices until it is in a sitemap."""
    assert slugify("Méthode et Architecture") == "methode-et-architecture"
    assert slugify("Prospection à froid") == "prospection-a-froid"


def test_a_slug_is_capped_because_it_becomes_a_file_name():
    assert len(slugify("un titre " * 20)) == 48


def test_the_loose_spelling_still_mangles_an_accent_and_this_is_measured():
    """The defect, pinned. It is what named the directories that exist on operators'
    machines, so making this test go green by pointing `slugify_loose` at `slugify` would
    silently rename a company's folder out from under it.

    When that migration is written, this test changes with it — deliberately, in a diff
    that says so.
    """
    assert slugify_loose("Méthode et Architecture") == "m-thode-et-architecture"
    assert slugify_loose("Méthode et Architecture") != slugify("Méthode et Architecture")


def test_the_two_spellings_agree_on_everything_without_an_accent():
    """The gap is exactly one thing — folding — plus the cap. If they diverged anywhere
    else, "keep both" would be hiding a second difference nobody had looked at."""
    for name in ("Vigil", "corp SEO 2026", "  Spaced  Out  ", "a-b-c"):
        assert slugify(name) == slugify_loose(name), name
