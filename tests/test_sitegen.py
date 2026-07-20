"""The sales site must be self-contained and carry the real offer and CTA."""

from pathlib import Path

from app import sitegen


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
