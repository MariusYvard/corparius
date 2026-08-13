"""The site's own review pass: what it measures, and what it refuses to claim.

The console was taken through thirteen rounds of *generate, review, fix, review again* by an agent that
had never seen it, and the finding that matters for the product is which reviews were worth acting on:
the ones carrying a number. "The card sits at 1.044:1 against its own page" produced a fix in minutes;
"it lacks compositional intent" produced four rounds of guessing. So the generated site gets the first
kind, and `corparius/sitegen/critique.py` is only allowed to say things it can prove.

This file holds three properties: the checks fire on real defects, they stay silent on a good page, and
**the pairs it measures are the pairs the page actually paints** — that last one is the guard on the
guard, because a contrast check that has not been told about a surface passes it by definition. The
reason it exists at all is `sitegen`'s own history: a dark pricing band shipped at 1.16:1, near-black
on near-black, and nothing in the repository knew what contrast was.
"""

import pathlib
import re

import pytest

from corparius.sitegen import critique, palette

# --- what it measures -----------------------------------------------------------


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_a_generated_palette_has_nothing_to_report(theme):
    """`palette_for` computes readable values rather than choosing them, so a finding here means the
    generator's own guarantee broke — which is exactly the regression this is for."""
    found = critique.contrast_findings(critique.palette_pairs(palette.palette_for(theme)))
    assert not found, [f.line() for f in found]


def test_the_band_that_shipped_at_1_16_would_be_caught():
    """The defect this module exists for, reconstructed: near-black text on the near-black pricing band.
    Measured rather than asserted as a shape — the finding has to carry the ratio."""
    pairs = [("pricing band", "#14110e", "#241f1a")]
    ratio = palette.contrast("#14110e", "#241f1a")
    assert ratio < 1.5, f"the reconstruction is not the defect: {ratio:.2f}:1"
    found = critique.contrast_findings(pairs)
    assert len(found) == 1
    assert f"{ratio:.2f}:1" in found[0].measure
    assert "pricing band" in found[0].line()


def test_every_surface_the_stylesheet_paints_is_measured():
    """The guard on the guard. A contrast check knows only about the pairs it was given, so a surface
    added to `style.py` and not added here passes by omission — which is the shape of the original bug,
    not a new one.

    Asserted against `palette_for`'s own keys: every colour it resolves for *text* must appear as the
    foreground of some measured pair. `accent_deep` is excluded and says why in the palette itself — it
    is a button's bottom edge, decoration with nothing on it.
    """
    resolved = palette.palette_for("light")
    measured = {text for _where, text, _bg in critique.palette_pairs(resolved)}
    text_keys = {"fg", "muted", "on_ink", "on_ink_muted", "on_accent"}
    for key in sorted(text_keys):
        assert resolved[key] in measured, f"{key} is text the page paints and nothing measures it"
    assert len(critique.palette_pairs(resolved)) >= len(text_keys)


# --- what it says about the words -----------------------------------------------


def test_an_offline_draft_reaching_the_page_is_a_finding_and_is_fixable():
    """`[mock:` on the page means an offline draft was used as a headline. It has happened, it is what
    `build_site`'s own fallback exists to prevent, and it is the one placeholder a redraft can fix."""
    found = critique.copy_findings("[mock:claude-3-5-haiku] Company: CVBoost.", "x" * 900)
    assert found, "an echoed mock draft has to be a finding"
    assert any(f.fixable_by_copy for f in found)
    assert any("[mock:" in f.what for f in found)


def test_a_label_is_not_a_claim():
    """A three-word H1 that names the company says nothing a visitor can act on. Fixable by copy, so it
    reaches the next draft's brief."""
    found = critique.copy_findings("CVBoost", "y" * 900)
    assert any("label rather than a claim" in f.what for f in found)
    assert all(f.fixable_by_copy for f in found if "label" in f.what)


def test_a_paragraph_is_not_a_headline():
    found = critique.copy_findings("A " * 80, "y" * 900)
    assert any("paragraph" in f.what for f in found)
    assert any("characters" in f.measure for f in found if f.measure)


def test_a_real_headline_and_a_real_page_report_nothing():
    """The silent case, and it has to be silent: a critique that always finds something is a critique
    nobody reads twice. This headline and length are from a real generation."""
    head = "An AI resume optimiser that rewrites a CV to match a target job description"
    assert not critique.copy_findings(head, "z" * 1600), "a good page must produce no findings"


def test_a_thin_page_is_a_finding_the_model_cannot_fix():
    """Four hundred characters is a stub, and no headline rewrite changes that — it is the company's
    configuration. So it must **not** be marked fixable by copy, or the loop would send a model to do
    something it cannot."""
    found = [
        f
        for f in critique.copy_findings("A clear claim about the product", "z" * 400)
        if f.where == "page"
    ]
    assert found and not found[0].fixable_by_copy


# --- what the loop does with them ------------------------------------------------


def test_the_brief_carries_only_what_a_redraft_can_fix():
    """The loop's whole content. Telling a model to raise a contrast ratio it cannot see produces an
    apology, not a fix, so the brief holds the copy findings and the build says the rest out loud."""
    findings = critique.copy_findings("CVBoost", "z" * 400) + critique.contrast_findings(
        [("pricing band", "#14110e", "#241f1a")]
    )
    brief = critique.brief(findings)
    assert brief, "there were fixable findings and the brief is empty"
    assert "label rather than a claim" in brief
    assert "1.16" not in brief and "pricing band" not in brief, (
        "a model cannot fix a colour it cannot see"
    )
    assert brief.count("\n- ") >= 1


def test_no_findings_means_no_brief():
    """An empty instruction is worse than none: it spends a prompt saying nothing and teaches the next
    turn that the loop always talks."""
    assert critique.brief([]) == ""
    good = critique.copy_findings("An AI resume optimiser that rewrites a CV", "z" * 1600)
    assert critique.brief(good) == ""


# --- the layer rule -------------------------------------------------------------


def test_the_module_stays_in_its_layer():
    """Rank 4. A critique that reached the network or the store would be a critique that cannot run in a
    test, and `tests/test_layers.py` holds the rule for the package — this says it at the file, where
    somebody adding an import will read it."""
    source = pathlib.Path("corparius/sitegen/critique.py").read_text(encoding="utf-8")
    for banned in ("import requests", "import subprocess", "import sqlite3", "time.sleep"):
        assert banned not in source, f"critique.py reaches for {banned}"
    imports = re.findall(r"^from \.(\w+) import|^from \.\.(\S+) import", source, re.M)
    flat = [a or b for a, b in imports]
    assert flat == ["palette"], f"critique.py should need only the palette, it imports {flat}"
