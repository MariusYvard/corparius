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


# --- a remedy on the tab it is shown on must actually do something -------------


def test_the_backlog_remedy_is_settled_in_place_not_by_switching_tabs():
    """Reported twice by the operator: "nothing happens when I click Open the
    backlog". The notice renders on the Operations tab, and the remedy switched to
    the Operations tab — so pressing it was a no-op by construction.

    A fix whose destination is the tab the notice is already on cannot be a
    tab switch. It has to carry controls."""
    from corparius.inbox import FIXES

    html = PAGE.read_text(encoding="utf-8")
    # The notices are rendered into #inbox, which lives on the operations tab.
    assert FIXES["backlog"] == "operations"
    assert "ibAssign(m, d)" in html, "the notice does not render its own controls"
    assert "data-ib-assign=" in html and "data-ib-owner=" in html and "data-ib-tool=" in html
    # And the tab-switch button is suppressed for a notice that can be settled here,
    # rather than sitting next to the controls doing nothing.
    assert "m.fix && !ibTask(m) ?" in html


def test_the_assignment_reaches_the_task_api_and_resolves_the_notice():
    html = PAGE.read_text(encoding="utf-8")
    handler = html[html.index("if (b.dataset.ibAssign)") : html.index("if (b.dataset.ibFix)")]
    assert '"/api/tasks"' in handler and "decision:" in handler
    assert "target: owner.value" in handler and "tool: tool.value" in handler
    assert '"/api/inbox"' in handler, "the notice would stay pending after being settled"


def test_changing_the_agent_re_offers_that_agents_tools():
    """Otherwise Assign hands a task a tool the chosen agent never runs — the
    untooled task again, wearing a different hat."""
    html = PAGE.read_text(encoding="utf-8")
    assert 'const owner = ev.target.closest("[data-ib-owner]")' in html
    block = html[html.index('const owner = ev.target.closest("[data-ib-owner]")') :][:900]
    assert "agent_tools" in block and "tool.innerHTML" in block


def test_a_notice_can_carry_the_task_it_is_about():
    """`inbox.notify` is idempotent on the title, so the id belongs in the title:
    two held tasks used to collapse into one notice, and settling one left the
    other invisible."""
    src = Path("corparius/agents.py").read_text(encoding="utf-8")
    assert "f\"Task #{task['id']} is waiting for an owner\"" in src
    assert "options=(f\"task:{task['id']}\",)" in src
