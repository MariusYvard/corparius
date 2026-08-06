"""What a company knows is rarely in company.yaml.

It is in a pitch deck, a spec, a price list. None of it could reach an agent:
the only ways in were the config, a hand-written skill, or whatever the model
happened to remember. A folder per company fixes that — and the rule that
governs every other input applies here too, which is that a wrong extraction is
worse than none.
"""

import zipfile

import pytest

from corparius import documents


@pytest.fixture
def drop(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    from corparius.config import cfg

    cfg.invalidate()
    folder = tmp_path / "companies" / "acme" / "documents"
    folder.mkdir(parents=True)
    return folder


def test_a_markdown_note_is_read(drop):
    (drop / "notes.md").write_text("Founder price 9 EUR", encoding="utf-8")
    doc = documents.load("acme")[0]
    assert doc.kind == "text" and "Founder price" in doc.text


def test_a_docx_is_a_zip_and_needs_no_dependency(drop):
    with zipfile.ZipFile(drop / "brief.docx", "w") as z:
        z.writestr("word/document.xml", "<w:p><w:t>Not a diagnosis</w:t></w:p>")
    doc = documents.load("acme")[0]
    assert doc.kind == "text" and "Not a diagnosis" in doc.text


def test_paragraph_boundaries_do_not_run_words_together(drop):
    """Without this every document arrives as one run-on word."""
    with zipfile.ZipFile(drop / "b.docx", "w") as z:
        z.writestr("word/document.xml", "<w:p><w:t>one</w:t></w:p><w:p><w:t>two</w:t></w:p>")
    assert "one two" in documents.load("acme")[0].text


def test_a_pptx_and_an_xlsx_go_through_the_same_door(drop):
    with zipfile.ZipFile(drop / "deck.pptx", "w") as z:
        z.writestr("ppt/slides/slide1.xml", "<a:p><a:t>Ninety seconds</a:t></a:p>")
    with zipfile.ZipFile(drop / "book.xlsx", "w") as z:
        z.writestr("xl/sharedStrings.xml", "<si><t>Revenue</t></si>")
    kinds = {d.name: d for d in documents.load("acme")}
    assert "Ninety seconds" in kinds["deck.pptx"].text
    assert "Revenue" in kinds["book.xlsx"].text


def test_a_csv_gives_its_shape_not_its_thousand_rows(drop):
    rows = "\n".join(f"a{i},b{i}" for i in range(500))
    (drop / "data.csv").write_text("col1,col2\n" + rows, encoding="utf-8")
    doc = documents.load("acme")[0]
    assert "col1, col2" in doc.text
    assert "a499" not in doc.text, "a thousand rows in a prompt is noise"


def test_a_pdf_with_a_text_layer_is_read(drop):
    (drop / "p.pdf").write_bytes(b"%PDF-1.4\nstream\nBT (Protocol validated) Tj ET\nendstream")
    doc = documents.load("acme")[0]
    assert doc.kind == "text" and "Protocol validated" in doc.text


def test_a_scanned_pdf_says_so_rather_than_returning_noise(drop):
    """A wrong extraction would put invented words in an agent's context and
    look exactly like knowledge."""
    (drop / "scan.pdf").write_bytes(b"%PDF-1.4\n" + bytes(range(256)) * 4)
    doc = documents.load("acme")[0]
    assert doc.kind == "unreadable" and "no text layer" in doc.note


def test_an_image_is_offered_not_described(drop):
    """Describing one needs a multimodal call. Saying so beats dropping it
    silently or inventing a caption."""
    (drop / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    doc = documents.load("acme")[0]
    assert doc.kind == "image" and doc.text == ""
    assert [p.name for p in documents.images("acme")] == ["shot.png"]


def test_a_format_with_no_extractor_is_named_not_guessed(drop):
    (drop / "a.zip").write_bytes(b"PK\x03\x04")
    doc = documents.load("acme")[0]
    assert doc.kind == "unreadable" and "no extractor" in doc.note


def test_a_long_document_is_cut_and_says_that_it_was(drop):
    """An agent reasoning about a truncated document should know it was
    truncated."""
    (drop / "big.md").write_text("word " * 5000, encoding="utf-8")
    doc = documents.load("acme")[0]
    assert len(doc.text) <= documents.MAX_CHARS
    assert "of" in doc.note and "characters" in doc.note


def test_the_prompt_block_is_bounded(drop):
    """This rides on every prompt, and an unscoped 3 815-character skill already
    taught this project what that costs."""
    for i in range(10):
        (drop / f"d{i}.md").write_text("x" * 3000, encoding="utf-8")
    assert len(documents.context("acme", budget=6000)) <= 6500


def test_newest_first_so_this_morning_displaces_last_month(drop):
    import os
    import time

    (drop / "old.md").write_text("old note", encoding="utf-8")
    (drop / "new.md").write_text("new note", encoding="utf-8")
    old = time.time() - 86400
    os.utime(drop / "old.md", (old, old))
    assert documents.load("acme")[0].name == "new.md"


def test_a_company_with_no_folder_gets_nothing_and_no_error():
    assert documents.load("nobody") == []
    assert documents.context("nobody") == ""


def test_only_readable_documents_reach_the_prompt(drop):
    (drop / "a.zip").write_bytes(b"PK\x03\x04")
    (drop / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert documents.context("acme") == ""


# --------------------------------------------------------------------------
# Written by the company, not only read by it
# --------------------------------------------------------------------------


def test_a_deliverable_survives_the_turn_that_produced_it(drop):
    """Four tools produced real prose and kept 120 characters of it as a log
    line. The rest was discarded on the spot — including from the agent that
    would want it next turn."""
    import types

    from corparius.tools.registry import TOOLS

    ctx = types.SimpleNamespace(company={"slug": "acme", "name": "Acme"}, store=None)
    brief = "A severe visual identity, dark tones, deep blue accents. " * 8
    line = TOOLS["draft_design_brief"].run(ctx, brief).output

    assert len(line) < 200, "the log line stays a log line"
    kept = [d for d in documents.load("acme") if d.name == "design-brief.md"]
    assert kept, "the brief was not kept"
    assert "deep blue accents" in kept[0].text
    assert len(kept[0].text) > len(line), "more was kept than was logged"


def test_what_the_agents_wrote_is_context_next_turn(drop):
    documents.write("acme", "Design brief", "Dark tones and deep blue accents.")
    assert "deep blue accents" in documents.context("acme")


def test_a_rewrite_replaces_rather_than_accumulates(drop):
    """Nineteen near-identical briefs in a folder is the queue-of-drafts problem
    in another costume."""
    documents.write("acme", "Design brief", "first version")
    documents.write("acme", "Design brief", "second version")
    briefs = [d for d in documents.load("acme") if d.name == "design-brief.md"]
    assert len(briefs) == 1 and "second version" in briefs[0].text


def test_written_and_dropped_files_live_apart_but_both_count(drop):
    (drop / "operator.md").write_text("what the operator dropped", encoding="utf-8")
    documents.write("acme", "Weekly review", "what the company wrote")
    names = {d.path.parent.name for d in documents.load("acme")}
    assert names == {"documents", documents.WRITTEN}
    block = documents.context("acme")
    assert "operator dropped" in block and "company wrote" in block


def test_an_empty_draft_writes_nothing(drop):
    documents.write("acme", "Nothing", "   ")
    assert documents.load("acme") == []
