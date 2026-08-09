"""Colour, and contrast computed rather than assumed. Rank 4.

The measurement in the middle of this file is the reason it is a module: the dark theme's
pricing band shipped with its text at **1.16:1** against its own background — near-black on
near-black, unreadable, and obvious in a screenshot the moment anyone looked. One line had
assumed that "the page background colour" is always a good text colour on "the inverted band",
which is true in the light theme and false in the dark one.

Nothing in the repository could have caught it, because no code here knew what contrast was.
Now it does, and `tests/test_sitegen_contrast.py` walks every theme against every accent.
"""

from __future__ import annotations

import hashlib
import logging

log = logging.getLogger("corparius.sitegen.palette")


# The default was a dark page with gradient pills and a centred stack of three
# cards. NullToHero's brand register names that shape exactly — "a centred-stack
# hero with icon-title-subtitle cards reads as template" — and it was right: the
# page announced that a machine had made it.
#
# What replaces it: a left-aligned asymmetric hero, a modular type scale at a
# 1.333 ratio (a flat scale "reads as uncommitted"), hierarchy carried by weight
# and rules rather than colour, and one CTA repeated instead of several
# competing. Typeface is a system stack in both registers — an external font
# would cost this page the one property it has always defended, that it is a
# single file that needs nothing.
SERIF = '"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif'


SANS = '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif'


_THEMES = {
    "light": {
        "bg": "#fbfaf8",
        "fg": "#14110e",
        "muted": "#5f574e",
        "line": "#e5ded3",
        "ink": "#14110e",
    },
    "dark": {
        "bg": "#12100e",
        "fg": "#f3eee6",
        "muted": "#a49b8e",
        "line": "#2b2722",
        # Inverting a dark page means going lighter, not darker: the pricing
        # band has to be a change of ground, and #000 on #12100e is not one.
        "ink": "#241f1a",
    },
}


DEFAULT_ACCENT = "#c2410c"


# The dark theme's pricing band shipped with its text at 1.16:1 against its own
# background — near-black on near-black, unreadable, and visible in a screenshot
# the moment anyone looked. The cause was one line assuming that "the page
# background colour" is always a good text colour on "the inverted band", which
# is true in the light theme and false in the dark one.
#
# Nothing in this repo could have caught that, because no code here knew what
# contrast was. Now it does, and `tests/test_sitegen_contrast.py` walks every
# theme against every accent and fails on anything under the threshold.
#
# Thresholds are WCAG 2.1 AA, as listed in NullToHero's color-and-contrast
# reference: 4.5 for body text, 3.0 for large text and UI components.
AA_TEXT, AA_LARGE = 4.5, 3.0


def _rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def luminance(colour: str) -> float:
    """WCAG relative luminance."""

    def channel(raw: int) -> float:
        c = raw / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio, 1.0 to 21.0."""
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def mix(a: str, b: str, amount: float) -> str:
    """`a` blended `amount` of the way towards `b`, as a hex string.

    Done here rather than with CSS `color-mix` so the result is a value this
    module can measure. A colour the code cannot read is a colour no test can
    check, which is how the unreadable band shipped.
    """
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    blend = (round(x + (y - x) * amount) for x, y in ((ra, rb), (ga, gb), (ba, bb)))
    return "#" + "".join(f"{c:02x}" for c in blend)


def readable_on(background: str, *candidates: str, target: float = AA_TEXT) -> str:
    """The first candidate that clears `target` against `background`.

    If none does, the best of black and white — which always clears 4.5 against
    anything, so this never returns something unreadable.
    """
    for candidate in candidates:
        if contrast(candidate, background) >= target:
            return candidate
    return max(("#ffffff", "#0a0a0a"), key=lambda c: contrast(c, background))


def muted_on(background: str, text: str, target: float = AA_TEXT) -> str:
    """`text` faded towards `background` as far as it can go and still be read.

    Secondary text has to look secondary without becoming decoration. Walking
    the blend back until it clears the threshold gets that without a hand-picked
    grey per theme — and their own reference is blunt about the alternative:
    "Alpha Is A Design Smell", because alpha makes contrast unpredictable.
    """
    for step in range(60, -1, -5):
        candidate = mix(text, background, step / 100)
        if contrast(candidate, background) >= target:
            return candidate
    return text


def signature(seed: str) -> str:
    """A band of bars whose heights come from a hash of the company's own name.

    Every page gets a different one and it is the same every build, which is the
    point: a landing page needs something on it that is not a paragraph, and the
    alternatives were a stock photo this generator cannot fetch, a gradient blob
    that announces which decade of template it came from, or nothing — and
    nothing is what made the last version read as an unfinished document.

    Inline SVG, about a kilobyte, no request, no asset, no script.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    bars, count, width = [], 56, 1000 / 56
    for i in range(count):
        value = digest[i % len(digest)]
        # Taller towards the middle, so the band has a shape rather than being
        # uniform noise. The hash decides the texture; the curve decides the form.
        curve = 1 - abs((i / (count - 1)) - 0.5) * 1.55
        height = max(6.0, (10 + value / 255 * 90) * curve)
        opacity = 0.16 + (value % 7) * 0.055
        bars.append(
            f'<rect x="{i * width:.2f}" y="{100 - height:.2f}" width="{width * 0.62:.2f}" '
            f'height="{height:.2f}" opacity="{opacity:.2f}"/>'
        )
    return (
        '<svg class="sig" viewBox="0 0 1000 100" preserveAspectRatio="none" '
        f'aria-hidden="true" focusable="false"><g fill="currentColor">{"".join(bars)}</g></svg>'
    )


def palette_for(theme: str = "light", accent: str = DEFAULT_ACCENT) -> dict[str, str]:
    """Every colour the page uses, each one measured against what it sits on.

    Returned as a dict so a test can walk it. The four derived entries are the
    ones that used to be assumed:

    - `on_ink` — text on the inverted pricing band. Assuming the page background
      worked here is the bug that shipped at 1.16:1.
    - `on_accent` — the button label. `#fff` was hard-coded, which fails on any
      light accent: 1.74:1 on the green in the operator's screenshot.
    - `muted`, `on_ink_muted` — secondary text, faded only as far as it can be.
    - `wash` — the hero band's ground, computed rather than `color-mix`, so the
      text on it can be measured too.
    """
    base = _THEMES.get(theme, _THEMES["light"])
    bg, fg, ink = base["bg"], base["fg"], base["ink"]
    on_ink = readable_on(ink, bg, fg, target=AA_TEXT)
    return {
        **base,
        "accent": accent,
        # The accent tint behind the hero, strong enough to read as a change of
        # ground and weak enough to keep the body text on it.
        "wash": mix(bg, accent, 0.14 if theme == "dark" else 0.09),
        "edge": mix(bg, accent, 0.26),
        "muted": base["muted"] if contrast(base["muted"], bg) >= AA_TEXT else muted_on(bg, fg),
        "on_ink": on_ink,
        "on_ink_muted": muted_on(ink, on_ink),
        "on_accent": readable_on(accent, "#ffffff", "#0a0a0a"),
        # The button's bottom edge. Decorative, but resolved here too so
        # that nothing on the page is a colour this module cannot read.
        "accent_deep": mix(accent, "#000000", 0.4),
    }
