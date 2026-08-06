"""A cold email with a blank in it must never be drafted, and never be sent.

Reported from a real console: the approval card offered

    Bonjour Dr [Nom],
    j'ai lu votre publication sur [thème de publication] et …

and the operator asked whether something would fill those in. Nothing would.
`_send_outreach` passes the draft to `send_email_tracked` verbatim, so approving it
sends `Bonjour Dr [Nom]` to a real prospect.

Two causes, both fixed here. The company had no lead at all, and the tool drafted
anyway — a real model call every three hours to write a letter to nobody, which is
the same waste `draft_support_reply` stopped paying on a company with no mailbox.
And the only thing standing between a placeholder and an inbox was an instruction in
the prompt, which is a request.
"""

import types

import pytest

from corparius.tools.effects import unfilled_blanks
from corparius.tools.registry import TOOLS


class _Lead:
    def __init__(self, email="", name=""):
        self.email = email
        self.name = name

    def label(self):
        return self.name


def _ctx(leads=None):
    return types.SimpleNamespace(
        company={"slug": "acme", "name": "Acme", "offer": {"product": "Widgets"}},
        leads=leads or [],
        store=None,
    )


# --- do not draft to nobody ---------------------------------------------------


def test_no_lead_means_no_draft_and_no_model_call():
    """Checked before the draft, like the mailbox check on the tool next to it:
    with nobody to write to there is nothing to write, and paying a model call to
    find that out is the waste that check exists for."""
    reason = TOOLS["send_outreach"].skip_reason(_ctx())
    assert reason, "it would still draft a letter to nobody"
    assert "nobody to write to" in reason
    # And it says what to do about it rather than only that it stopped.
    assert "CORP_LEADS_CSV" in reason


def test_a_lead_with_no_address_is_not_somebody_to_write_to():
    """`find_targets` can return a person with no email. A letter cannot be sent
    to a name."""
    assert TOOLS["send_outreach"].skip_reason(_ctx([_Lead(name="Dr Roux")]))


def test_a_real_lead_lets_the_draft_happen():
    assert TOOLS["send_outreach"].skip_reason(_ctx([_Lead("dr@example.org", "Dr Roux")])) == ""


def test_the_prompt_names_the_person_once_there_is_one():
    """The instruction against placeholders only means something when there is a
    name to use instead."""
    prompt = TOOLS["send_outreach"].draft_prompt(_ctx([_Lead("dr@example.org", "Dr Roux")]))
    assert "Dr Roux" in prompt
    assert "Never write a placeholder" in prompt


# --- and never send one that slipped through ----------------------------------


@pytest.mark.parametrize(
    "text,found",
    [
        ("Bonjour Dr [Nom], j'ai lu votre publication sur [thème]", ["[Nom]", "[thème]"]),
        ("Hello {{first_name}},", ["{{first_name}}"]),
        ("Bonjour Dr Roux, j'ai lu votre article sur la résilience.", []),
        # Narrow on purpose: a false positive refuses a good email.
        ("We cut costs by 30% [sic] last year", ["[sic]"]),
        ("", []),
    ],
)
def test_blanks_are_found_in_the_text_that_would_actually_go_out(text, found):
    assert unfilled_blanks(text) == found


def test_a_draft_with_a_blank_is_refused_and_says_which(monkeypatch):
    """The prompt already forbids placeholders. A prompt is a request, and the
    draft is sent verbatim — so this reads the text that is about to leave."""
    from corparius.tools import effects as tools_mod

    def explode(*a, **k):
        raise AssertionError("an email with a blank in it was sent")

    monkeypatch.setattr(tools_mod.integrations, "send_email_tracked", explode)
    monkeypatch.setattr(tools_mod.integrations, "send_outreach_email", explode)

    out = tools_mod._send_outreach(
        _ctx([_Lead("dr@example.org", "Dr Roux")]), "Bonjour Dr [Nom], vu [thème]."
    )
    assert out.startswith("Not sent")
    assert "[Nom]" in out and "2 blank" in out


def test_a_clean_draft_still_goes_out(monkeypatch):
    """The guard has to be narrow enough to let a real letter through."""
    from corparius.tools import effects as tools_mod

    sent = []
    monkeypatch.setattr(
        tools_mod.integrations,
        "send_email_tracked",
        lambda to, subject, body: (sent.append((to, body)), "sent", "mid-1")[1:],
    )
    out = tools_mod._send_outreach(
        _ctx([_Lead("dr@example.org", "Dr Roux")]),
        "Bonjour Dr Roux, j'ai lu votre article sur la résilience.",
    )
    assert sent and "Dr Roux" in sent[0][1]
    assert "1 sent" in out
