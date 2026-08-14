"""The four document endpoints, and the distinction that runs through all of them.

**A refused file is not a failed request.** Asking to store a `.zip` is a well-formed thing to ask;
the answer is `stored: false` with a `reason` code the client turns into a sentence. So the error
envelope is reserved for requests that were wrong — an unknown company, a body that is not base64 —
and the outcome of a well-formed one travels in the payload. That is what lets a drop of seven files
report six stored and one skipped in one pass, instead of a banner claiming the upload failed.

The number these exist to surface is not how many files a company has. It is how many reach a prompt:
`reaching` against `total`, `used` against `budget`. Twelve documents can be two in context and ten
on disk looking like knowledge, and nothing in the product said so before this.
"""

import base64
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

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
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
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=10)
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


def _put(srv, name, text=b"A price list for the clinic.\n"):
    return _call(
        srv,
        "POST",
        "/api/v1/documents",
        {"name": name, "data": base64.b64encode(text).decode(), "company": "example"},
    )


# --- the inventory --------------------------------------------------------------


def test_the_inventory_says_how_much_of_the_folder_reaches_a_prompt(server):
    status, data = _put(server, "prices.txt")
    assert status == 200 and data["stored"] is True
    assert data["total"] >= 1
    assert data["reaching"] >= 1, "a readable file in an empty folder has to reach the prompt"
    assert data["used"] > 0 and data["budget"] > 0
    row = next(d for d in data["documents"] if d["path"] == "prices.txt")
    assert row["reaches"] is True
    assert row["reason"] == "prompt"
    assert row["written"] is False, "the operator dropped this one in"


def test_the_limits_come_from_the_one_place_that_decides_them(server):
    """The drop zone states them before an operator drags a file, and a second copy in the page
    would be a promise the server breaks."""
    from corparius import documents

    _status, data = _call(server, "GET", "/api/v1/documents?company=example")
    assert data["max_upload"] == documents.MAX_UPLOAD
    assert set(data["accepts"]) == documents.UPLOAD_SUFFIXES


def test_a_file_the_agents_wrote_is_marked_as_theirs(server):
    """Provenance from the path, which is why `write` puts its output in a subfolder instead of
    dropping it in beside the operator's own files."""
    from corparius import documents

    documents.write("example", "monday-brief.md", "What the design agent decided.")
    _status, data = _call(server, "GET", "/api/v1/documents?company=example")
    written = [d for d in data["documents"] if d["written"]]
    assert written, "a document the company wrote must say so"
    assert all(documents.WRITTEN in d["path"].split("/") for d in written)


def test_an_unknown_company_is_refused_by_code(server):
    for method, path, body in (
        ("GET", "/api/v1/documents?company=nope", None),
        ("GET", "/api/v1/documents/text?company=nope&path=x.txt", None),
        ("POST", "/api/v1/documents", {"company": "nope", "name": "a.txt", "data": ""}),
        ("POST", "/api/v1/documents/delete", {"company": "nope", "path": "a.txt"}),
    ):
        status, data = _call(server, method, path, body)
        assert status == 404, (method, path, data)
        assert data["error"]["code"] == "unknown_company"
        assert data["error"]["detail"]["slug"] == "nope"


# --- storing ---------------------------------------------------------------------


def test_a_refused_file_is_a_successful_request_with_a_reason(server):
    """The distinction the whole tab is built on. `ok` qualifies the request; `stored` qualifies the
    file. A 400 here would make a seven-file drop look like a broken console."""
    status, data = _call(
        server,
        "POST",
        "/api/v1/documents",
        {
            "name": "archive.zip",
            "data": base64.b64encode(b"PK\x03\x04").decode(),
            "company": "example",
        },
    )
    assert status == 200, "a well-formed request about an unsupported file is not a failed request"
    assert data["ok"] is True and data["stored"] is False
    assert data["reason"] == "no-extractor"
    assert data["name"] == "archive.zip"
    # And the inventory still rides back, so the card is the folder as it now stands.
    assert "documents" in data and "reaching" in data


def test_every_refusal_reason_has_a_string_to_render_it(server):
    """The other end of the wire. A reason the front end has no string for renders the raw key on
    screen, which is the `docs.` collision's failure mode by a different route — so the codes the
    server can emit are held against the table that has to display them."""
    import ast
    import pathlib

    en = json.loads(pathlib.Path("web/i18n/en.json").read_text(encoding="utf-8"))
    source = pathlib.Path("corparius/documents.py").read_text(encoding="utf-8")
    # Every `Refused("code", ...)` raised in the module, read from the source rather than by
    # provoking each one: two of the seven need a read-only folder or a name the OS rejects.
    raised = {
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Refused"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert len(raised) >= 5, f"the refusal scan found only {sorted(raised)}"
    missing = sorted(code for code in raised if f"docs.refused.{code}" not in en)
    assert not missing, f"these refusal codes have no string: {missing}"


def test_the_state_codes_the_inventory_can_report_all_have_strings():
    """`reason` on a row, as opposed to on a refusal. Same argument: an unrendered code is a raw key
    where a sentence belongs, and only a screenshot would find it."""
    import pathlib

    en = json.loads(pathlib.Path("web/i18n/en.json").read_text(encoding="utf-8"))
    # The vocabulary is written down in `Document.reason`'s own comment, plus the one `inventory`
    # assigns. Read from the docstring would be cute and fragile; this is the list, asserted.
    #
    # `budget` was here and is gone with its string. It meant "readable, on file, and past the prompt
    # budget — no agent reads it", which was the most useful thing this card said while retrieval took
    # the newest 6 000 characters whole. Every readable file's headings now ride on every prompt, so
    # nothing can be in that state and `inventory` never sets the code. Both ends struck off together:
    # a code with no string renders a raw key, and a string for no code describes a product that does
    # not exist.
    #
    # `cut` followed it one commit later, for a reason that rhymes. `inventory` reads with
    # `max_chars=0` now — the map was being built from the first 4 000 characters of each file, so a
    # heading past the cut had no way to exist and the executor's second round could not ask for it.
    # The code is still produced by a default `read`, which is why `Document.reason` still lists it
    # and `test_a_long_document_is_cut_and_says_that_it_was` still holds; what it can no longer be is
    # a **row on this card**, and `docs.why.cut` said "reaches the agents: first {n} of {total}
    # characters", which is a claim about the agents rather than about a preview.
    for code in (
        "image",
        "no-text-layer",
        "no-extractor",
        "empty",
        "os-error",
        "prompt",
    ):
        assert f"docs.why.{code}" in en, f"a row can report {code!r} and nothing can render it"
    for retired in ("docs.why.budget", "docs.why.cut"):
        assert retired not in en, f"{retired}: a retired state must not keep its string"


def test_a_body_that_is_not_base64_is_the_request_being_wrong(server):
    """The other side of the line: this one *is* a malformed request, so it gets the envelope. And it
    is refused before anything is written — a lenient decode would put whatever survived into the
    operator's folder."""
    status, data = _call(
        server,
        "POST",
        "/api/v1/documents",
        {"name": "a.txt", "data": "not base64 at all!!", "company": "example"},
    )
    assert status == 400
    assert data["error"]["code"] == "invalid" and data["error"]["detail"]["field"] == "data"


def test_storing_the_same_name_twice_says_it_replaced(server):
    """`replaced` rather than a silent overwrite: the operator dropped this quarter's price list on
    last quarter's and should be told, not left to wonder whether both are there."""
    assert _put(server, "prices.txt", b"one\n")[1]["replaced"] is False
    status, data = _put(server, "prices.txt", b"two\n")
    assert status == 200 and data["stored"] is True and data["replaced"] is True
    assert sum(1 for d in data["documents"] if d["path"] == "prices.txt") == 1


# --- reading ---------------------------------------------------------------------


def test_the_text_endpoint_applies_no_prompt_budget(server):
    """The reading surface and the prompt budget are different questions. `MAX_CHARS` caps what an
    agent gets so a thirty-page deck cannot swallow a turn; a person rereading their own brief wants
    the file, and used to have to go and open it."""
    from corparius import documents

    long_text = ("Every line of the brief is worth keeping. " * 400).encode()
    assert len(long_text) > documents.MAX_CHARS
    _put(server, "brief.txt", long_text)

    _status, listed = _call(server, "GET", "/api/v1/documents?company=example")
    row = next(d for d in listed["documents"] if d["path"] == "brief.txt")
    assert row["chars"] == row["total"] > documents.MAX_CHARS, "the row shows what an agent gets"
    assert len(row["text"]) == documents.MAX_CHARS, "and the inline preview stays a preview"

    status, whole = _call(server, "GET", "/api/v1/documents/text?company=example&path=brief.txt")
    assert status == 200
    assert len(whole["text"]) > documents.MAX_CHARS
    assert whole["path"] == "brief.txt"


def test_reading_something_that_is_not_there_is_not_found(server):
    status, data = _call(server, "GET", "/api/v1/documents/text?company=example&path=ghost.txt")
    assert status == 404 and data["error"]["code"] == "not_found"
    assert data["error"]["detail"]["path"] == "ghost.txt"


def test_reading_with_no_path_names_the_field(server):
    status, data = _call(server, "GET", "/api/v1/documents/text?company=example")
    assert status == 400 and data["error"]["detail"]["field"] == "path"


def test_a_path_outside_the_folder_is_refused(server):
    """The traversal guard, at the endpoint rather than only in the module. `..` in a path is the
    oldest request in the book and it must not reach the filesystem."""
    _status, data = _call(
        server, "GET", "/api/v1/documents/text?company=example&path=../../company.yaml"
    )
    assert data["ok"] is False, "a path out of the folder must not be readable"


# --- removing --------------------------------------------------------------------


def test_removing_moves_the_file_aside_and_says_where(server):
    """Moved rather than erased, like a deleted company: a misread badge stays recoverable, and the
    answer names the file it became."""
    _put(server, "prices.txt")
    status, data = _call(
        server, "POST", "/api/v1/documents/delete", {"path": "prices.txt", "company": "example"}
    )
    assert status == 200 and data["removed"] is True
    assert data["trashed"], "an operator who removed the wrong file needs to know where it went"
    assert not [d for d in data["documents"] if d["path"] == "prices.txt"]


def test_removing_something_absent_is_reported_and_not_a_failed_request(server):
    """Same rule as storing: a well-formed question about a file somebody else already removed is a
    successful request whose answer is no."""
    status, data = _call(
        server, "POST", "/api/v1/documents/delete", {"path": "ghost.txt", "company": "example"}
    )
    assert status == 200 and data["ok"] is True
    assert data["removed"] is False and data["reason"] == "no-such-document"


def test_removing_a_path_outside_the_folder_is_refused(server):
    status, data = _call(
        server,
        "POST",
        "/api/v1/documents/delete",
        {"path": "../company.yaml", "company": "example"},
    )
    assert data.get("removed") is False and data["reason"] == "outside"


# --- and the terminal, which could not reach any of this ------------------------


def test_the_terminal_can_finally_read_the_folder(tmp_path, monkeypatch, capsys):
    """The capability gap stage 6 exists to close, still open here until now. Measured before writing
    `cmd_docs`: **no CLI module referenced `documents` at all**, so an operator on a headless box
    could not see that ten of their twelve files sat past the prompt budget, and could not read a
    brief their own design agent had written.

    The same `documents.inventory` the console reads, so the two cannot disagree about which files
    reach a prompt.
    """
    import types

    from corparius import documents
    from corparius.cli import operate
    from corparius.config import cfg

    home = tmp_path / "home"
    (home / "companies" / "t").mkdir(parents=True)
    company = home / "companies" / "t" / "company.yaml"
    company.write_text(
        "slug: t\nname: T\noffer: {product: p}\nicp: {segment: s, pains: [x]}\nagents: {ceo: true}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORP_HOME", str(home))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()

    documents.save("t", "prices.txt", b"49 EUR a month.\n")
    # No dot in the name: `write` slugifies it and appends `.md`, so "brief.md" lands as
    # "brief-md.md". Asserted against what it actually does rather than against what reads nicely.
    documents.write("t", "monday brief", "What the design agent decided on Monday.")

    args = types.SimpleNamespace(company=str(company), read="", remove="")
    operate.cmd_docs(args)
    said = capsys.readouterr().out
    assert "prices.txt" in said and "monday-brief.md" in said
    assert "reach the agents" in said, "the count that matters has to be in the output"
    assert "dropped" in said and "written" in said, "provenance, or the listing is just filenames"

    operate.cmd_docs(types.SimpleNamespace(company=str(company), read="prices.txt", remove=""))
    assert "49 EUR a month." in capsys.readouterr().out

    operate.cmd_docs(types.SimpleNamespace(company=str(company), read="", remove="prices.txt"))
    assert "moved out of the folder" in capsys.readouterr().out

    operate.cmd_docs(types.SimpleNamespace(company=str(company), read="ghost.txt", remove=""))
    assert "no document at ghost.txt" in capsys.readouterr().out

    operate.cmd_docs(types.SimpleNamespace(company=str(company), read="", remove="ghost.txt"))
    assert "was not removed" in capsys.readouterr().out


@pytest.fixture()
def bare_company(tmp_path, monkeypatch):
    """A company with a real folder and nothing in it."""
    from corparius.config import cfg

    home = tmp_path / "home"
    (home / "companies" / "t").mkdir(parents=True)
    company = home / "companies" / "t" / "company.yaml"
    company.write_text(
        "slug: t\nname: T\noffer: {product: p}\nicp: {segment: s, pains: [x]}\nagents: {ceo: true}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORP_HOME", str(home))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    return company


def test_the_terminal_says_where_to_put_files_when_there_are_none(bare_company, capsys):
    """An empty folder is the first thing a new operator sees, so it has to say what to do rather
    than print a header and stop."""
    import types

    from corparius.cli import operate

    operate.cmd_docs(types.SimpleNamespace(company=str(bare_company), read="", remove=""))
    said = capsys.readouterr().out
    assert "nothing on file" in said
    assert "copy a PDF" in said, "the empty state has to name the action"


def test_the_terminal_says_how_many_it_did_not_list(bare_company, capsys, monkeypatch):
    """`INVENTORY_MAX` bounds the listing, and a bounded list that does not say so reads as the whole
    folder — the same silent-truncation failure as a `done` column headed by its row count.

    The cap is patched rather than fed sixty-one files: the branch is about *the cap*, and extracting
    sixty files to prove an `if` would be measuring the fixture.
    """
    import types

    from corparius import documents
    from corparius.cli import operate

    monkeypatch.setattr(documents, "INVENTORY_MAX", 2)
    for i in range(4):
        documents.save("t", f"note-{i}.txt", f"Line {i}.\n".encode())
    operate.cmd_docs(types.SimpleNamespace(company=str(bare_company), read="", remove=""))
    said = capsys.readouterr().out
    assert "2 more on file, not listed" in said, said


def test_the_console_and_the_terminal_read_one_inventory():
    """The `test_two_callers_agree` property, asserted here because that file's scanner cannot see it.

    Its `_app_calls` matches `app_<module>.<fn>(` — the rank-5 services — and `documents.py` is rank 4
    and already host-free, so it *is* the service and never grew an `app_` wrapper. Correct design,
    invisible ratchet. Stated directly instead: both surfaces call the same function, so they cannot
    come to disagree about which files reach a prompt.
    """
    import pathlib
    import re

    for path in ("corparius/api/handlers.py", "corparius/cli/operate.py"):
        source = pathlib.Path(path).read_text(encoding="utf-8")
        assert re.search(r"\bdocuments\.inventory\(", source), (
            f"{path} no longer reads the inventory"
        )


def test_the_terminal_has_no_add_and_that_is_the_point(tmp_path):
    """Stated as an assertion so nobody adds one by reflex.

    Copying a file into the folder `--list` prints *is* the upload: `load()` re-reads the directory on
    every call, and a file nothing can extract simply reports `no-extractor` in the listing. A command
    that shelled out to `cp` for the operator would be ceremony over a path they already have.
    """
    import argparse

    from corparius.cli import operate

    parser = argparse.ArgumentParser()
    operate.register(parser.add_subparsers())
    docs = parser._subparsers._group_actions[0].choices["docs"]  # type: ignore[union-attr]
    flags = {opt for action in docs._actions for opt in action.option_strings}
    assert "--read" in flags and "--remove" in flags
    assert "--add" not in flags and "--upload" not in flags
