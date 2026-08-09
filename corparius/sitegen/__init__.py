"""Sales-site generator. Rank 4.

One landing page built from a company config, as a single self-contained HTML file — inline CSS,
no build step, no external asset. Where NullToHero is a broad design-and-audit toolkit, this is
the straight-to-the-point path: config in, a sellable page out, with a checkout CTA wired to a
Stripe payment link.

This was 1 339 lines in one module. Eight now, split by what a reader is looking for, and the
imports run one way:

```text
base        esc and norm, the two every other file reaches for
palette     colour, and contrast computed rather than assumed
copy        what the page says, and the two things it refuses to write
style       the stylesheet, emitted from a palette
head        the tags a stranger never sees and a crawler reads first
sections    the optional blocks, each absent unless the config supplies it
companions  robots.txt and sitemap.xml, which are files and not tags
build       one page, assembled
```

**Stage 9 rebuilds the console, not this.** A generated sales page has no framework and wants
none: it is read by a stranger on a phone in one round trip, and every byte is inline on purpose.
The framework decision applies to `webui.html`, which is a different program that happens to be
written in the same language.

Unlike `api/`, these modules import **names** rather than each other, and that was measured
rather than preferred: every name here is unique across the eight files, and three of the module
names — `base`, `head`, `palette` — are already bound as local variables in this code. Qualified
access would have made `head.opening(...)` resolve against a string.

`build_site` is re-exported because it is the entry point and the only name outside this package
needs: 19 call sites, against 6 for the next most-used. The rest are imported from their real
homes, which is what keeps `tests/test_layers.py` able to see the edges.
"""

from __future__ import annotations

from .build import build_site

__all__ = ["build_site"]
