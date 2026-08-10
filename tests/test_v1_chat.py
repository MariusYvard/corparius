"""The CEO conversation, once it survives the process that had it.

This tab could not have been built honestly before schema 21. The history was `UiState.chats`, a deque
per company in the console's process, so:

  * closing the console lost every exchange — including the ones in which the CEO paused a role or set
    a focus, which are the turns an operator most wants to look back at;
  * a phone could not read any of it, which is the premise of the whole v1 contract;
  * `corparius ceo` was a stranger to the thread: it passed a fresh list and got one turn.

Two docstrings had promised the table and named it — `app/chat.py` and `cli/operate.cmd_ceo` both said,
correctly, that conversation surviving a process is a store table and not something they could pretend
to have. The plan named it beside `jobs`; it was the half of schema 19 never written.
"""

import json
import shutil
import threading
from http.client import HTTPConnection

import pytest


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from corparius.api.server import build_server
    from corparius.config import cfg
    from corparius.config.settings import Settings

    from .conftest import EXAMPLE_COMPANY

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    home = tmp_path / "home"
    shutil.copytree(EXAMPLE_COMPANY, home / "companies" / "example")
    monkeypatch.setenv("CORP_HOME", str(home))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _call(srv, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=20)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        {"Content-Type": "application/json"},
    )
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, json.loads(raw or b"{}")


# --- it survives the process ------------------------------------------------------


def test_a_conversation_survives_the_console_that_had_it(tmp_path, monkeypatch):
    """The property schema 21 exists for, proved across two **real processes**.

    Two `build_server` calls in one interpreter would not prove it — the store is shared through the
    same module and an in-process deque would have looked persistent. So the first console is a
    subprocess, it is killed, and a second one is asked what was said.
    """
    import shutil as sh

    from corparius.config import cfg

    from .conftest import EXAMPLE_COMPANY
    from .test_durable_jobs import _console, _free_port, _kill

    home = tmp_path / "home"
    sh.copytree(EXAMPLE_COMPANY, home / "companies" / "example")
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_HOME", str(home))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    cfg.invalidate()
    env = {
        "CORP_DATA_PATH": str(tmp_path / "data"),
        "CORP_HOME": str(home),
        "CORP_LLM_MOCK": "true",
        "CORP_UPDATE_CHECK": "false",
    }

    port = _free_port()
    first = _console(port, tmp_path, env)
    try:
        status, said = _call_port(
            port, "POST", "/api/v1/chat", {"message": "Bonjour", "company": "example"}
        )
        assert status == 200, said
        assert said["reply"]
    finally:
        _kill(first)

    port = _free_port()
    second = _console(port, tmp_path, env)
    try:
        status, back = _call_port(port, "GET", "/api/v1/chat?company=example")
        assert status == 200
        spoken = [t["text"] for t in back["history"] if t["role"] == "user"]
        assert spoken == ["Bonjour"], (
            "a console that did not witness the exchange cannot see it: the conversation did not "
            "survive the process"
        )
    finally:
        _kill(second)


def _call_port(port, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        {"Content-Type": "application/json"},
    )
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, json.loads(raw or b"{}")


# --- the read ---------------------------------------------------------------------


def test_an_empty_conversation_is_an_empty_list(server):
    status, data = _call(server, "GET", "/api/v1/chat?company=example")
    assert status == 200 and data["history"] == []


def test_the_turns_come_back_oldest_first(server):
    """The order a conversation is read in, and the order a prompt needs. Reversed, the model would be
    handed the exchange backwards — which reads as coherent and answers the wrong question."""
    _call(server, "POST", "/api/v1/chat", {"message": "un", "company": "example"})
    _call(server, "POST", "/api/v1/chat", {"message": "deux", "company": "example"})
    _status, data = _call(server, "GET", "/api/v1/chat?company=example")
    assert [t["text"] for t in data["history"] if t["role"] == "user"] == ["un", "deux"]
    assert data["history"][0]["role"] == "user", "an exchange starts with the operator"


def test_a_turn_names_which_model_answered(server):
    """Per turn, not per conversation: a chat can span a tier change or a fallback, and "who said
    this" is a question about one reply."""
    _status, data = _call(
        server, "POST", "/api/v1/chat", {"message": "Bonjour", "company": "example"}
    )
    assistant = [t for t in data["history"] if t["role"] == "assistant"]
    assert assistant and assistant[-1]["provider"] == "mock"
    assert assistant[-1]["model"], "the model has to be named, not just the provider"


def test_the_limit_is_bounded_whatever_a_client_asks(server):
    """A client naming a limit is fine; one naming a million is a table scan on a polled path."""
    _status, data = _call(server, "GET", "/api/v1/chat?company=example&limit=100000")
    assert data["history"] == []
    status, _ = _call(server, "GET", "/api/v1/chat?company=example&limit=0")
    assert status == 200, "a zero limit must not 500"


def test_an_unknown_company_is_refused_by_code(server):
    for method, path, body in (
        ("GET", "/api/v1/chat?company=nope", None),
        # A slug-scoped POST carries `company` in the body: `Ctx` reads a GET from the query string
        # and a POST from the JSON body, and every POST in this file had it in the query at first —
        # which 404s for the wrong reason, no slug at all rather than an unknown one.
        ("POST", "/api/v1/chat", {"message": "hi", "company": "nope"}),
        ("POST", "/api/v1/chat/forget", {"company": "nope"}),
    ):
        status, data = _call(server, method, path, body)
        assert status == 404, (path, data)
        assert data["error"]["code"] == "unknown_company"


# --- the write --------------------------------------------------------------------


def test_an_empty_message_is_refused_before_a_model_is_called(server):
    """Refused on the field, not answered. Sending a blank question to a paid model and rendering
    whatever came back would spend the operator's tokens on nothing."""
    status, data = _call(server, "POST", "/api/v1/chat", {"message": "   ", "company": "example"})
    assert status == 400 and data["error"]["detail"]["field"] == "message"
    _status, after = _call(server, "GET", "/api/v1/chat?company=example")
    assert after["history"] == [], "a refused message must leave no turn"


def test_the_reply_and_the_history_come_back_together(server):
    """So a client renders the exchange from one answer rather than posting and then polling — which
    is a second request whose only purpose is to see what it just did."""
    status, data = _call(
        server, "POST", "/api/v1/chat", {"message": "Bonjour", "company": "example"}
    )
    assert status == 200
    assert data["reply"] and data["history"]
    assert data["history"][-1]["text"] == data["reply"]


def test_forgetting_clears_it_and_says_how_many_went(server):
    _call(server, "POST", "/api/v1/chat", {"message": "Bonjour", "company": "example"})
    status, data = _call(server, "POST", "/api/v1/chat/forget", {"company": "example"})
    assert status == 200 and data["forgotten"] == 2
    assert _call(server, "GET", "/api/v1/chat?company=example")[1]["history"] == []


def test_both_spellings_of_the_read_answer_from_the_table(server):
    """The legacy `/api/chat` read `ctx.state.chats`, and that field went with schema 21 — so it was an
    `AttributeError` on the shipped page's first poll. `tests/test_api_version.py` caught it by asking
    whether both spellings reach one function, which is the second live break that ratchet has found."""
    _call(server, "POST", "/api/v1/chat", {"message": "Bonjour", "company": "example"})
    status, legacy = _call(server, "GET", "/api/chat?company=example")
    assert status == 200, legacy
    _status, versioned = _call(server, "GET", "/api/v1/chat?company=example")
    assert [t["text"] for t in legacy["history"]] == [t["text"] for t in versioned["history"]]


# --- the tab list, both ends ------------------------------------------------------


def test_every_tab_has_a_nav_label():
    """`nav.ceo` did not exist: the shipped page hardcodes the string "CEO", which is why the tab had
    no key. `App.svelte` renders `t("nav." + entry.id)`, so a CEO tab would have printed `nav.ceo` on
    screen — the same visible failure as an invented key, arriving from the other direction.

    Both ends: every id in `TABS` has a label, and every `nav.` key belongs to a tab or is declared
    below as one not yet rebuilt.
    """
    import pathlib
    import re

    en = json.loads(pathlib.Path("web/i18n/en.json").read_text(encoding="utf-8"))
    app = pathlib.Path("web/src/App.svelte").read_text(encoding="utf-8")
    ids = re.findall(r'\{ id: "([a-z]+)", component:', app)
    assert len(ids) >= 6, f"the tab scan found {ids}"
    missing = [i for i in ids if f"nav.{i}" not in en]
    assert not missing, f"tabs with no label: {missing}"

    # Every `nav.` key now belongs to a rebuilt tab — `plugins` was the last one declared here as
    # "not yet", and deleting that line is what finishing it looked like. The set is exact in both
    # directions: a tab with no label fails above, and a label with no tab fails here.
    keys = {k.removeprefix("nav.") for k in en if k.startswith("nav.")}
    assert keys == set(ids), (
        f"labels with no tab: {sorted(keys - set(ids))}; tabs with no label: {sorted(set(ids) - keys)}"
    )
    assert len(ids) == 7, f"the shipped page has seven tabs; this console renders {len(ids)}"
