"""The content contract, and the language of the page's own furniture.

A real page shipped with this H1:

    "Check-in, anonyme, en 90 secondes." Alternatively, a more punchy version:
    "Mental Check-in en 90s"

That is the model deliberating, published at 4rem on a customer's website. The
same page carried `The problem` and `Pay as you go` above French copy, and a
pricing box promising "Cancel anytime" and "Instant onboarding" — terms of sale
that the generator invented and nobody had agreed to.

Every test here is one of those three, held shut.
"""

import re

from corparius import company as company_mod
from corparius import sitegen

# Verbatim, from the generation that shipped.
SHIPPED = (
    '"Check-in, anonyme, en 90 secondes." Alternatively, a more punchy version: '
    '"Mental Check-in en 90s"'
)


def _company(**over):
    base = {
        "slug": "t",
        "name": "Vigil",
        "language": "fr",
        "one_liner": "Le check-in santé fait pour ceux qui tiennent bon.",
        "offer": {"product": "Check-in anonyme", "price_eur": 9, "billing": "stripe"},
        "icp": {"segment": "PME", "pains": ["Personne ne dit rien avant de partir"]},
    }
    base.update(over)
    return base


def _build(tmp_path, headline=None, **over):
    path = sitegen.build_site(_company(**over), str(tmp_path / "site"), headline=headline)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _h1(page):
    return re.search(r"<h1>(.*?)</h1>", page, re.S).group(1)


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------


def test_the_headline_that_shipped_never_reaches_the_h1_again(tmp_path):
    page = _build(tmp_path, headline=SHIPPED)
    h1 = _h1(page)
    assert "Alternatively" not in h1
    assert "punchy" not in h1
    assert "Mental Check-in en 90s" not in h1
    # And what is left is the model's own first choice, not a fallback: salvage
    # beats discarding when the good line is right there in quotes.
    assert h1 == "Check-in, anonyme, en 90 secondes."


def test_meta_commentary_is_refused_across_the_shapes_a_model_produces():
    for raw in [
        'Here is a punchy headline: "Hire without the agency"',
        "Voici une accroche : « Recrutez sans agence »",
        "Option 1: Fast hiring. Option 2: Better hiring.",
        "I would suggest: Hire faster",
        "As an AI language model, I cannot write marketing copy.",
        "Alternatively, try this",
        "x" * (sitegen.MAX_HEADLINE + 1),
        "...",
        "",
        None,
    ]:
        got = sitegen.clean_headline(raw)
        assert got is None or not re.search(
            r"(?i)alternatively|as an ai|i would suggest|option \d", got
        ), f"{raw!r} produced {got!r}"


def test_a_good_headline_passes_through_untouched():
    for raw in [
        "Recrutez sans agence, avec une vraie mise en situation.",
        "Here is how you hire in 48 hours",
        "Ship faster. Sleep better.",
    ]:
        assert sitegen.clean_headline(raw) == raw


def test_wrapping_quotes_and_labels_are_peeled_not_rendered():
    assert sitegen.clean_headline('"Recrutez sans agence."') == "Recrutez sans agence."
    assert sitegen.clean_headline("« Recrutez sans agence »") == "Recrutez sans agence"
    assert sitegen.clean_headline("Headline: Hire without the agency") == "Hire without the agency"


def test_a_refused_headline_falls_back_to_what_a_human_wrote(tmp_path):
    page = _build(tmp_path, headline="As an AI language model, I cannot write marketing copy.")
    assert _h1(page) == "Le check-in santé fait pour ceux qui tiennent bon."


def test_a_company_with_nothing_written_still_gets_an_h1(tmp_path):
    """Every fallback exhausted: no headline, no one-liner, an unusable product
    string. The page must still have a heading, because a page whose H1 is empty
    is worse than one whose H1 is the company name."""
    page = _build(tmp_path, headline="...", one_liner="", offer={"product": "..."})
    assert _h1(page) == "Vigil"


# --------------------------------------------------------------------------
# The language
# --------------------------------------------------------------------------


def test_a_french_page_has_no_english_section_titles(tmp_path):
    page = _build(tmp_path)
    assert '<html lang="fr"' in page
    for english in ("The problem", "Why it works", "Pricing", "What you get", "Get started"):
        assert english not in page, f"{english!r} is still on a French page"
    # "Nous contacter" and not "Commencer" because this fixture has no payment
    # link — see test_the_button_says_what_it_does.
    assert "Le problème" in page and "Tarif" in page and "Nous contacter" in page


def test_every_shipped_language_translates_the_whole_frame(tmp_path):
    """A half-translated table would render an empty heading. `strings()` merges
    over English, so this checks the entries themselves are complete."""
    keys = set(sitegen.STRINGS["en"])
    for code in company_mod.LANGUAGES:
        assert code in sitegen.STRINGS, f"{code} is advertised in LANGUAGES but has no strings"
        missing = keys - set(sitegen.STRINGS[code])
        assert not missing, f"{code} is missing {sorted(missing)}"
        assert all(v.strip() for v in sitegen.STRINGS[code].values()), code
    # And the segment placeholder has to survive translation, or the page says
    # "For {segment}" to a real visitor.
    for code in company_mod.LANGUAGES:
        assert "{segment}" in sitegen.STRINGS[code]["for"], code


def test_an_unknown_language_keeps_english_furniture_rather_than_inventing(tmp_path):
    page = _build(tmp_path, language="ja")
    assert '<html lang="ja"' in page
    assert "Pricing" in page  # honest fallback, not a machine translation


def test_a_regional_code_resolves_to_its_base_language(tmp_path):
    page = _build(tmp_path, language="fr-be")
    assert "Le problème" in page
    assert '<html lang="fr-be"' in page


# --------------------------------------------------------------------------
# Claims the company never made
# --------------------------------------------------------------------------


def test_the_page_promises_nothing_the_config_does_not_say(tmp_path):
    page = _build(tmp_path)
    for invented in (
        "Cancel anytime",
        "Instant onboarding",
        "Live in minutes",
        "Full access",
        "One prompt turns into a working offer",
    ):
        assert invented not in page, f"the generator invented {invented!r}"


def test_what_you_get_is_listed_only_when_the_operator_listed_it(tmp_path):
    bare = _build(tmp_path)
    assert "What you get" not in bare and "Ce que vous obtenez" not in bare

    filled = _build(
        tmp_path,
        offer={
            "product": "Check-in anonyme",
            "price_eur": 9,
            "billing": "stripe",
            "includes": ["Sans engagement", "Export CSV"],
        },
    )
    assert "Ce que vous obtenez" in filled
    assert "Sans engagement" in filled and "Export CSV" in filled


def test_a_section_with_no_content_is_absent_not_templated(tmp_path):
    page = _build(tmp_path, icp={"segment": "", "pains": []})
    assert "Le problème" not in page
    assert "Too much manual work" not in page
    # The pricing section is the one that always renders: a sales page without a
    # price is not a sales page.
    assert "Tarif" in page


def test_a_long_segment_becomes_a_sentence_instead_of_being_dropped(tmp_path):
    """vigil's `icp.segment` is 200 characters of who it serves. It does not fit
    in a chip beside the price, and losing it altogether would be worse."""
    long = "Militaires, soignants, pompiers et ingénieurs sous pression — " + ("et leurs " * 12)
    page = _build(tmp_path, icp={"segment": long, "pains": []})
    assert 'class="who"' in page
    assert "Militaires, soignants" in page
    assert "…" not in page and "..." not in page, "a positioning line was cut mid-sentence"


# --------------------------------------------------------------------------
# The page itself
# --------------------------------------------------------------------------


def test_one_call_to_action_repeated_never_two_competing_labels(tmp_path):
    page = _build(
        tmp_path,
        offer={
            "product": "p",
            "price_eur": 9,
            "billing": "stripe",
            "payment_link": "https://buy.stripe.com/x",
        },
    )
    labels = set(re.findall(r'class="btn"[^>]*>(.*?)</a>', page))
    assert labels == {"Commencer"}
    assert page.count('class="btn"') >= 2, "the CTA should be repeated down the page"


def test_the_button_says_what_it_does(tmp_path):
    """A button that opens Stripe and a button that scrolls to a price are not
    the same button, and they should not carry the same word."""
    buy = _build(
        tmp_path,
        offer={
            "product": "p",
            "price_eur": 9,
            "billing": "stripe",
            "payment_link": "https://buy.stripe.com/x",
        },
    )
    talk = _build(tmp_path, offer={"product": "p", "price_eur": None, "billing": "none"})
    assert "Commencer" in buy and "https://buy.stripe.com/x" in buy
    assert "Nous contacter" in talk and "Parlons-en" in talk


def test_the_closing_block_does_not_repeat_the_headline_word_for_word(tmp_path):
    page = _build(tmp_path, headline="Check-in, anonyme, en 90 secondes.")
    closing = re.search(r'<div class="close">\s*<h2>(.*?)</h2>', page, re.S).group(1)
    assert closing != _h1(page)


def test_a_long_description_is_a_paragraph_not_a_heading_or_a_hero_lede(tmp_path):
    """Found by building vigil's real page: `offer.product` there is 500
    characters about the protocol and the founder. It was landing whole in the
    hero lede and again as a 500-character closing <h2>."""
    long = (
        "Check-in mental vocal de 90 secondes. L'application apprend la baseline "
        "vocale de l'utilisateur et signale un écart durable à sa propre normale. "
        "Analyse prosodique sur l'appareil, voix détruite en moins de 2 secondes. "
        "Conçu par un ex-officier de marine ; le ton est direct, axé mission."
    )
    page = _build(tmp_path, one_liner="", offer={"product": long, "price_eur": 9})

    lede = re.search(r'class="lede">(.*?)</p>', page, re.S).group(1)
    assert len(lede) <= 260, "the hero lede is a strapline, not a description"
    # Whole sentences while they fit, otherwise an ellipsis — never a half word.
    assert lede.endswith((".", "!", "?", "…")), lede[-40:]

    closing = re.search(r'<div class="close">\s*<h2>(.*?)</h2>', page, re.S).group(1)
    assert len(closing) <= 120, "a closing heading is a heading"

    # And none of it is lost: the whole description is on the page as prose.
    assert 'class="story"' in page
    assert "ex-officier de marine" in page


def test_the_opening_never_cuts_mid_word():
    from corparius.sitegen import _opening

    assert _opening("Court.") == "Court."
    long = "Une phrase. " + "mot " * 200
    got = _opening(long)
    assert got == "Une phrase."
    nosentence = "mot " * 200
    got = _opening(nosentence)
    assert got.endswith("…") and not got.endswith("mo…")


def test_the_look_follows_the_config_and_refuses_nonsense(tmp_path):
    dark = _build(tmp_path, site={"theme": "dark", "font": "sans", "accent": "#4ade80"})
    assert "#4ade80" in dark and "#12100e" in dark
    light = _build(tmp_path)
    assert sitegen.DEFAULT_ACCENT in light and "#fbfaf8" in light

    cfg, _, warnings = company_mod.validate(
        {"name": "T", "offer": {"product": "p"}, "site": {"accent": "rouge vif"}}
    )
    assert not (cfg.get("site") or {}).get("accent")
    assert any("accent" in w for w in warnings)


def test_the_page_has_something_on_it_that_is_not_a_paragraph(tmp_path):
    """The first redesign removed the template and put nothing in its place —
    "on dirait une page blanche avec du texte". Restraint without intent reads
    as unfinished, so the page now commits: a washed hero band, an inverted
    pricing band, and a signature. This test is here so a later tidy-up cannot
    quietly take them back out."""
    page = _build(tmp_path)
    assert page.count('class="band') >= 3, "the page no longer changes ground"
    assert "band-hero" in page and "band-dark" in page
    assert '<svg class="sig"' in page and page.count("<rect") > 20


def test_the_signature_belongs_to_the_company_and_does_not_move(tmp_path):
    """Different per company so two corparius pages are not twins; identical
    across builds so a rebuild is not a redesign."""
    assert sitegen.signature("vigil") != sitegen.signature("acme")
    assert sitegen.signature("vigil") == sitegen.signature("vigil")
    # Decorative, so it must be hidden from anyone using a screen reader.
    assert 'aria-hidden="true"' in sitegen.signature("vigil")


def test_the_page_is_still_one_file_that_needs_nothing(tmp_path):
    """The property this generator has defended from the start. A redesign that
    reached for a webfont or a script would have quietly traded it away.

    What is banned is *loading* something from elsewhere, not linking to it: the
    checkout button points at Stripe, and that is the entire purpose of the
    page. So this checks `src`, `<link>` and CSS fetches, and deliberately not
    `<a href>` — an earlier version of this test banned both and would have
    failed on the first real company that had a payment link.
    """
    page = _build(
        tmp_path,
        offer={
            "product": "p",
            "price_eur": 9,
            "billing": "stripe",
            "payment_link": "https://buy.stripe.com/x",
        },
    )
    assert "https://buy.stripe.com/x" in page, "the CTA has to reach the checkout"
    # The only script element allowed is the structured-data block, which is
    # read by crawlers and executed by nobody.
    assert all(
        'type="application/ld+json"' in attrs for attrs in re.findall(r"<script([^>]*)>", page)
    )
    assert not re.search(r'<link[^>]+rel="(?:stylesheet|preload|prefetch)"', page)
    assert not re.search(r'\ssrc\s*=\s*"', page)
    assert "@import" not in page and "url(" not in page
