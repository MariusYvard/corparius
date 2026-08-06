"""A company drafts in the language it speaks.

From a real session log, on a company whose every config field is French:

    Reply drafted: "Thank you for contacting us…"

Nothing in any agent prompt had ever named a language, so the model used the
one the system prompt was written in. `company.yaml` has a `language` field now,
and `agents._messages` is the single place every drafting tool passes through.
"""

from corparius import agents
from corparius.company import LANGUAGES
from corparius.roster import ROSTER
from corparius.tools.registry import TOOLS


class _Ctx:
    def __init__(self, company):
        self.company = company
        self.skills = None
        self.memory_top_k = 0


def _system(language):
    company = {
        "name": "Vigil",
        "slug": "vigil",
        "language": language,
        "offer": {"product": "Check-in anonyme"},
    }
    messages = agents._messages(ROSTER["support"], _Ctx(company), TOOLS["draft_support_reply"])
    assert messages[0]["role"] == "system"
    return messages[0]["content"]


def test_every_drafting_prompt_names_the_companys_language():
    assert "French" in _system("fr")
    assert "German" in _system("de")
    assert "English" in _system("en")


def test_the_language_reaches_every_agent_in_the_roster():
    """One insertion point, so this is really checking that no role bypasses
    `_messages` — which is the property that made the fix one line."""
    company = {"name": "V", "slug": "v", "language": "fr", "offer": {"product": "p"}}
    for role, spec in ROSTER.items():
        assert spec.playbook, f"{role} has an empty playbook"
        for name in spec.playbook:
            system = agents._messages(spec, _Ctx(company), TOOLS[name])[0]["content"]
            assert "French" in system, f"{role}/{name} drafts without a language"


def test_it_never_reads_as_translate_this_word():
    """The bug this repo already paid for once: `Write 'reply' in French` made
    the CEO chat answer with the word "Réponse". A language instruction must
    never name a field in the same clause as a language."""
    line = agents.language_line({"language": "fr"})
    assert "field names" in line and "stay exactly as given" in line
    import re

    # An apostrophe is fine; a *quoted token* is the shape that misfires.
    assert not re.search(r"['\"`]\w+['\"`]", line), line


def test_an_unlisted_language_is_passed_through_not_dropped():
    line = agents.language_line({"language": "ja"})
    assert "ja" in line
    assert agents.language_line({}) == agents.language_line({"language": "en"})


def test_every_language_the_site_ships_has_a_name_for_the_prompt():
    for code in LANGUAGES:
        assert code in agents.LANGUAGE_NAMES, code
