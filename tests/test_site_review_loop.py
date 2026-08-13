"""The site review loop: measured first, judged second, and the next draft reads the verdict.

`build_sales_site` writes a headline. `review_generated_site` reads the page back and says what to
change. The next build's prompt carries that verdict. That is the whole loop, and it is the shape the
console itself was taken through sixteen times — where the thing that made it work was that every
review came back as a list somebody could act on rather than as a score.

Two decisions this file exists to hold:

**The judge is a different role.** Design writes the page; strategy reviews it. Not style — a tool
effect reaches `company`, `data_path`, `leads`, `store` and `structured` and deliberately *not* a model
handle, because the executor owns routing and the token budget, so a critique round inside the build
would have to be a new executor capability. A separate tool on another role needs none, and roles carry
their own model pin, so pinning the reviewing role is how a different model actually gets to judge.

**And it does not pretend that separation happened.** Without a pin the two turns route independently,
which is not a guarantee. So the tool reads `source` off both actions and *says* when they matched —
schema 18 made that a column rather than a supposition, and a second opinion from the same model is one
opinion twice.
"""

import pathlib

import pytest

from corparius.tools import effects
from corparius.tools.registry import TOOLS
from corparius.tools.spec import SPEC


class Ctx:
    """The five things a tool effect can reach, and nothing else — which is the point above."""

    def __init__(self, tmp_path, company=None, store=None, structured=None):
        self.company = company or {"slug": "example", "name": "CVBoost"}
        self.data_path = str(tmp_path)
        self.store = store
        self.structured = structured
        self.leads = None
        self.role = "strategy"


class Structured:
    def __init__(self, data, source=""):
        self.data = data
        self.source = source


def _page(tmp_path, headline: str, body: str = "") -> pathlib.Path:
    from corparius.kernel import paths

    out = pathlib.Path(paths.site_dir(str(tmp_path), "example"))
    out.mkdir(parents=True, exist_ok=True)
    page = out / "index.html"
    filler = body or ("A sentence about what the product does for whoever is reading. " * 20)
    page.write_text(
        f"<html><head><style>.a{{color:red}}</style></head><body><h1>{headline}</h1>"
        f"<p>{filler}</p><script>ignored()</script></body></html>",
        encoding="utf-8",
    )
    return page


# --- both ends of the wire ------------------------------------------------------


def test_the_tool_is_registered_at_both_ends():
    """`test_registries` holds this for every tool; named here too because a review tool with no
    behaviour is a loop that looks closed and is not."""
    assert "review_generated_site" in SPEC and "review_generated_site" in TOOLS
    assert SPEC["review_generated_site"].needs_draft, "it has to draft, or no model ever judges"
    assert SPEC["review_generated_site"].schema, "findings have to come back in one shape"


def test_the_judge_is_not_the_role_that_writes_the_page():
    """The decision the whole design rests on: a writer reviewing their own work is one opinion twice."""
    from corparius import roster

    by_name = {getattr(role, "value", role): spec for role, spec in roster.ROSTER.items()}
    assert "review_generated_site" in by_name["strategy"].playbook
    assert "review_generated_site" not in by_name["design"].playbook
    assert "build_sales_site" in by_name["design"].playbook


# --- what it reads --------------------------------------------------------------


def test_it_reads_the_generated_page_and_not_the_owned_one(tmp_path, monkeypatch):
    """Two different files with two different owners. Reviewing the hand-written site under this tool's
    name would be the fourth time in this repository that two surfaces claiming one job disagreed."""
    from corparius.kernel import paths

    _page(tmp_path, "A claim about the product that says something")
    monkeypatch.setattr(paths, "owned_site", lambda slug: None)
    headline, body = effects._generated_page(Ctx(tmp_path))
    assert headline == "A claim about the product that says something"
    assert "ignored()" not in body and ".a{color:red}" not in body, "script and style are not prose"
    assert "sentence about what the product does" in body

    monkeypatch.setattr(paths, "owned_site", lambda slug: tmp_path)
    assert effects._generated_page(Ctx(tmp_path)) == ("", "")
    assert "writes its own site" in effects._no_generated_page(Ctx(tmp_path))


def test_the_prompt_carries_what_was_already_measured(tmp_path, monkeypatch):
    """A judge told "the H1 is 214 characters" writes a shorter one instead of arguing about whether it
    is long — and stops spending its answer on what a rule already caught."""
    from corparius.kernel import paths

    monkeypatch.setattr(paths, "owned_site", lambda slug: None)
    _page(tmp_path, "CVBoost")
    prompt = effects._review_generated_prompt(Ctx(tmp_path))
    assert "Already measured" in prompt
    assert "label rather than a claim" in prompt
    assert "You did not write it" in prompt
    assert "cannot see is worth nothing" in prompt, "it must not judge colour or layout from text"


def test_a_page_with_nothing_wrong_asks_for_no_repeats(tmp_path, monkeypatch):
    from corparius.kernel import paths

    monkeypatch.setattr(paths, "owned_site", lambda slug: None)
    _page(tmp_path, "An AI resume optimiser that rewrites a CV to match a job")
    assert "Already measured" not in effects._review_generated_prompt(Ctx(tmp_path))


# --- what it reports ------------------------------------------------------------


def test_the_verdict_merges_the_measured_and_the_judged(tmp_path, monkeypatch):
    from corparius.kernel import paths

    monkeypatch.setattr(paths, "owned_site", lambda slug: None)
    _page(tmp_path, "CVBoost")
    ctx = Ctx(
        tmp_path, structured=Structured({"findings": ["say who it is for"], "worst": "no offer"})
    )
    said = effects._review_generated_site(ctx)
    assert said.startswith("Generated page reviewed: no offer")
    assert "more)" in said, "the count has to include what was measured as well as what was judged"


def test_it_says_when_the_judge_also_wrote_the_page(tmp_path, monkeypatch):
    """The honest half. Without a per-role pin the two turns route independently, which is not a
    guarantee — so when `source` says the same provider did both, the log says so."""
    from corparius.kernel import paths

    monkeypatch.setattr(paths, "owned_site", lambda slug: None)
    _page(tmp_path, "CVBoost")

    class Store:
        def recent_actions(self, company, limit=25):
            return [{"tool": "build_sales_site", "source": "groq", "output": "Sales site built"}]

    ctx = Ctx(tmp_path, store=Store(), structured=Structured({"findings": ["x"]}, source="groq"))
    assert "also wrote it" in effects._review_generated_site(ctx)

    other = Ctx(
        tmp_path, store=Store(), structured=Structured({"findings": ["x"]}, source="mistral")
    )
    assert "also wrote it" not in effects._review_generated_site(other)


def test_nothing_to_change_says_so(tmp_path, monkeypatch):
    """The silent case has to be silent, or the next build gets a brief that says nothing and the loop
    spends a prompt every cadence teaching the model that reviews are noise."""
    from corparius.kernel import paths

    monkeypatch.setattr(paths, "owned_site", lambda slug: None)
    _page(tmp_path, "An AI resume optimiser that rewrites a CV to match a job")
    ctx = Ctx(tmp_path, structured=Structured({"findings": [], "worst": ""}))
    assert effects._review_generated_site(ctx) == "Generated page reviewed: nothing to change"


# --- the loop closes ------------------------------------------------------------


def test_the_next_build_prompt_carries_the_last_verdict(tmp_path):
    """The half that makes it a loop rather than a report. The cheapest durable place for the next
    draft to read a review is the log line the review already wrote: no schema change, no new table,
    and it survives a restart because the action log does."""

    class Store:
        def recent_actions(self, company, limit=25):
            return [
                {
                    "tool": "review_generated_site",
                    "output": "Generated page reviewed: the H1 names nobody (+2 more)",
                }
            ]

    prompt = effects._build_site_prompt(Ctx(tmp_path, store=Store()))
    assert "punchy sales headline" in prompt, "the original instruction has to survive"
    assert "the H1 names nobody" in prompt
    assert "no longer true" in prompt


def test_a_clean_review_does_not_nag_the_next_draft(tmp_path):
    class Store:
        def recent_actions(self, company, limit=25):
            return [
                {
                    "tool": "review_generated_site",
                    "output": "Generated page reviewed: nothing to change",
                }
            ]

    prompt = effects._build_site_prompt(Ctx(tmp_path, store=Store()))
    assert "no longer true" not in prompt
    assert prompt.endswith(".")


def test_the_first_build_has_no_verdict_to_carry(tmp_path):
    """No store, no reviews yet, and the prompt is still renderable — every `needs_draft` tool in this
    package is held to that, because a prompt that can come back empty is a tool that calls a model
    with nothing in it."""
    assert effects._build_site_prompt(Ctx(tmp_path)).strip()


@pytest.mark.parametrize("tool", ["review_generated_site", "build_sales_site"])
def test_the_prompts_render_without_a_model_or_a_page(tmp_path, tool):
    assert TOOLS[tool].draft_prompt(Ctx(tmp_path)).strip()
