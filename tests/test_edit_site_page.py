"""Acting on the review, instead of writing the same list down again.

`review_site` reads a company's own pages and files what to change; its docstring called that "a
punch list that names files and quotes text, which is what the operator **or a later task** acts
on". There was no later task. Measured on a real install, three consecutive design days:

```text
    tick 265   Site reviewed: 17 change(s) written to documents
    tick 273   Site reviewed: 16 change(s) written to documents
    tick 281   Site reviewed: 18 change(s) written to documents
```

The same faults re-found every time, because **no tool in the package writes into a company's own
site**: `write_site_content` refuses (the copy would go to `company.yaml`, which this company does
not render from) and `build_sales_site` refuses (it will not overwrite a site somebody wrote). The
operator's site could not improve. It was not slow, it was impossible.

**Text only, and that is what makes it safe rather than brave.** The objection in that docstring is
real: editing hand-written HTML from a prompt, with no build and no test, is how a working site
becomes a broken one. So neither side of the change may contain `<` or `>` — the structure of the
document cannot change, only the words in it. And every finding the review actually produces is a
wording fix; the worst one on the real run was *"index.html annonce au présent 'Vigil apprend ce qui
est normal pour vous' : la promesse n'est pas encore livrée"*, which is the first test below.

The rest are refusals, and each is the cheapest check for a different way this could go wrong: a page
that is not the company's, markup in the change, a quote the page does not contain, and a quote it
contains twice.
"""

import pathlib
import types

import pytest

from corparius.config import cfg
from corparius.tools.registry import TOOLS

PAGE = (
    "<!doctype html><meta charset='utf-8'>"
    "<link rel='stylesheet' href='/assets/style.css'>"
    "<h1>Le check-in mental fait pour ceux qui tiennent bon</h1>"
    "<p>Vigil apprend ce qui est normal pour vous, et signale un écart durable.</p>"
    "<p>Un mot répété, et le même mot répété.</p>"
)


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cfg.invalidate()
    folder = tmp_path / "companies" / "vigil" / "site"
    folder.mkdir(parents=True)
    (folder / "index.html").write_text(PAGE, encoding="utf-8")
    (folder / "tech.html").write_text("<h1>Architecture</h1>", encoding="utf-8")
    return folder


def _run(**data):
    ctx = types.SimpleNamespace(
        company={"slug": "vigil", "name": "Vigil"},
        store=None,
        structured=types.SimpleNamespace(data=data),
    )
    return TOOLS["edit_site_page"].run(ctx)


# --- the change it exists to make --------------------------------------------------


def test_the_finding_from_the_real_run_is_applied(site):
    """The wording the design agent flagged on three consecutive days and could never fix."""
    result = _run(
        page="index.html",
        find="Vigil apprend ce qui est normal pour vous, et signale un écart durable",
        replace="Vigil apprendra ce qui est normal pour vous et signalera un écart durable",
        why="le présent annonçait une capacité qui n'est pas encore livrée",
    )
    assert result.ok is True, result.output

    now = (site / "index.html").read_text(encoding="utf-8")
    assert "Vigil apprendra ce qui est normal" in now
    assert "Vigil apprend ce qui est normal" not in now


def test_the_page_around_it_is_untouched(site):
    """One change, and only one. A tool that rewrote the file would be the rewrite this deliberately
    is not — and the headline, the stylesheet link and the doctype are how you can tell."""
    before = (site / "index.html").read_text(encoding="utf-8")
    _run(page="index.html", find="et signale un écart durable", replace="et signalera un écart")
    after = (site / "index.html").read_text(encoding="utf-8")

    assert "<h1>Le check-in mental fait pour ceux qui tiennent bon</h1>" in after
    assert "href='/assets/style.css'" in after
    assert len(before) - len(after) < 30, "more changed than the words that were named"


def test_an_empty_replacement_deletes_the_words(site):
    """A finding is sometimes "this sentence should not be here", and refusing to express that would
    push the model into replacing it with something invented."""
    assert _run(page="index.html", find=", et signale un écart durable", replace="").ok is True
    assert "signale un écart" not in (site / "index.html").read_text(encoding="utf-8")


def test_the_other_pages_are_reachable_too(site):
    """`review_site` reads four pages and names the one it is talking about, so the editor has to be
    able to open any of them — a tool that only edited the home page would silently drop three
    quarters of every review."""
    assert _run(page="tech.html", find="Architecture", replace="L'architecture").ok is True


# --- and the four ways it refuses --------------------------------------------------


def test_a_page_that_is_not_the_company_s_is_refused(site):
    """The value is model output being used to open a file. By name against the pages actually
    listed, so a path never gets built out of it — the same rule as everywhere else here: only names
    that exist are ever opened."""
    result = _run(page="../../company.yaml", find="name", replace="x")
    assert result.ok is False and "not one of this company's pages" in result.output
    assert (site.parent / "company.yaml").exists() is False


def test_markup_on_either_side_is_refused(site):
    """The whole safety argument in one assertion. With no `<` or `>` the document's structure cannot
    change, so no build and no test are needed to know the page still works."""
    assert _run(page="index.html", find="<h1>", replace="<h2>").ok is False
    assert _run(page="index.html", find="Architecture", replace="<b>x</b>").ok is False
    assert "<h1>" in (site / "index.html").read_text(encoding="utf-8")


def test_words_the_page_does_not_contain_are_refused(site):
    """A model quoting something it did not read. Guessing at what it meant is how a fix lands in
    the wrong sentence, and this is also the cheapest hallucination check available here."""
    result = _run(page="index.html", find="une phrase qui n'existe pas", replace="x")
    assert result.ok is False and "quote the page exactly" in result.output


def test_words_the_page_contains_twice_are_refused(site):
    """Picking the first is a coin toss on which half of the site changes. The refusal says what to
    do about it, because "ambiguous" alone leaves the next round no better off."""
    result = _run(page="index.html", find="répété", replace="dit")
    assert result.ok is False and "2 times" in result.output
    assert "quote more of the sentence" in result.output


def test_a_company_with_no_site_of_its_own_skips_it(tmp_path, monkeypatch):
    """Exclusive with `write_site_content` by design: a company whose page is generated from
    `company.yaml` is edited by writing that file, not by patching the output."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cfg.invalidate()
    ctx = types.SimpleNamespace(company={"slug": "acme"}, store=None)
    # Through the behaviour, because `Tool.__getattr__` forwards to the *spec* and `skip_when` lives
    # on the behaviour beside the effect. Reading it off the tool raises, which is the registry
    # telling the truth about which half holds what.
    assert "no site of its own" in TOOLS["edit_site_page"].behaviour.skip_when(ctx)


# --- where it sits ------------------------------------------------------------------


def test_it_runs_after_the_review_that_feeds_it():
    """Order is the whole point: the punch list this acts on has to be today's."""
    from corparius.kernel.records import AgentRole
    from corparius.roster import ROSTER

    playbook = ROSTER[AgentRole.DESIGN].playbook
    assert playbook.index("edit_site_page") == playbook.index("review_site") + 1


def test_it_is_weighed_as_a_local_write():
    """It changes a file in the operator's company folder. `write_skill` and `write_style_rule` are
    weighed the same way, and for the same reason: what it writes is read again later."""
    from corparius.config import permissions

    assert TOOLS["edit_site_page"].risk == permissions.WRITE_LOCAL


def test_the_prompt_states_the_one_rule_that_matters(site):
    """Saying it as well as checking it is not duplication — the cheapest refusal is the one that
    never happens, which is the same argument the house style makes for naming its rules in the
    prompt rather than only enforcing them after."""
    ctx = types.SimpleNamespace(company={"slug": "vigil", "name": "Vigil"}, store=None)
    asked = TOOLS["edit_site_page"].draft_prompt(ctx)
    assert "index.html" in asked and "tech.html" in asked
    assert "character for character" in asked
    assert "`<` or `>`" in asked


def test_the_page_still_renders_after_a_change(site):
    """The proof the argument above is not merely an argument.

    Skipped where there is no browser, which is honest: on such a machine this test cannot be run
    and the safety comes from the markup rule alone.
    """
    from corparius.providers import screenshot

    if not screenshot.browser():
        pytest.skip("no Chromium-family browser on this machine")

    _run(
        page="index.html",
        find="Vigil apprend ce qui est normal pour vous",
        replace="Vigil apprendra ce qui est normal pour vous",
    )
    made = screenshot.capture_all([str(site / "index.html")], site.parent / ".shots")
    assert made, "the page stopped rendering after a wording change"
    assert pathlib.Path(made[0]).stat().st_size > 2000
