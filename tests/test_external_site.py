"""A site the operator runs outside corparius entirely.

Three kinds of site exist and only this one is new. `companies/<slug>/site/` holds pages corparius
publishes on the operator's behalf, and `test_owned_site.py` covers those. A generated page is built
from four fields of `company.yaml`. This third kind lives somewhere else, is deployed by something
else, and is declared as an address plus `site.external: true`.

**The half that was a defect rather than a feature.** `readiness` counted a site as existing only
when corparius had published one, so the utility gate held the outreach agent forever on exactly the
companies most ready to use it: the ones that already had a working site. A public address is a
public address, and the roles waiting on one have no business asking who deployed it.

The rest is corparius keeping its hands off: nothing generates a competing page, nothing reviews a
page it did not write, and nothing pushes into a deployment pipeline that is not its own.
"""

import types

import pytest

from corparius import readiness
from corparius.company import validate
from corparius.tools import effects
from corparius.tools.registry import TOOLS

OUTSIDE = {
    "slug": "acme",
    "name": "Acme",
    "site": {"url": "https://acme.example", "external": True},
}


def _ctx(tmp_path, company=None, store=None):
    return types.SimpleNamespace(
        company=company or dict(OUTSIDE),
        data_path=str(tmp_path),
        store=store,
        role="design",
        structured=None,
    )


# --- what the operator declares ---------------------------------------------------


def test_the_flag_needs_an_address_to_mean_anything(tmp_path):
    """`external: true` with no URL says a site exists somewhere and does not say where. Every
    consumer of this wants the address (the gate, the outreach link, the go-live card), so a flag
    without one is dropped and said out loud rather than remembered as a half fact."""
    # `(cfg, errors, warnings)`, in that order.
    loaded, _errors, warnings = validate({**OUTSIDE, "site": {"external": True}})
    assert "external" not in (loaded.get("site") or {})
    assert any("site.external" in w for w in warnings)


def test_an_address_alone_is_not_a_claim_of_ownership(tmp_path):
    """`site.url` has always meant "where the generated page will live once hosted", and thousands of
    companies set it for exactly that. Reading it as "this site is not yours to touch" would change
    what an existing config means, which is worse than asking for one more word."""
    loaded, _err, _warn = validate({**OUTSIDE, "site": {"url": "https://acme.example"}})
    assert "external" not in (loaded.get("site") or {})
    assert readiness.facts(loaded, str(tmp_path))["site"] is False


# --- the gate this fixes ----------------------------------------------------------


def test_an_external_site_satisfies_the_roles_that_wait_for_one(tmp_path):
    """The defect the utility gate introduced. Outreach with no public address sends a link to
    nothing, which is why it waits; a company running its own site has the address, so it does not.
    Nothing about who published it changes what an outreach email needs."""
    from corparius.kernel.records import AgentRole
    from corparius.orchestrator import due_roles, held_roles

    loaded, _err, _warn = validate(OUTSIDE)
    assert readiness.facts(loaded, str(tmp_path))["site"] is True

    enabled = {r.value: True for r in AgentRole}
    ready = {f for f, ok in readiness.facts(loaded, str(tmp_path)).items() if ok}
    ran = {s.role.value for hour in range(48) for s in due_roles(hour, enabled, ready=ready)}
    assert "outreach" in ran
    assert "outreach" not in held_roles(enabled, ready)


# --- corparius keeping its hands off ----------------------------------------------


def test_nothing_builds_a_second_site(tmp_path):
    """A generated page beside a live one is two sites with one name, and the design agent's work
    landing in the one nobody visits. Measured on a real install once already, with a different
    cause: six hand-built pages, and this tool rewriting a single page from four config fields every
    design turn while reporting success."""
    out = effects._build_site(_ctx(tmp_path), "")
    assert "runs itself" in out and "acme.example" in out
    assert not (tmp_path / "sites").exists(), "it built a page anyway"


def test_nothing_reviews_a_page_it_did_not_write(tmp_path):
    """Two review tools and they are exclusive by design: `review_site` judges the pages a company
    wrote, `review_generated_site` judges the one corparius built. A company whose site is elsewhere
    has neither, and both have to say so rather than review an empty string.

    `review_site` already declined for its own reason (no pages under `companies/<slug>/site/`) and
    keeps it. The one that needed the new answer is the other."""
    assert "no site of its own" in TOOLS["review_site"].skip_reason(_ctx(tmp_path))
    generated = TOOLS["review_generated_site"].skip_reason(_ctx(tmp_path))
    assert "runs it itself" in generated and "acme.example" in generated


def test_a_deploy_refuses_rather_than_reporting_a_success(tmp_path):
    """Refused, not skipped. This tool sits at the human gate, and a "published" that pushed nothing
    into somebody else's domain is the exact report this function was rewritten to stop making."""
    result = effects._deploy_site(_ctx(tmp_path))
    assert result.ok is False
    assert "deploys it itself" in result.output
    # Where to change it, in the surface the operator is standing in. `tests/test_inbox_remedy.py`
    # holds the rule and caught the first version of this line: a notice naming a file to edit is
    # asking somebody looking at a web page to go and be a developer.
    assert "company editor" in result.output, "it refused without saying how to change its mind"


def test_a_company_that_did_not_ask_is_untouched(tmp_path):
    """The other end of every assertion above. All of this is opt-in, and a company with no
    `site.external` keeps the behaviour it has always had."""
    plain = {"slug": "acme", "name": "Acme", "offer": {"product": "p"}}
    assert effects._external_site(plain) == ""
    assert "runs it itself" not in TOOLS["review_site"].skip_reason(_ctx(tmp_path, plain))


@pytest.mark.parametrize(
    "site",
    [{"external": "yes", "url": "https://a.example"}, {"external": 1, "url": "https://a.example"}],
)
def test_the_ways_a_person_writes_true_in_yaml(site):
    """`external: yes` is what somebody types, and YAML hands it over as a string in some versions
    and a bool in others. A flag that only works when it is spelled one way is a flag that silently
    does nothing."""
    loaded, _err, _warn = validate({**OUTSIDE, "site": site})
    assert (loaded.get("site") or {}).get("external") is True


# --- who publishes this site --------------------------------------------------------


def test_the_legal_notice_renders_only_what_the_operator_filled(tmp_path):
    """A legal notice is a list of register identifiers, and corparius can invent none of them.

    So the section renders the lines that have a value and omits the rest. `RCS:` followed by
    nothing is worse than no line at all: it says the company looked the number up and found none,
    on a page whose whole purpose is being checkable.
    """
    from corparius.sitegen.copy import strings
    from corparius.sitegen.sections import legal_html

    filled = {
        "legal": {
            "publisher": "Acme SAS",
            "address": "1 rue de la Paix, 75002 Paris",
            "registration": "RCS Paris 900 123 456",
            "host": "OVHcloud, 2 rue Kellermann, 59100 Roubaix",
        }
    }
    html = legal_html(filled, strings("fr"))
    assert "Mentions légales" in html
    assert "RCS Paris 900 123 456" in html and "Hébergeur" in html
    assert "TVA" not in html, "a field with no value rendered its label anyway"
    assert "Directeur" not in html

    assert legal_html({}, strings("fr")) == "", "an empty block rendered a heading"
    assert legal_html({"legal": {"publisher": "   "}}, strings("fr")) == ""


def test_the_heading_exists_in_every_language_the_page_can_be_written_in():
    """The page's furniture falls back to English word by word, so a missing key renders an English
    heading over French content. Seven languages ship and all seven need both new strings."""
    from corparius.sitegen.copy import STRINGS

    missing = [
        lang for lang, table in STRINGS.items() if "legal" not in table or "host" not in table
    ]
    assert not missing, missing


def test_an_unknown_legal_field_is_named_rather_than_kept(tmp_path):
    """It would never render, so keeping it silently would leave an operator believing they had
    declared something. The rest of the block still loads."""
    from corparius.company import validate

    loaded, _errors, warnings = validate(
        {"slug": "acme", "name": "Acme", "legal": {"publisher": "Acme SAS", "siret_typo": "x"}}
    )
    assert loaded["legal"] == {"publisher": "Acme SAS"}
    assert any("legal.siret_typo" in w for w in warnings)


def test_the_doctor_notices_a_company_that_sells_without_one(tmp_path, monkeypatch):
    """corparius cannot write the notice and can notice its absence, which is the honest division.

    Gated on being able to take money rather than on having a page: the obligation follows selling.
    A warning and never an error, because whether it applies is a question about the operator's
    jurisdiction rather than about their config.
    """
    import yaml

    from corparius.config import cfg
    from corparius.config.settings import Settings
    from corparius.doctor import _check_legal_notice

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cfg.invalidate()
    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    base = {"slug": "acme", "name": "Acme", "offer": {"product": "p", "price_eur": 9}}

    (folder / "company.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    settings = Settings()
    settings.data_path = str(tmp_path / "data")
    level, _, _ = _check_legal_notice(settings)
    assert level == "ok", "a company that cannot be paid yet is not being asked for one"

    sells = {**base, "offer": {**base["offer"], "payment_link": "https://buy.example/x"}}
    (folder / "company.yaml").write_text(yaml.safe_dump(sells), encoding="utf-8")
    level, _, said = _check_legal_notice(settings)
    assert level == "warn" and "acme" in said and "conformite-fr" in said

    (folder / "company.yaml").write_text(
        yaml.safe_dump({**sells, "legal": {"publisher": "Acme SAS"}}), encoding="utf-8"
    )
    assert _check_legal_notice(settings)[0] == "ok"
