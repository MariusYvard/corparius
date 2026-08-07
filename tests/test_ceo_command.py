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


def test_the_history_is_the_callers_to_own(store, home):
    """The one line that kept a terminal out. Passing it in is what makes the service
    reachable — and passing nothing is a legitimate answer, not a degraded one.

    The returned history holds *this* exchange and nothing before it. My first version of this
    asserted it came back empty, which was wrong about the service rather than the other way
    round: the console needs the turn to render, and a caller that keeps no history simply has
    nothing carried over.
    """
    out = app_chat.once(store, Settings(), "acme", "Bonjour", history=None)
    assert out["ok"] and out["reply"]
    assert [turn["role"] for turn in out["history"]] == ["user", "assistant"]
    assert out["history"][0]["text"] == "Bonjour", "and it is this exchange, not another"

    again = app_chat.once(store, Settings(), "acme", "Autre chose", history=None)
    assert len(again["history"]) == 2, "nothing was kept between the two calls"
    assert again["history"][0]["text"] == "Autre chose"


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
