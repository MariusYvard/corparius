"""Creating a company from a terminal — the gap `test_two_callers_agree.py` names.

`cli.cmd_init` looks like the command-line half of the console's wizard and is not: it stamps
the state of a company that already exists. So there was no way to create one from a terminal
at all, and an operator wrote `companies/<slug>/company.yaml` by hand — guessing the shape, the
field names, and which of them are required, with nothing running `company.validate` at
creation time.

That is worse than a missing convenience. The wizard's own design note is that it "asks for two
fields and fills the rest from the same validator the editor uses, so a company created here
and one edited later can never disagree about what a company is". A hand-written file had none
of it.
"""

import pytest
import yaml

from corparius import company as company_mod
from corparius.app import companies as app_companies
from corparius.app.errors import Refused
from corparius.store import Store


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture()
def store(home):
    s = Store(str(home / "data"))
    yield s
    s.close()


def _written(home, slug):
    path = home / "companies" / slug / "company.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- the service ----------------------------------------------------------------


def test_two_fields_are_enough(store, home):
    """The wizard's whole claim. Everything else has a default, and a hand-written file is
    where an operator finds out which fields those were."""
    out = app_companies.create(store, name="Acme", product="Un audit")
    assert out["slug"] == "acme"
    written = _written(home, "acme")
    assert written["name"] == "Acme"
    assert written["offer"]["product"] == "Un audit"
    assert written["agents"], "the roster has to be filled or nothing runs"


def test_the_slug_survives_the_name(store, home):
    """`slugify` folds accents; the naive version turned "Méthode et Architecture" into
    `m-thode-et-architecture` — the accent became a hyphen and the word lost a letter. A
    company created from a terminal has to get the same slug as one created from the page."""
    out = app_companies.create(store, name="Méthode et Architecture", product="p")
    assert out["slug"] == "methode-et-architecture"
    assert (home / "companies" / "methode-et-architecture" / "company.yaml").is_file()


def test_the_state_is_stamped_so_the_loop_starts_at_the_beginning(store, home):
    """The row `init` exists for. A company created and not stamped looks to the loop like one
    that has already played its first tick."""
    app_companies.create(store, name="Acme", product="p")
    assert store.load_state("acme")["tick"] == 0


def test_a_template_fills_the_examples(store, home):
    out = app_companies.create(store, name="Acme", template="saas")
    written = _written(home, "acme")
    assert written["offer"]["product"], "the template's product should be there"
    assert written["offer"]["billing"] == "stripe"
    assert out["config"]["agents"]["coder"] is True, "saas turns the coder on"


def test_an_explicit_field_beats_the_template(store, home):
    """The order that makes offering a template safe at all. A typed product must not be
    replaced by an example."""
    app_companies.create(store, name="Acme", product="Mon vrai produit", template="saas")
    assert _written(home, "acme")["offer"]["product"] == "Mon vrai produit"


def test_the_language_picks_which_examples(store, home):
    fr = app_companies.create(store, name="Acme FR", template="saas", lang="fr")
    en = app_companies.create(store, name="Acme EN", template="saas", lang="en")
    assert fr["config"]["offer"]["product"] != en["config"]["offer"]["product"]


def test_a_company_with_no_name_is_refused(store):
    with pytest.raises(Refused):
        app_companies.create(store, name="", product="p")


def test_creating_the_same_company_twice_is_refused(store, home):
    app_companies.create(store, name="Acme", product="p")
    with pytest.raises(Refused, match="already exists"):
        app_companies.create(store, name="Acme", product="p")


def test_a_repairable_field_is_warned_about_rather_than_refused(store, home):
    """`company.validate` repairs what it can and names the rest. Refusing a creation over a
    field it would have fixed is the wrong trade for somebody starting out."""
    out = app_companies.create(store, name="Acme", product="p", session_tokens=1)
    assert out["slug"] == "acme"
    assert out["warnings"], "a session_tokens below the floor should be reported"


def test_what_is_written_reloads_through_the_same_validator(store, home):
    """The property that makes this worth having at all: a created company and an edited one
    cannot disagree about what a company is, because one function decides."""
    app_companies.create(store, name="Acme", product="p", template="agency")
    again, errors, _ = company_mod.validate(_written(home, "acme"))
    assert not errors, errors
    assert again["slug"] == "acme"


def test_the_templates_are_listed_once_not_twice(store):
    """The console renders these in the wizard and a terminal lists them for `--template`. Two
    readings of one table is how they come to offer different sets."""
    listed = app_companies.templates("en")
    assert {t["id"] for t in listed} == {t["id"] for t in company_mod.TEMPLATES}
    assert all(t["label"] for t in listed)


# --- the command ----------------------------------------------------------------


def test_the_command_creates_and_says_what_to_do_next(home, capsys):
    from corparius import cli

    assert cli.main(["new", "--name", "Acme", "--product", "Un audit"]) == 0
    said = capsys.readouterr().out
    assert "created Acme (acme)" in said
    assert "corparius run --company acme" in said, "a first run is the next thing to say"
    assert (home / "companies" / "acme" / "company.yaml").is_file()


def test_the_command_lists_templates_without_creating_anything(home, capsys):
    from corparius import cli

    assert cli.main(["new", "--list-templates"]) == 0
    said = capsys.readouterr().out
    assert "saas" in said and "agency" in said
    # Not "companies/ does not exist": `main` calls `company.seed_examples()` before parsing
    # anything, which is the first-run seeding the frozen launcher does too. What listing must
    # not do is create a *company of its own* — the first version of this assertion was wrong
    # about the code rather than the other way round.
    made = sorted(p.parent.name for p in (home / "companies").glob("*/company.yaml"))
    assert made == ["example"] or made == [], f"listing created {made}"


def test_the_command_exits_non_zero_on_a_refusal(home, capsys):
    from corparius import cli

    assert cli.main(["new", "--name", "Acme", "--product", "p"]) == 0
    assert cli.main(["new", "--name", "Acme", "--product", "p"]) == 1
    assert "already exists" in capsys.readouterr().out
