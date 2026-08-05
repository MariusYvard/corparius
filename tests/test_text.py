"""The two slug spellings, and the gap between them held open on purpose.

Three functions did this job across two modules. Two were identical to the byte, docstring
included. The third had no accent folding and no length cap, and its only caller was the
line that derives a company's directory name — so the one spelling that reached the file
system was the broken one.

The plan assumed fixing it meant renaming directories. Measured, it did not: `company.load`
sets the slug from the *directory name* before validation, so both spellings are idempotent
for anything already on disk. The broken one only reached the file system through the
creation wizard, which derives a slug from a name.

So the two functions are two jobs — derive, and preserve — and these tests pin the seam.
"""

import pytest

from corparius import company
from corparius.kernel.text import slugify, slugify_loose


def test_a_slug_survives_an_accent():
    """`[^a-z0-9-]+` turned "Méthode et architecture" into `m-thode-et-architecture` — the
    accent became a hyphen and the word lost a letter. A French company got a broken URL
    for every page it wrote, and nobody notices until it is in a sitemap."""
    assert slugify("Méthode et Architecture") == "methode-et-architecture"
    assert slugify("Prospection à froid") == "prospection-a-froid"


def test_a_slug_is_capped_because_it_becomes_a_file_name():
    assert len(slugify("un titre " * 20)) == 48


def test_the_two_spellings_agree_on_everything_without_an_accent():
    """The gap is exactly two things — folding and the cap. If they diverged anywhere else,
    keeping both would be hiding a difference nobody had looked at."""
    for name in ("Vigil", "corp SEO 2026", "  Spaced  Out  ", "a-b-c"):
        assert slugify(name) == slugify_loose(name), name


def test_preserving_never_truncates_because_the_slug_is_a_folder_that_exists():
    """Why the two are not merged. A company whose directory is longer than 48 characters
    would have its config point at a folder that is not there."""
    long_slug = "a" * 60
    assert slugify_loose(long_slug) == long_slug
    assert slugify(long_slug) != long_slug


def test_a_new_company_gets_a_slug_that_survives_its_own_name():
    """The bug, at the one place it ever reached the file system: the creation wizard gives
    no slug, so it is derived from the name. This is what put `m-thode-et-architecture` on
    disk for a French company, and a broken URL in its sitemap."""
    cfg, errors, _ = company.validate(
        {"name": "Méthode et Architecture", "offer": {"product": "conseil"}}
    )
    assert not errors, errors
    assert cfg["slug"] == "methode-et-architecture"


@pytest.mark.parametrize("existing", ["m-thode-et-architecture", "vigil", "a" * 60])
def test_an_installed_company_is_never_renamed(existing):
    """The other half, and the reason this needed no migration: `load` fills the slug from
    the directory name, so validation must hand back exactly what it was given. A company
    already on disk keeps its folder, broken spelling and all."""
    cfg, errors, _ = company.validate(
        {"name": "Méthode et Architecture", "slug": existing, "offer": {"product": "conseil"}}
    )
    assert not errors, errors
    assert cfg["slug"] == existing
