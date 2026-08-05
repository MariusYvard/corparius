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

They are **not** merged here, and that is deliberate. Merging would either silently rename
the directories of companies already installed on operators' machines, or reintroduce the
accent bug in the two places that fixed it. So the identical pair became `slugify`, the odd
one became `slugify_loose` under its own name and with the gap written down, and the fix is
a separate job with a directory migration attached. A wrong thing that is labelled is
findable; a wrong thing folded into a right one is not.

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


def slugify_loose(name: str) -> str:
    """`slugify` without the accent folding or the length cap. **Known wrong**, and kept
    only because it named directories that exist on disk.

    Its single caller derives a company's folder from its name. Switching it to `slugify`
    is a one-word change and a rename migration for every installed company whose name
    carries an accent — a product decision, not a refactor. Until that is taken, the two
    behaviours have two names, so nobody picks the broken one by accident.
    """
    return _NOT_SLUG.sub("-", name.strip().lower()).strip("-")
