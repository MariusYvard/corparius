"""The documents folder worked, and nothing showed it.

An agent wrote a design brief, the file landed on disk, and it rode into the next
turn's prompt — while the operator paying for it had no way to read a word of it.
That is the same shape as the four deliverables that used to be cut to a log
line, one floor up.

And a worse one underneath: `context` stops at the prompt budget, so a company
holding twelve documents can be feeding two of them to its agents. The other ten
sit in the folder looking exactly like knowledge. These tests pin the console to
saying which two.
"""

import base64
import threading

import pytest

from corparius import cfg, documents, webui
from corparius.config import Settings

from .test_webui import _call


@pytest.fixture()
def server(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "companies" / "acme").mkdir(parents=True)
    (root / "companies" / "acme" / "company.yaml").write_text(
        "slug: acme\nname: Acme\n", encoding="utf-8"
    )
    # One lever, because `companies/` now has one source. This test needed two of
    # them the day it was written — a patched module attribute for the guard and
    # CORP_HOME for the folder — and setting only one left the endpoint listing a
    # directory inside the real checkout, which is how a test starts writing into
    # the repository it is testing.
    monkeypatch.setenv("CORP_HOME", str(root))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    srv = webui.build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()  # release the listening socket, not just the loop


@pytest.fixture()
def drop(server, tmp_path):
    folder = tmp_path / "root" / "companies" / "acme" / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _get(server, slug="acme"):
    return _call(server, "GET", f"/api/documents?company={slug}")


def _by_path(payload) -> dict:
    return {d["path"]: d for d in payload["documents"]}


def test_what_an_agent_wrote_is_readable_by_the_person_paying_for_it(drop, server):
    """The brief was on disk, was in the next prompt, and was invisible. Keeping
    it was half the fix; this is the half that lets someone read it."""
    brief = "A severe visual identity, dark tones, deep blue accents. " * 6
    documents.write("acme", "Design brief", brief)

    status, payload = _get(server)
    assert status == 200 and payload["ok"]
    entry = _by_path(payload)["written/design-brief.md"]
    assert "deep blue accents" in entry["text"]
    assert len(entry["text"]) > 200, "a log line's worth is what this replaced"
    assert entry["written"] is True and entry["reaches"] is True


def test_the_operators_files_and_the_companys_files_are_told_apart(drop, server):
    """Provenance comes from the path, which is why `write` uses a subfolder
    rather than dropping its output in beside what the operator brought."""
    (drop / "pricing.md").write_text("Founder price 9 EUR", encoding="utf-8")
    documents.write("acme", "Weekly review", "What the company wrote about itself.")

    docs = _by_path(_get(server)[1])
    assert docs["pricing.md"]["written"] is False
    assert docs["written/weekly-review.md"]["written"] is True


def test_a_document_past_the_budget_is_marked_rather_than_quietly_listed(drop, server):
    """The failure this surface exists to end. Four documents on file, two in the
    prompt, and nothing anywhere saying which — so ten files an agent has never
    read look precisely like ten files it has."""
    for i in range(4):
        (drop / f"d{i}.md").write_text("x" * 2000, encoding="utf-8")

    payload = _get(server)[1]
    assert payload["total"] == 4
    assert payload["reaching"] == 2, "the budget fits two 2 000-character files"
    assert payload["used"] <= payload["budget"]
    reasons = sorted(d["reason"] for d in payload["documents"])
    assert reasons == ["budget", "budget", "prompt", "prompt"]


def test_the_console_and_the_prompt_can_never_disagree(drop, server):
    """`context` and `inventory` share one selection loop. Written twice they
    would drift, and the console would then vouch for a document no agent has
    ever seen — a lie more expensive than the silence it replaced."""
    for i in range(4):
        (drop / f"note{i}.md").write_text("y" * 2000, encoding="utf-8")

    payload = _get(server)[1]
    block = documents.context("acme")
    for entry in payload["documents"]:
        # The full relative path, which is what the prompt now names a document
        # by. The card and the prompt read a document's identity out of the same
        # field, so there is nothing left for them to disagree about.
        assert (f"--- {entry['path']}" in block) is entry["reaches"], f"{entry['path']}"


def test_two_files_of_the_same_name_are_two_things_in_the_prompt(drop, server):
    """`design-brief.md` dropped in and `design-brief.md` written by the design
    agent were two identical headings in one prompt, with nothing for a model to
    tell them apart by. The relative path separates them and says which of the
    two the company wrote, at no cost."""
    (drop / "design-brief.md").write_text("What the operator wants.", encoding="utf-8")
    documents.write("acme", "Design brief", "What the design agent decided.")

    block = documents.context("acme")
    assert "--- design-brief.md" in block
    assert "--- written/design-brief.md" in block
    paths_seen = {d["path"] for d in _get(server)[1]["documents"]}
    assert paths_seen == {"design-brief.md", "written/design-brief.md"}


def test_each_way_of_being_unreadable_says_which_way_it_was(drop, server):
    """A code, not a sentence: the console is bilingual and an English note in a
    French card is the gap the parity test exists to catch."""
    (drop / "scan.pdf").write_bytes(b"%PDF-1.4\n" + bytes(range(256)) * 4)
    (drop / "archive.zip").write_bytes(b"PK\x03\x04")
    (drop / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    docs = _by_path(_get(server)[1])
    assert docs["scan.pdf"]["reason"] == "no-text-layer"
    assert docs["archive.zip"]["reason"] == "no-extractor"
    assert docs["shot.png"]["reason"] == "image"
    assert not any(docs[name]["reaches"] for name in docs), "none of these reach a prompt"


def test_a_cut_document_carries_its_real_length_as_a_number(drop, server):
    """It lived only inside an English note as prose, so anything reading the
    payload saw 4 000 characters and could not learn the document was three
    times that."""
    (drop / "big.md").write_text("z" * 12000, encoding="utf-8")

    entry = _by_path(_get(server)[1])["big.md"]
    assert entry["chars"] == documents.MAX_CHARS
    assert entry["total"] == 12000
    assert entry["reason"] == "cut" and entry["reaches"] is True


def test_a_capped_list_still_reports_the_real_count(drop, server):
    """Sixty rows presented as everything is the truncation this project keeps
    finding. The header counts the folder, not the payload."""
    for i in range(documents.INVENTORY_MAX + 5):
        (drop / f"f{i:03d}.md").write_text(f"note {i}", encoding="utf-8")

    payload = _get(server)[1]
    assert len(payload["documents"]) == documents.INVENTORY_MAX
    assert payload["total"] == documents.INVENTORY_MAX + 5


def test_a_company_with_an_empty_folder_gets_the_folder_and_no_error(server):
    status, payload = _get(server)
    assert status == 200 and payload["documents"] == []
    assert payload["total"] == 0 and payload["reaching"] == 0
    # The card tells the operator where to put a file. An empty state that does
    # not say what to do next is a dead end.
    assert payload["folder"].endswith("documents")


@pytest.mark.parametrize("slug", ["nobody", "..", "../..", "example"])
def test_an_unknown_or_traversing_slug_is_refused(server, slug):
    """`slug in _companies()` is the guard, as everywhere else: `documents.folder`
    builds a filesystem path out of this name. `example` is real in a checkout
    and absent from this fixture's root, which is exactly the case a guard on
    "does the folder exist" would wave through."""
    status, payload = _call(server, "GET", f"/api/documents?company={slug}")
    assert status == 404 and payload["ok"] is False


def test_the_endpoint_is_not_public(server):
    """It reads the operator's own files. It has to sit behind the token like
    every other read."""
    route = webui._match("GET", "/api/documents")
    assert route is not None and route.public is False


# --------------------------------------------------------------------------
# Dropping a file on the console
# --------------------------------------------------------------------------


def _drop(server, name, data: bytes, slug="acme"):
    return _call(
        server,
        "POST",
        "/api/documents",
        {"company": slug, "name": name, "data": base64.b64encode(data).decode()},
    )


def test_a_dropped_file_becomes_context_without_touching_a_shell(drop, server):
    status, payload = _drop(server, "pricing.md", b"Founder price 9 EUR")
    assert status == 200 and payload["stored"] is True and payload["replaced"] is False
    # It is context on the next turn, which is the entire point of storing it.
    assert "Founder price 9 EUR" in documents.context("acme")
    # And the answer carries the folder as it now stands, so the card is never a
    # drop behind what the operator just did.
    assert [d["path"] for d in payload["documents"]] == ["pricing.md"]


def test_a_dropped_file_lands_where_the_operator_dropped_it(drop, server):
    """Not in `written/`. Provenance is read from the path everywhere in this
    module, so filing an operator's file under the agents' folder would make the
    console's own badge lie about who produced it."""
    _drop(server, "deck.md", b"Ninety seconds to value")
    entry = _by_path(_get(server)[1])["deck.md"]
    assert entry["written"] is False


def test_replacing_a_file_says_that_it_replaced_one(drop, server):
    """Overwriting is right — a re-dropped price list is the common case — and
    silence about it is not."""
    assert _drop(server, "pricing.md", b"nine euro")[1]["replaced"] is False
    second = _drop(server, "pricing.md", b"eleven euro")[1]
    assert second["stored"] is True and second["replaced"] is True
    assert second["total"] == 1, "replaced, not accumulated"
    assert "eleven euro" in documents.context("acme")


@pytest.mark.parametrize(
    "name,data,reason",
    [
        ("notes.zip", b"PK\x03\x04", "no-extractor"),
        ("Makefile", b"all:", "no-extractor"),
        (".env", b"CORP_UI_TOKEN=secret", "bad-name"),
        ("", b"content", "bad-name"),
        ("empty.md", b"", "empty-file"),
    ],
)
def test_a_refused_file_is_a_good_request_with_a_reason(drop, server, name, data, reason):
    """`ok` qualifies the request, not the verdict. Asking to store a .zip is a
    perfectly well-formed thing to ask; the answer is no, and which file, and why.
    A 400 here would tell the page its own request was broken."""
    status, payload = _drop(server, name, data)
    assert status == 200 and payload["ok"] is True
    assert payload["stored"] is False and payload["reason"] == reason
    assert payload["total"] == 0, "nothing was written"


def test_a_dotfile_is_refused_rather_than_stored_and_never_read(drop, server):
    """`load` skips names starting with a dot, so accepting one would write a
    file that is on disk, invisible in the console, and never context. That is
    the worst of the three available answers."""
    _drop(server, ".secrets.md", b"anything")
    assert list(drop.rglob("*")) == [], "nothing reached the folder"


@pytest.mark.parametrize(
    "name",
    ["../../.env", "..\\..\\.env", "/etc/passwd", "sub/dir/notes.md", "C:\\Windows\\notes.md"],
)
def test_a_name_cannot_escape_the_documents_folder(drop, server, name):
    """A browser is not the only thing that can POST here, and "../../.env" is an
    ordinary file name right up until it is not. Backslashes are folded first:
    they are legal in a POSIX name, so Path().name alone would keep one."""
    _drop(server, name, b"escaped")
    written = [p for p in drop.rglob("*") if p.is_file()]
    for path in written:
        assert path.parent == drop, f"{path} left the folder"
    assert not (drop.parent.parent / ".env").exists()
    assert b"escaped" not in (drop / "..").resolve().joinpath("company.yaml").read_bytes()


def test_a_file_over_the_limit_is_refused_with_the_limit_named(drop, server):
    """ "Too large" without a number is a dead end. The page also checks before
    sending, so this is the server half of the same promise."""
    status, payload = _drop(server, "huge.md", b"x" * (documents.MAX_UPLOAD + 1))
    assert status == 200 and payload["stored"] is False
    assert payload["reason"] == "too-large" and payload["detail"]


def test_a_body_over_the_route_ceiling_is_refused_without_being_read(server):
    """The ceiling belongs to the route: this one carries a file and the others
    carry a handful of fields, so raising it for everybody would widen every
    other endpoint at the same time."""
    route = webui._match("POST", "/api/documents")
    assert route.max_body > webui.MAX_BODY, "a 6 MB file cannot fit the default"
    assert route.max_body >= documents.MAX_UPLOAD, "and base64 costs a third on top"
    # Every other POST keeps the tight default.
    assert webui._match("POST", "/api/drafts").max_body == webui.MAX_BODY


def test_a_body_that_is_not_base64_says_so_rather_than_writing_it(drop, server):
    status, payload = _call(
        server, "POST", "/api/documents", {"company": "acme", "name": "x.md", "data": "not!base64"}
    )
    assert status == 400 and payload["ok"] is False
    assert list(drop.rglob("*")) == []


def test_dropping_into_an_unknown_company_is_refused(server):
    status, payload = _drop(server, "notes.md", b"content", slug="nobody")
    assert status == 404 and payload["ok"] is False


# --------------------------------------------------------------------------
# Taking one back out
# --------------------------------------------------------------------------


def _remove(server, path, slug="acme"):
    return _call(server, "POST", "/api/documents/delete", {"company": slug, "path": path})


def test_a_document_can_be_taken_back_out(drop, server):
    """A drop zone with no way back is a folder that only grows, and an operator
    who dropped the wrong quarter's price list had to go find the directory."""
    (drop / "pricing.md").write_text("nine euro", encoding="utf-8")
    assert "nine euro" in documents.context("acme")

    status, payload = _remove(server, "pricing.md")
    assert status == 200 and payload["removed"] is True
    assert payload["total"] == 0
    assert documents.context("acme") == "", "and it stops reaching the agents"


def test_removing_moves_aside_rather_than_destroys(drop, server):
    """The operator's files are not ours to erase, which is the same answer a
    deleted company gets. A misread badge has to be recoverable."""
    (drop / "pricing.md").write_text("nine euro", encoding="utf-8")
    payload = _remove(server, "pricing.md")[1]

    trashed = list((drop / documents.TRASH).glob("pricing-*.md"))
    assert trashed and trashed[0].read_text(encoding="utf-8") == "nine euro"
    # And the answer says where it went, rather than only that it is gone.
    assert payload["trashed"] == trashed[0].name


def test_what_was_moved_aside_does_not_come_back_as_context(drop, server):
    """The walk used to test `p.name` alone, so a hidden *folder* was walked into.
    A removed document would have gone straight back into the prompt it had just
    been taken out of — and a stray `.git` or `.obsidian` in the folder was being
    read all along."""
    (drop / "pricing.md").write_text("nine euro", encoding="utf-8")
    _remove(server, "pricing.md")

    assert documents.load("acme") == []
    assert "nine euro" not in documents.context("acme")
    assert _get(server)[1]["total"] == 0


def test_a_document_an_agent_wrote_can_be_removed_too(drop, server):
    """A brief the design agent got wrong is exactly the row worth removing, and
    provenance is a label on it, not a permission."""
    documents.write("acme", "Design brief", "A brief the operator disagrees with.")
    assert _remove(server, "written/design-brief.md")[1]["removed"] is True
    assert _get(server)[1]["total"] == 0


@pytest.mark.parametrize(
    "path", ["../company.yaml", "..\\company.yaml", "../../.env", "/etc/passwd", "", "."]
)
def test_a_path_cannot_reach_outside_the_folder(drop, server, path):
    """It arrives in a request body. Coming from our own page a moment earlier is
    not a property the server can check, so it resolves and compares instead."""
    (drop.parent / "company.yaml").write_text("slug: acme\nname: Acme\n", encoding="utf-8")
    status, payload = _remove(server, path)
    assert status == 200 and payload["ok"] is True
    assert payload["removed"] is False
    assert (drop.parent / "company.yaml").is_file(), "the config survived"


def test_removing_something_absent_says_so_rather_than_failing(drop, server):
    status, payload = _remove(server, "never-existed.md")
    assert status == 200 and payload["ok"] is True
    assert payload["removed"] is False and payload["reason"] == "no-such-document"


def test_removing_from_an_unknown_company_is_refused(server):
    status, payload = _remove(server, "x.md", slug="nobody")
    assert status == 404 and payload["ok"] is False


def test_removal_keeps_the_tight_body_ceiling(server):
    """It carries a path, not a file. Only the endpoint that takes a file gets the
    wide ceiling, and that stays visible in the table."""
    assert webui._match("POST", "/api/documents/delete").max_body == webui.MAX_BODY
    assert webui._match("POST", "/api/documents").max_body > webui.MAX_BODY


def test_the_page_is_told_the_limits_rather_than_repeating_them(drop, server):
    """A second copy of the accepted list in the HTML would be a promise the
    server gets to break."""
    payload = _get(server)[1]
    assert payload["max_upload"] == documents.MAX_UPLOAD
    assert set(payload["accepts"]) == documents.UPLOAD_SUFFIXES
    assert ".pdf" in payload["accepts"] and ".zip" not in payload["accepts"]
