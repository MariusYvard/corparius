"""The sales site must be self-contained and carry the real offer and CTA."""

from pathlib import Path

import pytest

from corparius import sitegen


def _company() -> dict:
    return {
        "slug": "t",
        "name": "CVBoost",
        "one_liner": "AI resume optimiser",
        "offer": {
            "product": "Web app",
            "price_eur": 9,
            "billing": "stripe",
            "payment_link": "https://buy.stripe.com/test_123",
        },
        "icp": {"segment": "Job seekers", "pains": ["ATS rejects the CV"]},
    }


def test_build_site_is_self_contained_and_on_offer(tmp_path):
    path = sitegen.build_site(_company(), str(tmp_path))
    assert path.endswith("index.html")
    html = Path(path).read_text(encoding="utf-8")
    assert "<!doctype html>" in html.lower()
    assert "CVBoost" in html
    assert "9 EUR" in html
    assert "https://buy.stripe.com/test_123" in html  # CTA wired to checkout
    assert "ATS rejects the CV" in html  # ICP pain shown
    assert "<script src" not in html  # no external assets


def test_headline_override(tmp_path):
    path = sitegen.build_site(_company(), str(tmp_path), headline="Beat the bots")
    assert "Beat the bots" in Path(path).read_text(encoding="utf-8")


# --- a FAQ written once, at build time ------------------------------------
def _faq_company(**over):
    return {
        "slug": "t",
        "name": "T",
        "offer": {"product": "p", "price_eur": 9},
        "icp": {"segment": "s", "pains": []},
        "site": {"faq_app": "faq", "faq": ["How much?", "For whom?"]},
        **over,
    }


@pytest.fixture()
def faq_app(tmp_path, monkeypatch):
    import yaml

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    d = tmp_path / "companies" / "t" / "apps"
    d.mkdir(parents=True)
    (d / "faq.yaml").write_text(
        yaml.safe_dump({"name": "faq", "system": "Answer."}), encoding="utf-8"
    )


def _model(monkeypatch, text="an answer"):
    from corparius.models import LLMResult, Usage

    class _R:
        def __init__(self, settings):
            pass

        def generate(self, *a, **k):
            return LLMResult(text=text, usage=Usage(5, 5, 0.0), model="m", provider="p")

    monkeypatch.setattr("corparius.llm.HybridRouter", _R)


def test_the_faq_is_baked_into_the_page(tmp_path, monkeypatch, faq_app):
    from corparius.store import Store

    _model(monkeypatch)
    path = sitegen.build_site(_faq_company(), str(tmp_path / "site"), store=Store(str(tmp_path)))
    html = Path(path).read_text(encoding="utf-8")
    assert 'id="faq"' in html
    assert "How much?" in html and "an answer" in html


def test_the_page_stays_one_static_file_with_no_script(tmp_path, monkeypatch, faq_app):
    """The whole point of baking it: no JavaScript, no endpoint to reach, and
    nothing to leave running. A chat widget would have traded that away.

    Narrowed from "no <script> at all" when structured data arrived: a
    `application/ld+json` block is data a crawler reads, never code a browser
    runs. So the rule is now that every script element on the page is one of
    those — which still refuses the widget, and refuses it by name rather than
    by hoping nobody adds one.
    """
    import re

    from corparius.store import Store

    _model(monkeypatch)
    path = sitegen.build_site(_faq_company(), str(tmp_path / "site"), store=Store(str(tmp_path)))
    html = Path(path).read_text(encoding="utf-8")
    scripts = re.findall(r"<script([^>]*)>", html, re.I)
    assert scripts, "the structured data block is missing"
    assert all('type="application/ld+json"' in attrs for attrs in scripts), scripts
    assert "fetch(" not in html and "onclick" not in html and "javascript:" not in html
    # No site.url, so no companion files are invented either.
    assert sorted(p.name for p in Path(path).parent.iterdir()) == ["index.html"]


def test_no_store_means_no_faq_and_no_error(tmp_path, faq_app):
    """Every build path passes one now, but a caller that cannot must still get
    the page it got before."""
    path = sitegen.build_site(_faq_company(), str(tmp_path / "site"))
    assert 'id="faq"' not in Path(path).read_text(encoding="utf-8")


def test_a_company_that_asked_for_no_faq_gets_none(tmp_path, monkeypatch, faq_app):
    from corparius.store import Store

    _model(monkeypatch)
    company = _faq_company()
    del company["site"]
    path = sitegen.build_site(company, str(tmp_path / "site"), store=Store(str(tmp_path)))
    assert 'id="faq"' not in Path(path).read_text(encoding="utf-8")


def test_an_unreachable_model_omits_the_section_and_builds_anyway(tmp_path, monkeypatch, faq_app):
    """A page that fails to build because a free provider hiccuped would be a
    bad trade for a FAQ."""
    import requests

    from corparius.store import Store

    class _Down:
        def __init__(self, settings):
            pass

        def generate(self, *a, **k):
            raise requests.ConnectionError("refused")

    monkeypatch.setattr("corparius.llm.HybridRouter", _Down)
    path = sitegen.build_site(_faq_company(), str(tmp_path / "site"), store=Store(str(tmp_path)))
    html = Path(path).read_text(encoding="utf-8")
    assert 'id="faq"' not in html and "<h1>" in html


def test_naming_an_app_that_does_not_exist_omits_the_section(tmp_path, monkeypatch, faq_app):
    from corparius.store import Store

    _model(monkeypatch)
    company = _faq_company(site={"faq_app": "absent", "faq": ["How much?"]})
    path = sitegen.build_site(company, str(tmp_path / "site"), store=Store(str(tmp_path)))
    assert 'id="faq"' not in Path(path).read_text(encoding="utf-8")


def test_an_answer_is_escaped_like_everything_else(tmp_path, monkeypatch, faq_app):
    """It is model output on a public page: the one place HTML must not pass."""
    from corparius.store import Store

    _model(monkeypatch, text="<script>alert(1)</script>")
    path = sitegen.build_site(_faq_company(), str(tmp_path / "site"), store=Store(str(tmp_path)))
    html = Path(path).read_text(encoding="utf-8")
    assert "<script>alert" not in html and "&lt;script&gt;" in html
