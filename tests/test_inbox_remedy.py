"""A notice has to say what to do *in the console*.

Reported from a real console: the CEO filed "Providers are failing — 25 failed
call(s) recently. Run `corparius preflight` to see which configured models still
answer", with a button labelled "Ouvrir les fournisseurs". Three things wrong at
once, and the operator said the plain version of it: this does not say clearly
enough what I am supposed to do.

- The remedy was a **terminal command**, told to somebody reading a web page.
- The console has had a button doing exactly that all along.
- And the button offered opened a tab and stopped, leaving the operator in front of
  nine provider rows with no idea which control was the answer.

So: the agent's note carries the measured fact, and the console carries the next
step, in the operator's language. `fix` is the seam.
"""

import re
from pathlib import Path

import pytest

from corparius.inbox import FIXES

PAGE = Path("corparius/webui.html")
TOOLS = Path("corparius/tools.py")


def _i18n_keys(lang: str) -> set[str]:
    html = PAGE.read_text(encoding="utf-8")
    block = html[html.index("const I18N = {") : html.index("const urlq =")]
    table = (
        block[block.index("en:") : block.index("fr:")]
        if lang == "en"
        else block[block.index("fr:") :]
    )
    return set(re.findall(r'"([a-zA-Z][\w.-]*\.[\w.-]+)":', table))


def test_no_notice_tells_the_operator_to_open_a_terminal():
    """The console is the surface. An agent note naming a shell command is asking
    somebody looking at a web page to go and be a developer."""
    offenders = [
        line.strip()
        for line in TOOLS.read_text(encoding="utf-8").splitlines()
        if "corparius " in line and "`" in line and "inbox.notify" not in line and "#" not in line
    ]
    # Narrow to the ones that are notice or question text rather than docs.
    shouting = [o for o in offenders if o.startswith(('"', 'f"', "'"))]
    assert not shouting, f"a notice names a terminal command: {shouting}"


@pytest.mark.parametrize("fix", sorted(FIXES))
def test_every_fix_has_a_button_label_in_both_languages(fix):
    """A fix with no label renders a button with a key in it."""
    for lang in ("en", "fr"):
        assert f"ib.fix.{fix}" in _i18n_keys(lang), f"ib.fix.{fix} missing from {lang}"


@pytest.mark.parametrize("fix", sorted(FIXES))
def test_every_fix_says_what_pressing_it_will_do(fix):
    """The sentence the operator was missing. "Open providers" says where to look;
    it does not say what to do once there."""
    for lang in ("en", "fr"):
        assert f"ib.next.{fix}" in _i18n_keys(lang), f"ib.next.{fix} missing from {lang}"


def test_every_fix_points_at_a_tab_that_exists():
    """A notice pointing at a tab nobody built renders a button that does nothing,
    which is worse than the log line it replaced."""
    tabs = set(re.findall(r'aria-controls="tab-([a-z]+)"', PAGE.read_text(encoding="utf-8")))
    missing = sorted(dest for dest in FIXES.values() if dest not in tabs)
    assert not missing, f"fixes point at tabs that do not exist: {missing}"


def test_the_provider_failure_notice_offers_to_run_the_preflight():
    """Not merely to open the tab. The label of the fix and the label of the
    control it presses are the same words on purpose."""
    src = TOOLS.read_text(encoding="utf-8")
    assert 'fix="preflight"' in src, "the notice still only opens the providers tab"
    html = PAGE.read_text(encoding="utf-8")
    assert '"ib.fix.preflight":"Prove these models"' in html
    assert '"prov.preflight":"Prove these models"' in html, "the two labels have drifted apart"
    # And the handler actually presses it.
    assert 'ibFix === "preflight"' in html and "#run-preflight" in html
