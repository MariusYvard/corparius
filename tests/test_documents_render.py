"""The card is rendered by the real function, not by a copy of it.

`node --check` proves the console parses. It says nothing about what a renderer
puts on the screen, and this one has a job that a brace check cannot see: a
document past the prompt budget has to look different from one that reaches an
agent, in both languages. So the function is lifted out of the page as shipped
and run.

Skipped where node is absent, like the other two checks that need it.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

PAGE = Path("corparius/webui.html")


def _i18n() -> str:
    html = PAGE.read_text(encoding="utf-8")
    return html[html.index("const I18N = {") : html.index("const urlq =")]


def _fn(name: str) -> str:
    """One top-level function, verbatim from the page as shipped.

    Lifted rather than duplicated: a fixture copy would pass forever while the
    page it claims to test drifted away from it. These are top level, so the
    closing brace is the only `}` that starts a line — cheaper and steadier than
    counting braces through template literals full of `${...}` and "{n}".
    """
    html = PAGE.read_text(encoding="utf-8")
    match = re.search(rf"^(?:async )?function {name}\([^)]*\) \{{.*?^\}}", html, re.S | re.M)
    assert match, f"{name} is gone from the page; this test watches nothing"
    return match.group(0)


def _const(name: str) -> str:
    """A top-level constant, lifted for the same reason the functions are: a copy
    of `MB` in this file would let the page's own value drift away from it."""
    html = PAGE.read_text(encoding="utf-8")
    match = re.search(rf"^const {name} = .*?;$", html, re.M)
    assert match, f"const {name} is gone from the page"
    return match.group(0)


def _exec(body: str, lang: str, *functions: str) -> str:
    """Run the shipped functions against a stub DOM and return what they printed."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    lifted = _const("MB") + "\n" + "\n".join(_fn(name) for name in functions)
    harness = f"""
{_i18n()}
let lang = {json.dumps(lang)};
const t = k => I18N[lang][k] ?? I18N.en[k] ?? k;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]));
const state = {{ company: "acme" }};
// One node per selector, so a function that writes to two elements is seen to.
const els = {{}};
const $ = q => (els[q] ??= {{
  innerHTML: "", textContent: "", attrs: {{}},
  setAttribute(k, v) {{ this.attrs[k] = v; }},
}});
{lifted}
{body}
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "card.mjs"
        path.write_text(harness, encoding="utf-8")
        # utf-8 explicitly: node writes it, and `text=True` alone decodes with
        # the locale encoding — cp1252 on Windows. Every accent-free assertion
        # passed under that, so the gap only showed up on the first French
        # string with an ê in it.
        proc = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _render(payload: dict, lang: str) -> str:
    return _exec(
        f'renderDocuments({json.dumps(payload)});\nconsole.log($("#documents").innerHTML);',
        lang,
        "renderDocuments",
    )


def _entry(**over) -> dict:
    base = {
        "path": "notes.md",
        "name": "notes.md",
        "kind": "text",
        "chars": 20,
        "total": 20,
        "note": "",
        "reason": "prompt",
        "written": False,
        "reaches": True,
        "text": "Founder price 9 EUR",
        "mtime": 1700000000,
    }
    return {**base, **over}


def _payload(*docs, **over) -> dict:
    base = {
        "folder": "/home/op/companies/acme/documents",
        "documents": list(docs),
        "total": len(docs),
        "reaching": sum(1 for d in docs if d["reaches"]),
        "budget": 6000,
        "used": 2000,
    }
    return {**base, **over}


def test_rows_in_different_states_do_not_read_the_same():
    """The whole point of the card: two rows that read alike put the operator back where they
    started.

    The contrast has been narrowed twice, and both times because the state stopped existing rather
    than because the card got worse. It was "reaches the agents" against "past the budget", until
    every readable file's headings began riding on every prompt. Then it was whole against cut at
    `MAX_CHARS`, until `load` started reading whole files so the map could be built from all of them.
    What remains is the honest vocabulary: a file whose text is in the index, a picture that is sent
    rather than read, and a PDF that has no text to extract — three different answers to "why is this
    file in this state", and the card has to give three different sentences.
    """
    out = _render(
        _payload(
            _entry(path="brief.md"),
            _entry(path="logo.png", kind="image", reason="image", reaches=False),
            _entry(path="scan.pdf", kind="unreadable", reason="no-text-layer", reaches=False),
        ),
        "en",
    )
    # The state badge, which is the first on each row. The provenance badge beside it repeats on
    # purpose — three files the operator dropped in *are* three files the operator dropped in — so a
    # blanket uniqueness check over every badge fails for the one reason that is not a defect.
    states = re.findall(r'<span class="badge (?:ok|dim|warn|danger)">([^<]+)</span>', out)[::2]
    assert len(states) == 3 and len(set(states)) == 3, states
    assert "reaches the agents" in states


def test_the_french_card_is_french_including_the_reasons():
    """`doc.why.*` is reached by building the key, which is exactly the shape
    that escaped the parity test for as long as it existed."""
    out = _render(
        _payload(
            _entry(path="reaches.md"),
            # The real note this document carries. It is English on purpose —
            # that sentence rides into a prompt — so the card has to translate
            # the state and drop the sentence, not print both.
            _entry(
                path="scan.pdf",
                kind="unreadable",
                reaches=False,
                reason="no-text-layer",
                note="compressed or scanned; no text layer this build can read",
                text="",
                chars=0,
                total=0,
            ),
        ),
        "fr",
    )
    assert "atteint les agents" in out
    assert "aucune couche de texte" in out
    for english in ("reaches the agents", "no text layer"):
        assert english not in out, f"{english!r} leaked into the French card"


def test_an_os_message_is_the_one_note_the_card_keeps():
    """Every other state has a translated badge. This one carries whatever the
    operating system said, which is data — dropping it would leave the operator
    with "could not be opened" and no way to learn why."""
    out = _render(
        _payload(
            _entry(
                path="locked.md",
                kind="unreadable",
                reaches=False,
                reason="os-error",
                note="[Errno 13] Permission denied",
                text="",
                chars=0,
                total=0,
            ),
        ),
        "fr",
    )
    assert "n’a pas pu être ouvert" in out
    assert "Permission denied" in out


def test_provenance_is_on_the_row_not_inferred_from_the_name():
    out = _render(
        _payload(
            _entry(path="written/design-brief.md", written=True),
            _entry(path="pricing.md", written=False),
        ),
        "en",
    )
    assert "written by the company" in out and "you dropped it in" in out


def test_what_the_payload_left_behind_is_said_on_the_card():
    """A list of sixty presented as everything is the truncation this project
    keeps finding. The row count and the header must not disagree."""
    out = _render(_payload(*[_entry(path=f"f{i}.md") for i in range(60)], total=65), "en")
    assert "5 more on file, not listed here." in out


def test_an_empty_folder_still_says_where_to_put_a_file():
    """An empty state that does not say what to do next is a dead end, and the
    folder path is the whole answer here."""
    out = _render(_payload(), "en")
    assert "Nothing on file yet" in out
    assert "/home/op/companies/acme/documents" in out
    assert "Read the folder again" in out, "and a way to look again once you have"


def test_the_text_is_behind_a_disclosure_not_poured_onto_the_page():
    """Ten documents at four thousand characters each is the Done column all
    over again: a card that pushes everything below it off the screen."""
    out = _render(_payload(_entry(text="A severe visual identity." * 40)), "en")
    assert "<details" in out and "<summary>" in out
    assert "A severe visual identity." in out


def test_every_row_offers_a_way_back_out_including_the_unreadable_ones():
    """A scanned PDF nothing can extract is the row an operator most wants gone,
    and it is also the one row with no disclosure to hide a button inside."""
    out = _render(
        _payload(
            _entry(path="notes.md"),
            _entry(
                path="scan.pdf",
                kind="unreadable",
                reaches=False,
                reason="no-text-layer",
                text="",
                chars=0,
                total=0,
            ),
        ),
        "en",
    )
    assert out.count("data-doc-remove=") == 2
    assert 'data-doc-remove="scan.pdf"' in out
    # The copy button still belongs only to rows that have something to copy.
    assert out.count("data-doc-copy=") == 1


def test_a_path_in_the_remove_button_cannot_break_out_of_its_attribute():
    out = _render(_payload(_entry(path='a" onclick="alert(1)".md')), "en")
    assert 'onclick="alert(1)"' not in out
    assert "&quot;" in out


def test_the_limits_shown_come_from_the_server_not_from_the_page():
    """The accepted list and the size cap are the server's to decide. A second
    copy of either in the HTML would be a promise the server gets to break."""
    out = _exec(
        'describeDrop({accepts: [".md", ".pdf"], max_upload: 6291456});'
        "console.log(JSON.stringify({"
        'said: $("#doc-accepts").textContent, accept: $("#doc-file").attrs.accept}));',
        "en",
        "describeDrop",
    )
    said = json.loads(out)
    assert said["said"] == "Accepted: .md .pdf. Up to 6 MB per file."
    # And the picker offers exactly that, so the dialog cannot suggest a format
    # the server would refuse.
    assert said["accept"] == ".md,.pdf"


def test_the_french_refusal_is_french_and_names_the_file():
    """A refusal that does not say which of five dropped files it was, in the
    operator's own language, is a shrug."""
    out = _exec(
        "state.maxUpload = 6291456;"
        'console.log(docRefusal({name: "notes.zip", reason: "no-extractor", detail: ".zip"}));'
        'console.log(docRefusal({name: "huge.pdf", reason: "too-large"}));',
        "fr",
        "docRefusal",
    )
    assert "notes.zip n’a pas été enregistré" in out
    assert "rien ici ne sait lire .zip" in out
    assert "dépasse la limite de 6 Mo" in out
    assert "was not stored" not in out


def test_a_refused_name_cannot_smuggle_markup_into_the_result_line():
    out = _exec(
        'console.log(docRefusal({name: "<img src=x>.zip", reason: "no-extractor", '
        'detail: "<b>.zip</b>"}));',
        "en",
        "docRefusal",
    )
    assert "<img src=x" not in out and "<b>" not in out
    assert "&lt;img src=x&gt;.zip" in out


def test_a_filename_cannot_close_the_tag_it_sits_in():
    """Names come off a disk somebody else may control, and the copy button is
    keyed by index precisely so a path never lands inside a selector."""
    out = _render(_payload(_entry(path='<img src=x onerror="alert(1)">.md')), "en")
    assert "<img src=x" not in out
    assert "&lt;img src=x" in out
    assert 'data-doc-copy="0"' in out
