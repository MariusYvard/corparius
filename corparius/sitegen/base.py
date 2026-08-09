"""The two helpers every other module here reaches for. Rank 4.

49 call sites for `esc` and 5 for `norm`, across six modules — which is the whole reason this
file exists, and the same reason `store/base.py` does.

Not in `kernel/text`, which is where the plan's module list put them. Measured: nothing outside
this package uses either, and promoting a one-line wrapper to rank 0 on the strength of a list
is the speculative generality this project keeps refusing. `slugify` is in `kernel/text`
because four packages call it; these are sitegen's.
"""

from __future__ import annotations

import html as _html
import re


def esc(value) -> str:
    return _html.escape(str(value))


def norm(text: str) -> str:
    """Loose comparison, for deciding whether two strings say the same thing."""
    return re.sub(r"[^\w]+", " ", str(text or "").lower()).strip()
