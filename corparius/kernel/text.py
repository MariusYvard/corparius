"""Turning a human string into a URL-safe one. Rank 0: pure.

Three functions did this, in two modules, and one of them carried the bug the other two
document as fixed. `company._slugify` and `sitegen._slugify` were **identical to the byte**,
docstring included; `company.slugify` was a third spelling with no accent folding and no
length cap, and its only caller was the line that derives a company's directory name.

Measured on the string that made the difference visible:

    « Méthode et Architecture »
      company._slugify  -> methode-et-architecture
      sitegen._slugify  -> methode-et-architecture
      company.slugify   -> m-thode-et-architecture   <- the company's own folder

They are **not** merged here, and that is deliberate — but not for the reason it first
looked like. The plan assumed the fix needed a rename migration. Measured, it does not:
`company.load` sets the slug from the *directory name* before validation runs, so for a
company already on disk both spellings are idempotent. The broken one only ever produced a
directory in one place, the creation wizard, where no slug is given and it is derived from
the name.

So the two names are two jobs, and that is the fix: **derive with `slugify`, preserve with
`slugify_loose`**. A company created from now on gets a slug that survives its own name;
nothing already installed is renamed. Merging them would truncate an existing folder name
longer than 48 characters and point its config at a directory that is not there.

Two modules also reached across a package boundary for `company._slugify` — a private name,
imported by `documents` and `tools`. That stops here too.

"""

from __future__ import annotations

import re
import unicodedata

_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """A URL-safe slug that survives accents.

    `[^a-z0-9-]+` turned "Méthode et architecture" into `m-thode-et-architecture` — the
    accent became a hyphen and the word lost a letter. A French company got a broken URL for
    every page it wrote, which is the kind of thing nobody notices until it is in a sitemap.

    Capped at 48 characters because these become file names, and a title can be a sentence.
    """
    folded = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return _NOT_SLUG.sub("-", folded.lower()).strip("-")[:48]


def slugify_loose(slug: str) -> str:
    """Normalise a slug that **already exists**, without folding or truncating it.

    This is the preserving half, and the distinction is the fix for the bug above. A slug
    that arrives from `company.load` is the name of a directory on disk: folding it would
    be a no-op (it has no accents left to fold), but the 48-character cap would not — a
    company whose folder is longer than that would have its config point at a directory
    that is not there.

    So: derive with `slugify`, preserve with this. Nothing on disk is renamed, and a
    company created from now on gets a slug that survives its own name.
    """
    return _NOT_SLUG.sub("-", slug.strip().lower()).strip("-")
