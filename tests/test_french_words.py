"""One French word per concept, held by a test because three design reviews found it drifting.

A translation test can only see whether a string exists. It cannot see that the same idea is called
three things on one screen, which is what these tables were doing:

* **the routing levels** were *tiers* in eight strings and *paliers* in three. In French *tiers* means a
  third party, so "Tiers de routage" reads as "third parties, for routing" — and the page's own
  "L'utiliser pour tous les paliers" was the right word sitting two cards from the wrong one;
* **the LLM unit** was *token* in five strings and *jeton* in one;
* **a company** was *société* in twenty-four strings and *entreprise* in six, and the settings registry
  said *company* outright. Two of those six I wrote myself an hour before this file existed, which is
  how fast a second word takes hold once one exists.

None of that is a missing translation, so `tests/test_i18n.py` passes on all of it. It is the first
thing a French reader notices and the last thing a key-set comparison can see.

The word chosen per concept is the one the table already used most: *société* by twenty-four to six,
*palier* because it is what the routing tiers are called in the three strings that got it right. Picked
by counting rather than by preference — I do not get a vote on somebody else's product's vocabulary.
"""

import json
import pathlib
import re

import pytest

FR = pathlib.Path("web/i18n/fr.json")
SPEC = pathlib.Path("corparius/config/settings_spec.py")

# concept -> (the word, a pattern for the words that must not appear, the keys that are exempt)
#
# The exemptions are the interesting part, and every one is a place where an English word carries two
# meanings. A rule written without them would force a mistranslation in the other direction, which is
# worse than the drift it exists to catch.
VOCABULARY = {
    "routing level": (
        "palier",
        r"\btiers?\b",
        # "du code tiers non audité" is third-party code — the word's other meaning, and correct.
        {"pl.unverified"},
    ),
    "the LLM unit": (
        "jeton",
        r"\btokens?\b",
        # An **access token** is a credential, and *token* is what a French operator calls one. These
        # six are about that rather than about a unit of model usage, and "jeton d'accès" in them would
        # be the same mistake pointing the other way.
        {
            "live.getNetlify",
            "live.hostReady",
            "live.netlifyToken",
            "token.needed",
            "token.ok",
            "token.save",
        },
    ),
    "a provider": (
        "fournisseur",
        r"providers?",
        # `nav.providers` is the tab's name and reads "Fournisseurs"; nothing is exempt here, which is
        # the point — fourteen strings said *provider* while the tab strip said *Fournisseurs*, so four
        # of them told an operator to open a tab by a name the console does not use.
        set(),
    ),
    "a company": (
        "société",
        r"\bentreprises?\b|\bcompan(?:y|ies)\b(?!/)",
        # `companies/…` as a path needs no exemption — the lookahead above handles it, which is why
        # `sk.intro` and `company.deleteHelp` are not listed here: the test refused them as dead
        # entries, correctly. What is left is three sentences using the plural for the operator's own
        # portfolio ("vos entreprises", "apprendre son métier à une entreprise"), where the sentence
        # reads correctly and changing it would be a rewrite rather than a fix.
        {"bk.warn", "sk.none", "up.confirm"},
    ),
}


def _fr() -> dict[str, str]:
    return json.loads(FR.read_text(encoding="utf-8"))


def test_there_is_a_french_table_to_check():
    """The guard on the guard: this file is worthless the moment it stops finding strings."""
    table = _fr()
    assert len(table) > 400, f"only {len(table)} French strings"
    for _concept, (word, _forbidden, _exempt) in VOCABULARY.items():
        assert any(word in v.lower() for v in table.values()), f"nothing says {word!r}"


@pytest.mark.parametrize("concept", sorted(VOCABULARY))
def test_one_word_per_concept(concept):
    word, forbidden, exempt = VOCABULARY[concept]
    guilty = {
        key: value
        for key, value in _fr().items()
        if key not in exempt and re.search(forbidden, value, re.I)
    }
    assert not guilty, (
        f"the French for {concept!r} is {word!r}, and these say something else:\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in guilty.items())
    )


def test_the_exemptions_are_still_needed():
    """Both ends of the wire. An exemption for a key that no longer trips the rule is a licence nobody
    will think to revoke."""
    table = _fr()
    for concept, (_word, forbidden, exempt) in VOCABULARY.items():
        for key in exempt:
            assert key in table, f"{concept}: {key} is exempt and no longer exists"
            assert re.search(forbidden, table[key], re.I), (
                f"{concept}: {key} no longer needs its exemption"
            )


def test_the_registry_uses_the_same_word_as_the_console():
    """Two surfaces, one vocabulary. The settings registry writes its own French in Python and is
    rendered into the same tab as these strings — it said "Versionnement des companies" while the table
    said *société*, which is the same defect as a missing translation with better spelling."""
    source = SPEC.read_text(encoding="utf-8")
    strings = re.findall(r'(?:help_fr|label_fr)\s*=\s*\n?\s*"([^"]*)"', source)
    strings += re.findall(r'"(?:help_fr|label_fr)":\s*\n?\s*"([^"]*)"', source)
    assert strings, "no French registry strings found; this test has gone blind"
    # The same lookahead the table's rule uses: `companies/<slug>/skills/` is a path on disk and stays
    # in English wherever it is printed.
    guilty = [s for s in strings if re.search(r"\bcompan(?:y|ies)\b(?!/)", s, re.I)]
    assert not guilty, "the registry still says company:\n  " + "\n  ".join(guilty)
