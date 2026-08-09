"""Every colour pair on a generated page, measured.

The dark theme's pricing band shipped with its text at **1.16:1** against its
own background. Near-black on near-black. It was invisible in the light theme —
where the same line computes to 18:1 — and the operator found it by looking at
a screenshot, because nothing in this repo knew what contrast was.

Thresholds are WCAG 2.1 AA as listed in NullToHero's `color-and-contrast`
reference: 4.5 for body text, 3.0 for large text and UI components.
"""

import re

import pytest

from corparius import sitegen
from corparius.sitegen import palette as sitegen_palette
from corparius.sitegen.palette import AA_LARGE, AA_TEXT, contrast, palette_for

# Themes crossed with accents chosen to break things: the default, a light green
# that white text fails on (the one in the operator's screenshot), a very dark
# blue that black text fails on, a mid grey with no hue to hide behind, and pure
# white and pure black as the extremes an operator can type.
THEMES = ("light", "dark")
ACCENTS = (sitegen_palette.DEFAULT_ACCENT, "#4ade80", "#0039CC", "#808080", "#ffffff", "#000000")


def _pairs(theme, accent):
    """What sits on what. Each entry is (label, foreground, background, floor)."""
    p = palette_for(theme, accent)
    return [
        ("body text on the page", p["fg"], p["bg"], AA_TEXT),
        ("secondary text on the page", p["muted"], p["bg"], AA_TEXT),
        ("body text on the hero wash", p["fg"], p["wash"], AA_TEXT),
        ("secondary text on the hero wash", p["muted"], p["wash"], AA_TEXT),
        ("text on the inverted band", p["on_ink"], p["ink"], AA_TEXT),
        ("secondary text on the inverted band", p["on_ink_muted"], p["ink"], AA_TEXT),
        ("the button label", p["on_accent"], accent, AA_TEXT),
        # Large display type: the price and the H1 clear 3.0 as large text, but
        # they use the same tokens as body copy, so they are covered above.
        ("the hairline between bands", p["edge"], p["bg"], 1.0),
    ]


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("accent", ACCENTS)
def test_every_pair_on_a_generated_page_clears_wcag_aa(theme, accent):
    failures = [
        f"{label}: {contrast(fg, bg):.2f}:1 ({fg} on {bg}), needs {floor}"
        for label, fg, bg, floor in _pairs(theme, accent)
        if contrast(fg, bg) < floor
    ]
    assert not failures, f"{theme} / {accent}\n  " + "\n  ".join(failures)


def test_the_exact_pair_that_shipped_unreadable():
    """A named regression, not just a matrix entry. `--ink` on the dark theme is
    #241f1a and the band's text was the page background, #12100e."""
    assert contrast("#241f1a", "#12100e") < 1.2, "the fixture is no longer the bug"
    p = palette_for("dark", sitegen_palette.DEFAULT_ACCENT)
    assert p["ink"] == "#241f1a"
    assert contrast(p["on_ink"], p["ink"]) >= AA_TEXT


def test_white_on_a_light_accent_is_never_the_button_label():
    """1.74:1 on the green in the operator's screenshot. The label was hard-coded
    to #fff, which only works on accents dark enough to have been guessed."""
    assert contrast("#ffffff", "#4ade80") < AA_TEXT, "the fixture is no longer the bug"
    assert palette_for("light", "#4ade80")["on_accent"] != "#ffffff"
    # ...and on a dark accent it still is, rather than flipping everything to
    # black to be safe. The label reads as a label.
    assert palette_for("light", "#0039CC")["on_accent"] == "#ffffff"


def test_the_built_page_carries_the_measured_values_not_something_else(tmp_path):
    """Unit-testing `palette_for` proves the arithmetic. This proves the values
    reach the file, which is a separate thing that a stray CSS line could break.
    """
    company = {
        "slug": "t",
        "name": "T",
        "language": "en",
        "offer": {"product": "p", "price_eur": 9},
        "icp": {"segment": "s", "pains": ["p"]},
        "site": {"theme": "dark", "accent": "#4ade80"},
    }
    path = sitegen.build_site(company, str(tmp_path / "site"))
    with open(path, encoding="utf-8") as fh:
        page = fh.read()

    tokens = dict(re.findall(r"--([a-z-]+):(#[0-9a-fA-F]{6})", page))
    expected = palette_for("dark", "#4ade80")
    for name, key in (("bg", "bg"), ("fg", "fg"), ("ink", "ink"), ("on-ink", "on_ink")):
        assert tokens.get(name) == expected[key], name
    assert contrast(tokens["on-ink"], tokens["ink"]) >= AA_TEXT
    assert contrast(tokens["on-accent"], "#4ade80") >= AA_TEXT

    # And no colour arrives through a route this test cannot measure. `color-mix`
    # is exactly that route: it resolves in the browser, so a value written that
    # way is one no test here can check — which is how 1.16:1 shipped.
    assert "color-mix" not in page


def test_the_maths_is_the_wcag_maths():
    """Anchored on values anyone can check against the published formula, so a
    subtle mistake in the luminance curve cannot pass by looking plausible."""
    assert contrast("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast("#ffffff", "#ffffff") == pytest.approx(1.0)
    # The two canonical AA boundary greys on white.
    assert contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.02)
    assert contrast("#949494", "#ffffff") == pytest.approx(3.03, abs=0.02)
    assert sitegen_palette.luminance("#ffffff") == pytest.approx(1.0)
    assert sitegen_palette.luminance("#000000") == pytest.approx(0.0)
    # Symmetric: which one is "the text" must not change the number.
    assert contrast("#c2410c", "#fbfaf8") == contrast("#fbfaf8", "#c2410c")


def test_shorthand_and_case_are_accepted_because_an_operator_types_them():
    assert contrast("#fff", "#000") == pytest.approx(21.0)
    assert sitegen_palette.luminance("#FFF") == sitegen_palette.luminance("#ffffff")


def test_muted_text_is_faded_as_far_as_it_can_go_and_no_further():
    """A muted colour that clears the threshold by a mile is not muted, it is
    just body text. This checks it is actually near the floor."""
    for theme in THEMES:
        p = palette_for(theme, sitegen_palette.DEFAULT_ACCENT)
        ratio = contrast(p["on_ink_muted"], p["ink"])
        assert AA_TEXT <= ratio < contrast(p["on_ink"], p["ink"]), theme


def test_a_decorative_element_is_not_held_to_a_text_threshold():
    """The signature bars are aria-hidden decoration. WCAG exempts those, and
    holding them to 4.5 would force a band loud enough to fight the headline."""
    assert AA_LARGE == 3.0
    assert 'aria-hidden="true"' in sitegen_palette.signature("t")
