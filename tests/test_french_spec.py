"""The registry's French, and the one defect a translation test cannot see.

`tests/test_i18n.py` holds the console's 528 strings to a key-for-key, value-for-value equality with
the page. The **settings registry** is a different surface: 80 fields with `label_fr` and `help_fr`
written in Python, rendered into the Settings tab, and checked by nothing.

Six of them had lost every accent — "Chaque dossier de company comme depot prive independant", "Commit
apres chaque run", "Portee 'repo'", "si vous y etes deja connecte" — and they had lost them silently,
because unaccented French is valid Python, valid UTF-8, and reads as French to a spell-checker that
does not have one. A blind design review found it by reading a screenshot; nothing in the repository
could have.

So the guard is crude on purpose: **a French string long enough to need an accent has one, or it is
named here.** The allow-list is six sentences, each checked by hand, and it is short because that is
what makes it readable in a diff. A seventh appearing is either a real find or a line for somebody to
add with a reason.

**What it does not catch, said plainly: one accent lost out of four.** Proved rather than assumed —
removing the first accent from a sentence that has three more leaves this file passing. It catches the
shape the defect actually had, which is every accent gone from a whole sentence, and that is what a
paste through a non-UTF-8 tool or a hand-retyped translation produces. A test that could tell "déjà"
from "deja" inside otherwise-correct French would need a dictionary, and a dictionary in the test suite
is a dependency this project does not take for a proofreading job.

The same file also carried English inside French — "Versionnement des companies", "dossier de company"
— which is the other half of the same defect: the product's own word in French is *entreprise*, and
`company` is the code's noun rather than the operator's.
"""

import ast
import pathlib

import pytest

SPEC = pathlib.Path("corparius/config/settings_spec.py")

# Accented characters French actually uses. Written out rather than derived from `unicodedata`, because
# a combining-mark test also passes on a stray diacritic in an English word and this is meant to be
# obvious.
ACCENTS = set("éèêëàâäîïôöûùüÿçœæÉÈÊËÀÂÄÎÏÔÖÛÙÜÇŒ")

# The threshold. Below it, plenty of correct French needs no accent ("Jeton GitHub", "Port SMTP"), and a
# guard that fires on those teaches people to widen the allow-list until it means nothing.
LONG = 30

# Correct French that happens to need no accent. Every one read by hand.
NO_ACCENT_NEEDED = {
    "127.0.0.1 garde la console sur cette machine. Autre chose exige un token.",
    "Outils exigeant une approbation",
    "993 = TLS implicite, 143 = STARTTLS.",
    "Seulement si la lecture utilise un autre compte que l'envoi.",
    "Seulement si la lecture utilise un autre mot de passe que l'envoi.",
    "0 = aucun plafond. Chauffez un domaine neuf progressivement.",
}


def _french_strings() -> list[str]:
    """Every `label_fr` and `help_fr` literal, in both shapes the file writes them.

    Read as an AST rather than with a regex: the values are implicitly concatenated across lines, and a
    regex that matched one line at a time would have missed four of the six defects — the ones whose
    stripped accents were on the second line of a wrapped string.
    """
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in ("help_fr", "label_fr"):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                found.append(node.value.value)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                named = isinstance(key, ast.Constant) and key.value in ("help_fr", "label_fr")
                if named and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.append(value.value)
    return found


def test_there_are_french_strings_to_check():
    """The guard on the guard. If the spec stops carrying its French inline — a real possibility, since
    it could move to a table — this file becomes vacuous, and a vacuous test that passes is worse than
    no test."""
    strings = _french_strings()
    assert len(strings) > 100, f"only {len(strings)} French strings in the registry"
    assert sum(1 for s in strings if len(s) > LONG) > 40


def test_every_long_french_string_is_accented_or_declared():
    """The defect, stated as a rule. Six of these had every accent stripped and rendered that way in the
    console's Settings tab for as long as the tab has existed."""
    offenders = [
        s
        for s in _french_strings()
        if len(s) > LONG and not (ACCENTS & set(s)) and s not in NO_ACCENT_NEEDED
    ]
    assert not offenders, (
        "French registry strings with no accent at all:\n  "
        + "\n  ".join(offenders)
        + "\n\nEither they lost their accents, or they are correct and belong in NO_ACCENT_NEEDED "
        "with a reason."
    )


def test_the_allow_list_has_no_dead_entries():
    """Both ends of the wire. An entry naming a string the file no longer contains is a line nobody
    will ever delete, and the next reader trusts it."""
    strings = set(_french_strings())
    stale = sorted(NO_ACCENT_NEEDED - strings)
    assert not stale, f"NO_ACCENT_NEEDED names strings the spec no longer has: {stale}"


@pytest.mark.parametrize("word", ["company", "companies"])
def test_the_french_says_entreprise(word):
    """The code's noun is `company`; the operator's French noun is *entreprise*. "Versionnement des
    companies" and "dossier de company" shipped in the French Settings tab, which is the same defect as
    a stripped accent wearing different clothes."""
    guilty = [s for s in _french_strings() if word in s.lower().split() or f" {word} " in s.lower()]
    assert not guilty, f"French registry strings still saying {word!r}:\n  " + "\n  ".join(guilty)
