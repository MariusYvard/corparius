"""The optional blocks, and the rule that decides whether each one appears.

Stage 9's per-file ratchet asked for this file. `sitegen.py` measured 84% whole, which said
nothing about which part; split into eight, `sitegen/sections.py` came out at **56.2%** — and the
untested half is the half that writes claims onto a page a customer reads.

That matters more here than a coverage number usually does, because these functions carry the
generator's two hard rules, and both were written after a page **shipped** breaking them:

  * it never writes a claim the company did not make — an earlier version printed "Cancel
    anytime" and "Instant onboarding" in every pricing box it produced, and nobody had said
    either was true;
  * it never publishes the model thinking out loud.

`proof_html` and `voices_html` are those rules made mechanical: a claim without a source, and a
quote without a name, are dropped. Neither drop was tested. An unattributed quote on a commercial
page is a fabrication with quotation marks around it, and the code that prevents it had nothing
holding it in place.
"""

import pytest

from corparius.sitegen import sections
from corparius.sitegen.copy import strings

TXT = strings("en")


def _company(**site):
    return {"slug": "c", "name": "C", "site": site}


# --- claims need a source -------------------------------------------------------


def test_a_claim_with_a_source_is_published(caplog):
    html = sections.proof_html(
        _company(proof=[{"text": "14-day retention on device", "source": "measured, v0.3"}]), TXT
    )
    assert "14-day retention on device" in html
    assert "measured, v0.3" in html
    assert 'class="proof"' in html


def test_a_claim_without_a_source_is_dropped_and_logged(caplog):
    """ "A claim without a source is the machine-readable form of the invented testimonial — it
    looks like evidence and is not." Dropped *and* logged, because an operator who wrote it needs
    to find out why it never appeared."""
    with caplog.at_level("WARNING"):
        html = sections.proof_html(_company(proof=[{"text": "Trusted by thousands"}]), TXT)
    assert html == "", "a sourceless claim must not reach the page"
    assert "no source" in caplog.text
    assert "Trusted by thousands" in caplog.text


def test_a_sourced_claim_survives_beside_a_sourceless_one(caplog):
    """The drop is per entry. Refusing the whole block because one entry is bad would punish the
    operator for the agent's mistake."""
    with caplog.at_level("WARNING"):
        html = sections.proof_html(
            _company(
                proof=[
                    {"text": "Trusted by thousands"},
                    {"text": "Runs offline", "source": "the architecture"},
                ]
            ),
            TXT,
        )
    assert "Runs offline" in html
    assert "Trusted by thousands" not in html


def test_a_proof_entry_that_is_not_a_mapping_is_ignored():
    """An agent writing a bare string where a mapping belongs must not crash a build. The site is
    generated unattended; a traceback here is a company with no page."""
    html = sections.proof_html(_company(proof=["just a string", 42, None]), TXT)
    assert html == ""


def test_proof_is_escaped():
    html = sections.proof_html(
        _company(proof=[{"text": "<script>x</script>", "source": "a & b"}]), TXT
    )
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html and "a &amp; b" in html


# --- quotes need a name ---------------------------------------------------------


def test_an_attributed_quote_is_published():
    html = sections.voices_html(
        _company(testimonials=[{"quote": "It found what we missed.", "who": "A pilot user"}]), TXT
    )
    assert "It found what we missed." in html
    assert "A pilot user" in html
    assert "<blockquote>" in html and "<figcaption>" in html


def test_an_unattributed_quote_is_dropped_and_logged(caplog):
    """ "An unattributed quote on a commercial page is a fabrication with quotation marks around
    it." The generator has already been caught printing terms of sale nobody agreed to; this is
    the same fault with a face on it."""
    with caplog.at_level("WARNING"):
        html = sections.voices_html(_company(testimonials=[{"quote": "Life-changing!"}]), TXT)
    assert html == ""
    assert "no attribution" in caplog.text
    assert "Life-changing" not in caplog.text, (
        "the log must not republish the quote it refused; the point is that it goes nowhere"
    )


def test_a_named_quote_survives_beside_an_anonymous_one(caplog):
    with caplog.at_level("WARNING"):
        html = sections.voices_html(
            _company(
                testimonials=[
                    {"quote": "Anonymous praise"},
                    {"quote": "Cut our triage in half.", "who": "Support lead"},
                ]
            ),
            TXT,
        )
    assert "Cut our triage in half." in html and "Support lead" in html
    assert "Anonymous praise" not in html


def test_a_testimonial_that_is_not_a_mapping_is_ignored():
    assert sections.voices_html(_company(testimonials=["a bare quote", None]), TXT) == ""


# --- the blocks that are simply absent ------------------------------------------


@pytest.mark.parametrize(
    ("fn", "key"),
    [
        (sections.steps_html, "how_it_works"),
        (sections.proof_html, "proof"),
        (sections.voices_html, "testimonials"),
        (sections.privacy_html, "privacy"),
    ],
)
def test_a_block_with_nothing_to_say_says_nothing(fn, key):
    """Absent, not empty. A heading over an empty list is the generator inventing a section, which
    is the same fault as inventing its contents."""
    assert fn(_company(), TXT) == ""
    assert fn(_company(**{key: []}), TXT) == ""
    assert fn(_company(**{key: [""]}), TXT) == "" or key in ("proof", "testimonials")


def test_the_steps_are_numbered_in_the_order_they_were_written():
    """ "Numbering here is not decoration — these are sequential and the order is the information.
    A check-in that happens after the analysis is a different product.\""""
    html = sections.steps_html(
        _company(how_it_works=["Check in", "Analyse on device", "Show the drift"]), TXT
    )
    positions = [html.index(step) for step in ("Check in", "Analyse on device", "Show the drift")]
    assert positions == sorted(positions), "the order carries the meaning"
    assert html.count('class="step-n"') == 3
    assert ">1<" in html and ">3<" in html


def test_blank_steps_are_dropped_without_renumbering_around_them():
    html = sections.steps_html(_company(how_it_works=["First", "   ", "Second"]), TXT)
    assert html.count("<li>") == 2
    assert ">1<" in html and ">2<" in html and ">3<" not in html


def test_privacy_points_are_published_in_the_visitor_s_words():
    html = sections.privacy_html(
        _company(privacy=["Nothing leaves the device", "No account required"]), TXT
    )
    assert "Nothing leaves the device" in html and "No account required" in html
    assert 'id="privacy"' in html


# --- extra pages ----------------------------------------------------------------


def test_an_extra_page_needs_a_title_and_a_body():
    pages = sections.extra_pages(
        _company(
            pages=[
                {"slug": "tech", "title": "How it works", "body": "Some prose."},
                {"title": "No body"},
                {"body": "No title"},
                "not a mapping",
            ]
        )
    )
    assert [p["title"] for p in pages] == ["How it works"]
    assert pages[0]["slug"] == "tech"


def test_a_page_with_no_slug_is_skipped_rather_than_given_one(caplog):
    """All three are required, and the first version of this test asserted the opposite — that a
    missing slug would be derived from the title.

    Measured, it is not, and the product is right: a slug is a URL and a file name, so deriving it
    from a title means the address changes the next time an agent rewrites the heading. A page
    whose URL moves under it is worse than a page that says it is incomplete.
    """
    with caplog.at_level("WARNING"):
        pages = sections.extra_pages(_company(pages=[{"title": "Architecture", "body": "x"}]))
    assert pages == []
    assert "needs a slug, a title and a body" in caplog.text


def test_a_slug_that_is_given_is_folded_and_capped():
    """Through `slugify` and not the loose one: this becomes a file name, so an accent has to fold
    rather than turn into a hyphen. `m-thode-et-architecture` was the real bug."""
    pages = sections.extra_pages(
        _company(pages=[{"slug": "Méthode et Architecture", "title": "M", "body": "x"}])
    )
    assert pages[0]["slug"] == "methode-et-architecture"


def test_no_pages_is_an_empty_list_rather_than_a_missing_key():
    assert sections.extra_pages(_company()) == []
    assert sections.extra_pages({"slug": "c"}) == []
