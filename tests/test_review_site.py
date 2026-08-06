"""The design role, for a company whose site is its own files.

`write_site_content` drafts copy into `company.yaml`, which the generator renders.
A company that ships hand-written HTML gets nothing from that copy — and once
`deploy_site` started publishing the real folder, the design role was left with no
tool that could change anything at all. That is the "reachable and never reached"
shape arriving as a *consequence* of a fix rather than as an old bug, which is why
it is tested here rather than noticed later.

So exactly one of the two runs, and each says why when it is the other's turn.
`review_site` does not rewrite the HTML: editing hand-written pages from a prompt,
with no build and no test, turns a working site into a broken one — corparius
publishes what a company owns, it does not compile it. What it can do honestly is
leave a punch list naming files and quoting text, which is what NanoCorp's worker
does when it cannot act.
"""

import pytest

from corparius.kernel import paths
from corparius.tools import effects as tools
from corparius.tools.registry import TOOLS


class _Ctx:
    def __init__(self, slug="c", structured=None):
        self.company = {"slug": slug, "name": "C"}
        self.structured = structured
        self.store = None
        self.data_path = "unused"


class _Result:
    """The fields `_empty_draft` reads. It distinguishes "nothing to add" from "no
    provider answered", so a stand-in that omits `ok` hides that distinction."""

    def __init__(self, data, fell_back=False, ok=True):
        self.data = data
        self.fell_back = fell_back
        self.ok = ok


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    folder = tmp_path / "c" / "site" / "public"
    folder.mkdir(parents=True)
    return folder


def _page(folder, name, words, title="t"):
    (folder / name).write_text(
        f"<html><head><title>{title}</title><style>b{{color:red}}</style></head>"
        f"<body><script>x=1</script><p>{words}</p></body></html>",
        encoding="utf-8",
    )


# --- exactly one of the two applies ------------------------------------------


def test_write_site_content_stands_aside_for_a_real_site(owned):
    _page(owned, "index.html", "Ninety seconds a day.")
    reason = TOOLS["write_site_content"].skip_reason(_Ctx())
    assert "would not appear on it" in reason and "review_site" in reason


def test_write_site_content_still_runs_for_a_generated_page(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    (tmp_path / "c").mkdir()
    assert TOOLS["write_site_content"].skip_reason(_Ctx()) == ""


def test_review_site_stands_aside_when_the_page_is_generated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    (tmp_path / "c").mkdir()
    reason = TOOLS["review_site"].skip_reason(_Ctx())
    assert "no site of its own" in reason


def test_they_are_never_both_active(owned, tmp_path, monkeypatch):
    """The property, rather than two examples: which one applies is a fact about
    the company, so exactly one may be silent at a time."""
    _page(owned, "index.html", "x")
    with_site = (
        bool(TOOLS["write_site_content"].skip_reason(_Ctx())),
        bool(TOOLS["review_site"].skip_reason(_Ctx())),
    )
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path / "empty")
    (tmp_path / "empty" / "c").mkdir(parents=True)
    without = (
        bool(TOOLS["write_site_content"].skip_reason(_Ctx())),
        bool(TOOLS["review_site"].skip_reason(_Ctx())),
    )
    assert with_site == (True, False) and without == (False, True)


# --- what the model is shown --------------------------------------------------


def test_the_home_page_comes_first(owned):
    """Sorting by size put Vigil's 7 674-character tech.html first, it filled the
    whole budget on its own, and index.html — the page an operator means when they
    say "the site" — was never reviewed at all. Measured, then fixed."""
    _page(owned, "tech.html", "T" * 9000)
    _page(owned, "index.html", "Home page words.")
    prompt = tools._review_site_prompt(_Ctx())
    assert prompt.index("index.html") < prompt.index("tech.html")
    assert "Home page words." in prompt


def test_every_page_gets_a_share(owned):
    for name in ("index.html", "tech.html", "beta.html", "merci.html"):
        _page(owned, name, f"words of {name} " * 400)
    prompt = tools._review_site_prompt(_Ctx())
    for name in ("index.html", "tech.html", "beta.html", "merci.html"):
        assert f"--- {name}" in prompt, f"{name} never reached the prompt"
    assert len(prompt) < tools.SITE_REVIEW_BUDGET + 1500


def test_the_budget_holds(owned):
    for i in range(6):
        _page(owned, f"p{i}.html", "long " * 5000)
    _page(owned, "index.html", "short")
    assert len(tools._review_site_prompt(_Ctx())) < tools.SITE_REVIEW_BUDGET + 1500


def test_markup_and_scripts_are_stripped(owned):
    """45 000 characters of markup would eat a whole turn to say what 7 000
    characters of prose says, and a model reviewing copy does not need class names."""
    _page(owned, "index.html", "Real sentence.")
    prompt = tools._review_site_prompt(_Ctx())
    assert "Real sentence." in prompt
    assert "<p>" not in prompt and "x=1" not in prompt and "color:red" not in prompt


def test_the_prompt_says_how_much_was_cut(owned):
    """No silent truncation: a model told to judge a page it only half received
    would report the missing half as a fault."""
    _page(owned, "index.html", "word " * 4000)
    prompt = tools._review_site_prompt(_Ctx())
    assert "shown" in prompt and "Say nothing about pages you were not given" in prompt


def test_the_prompt_is_never_empty(tmp_path, monkeypatch):
    """A prompt that can come back empty is a tool that can call a model with
    nothing in it. `test_draft_prompts_render_without_a_model` holds every
    needs_draft tool to this, and it caught this one."""
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    (tmp_path / "c").mkdir()
    assert tools._review_site_prompt(_Ctx()).strip()


# --- what it writes -----------------------------------------------------------


def test_it_writes_a_punch_list_to_the_documents(owned, monkeypatch):
    written = {}
    monkeypatch.setattr(
        tools.documents, "write", lambda slug, name, body: written.update(name=name, body=body)
    )
    _page(owned, "index.html", "x")
    out = tools._review_site(
        _Ctx(
            structured=_Result(
                {
                    "findings": ["index.html: replace 'REMPLACER@TON-DOMAINE.fr'"],
                    "worst": "The contact address is a placeholder",
                }
            )
        )
    )
    assert written["name"] == "site-review"
    assert "REMPLACER" in written["body"] and "Most important" in written["body"]
    assert "1 change(s)" in out and "index.html" in out


def test_it_does_not_touch_the_html(owned):
    """Editing hand-written pages from a prompt, with no build and no test, is how
    a working site becomes a broken one."""
    _page(owned, "index.html", "Untouched.")
    before = (owned / "index.html").read_bytes()
    tools._review_site(_Ctx(structured=_Result({"findings": ["rewrite everything"], "worst": "x"})))
    assert (owned / "index.html").read_bytes() == before


def test_an_empty_answer_is_not_a_review(owned, monkeypatch):
    monkeypatch.setattr(
        tools.documents, "write", lambda *a: pytest.fail("it wrote an empty document")
    )
    _page(owned, "index.html", "x")
    out = tools._review_site(_Ctx(structured=_Result({"findings": [], "worst": ""})))
    assert "nothing written down" in out or "no provider" in out.lower()


def test_with_no_site_it_says_so_rather_than_inventing(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    (tmp_path / "c").mkdir()
    out = tools._review_site(_Ctx(structured=_Result({"findings": ["a"], "worst": "b"})))
    assert "No site of its own" in out


def test_the_tool_is_on_the_design_playbook():
    """A tool no playbook names is a tool that never runs — the defect
    tests/test_tool_reach.py exists for."""
    from corparius.kernel.records import AgentRole
    from corparius.roster import ROSTER

    assert "review_site" in ROSTER[AgentRole.DESIGN].playbook
