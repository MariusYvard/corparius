"""What a hosted page needs to be found, and what it must never claim.

The generator emitted four meta tags and nothing else: no canonical, no
structured data, no sitemap, no robots.txt. A landing page nobody can find is a
landing page nobody buys from.

The other half of this file is the part that matters more: structured data is
where a generator is most tempted to invent, because nothing on screen shows the
lie. A schema block claiming a rating nobody left is the machine-readable
version of printing "Cancel anytime".
"""

import json
import re

from corparius import company as company_mod
from corparius import sitegen


def _company(**over):
    base = {
        "slug": "vigil",
        "name": "Vigil",
        "language": "fr",
        "one_liner": "Le check-in fait pour ceux qui tiennent bon.",
        "offer": {"product": "Check-in anonyme", "price_eur": 9, "billing": "stripe"},
        "icp": {"segment": "PME", "pains": ["Personne ne dit rien"]},
    }
    base.update(over)
    return base


def _build(tmp_path, store=None, **over):
    out = tmp_path / "site"
    path = sitegen.build_site(_company(**over), str(out), store=store)
    with open(path, encoding="utf-8") as fh:
        return fh.read(), out


def _with_store(tmp_path):
    """`faq_pairs` refuses to ask anything without a store, which is correct and
    which this file's FAQ tests have to satisfy."""
    from corparius.store import Store

    return Store(str(tmp_path / "db"))


def _jsonld(page):
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
    return json.loads(raw)


# --------------------------------------------------------------------------
# Findable
# --------------------------------------------------------------------------


def test_the_head_carries_what_a_result_page_shows(tmp_path):
    page, _ = _build(tmp_path)
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    assert title and len(title) <= 60, f"{len(title)} chars: {title}"
    # The promise leads, not the company name — a reader scanning results has no
    # idea yet what "Vigil" is.
    assert not title.startswith("Vigil ·")
    assert re.search(r'<meta name="description" content="[^"]{20,}"', page)
    assert 'name="robots" content="index,follow' in page


def test_social_cards_are_complete_enough_to_render(tmp_path):
    page, _ = _build(tmp_path)
    for tag in ("og:type", "og:site_name", "og:title", "og:description", "og:locale"):
        assert f'property="{tag}"' in page, tag
    assert 'name="twitter:card" content="summary_large_image"' in page
    assert 'content="fr"' in page


def test_the_language_reaches_the_locale_not_just_the_html_tag(tmp_path):
    page, _ = _build(tmp_path, language="pt-br")
    assert '<html lang="pt-br"' in page
    # og:locale wants an underscore.
    assert 'og:locale" content="pt_br"' in page


def test_the_page_declares_its_landmarks(tmp_path):
    """Not decoration: <main> is how a screen reader skips the nav and how a
    crawler tells content from chrome. The banner used to be a div inside the
    hero band, which made it a section header rather than the page's."""
    page, _ = _build(tmp_path)
    assert page.count("<main>") == 1 and page.count("</main>") == 1
    assert re.search(r"<header[^>]*>", page) and "<footer>" in page
    assert page.index("<header") < page.index("<main>") < page.index("<footer>")
    assert page.count("<h1>") == 1, "exactly one H1"


# --------------------------------------------------------------------------
# The absolute address, which the generator will not guess
# --------------------------------------------------------------------------


def test_without_a_url_nothing_absolute_is_invented(tmp_path):
    page, out = _build(tmp_path)
    assert '<link rel="canonical"' not in page
    assert 'property="og:url"' not in page
    assert sorted(p.name for p in out.iterdir()) == ["index.html"]


def test_with_a_url_the_canonical_sitemap_and_robots_all_agree(tmp_path):
    page, out = _build(tmp_path, site={"url": "https://vigil.fr/"})
    assert '<link rel="canonical" href="https://vigil.fr/">' in page
    assert 'property="og:url" content="https://vigil.fr/"' in page

    files = {p.name: p.read_text(encoding="utf-8") for p in out.iterdir()}
    assert sorted(files) == ["index.html", "robots.txt", "sitemap.xml"]
    assert "Sitemap: https://vigil.fr/sitemap.xml" in files["robots.txt"]
    assert "<loc>https://vigil.fr/</loc>" in files["sitemap.xml"]
    assert files["sitemap.xml"].startswith("<?xml")


def test_a_url_that_is_not_a_url_is_refused_with_a_warning():
    for bad in ("vigil.fr", "ftp://vigil.fr", "/sites/vigil", "javascript:alert(1)"):
        cfg, _, warnings = company_mod.validate(
            {"name": "V", "offer": {"product": "p"}, "site": {"url": bad}}
        )
        assert not (cfg.get("site") or {}).get("url"), bad
        assert any("url" in w for w in warnings), bad


def test_a_trailing_slash_does_not_produce_a_double_slash(tmp_path):
    _, out = _build(tmp_path, site={"url": "https://vigil.fr/"})
    assert "//sitemap" not in (out / "robots.txt").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Structured data, and what it refuses to say
# --------------------------------------------------------------------------


def test_the_price_becomes_a_machine_readable_offer(tmp_path):
    page, _ = _build(
        tmp_path,
        offer={
            "product": "p",
            "price_eur": 9,
            "billing": "stripe",
            "payment_link": "https://buy.stripe.com/x",
        },
    )
    data = _jsonld(page)
    assert data["@context"] == "https://schema.org"
    product = next(n for n in data["@graph"] if n["@type"] == "Product")
    assert product["offers"]["price"] == "9"
    assert product["offers"]["priceCurrency"] == "EUR"
    assert product["offers"]["url"] == "https://buy.stripe.com/x"


def test_no_price_means_no_offer_rather_than_a_zero(tmp_path):
    """`price_eur: null` means "let's talk". Emitting `"price": "0"` would put a
    free product in a search result."""
    page, _ = _build(tmp_path, offer={"product": "p", "price_eur": None})
    product = next(n for n in _jsonld(page)["@graph"] if n["@type"] == "Product")
    assert "offers" not in product


def test_the_generator_never_claims_a_rating_or_a_review_count(tmp_path):
    """Nobody has left a review. The schema block is the one place a lie is
    invisible on screen and still shows up in the search result."""
    page, _ = _build(tmp_path, site={"url": "https://vigil.fr"})
    for invented in ("aggregateRating", "ratingValue", "reviewCount", "Review"):
        assert invented not in page, f"the generator invented {invented}"


def test_the_faq_is_answered_once_and_used_twice(tmp_path, monkeypatch):
    """The visible section and the FAQPage block come from the same answers.
    Asking a model the same questions twice to build one page would be paying
    twice for one answer."""
    calls = []

    def fake_run(app, slug, store, question, company):
        calls.append(question)
        return {"ok": True, "text": f"Réponse à {question}"}

    from corparius import apps as apps_mod

    monkeypatch.setattr(apps_mod, "get", lambda slug, name: object())
    monkeypatch.setattr(apps_mod, "run", fake_run)

    page, _ = _build(
        tmp_path,
        store=_with_store(tmp_path),
        site={"faq_app": "faq", "faq": ["Combien ça coûte ?", "Pour qui ?"]},
    )
    assert calls == ["Combien ça coûte ?", "Pour qui ?"], "asked more than once"

    faq = next(n for n in _jsonld(page)["@graph"] if n["@type"] == "FAQPage")
    assert [q["name"] for q in faq["mainEntity"]] == calls
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"].startswith("Réponse")
    # And it is on the page for a human too, not only for a crawler.
    assert "Combien ça coûte ?" in page and 'id="faq"' in page


def test_no_questions_means_no_faq_block(tmp_path):
    page, _ = _build(tmp_path)
    assert "FAQPage" not in page


def test_model_output_cannot_reach_the_html_parser_through_the_json_block(tmp_path, monkeypatch):
    """The FAQ answers are model output going into a <script> element, where
    HTML escaping is wrong because it would corrupt the JSON. Every angle
    bracket is a unicode escape instead, so there is nothing in the block a
    parser could read as markup — no reasoning about parser states required."""
    from corparius import apps as apps_mod

    payload = "</script><img src=x onerror=alert(1)><script>"
    monkeypatch.setattr(apps_mod, "get", lambda slug, name: object())
    monkeypatch.setattr(apps_mod, "run", lambda *a, **k: {"ok": True, "text": payload})

    page, _ = _build(tmp_path, store=_with_store(tmp_path), site={"faq_app": "faq", "faq": ["q"]})

    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
    assert "<" not in block and ">" not in block, "raw markup inside the data block"
    assert "\\u003c" in block
    # Still correct data once decoded: escaping must not corrupt the answer.
    faq = next(n for n in json.loads(block)["@graph"] if n["@type"] == "FAQPage")
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"] == payload
    # An attribute cannot exist without a tag, and there is no `<` left in the
    # block to open one — so `onerror=` surviving in there as inert text inside a
    # JSON string is not a finding. What would be a finding is a tag-opening
    # character reaching the parser, anywhere outside the escaped block.
    without_block = page.replace(block, "")
    assert "<img" not in without_block
    assert not re.search(r"<script(?![^>]*ld\+json)", without_block)
    # And the visible copy is HTML-escaped, as it always was.
    assert "&lt;script&gt;" in page and "&lt;img" in page
