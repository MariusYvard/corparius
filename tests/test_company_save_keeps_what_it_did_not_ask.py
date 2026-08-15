"""Saving from the company editor must not destroy what the form does not render.

**Measured on a real file, before the fix.** The console's `collectCompany()` builds a config out of
seven fields (name, one-liner, offer, ICP, agents, budgets, HITL tools) and `save_company` wrote that
as the whole file. One click of Save destroyed:

    site:      the address, the privacy points, the FAQ, the theme  ->  gone
    legal:     publisher, registration                              ->  gone
    language:  fr                                                   ->  en

The last one is the worst and the least visible. A French company whose language silently resets to
English has every agent drafting in English from the next tick, which is precisely the defect
`agents.language_line` was written to fix, arriving through a different door and leaving no trace.

The fix is that a save is a **merge**: what the form sends wins, and what it never sends is kept.
Clearing a field the form does render still clears it, because the form sends the empty value.
"""

import pathlib

import pytest
import yaml

from corparius.api import adapters

# What the console actually posts, copied from `collectCompany()` in `corparius/webui.html`. If that
# function grows a field this stays as it is: the point is that the *stored* file survives a form
# that knows less than the file does.
POSTED = {
    "name": "Acme",
    "one_liner": "",
    "offer": {"product": "p", "price_eur": 9, "billing": "stripe", "payment_link": ""},
    "icp": {"segment": "teams", "channels": ["linkedin"], "pains": []},
    "agents": {"ceo": True, "social": False},
    "budgets": {"session_tokens": 200000, "tokens_per_minute": 10000},
    "hitl_tools": ["deploy_site"],
}

STORED = {
    "slug": "acme",
    "name": "Acme",
    "language": "fr",
    "offer": {"product": "p", "price_eur": 9, "includes": ["Support par email"]},
    "site": {
        "url": "https://acme.example",
        "theme": "dark",
        "privacy": ["On ne revend rien."],
        "faq": ["Combien ça coûte ?"],
    },
    "legal": {"publisher": "Acme SAS", "registration": "RCS Paris 900 123 456"},
}


@pytest.fixture
def company(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    from corparius.config import cfg

    cfg.invalidate()
    path = pathlib.Path(tmp_path) / "companies" / "acme" / "company.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(STORED, allow_unicode=True), encoding="utf-8")
    return path


def _saved(path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_a_save_keeps_every_block_the_form_never_asked_about(company):
    """The three that were destroyed, named one by one so a regression says which."""
    result = adapters.save_company(None, "acme", dict(POSTED))
    assert result.get("saved") is True, result

    after = _saved(company)
    assert after["language"] == "fr", "a French company began drafting in English"
    assert after["site"]["url"] == "https://acme.example"
    assert after["site"]["privacy"] == ["On ne revend rien."]
    assert after["legal"]["registration"] == "RCS Paris 900 123 456"
    # One level in, too: the form sends `offer` without `includes`, and `includes` is the operator's.
    assert after["offer"]["includes"] == ["Support par email"]


def test_what_the_form_does_send_still_wins(company):
    """The other end. A merge that kept everything would be a form that changes nothing, and the
    editor exists to change things."""
    sent = {**POSTED, "offer": {**POSTED["offer"], "product": "a different product"}}
    adapters.save_company(None, "acme", sent)

    after = _saved(company)
    assert after["offer"]["product"] == "a different product"
    assert after["icp"]["segment"] == "teams"
    assert after["agents"]["social"] is False, "unticking a role no longer unticks it"


def test_clearing_a_field_the_form_renders_still_clears_it(company):
    """The case a merge could plausibly break: emptying a box has to empty the value. It works
    because the form sends the empty value rather than omitting the key, which is the distinction
    the merge is built on."""
    sent = {**POSTED, "offer": {**POSTED["offer"], "payment_link": ""}}
    adapters.save_company(None, "acme", {**sent, "one_liner": ""})
    assert _saved(company)["offer"]["payment_link"] == ""


def test_an_unreadable_file_does_not_block_the_edit(tmp_path, monkeypatch):
    """The one moment an operator most needs the editor is when the file is wrong. A save that
    refused because the stored config would not parse would lock them out of the only surface that
    can fix it."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    from corparius.config import cfg

    cfg.invalidate()
    path = pathlib.Path(tmp_path) / "companies" / "acme" / "company.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("name: [unclosed\n", encoding="utf-8")

    result = adapters.save_company(None, "acme", dict(POSTED))
    assert result.get("saved") is True, result
    assert _saved(path)["name"] == "Acme"


def test_the_legal_notice_survives_the_editor_and_reaches_the_page(company, tmp_path):
    """End to end, through the shape the console actually posts.

    The form sends `legal` as a partial object and `site` as `{external: ...}` alone, which only
    works because the save merges: sending `site` at all would have wiped the address, the privacy
    points and the FAQ under the old replace-everything behaviour.

    And the page is the other end. A legal notice an operator can type into a form and then not find
    on their own site is a form that lies about what it does.
    """
    from corparius.sitegen.build import build_site

    posted = {
        **POSTED,
        "site": {"external": False},
        "legal": {
            "publisher": "Acme SAS",
            "legal_form": "SAS",
            "address": "1 rue de la Paix, 75002 Paris",
            "registration": "RCS Paris 900 123 456",
            "host": "OVHcloud, Roubaix",
            # The fields the operator left blank in the form. They arrive as empty strings, and the
            # notice must not render a label with nothing after it.
            "capital": "",
            "vat": "",
            "director": "",
        },
    }
    assert adapters.save_company(None, "acme", posted).get("saved") is True

    stored = _saved(company)
    assert stored["legal"]["registration"] == "RCS Paris 900 123 456"
    assert "capital" not in stored["legal"], "an empty box was stored as a field"
    assert stored["site"]["privacy"] == ["On ne revend rien."], "the site block was wiped"

    page = pathlib.Path(build_site(stored, str(tmp_path / "out"))).read_text(encoding="utf-8")
    assert "Mentions légales" in page, "the company writes French, so the heading is French"
    assert "RCS Paris 900 123 456" in page and "OVHcloud" in page
    assert "Capital" not in page and "TVA" not in page


def test_the_form_can_hand_the_site_over_and_take_it_back(company):
    """The switch is a checkbox, so it sends `false` as readily as `true`. Handing a site over is a
    decision an operator changes their mind about, and a flag that could only ever be set would make
    them edit a file to unset it."""
    adapters.save_company(None, "acme", {**POSTED, "site": {"external": True}})
    assert _saved(company)["site"]["external"] is True

    adapters.save_company(None, "acme", {**POSTED, "site": {"external": False}})
    assert "external" not in _saved(company)["site"]
    assert _saved(company)["site"]["url"] == "https://acme.example", (
        "the address went with the flag"
    )
