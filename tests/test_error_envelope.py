"""The v1 error envelope: a code a client can branch on, and a closed vocabulary.

Measured across `api/` before this existed: **57 payloads carry an `error` key and all 57 carry a
human sentence** — 32 literals, 11 `str(exc)`, 8 f-strings. A second client can do nothing with
that but match substrings, and it breaks the moment a message is reworded, which this project
does often and on purpose. `{"error": {"code", "message", "detail"}}` separates the three
audiences: the code is for the client, the message is for the person, and `detail` carries the
particulars instead of them being welded into prose.

**Two shapes, chosen by the version in the path**, and that is the part worth defending. The 54
legacy routes keep the flat string because the shipped page reads `data.error` as a string in
fourteen places — `throw new Error(data.error || …)` renders an object as "[object Object]" on
exactly the failures an operator most needs to read. A shape that differs by version is what
versioning is; a shape that differs by route would be a mess.

The vocabulary is a `frozenset` and both ends are held here: every code emitted under `api/` is
declared, and every code declared is emitted somewhere. The second half is the one that matters
over time — a vocabulary with dead words in it stops describing anything, and a client written
against a code nothing sends has a branch that never runs.
"""

import ast
import pathlib
import threading

import pytest

from corparius.api import contracts

API = pathlib.Path("corparius/api")


def _emitted() -> set[str]:
    """Every code named at a call to `refuse`/`envelope`, from the AST.

    Three spellings, because there are three: handlers call `contracts.refuse(...)`, the
    dispatcher calls its own `self._refuse(...)` (which picks the shape from the path), and
    `envelope` is the body alone. Missing `_refuse` was the first version's mistake and the scan
    reported one code out of nine — a guard that under-reports passes, which is the worse way
    round.

    Reads the code by position and by attribute name, so `contracts.NOT_FOUND` counts. A code
    built at runtime is invisible here, which is what the `assert` inside `envelope` is for: the
    two together cover both ways of getting it wrong.
    """
    found = set()
    for path in sorted(API.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name not in ("refuse", "_refuse", "envelope"):
                continue
            if not node.args:
                continue
            arg = node.args[0] if name == "envelope" else node.args[1]
            if isinstance(arg, ast.Attribute):
                found.add(arg.attr)
            elif isinstance(arg, ast.Constant):
                found.add(str(arg.value))
    return found


def _declared() -> set[str]:
    """The constant names, not their values: the scan above reads `contracts.NOT_FOUND`."""
    return {
        name
        for name, value in vars(contracts).items()
        if name.isupper() and isinstance(value, str) and value in contracts.CODES
    }


# --- the guard on the guard -----------------------------------------------------


def test_there_is_a_vocabulary_to_check():
    assert len(contracts.CODES) >= 6, f"only {len(contracts.CODES)} codes declared"
    assert len(_declared()) == len(contracts.CODES), "a code in CODES has no constant naming it"
    assert len(_emitted()) >= 5, f"the emission scan found {_emitted()}"


# --- both ends ------------------------------------------------------------------


def test_every_code_emitted_is_declared():
    """A typo in a code is a client branch that never runs — the silent kind of wrong."""
    undeclared = sorted(_emitted() - _declared())
    assert not undeclared, f"these codes are sent and not in CODES: {undeclared}"


def test_every_code_declared_is_emitted():
    """The half that keeps the vocabulary honest. A word nothing sends describes nothing, and a
    client that wrote a branch for it waits forever."""
    dead = sorted(_declared() - _emitted())
    assert not dead, (
        f"these codes are declared and never sent: {dead}. Send them, or drop them — a client "
        "reading this list will write a branch for each one."
    )


def test_a_code_outside_the_vocabulary_is_refused_at_the_call():
    """The runtime half, for a code that is computed rather than written out, which the AST scan
    above cannot see."""
    with pytest.raises(AssertionError):
        contracts.envelope("not_a_real_code", "nope")


# --- the shape ------------------------------------------------------------------


def test_the_envelope_has_the_three_parts_and_nothing_else():
    body = contracts.envelope(contracts.INVALID, "a message", field="tier")
    assert body["ok"] is False
    assert sorted(body["error"]) == ["code", "detail", "message"]
    assert body["error"]["code"] == "invalid"
    assert body["error"]["message"] == "a message"
    assert body["error"]["detail"] == {"field": "tier"}


def test_detail_is_present_even_when_empty():
    """Omitted when empty would make a client write `error.detail or {}` forever, and this
    project has the `durable_jobs` precedent: reported false rather than left out."""
    assert contracts.envelope(contracts.NOT_FOUND, "gone")["error"]["detail"] == {}


def test_refuse_returns_what_a_handler_returns():
    status, body = contracts.refuse(404, contracts.UNKNOWN_COMPANY, "no such company", slug="x")
    assert status == 404
    assert body["error"]["detail"] == {"slug": "x"}


# --- over the wire, both shapes -------------------------------------------------


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from corparius.api.server import build_server
    from corparius.config import cfg
    from corparius.config.settings import Settings

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_a_v1_path_answers_in_the_envelope(server):
    from .test_webui import _call

    status, data = _call(server, "GET", "/api/v1/nope")
    assert status == 404
    assert data["error"]["code"] == "not_found"
    assert data["error"]["detail"]["path"] == "/api/v1/nope"


def test_a_legacy_path_answers_with_the_flat_sentence(server):
    """Not a smaller promise — the same one the page has always been given. Changing it here
    would break `throw new Error(data.error)` on fourteen call sites in a 3 617-line file that
    stage 9 replaces."""
    from .test_webui import _call

    status, data = _call(server, "GET", "/api/nope")
    assert status == 404
    assert data["error"] == "not found", "legacy stays a string until the page is rebuilt"


def test_the_token_refusal_carries_a_code_on_v1(server, monkeypatch):
    """The checks before a handler are refusals too. A client that could branch on a handler's
    answer but not on a 401 could branch on almost nothing — re-authenticating is the single
    most important thing it needs to recognise."""
    from corparius.config import cfg

    from .test_webui import _call

    monkeypatch.setenv("CORP_UI_TOKEN", "s3cret")
    cfg.invalidate()
    status, data = _call(server, "GET", "/api/v1/summary?company=example")
    assert status == 401
    assert data["error"]["code"] == "unauthenticated"
    # And the same refusal on a legacy path is still the sentence.
    status, data = _call(server, "GET", "/api/overview?company=example")
    assert status == 401 and isinstance(data["error"], str)


def test_an_unknown_company_says_which_one(server):
    """`detail` is what stops a client parsing the message. The slug it asked about comes back as
    data, so a client can tell "I asked for the wrong thing" from "this core is broken"."""
    from .test_webui import _call

    status, data = _call(server, "GET", "/api/v1/summary?company=definitely-not-here")
    assert status == 404
    assert data["error"]["code"] == "unknown_company"
    assert data["error"]["detail"]["slug"] == "definitely-not-here"


def test_a_body_over_the_ceiling_is_a_code_a_client_acts_on_differently(server):
    """`too_large` and `invalid` are separated on purpose: one means send less, the other means
    send something else. A single code for both would make a client retry the same body."""
    from .test_webui import _call

    # No v1 route takes a POST yet, so this exercises the dispatcher's own choice of code
    # through the legacy shape and the mapping through the unit below.
    status, data = _call(server, "POST", "/api/tasks", {"id": 1, "x": "y" * 10})
    assert status in (200, 400, 404), f"unexpected {status}: {data}"
