"""Asking the CEO something from a terminal, and the powers that come with it.

The console had this and a terminal did not, and the barrier was one line:
`state.chats.setdefault(slug, deque(...))` — the history lived in a dict in the console's
process, so the only caller that could exist was the console.

The history is a parameter now. A terminal passes a list and gets a single turn, and that limit
is **stated rather than hidden**: conversation surviving a process is a store table, not
something a one-shot command can pretend to have.

What comes with it matters more than the convenience. `directives.apply` is the half that makes
the CEO's answer true rather than polite — it used to answer "I will pause the campaigns" and
change nothing — and a terminal now reaches exactly the same one.
"""

import pytest

from corparius.app import chat as app_chat
from corparius.app import directives
from corparius.config.settings import Settings
from corparius.store import Store


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    # `cfg` caches its layers, so setting the variable is not enough — without this the router
    # reads the previous answer and the test reaches a real provider. conftest refuses that with
    # an assertion, which is how this was caught rather than paid for.
    from corparius.config import cfg

    cfg.invalidate()
    (tmp_path / "companies" / "acme").mkdir(parents=True)
    (tmp_path / "companies" / "acme" / "company.yaml").write_text(
        "name: Acme\nslug: acme\noffer:\n  product: p\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def store(home):
    s = Store(str(home / "data"))
    yield s
    s.close()


# --- the seam ------------------------------------------------------------------


def test_passing_nothing_means_the_stored_conversation(store, home):
    """What `history=None` means, and schema 21 inverted it.

    It used to mean "no memory": the caller kept a list or got a single turn. This test asserted
    `len(again["history"]) == 2` — "nothing was kept between the two calls" — and that assertion was
    the old contract, not a property worth preserving. `chat_turns` exists now, so passing nothing
    means *the conversation this company is having*, and the second call sees the first.

    Which is the point: one conversation per company whoever is typing, so `corparius ceo` and the
    console are in the same thread and a phone can read what either said. The same argument `cmd_run`
    makes for recording a foreground run in `jobs`.
    """
    out = app_chat.once(store, Settings(), "acme", "Bonjour", history=None)
    assert out["ok"] and out["reply"]
    assert [turn["role"] for turn in out["history"]] == ["user", "assistant"]
    assert out["history"][0]["text"] == "Bonjour"

    again = app_chat.once(store, Settings(), "acme", "Autre chose", history=None)
    assert [turn["text"] for turn in again["history"] if turn["role"] == "user"] == [
        "Bonjour",
        "Autre chose",
    ], "the second call did not see the first: the conversation is not being kept"
    assert len(store.chat_history("acme")) == 4, "both sides of both exchanges are on disk"


def test_an_empty_list_is_the_one_shot_with_no_trace(store, home):
    """The override, and it has to stay reachable.

    "Answer this once and remember nothing" is a real thing to ask for — and a silent inability to
    ask for it would be worse than a parameter. `history=[]` is falsy but not `None`, which is what
    separates "no memory" from "not specified".
    """
    out = app_chat.once(store, Settings(), "acme", "Juste une fois", history=[])
    assert out["ok"] and out["reply"]
    assert store.chat_history("acme") == [], "a one-shot must leave no transcript"


def test_the_stored_conversation_is_per_company(store, home):
    """Two companies are two conversations. Sharing them would put one company's plan in another's
    prompt, which is the tenancy mistake this project has no reason to make."""
    app_chat.once(store, Settings(), "acme", "Pour acme", history=None)
    assert [t["text"] for t in store.chat_history("acme") if t["role"] == "user"] == ["Pour acme"]
    assert store.chat_history("autre") == []


def test_forgetting_the_conversation_is_the_operators_to_do(store, home):
    """Their own transcript, theirs to clear — the same argument as `forget` for a memory. Deleted
    rather than archived: a skill is knowledge the curator may want back, a chat is a conversation
    they have decided to end."""
    app_chat.once(store, Settings(), "acme", "Bonjour", history=None)
    assert store.forget_chat("acme") == 2
    assert store.chat_history("acme") == []
    assert store.forget_chat("acme") == 0, "clearing an empty conversation is not an error"


def test_a_caller_that_keeps_history_gets_it_back(store, home):
    """What the console does with its deque, in miniature: two turns, and the second sees the
    first."""
    history: list = []
    app_chat.once(store, Settings(), "acme", "Première question", history=history)
    app_chat.once(store, Settings(), "acme", "Deuxième question", history=history)
    said = [turn["text"] for turn in history if turn["role"] == "user"]
    assert said == ["Première question", "Deuxième question"]


def test_the_signature_takes_no_console_object(store):
    """Stated as a test because it is the whole reason this moved. `UiState` in the signature is
    what kept the command line out, exactly as it did for `persist`."""
    import inspect

    params = list(inspect.signature(app_chat.once).parameters)
    assert params[:2] == ["store", "settings"], params
    assert "state" not in params


def test_the_tokens_are_billed_to_the_company(store, home):
    """Whoever calls it, the spend lands on the company. A terminal chat that cost nothing on
    the books would make the budget a fiction."""
    app_chat.once(store, Settings(), "acme", "Bonjour")
    assert store.status("acme")["tokens"] > 0


# --- the powers, which is the part that matters ---------------------------------


def test_a_terminal_reaches_the_same_directives(store, home):
    """Not "it can chat" — it can *act*, through the same function. `chat` writes a sentence and
    this is what makes it true."""
    changed = directives.apply(store, "acme", {"pause": ["social"]}, "en")
    assert "social" in changed
    assert {d["target"] for d in store.directives("acme", "pause")} == {"social"}


def test_a_pin_with_no_provider_prefix_is_still_refused(store, home):
    """The guard that saved this from the mock. Every prefix-less value resolves to `local:`, so
    storing one would put a role on a model nobody chose — and the mock's own placeholder is
    exactly that shape, which is how it got tested for free."""
    directives.apply(store, "acme", {"model": {"design": "[mock:haiku] design"}}, "en")
    assert store.get_setting("CORP_MODEL_DESIGN") in (None, ""), "a garbage pin must not stick"


def test_a_role_that_is_not_pausable_is_refused(store, home):
    """`PAUSABLE` is the list the prompt names. A role outside it is a model inventing one."""
    changed = directives.apply(store, "acme", {"pause": ["not-a-role"]}, "en")
    assert store.directives("acme", "pause") == []
    assert "not-a-role" not in changed or "unknown" in changed.lower()


def test_the_mock_applies_nothing(store, home):
    """Measured on a real run of the command: the mock echoes the schema's field names into its
    answer, so a chat in offline mode looks like it asked for a pin and an approval. Nothing
    must land — a default-on offline mode that quietly reconfigures a company would be worse
    than no offline mode."""
    app_chat.once(store, Settings(), "acme", "Combien de tâches ouvertes ?")
    assert store.directives("acme") == []


# --- the command ----------------------------------------------------------------


def test_the_command_prints_the_answer_and_where_it_came_from(home, capsys):
    from corparius import cli

    assert cli.main(["ceo", "--company", "acme", "Combien de tâches ?"]) == 0
    said = capsys.readouterr().out
    assert said.strip(), "an empty answer is not an answer"
    assert "-- mock" in said, "which model replied has to be visible, as it is in the console"


def test_the_command_exits_non_zero_when_no_model_answered(home, capsys, monkeypatch):
    """`unanswered` exists so the page can render a failure as a failure rather than as the CEO
    having said something odd. A terminal says it with an exit code."""
    from corparius import cli
    from corparius.app import chat as chat_mod

    monkeypatch.setattr(
        chat_mod,
        "once",
        lambda *a, **k: {
            "ok": True,
            "reply": "no model answered",
            "unanswered": True,
            "model": "",
            "provider": "",
            "proposal": None,
            "history": [],
        },
    )
    assert cli.main(["ceo", "--company", "acme", "quoi ?"]) == 1


def test_the_command_says_what_the_ceo_wants_to_do(home, capsys, monkeypatch):
    """The console renders a proposal as a button. A terminal can only say it — and saying
    nothing would hide a decision the CEO is waiting on."""
    from corparius import cli
    from corparius.app import chat as chat_mod

    monkeypatch.setattr(
        chat_mod,
        "once",
        lambda *a, **k: {
            "ok": True,
            "reply": "on lance ?",
            "unanswered": False,
            "model": "m",
            "provider": "p",
            "proposal": {"label": "Lancer une journée"},
            "history": [],
        },
    )
    assert cli.main(["ceo", "--company", "acme", "on lance ?"]) == 0
    assert "it wants to: Lancer une journée" in capsys.readouterr().out


# --- when no model can be reached at all ------------------------------------------


def test_a_router_that_reaches_nothing_answers_instead_of_crashing(home, monkeypatch):
    """Measured on a real console, and it arrived as an HTTP 500 with a traceback.

    The router catches each remote step and moves on ("trying next step"), but the local one is the
    last resort: it retries once for an Ollama cold start and then lets the exception out. With every
    cloud key rate-limited and no Ollama running — which is an ordinary Tuesday on free tiers — the
    exception went all the way through `app_chat.once`, `adapters.chat` and the handler, and the tab
    whose entire job is to be asked what is going on answered with a stack trace.

    So it is caught, and the operator gets a sentence naming both halves of the cause.
    """
    import requests

    from corparius.providers import llm

    def dead(*a, **k):
        raise requests.RequestException("404 Client Error: Not Found for /api/chat")

    monkeypatch.setattr(llm.HybridRouter, "generate", dead)
    store = Store(str(home / "data"))
    out = app_chat.once(store, Settings(), "acme", "où en est le backlog ?", lang="fr")

    assert isinstance(out, dict) and out.get("reply"), out
    assert "Aucun modèle n'a pu être joint" in out["reply"]
    assert "Providers" in out["reply"], "the sentence has to name where to go and look"
    assert "Traceback" not in out["reply"]


def test_unreachable_is_not_reported_as_a_silent_model(home, monkeypatch):
    """The distinction the fix is built around, and the reason it is not repaired in the router.

    "Nothing could be reached" and "the model answered nothing" want different actions from an
    operator: start Ollama or fix a key, versus try again or pick another tier. Returning an empty
    answer from the router would collapse the two into the message below, which would send somebody
    to the wrong place.
    """
    import requests

    from corparius.providers import llm

    monkeypatch.setattr(
        llm.HybridRouter,
        "generate",
        lambda *a, **k: (_ for _ in ()).throw(requests.RequestException("down")),
    )
    store = Store(str(home / "data"))
    said = app_chat.once(store, Settings(), "acme", "salut", lang="en")["reply"]

    assert "No model could be reached" in said
    # A fragment of the *other* message, not the phrase "did not answer": this one says "the local
    # one did not answer" itself, and asserting on that would have been a test of my own wording
    # rather than of which of the two branches ran.
    assert "the tier may be misconfigured" not in said, "reported as a model that stayed silent"


def test_the_turn_is_still_recorded_so_the_transcript_has_no_hole(home, monkeypatch):
    """A question that was asked stays asked. Dropping it would leave the operator scrolling a
    conversation where their own message is missing and the reason it failed is missing with it."""
    import requests

    from corparius.providers import llm

    monkeypatch.setattr(
        llm.HybridRouter,
        "generate",
        lambda *a, **k: (_ for _ in ()).throw(requests.RequestException("down")),
    )
    store = Store(str(home / "data"))
    app_chat.once(store, Settings(), "acme", "une question qui a échoué", lang="fr")

    said = [turn["text"] for turn in store.chat_history("acme")]
    assert "une question qui a échoué" in said
    assert any("Aucun modèle" in text for text in said)
