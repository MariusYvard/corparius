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


def test_the_index_sees_past_the_cut_that_a_reader_stops_at(drop):
    """The cut is a *reading* bound, and it had quietly become a **retrieval** bound.

    `load` truncated every file at 4 000 characters, which was the right answer while the block was
    "the newest files until the budget is gone": there was no point extracting a thirty-page review
    when only the first 4 000 characters could ever be sent. With a map in front of them it became
    the constraint on the whole feature — the outline was built from the first 4 000 characters, so a
    heading past the cut did not exist, no agent could name it, and the second round could not ask
    for what it could not see.

    Both halves here, because either alone is half a rule: the default still cuts and still says so,
    and `max_chars=0` reaches the section only a full read can find.
    """
    filler = "The reviewer went on at length about margins. " * 120  # ~5 400 characters
    (drop / "review.md").write_text(
        f"# Pricing\nThe annual toggle lowered conversion.\n{filler}\n\n"
        "# Hosting\nThe bucket is static so a deploy cannot break the checkout.\n",
        encoding="utf-8",
    )
    cut = documents.load("acme")[0]
    assert len(cut.text) <= documents.MAX_CHARS, "the default is still a cut"
    assert "cannot break the checkout" not in cut.text, "and this is what the cut costs"

    whole = documents.load("acme", max_chars=0)
    titles = [s.title for s in documents.sections(whole)]
    assert "Hosting" in titles, f"the map still stops at 4 000 characters: {titles}"
    assert "cannot break the checkout" in documents.context("acme", query="deploy checkout")


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


# --- structure survives extraction ------------------------------------------------


def test_reading_a_document_keeps_its_line_structure(tmp_path):
    """The defect this pins, and it was silent: `read` ended in `" ".join(text.split())`, so **every
    newline in every file was destroyed at read time**. A model received a contract as one unbroken
    line, and `docindex` could not find a heading in a single real document — it worked perfectly on
    strings in its own unit tests and returned one giant section on anything loaded from disk.

    The collapse was written for PDF and OOXML, whose extraction is a mess of ragged spacing. But both
    of those extractors already flatten their own output, so the only files this changed were the ones
    whose structure was worth keeping: the agents' markdown, the operator's notes, and CSV rows that
    `_from_csv` had deliberately joined with newlines.
    """
    doc = tmp_path / "notes.md"
    doc.write_text(
        "# Pricing\nSingle seat is 19 a month.\n\n\n\n## Discounts\nNone given.\n", encoding="utf-8"
    )
    text = documents.read(doc).text
    assert "# Pricing" in text.split("\n"), "a heading has to survive on its own line"
    assert "## Discounts" in text.split("\n")
    assert "\n\n\n" not in text, "runs of blank lines are still collapsed"
    assert "  " not in text, "runs of spaces are still squeezed"


def test_csv_rows_are_still_rows(tmp_path):
    """`_from_csv` joins rows with newlines on purpose. The global collapse glued them back into one
    run of comma-separated cells, which is the same table with its shape removed."""
    doc = tmp_path / "leads.csv"
    doc.write_text("name,city\nAda,Paris\nGrace,Lyon\n", encoding="utf-8")
    lines = documents.read(doc).text.split("\n")
    assert len(lines) >= 3, f"a three-row csv came back as {len(lines)} line(s)"


def test_a_picture_among_the_files_is_skipped_by_the_index_rather_than_indexed(drop):
    """The branch the coverage ratchet found unentered: `sections()` walking a document that is not
    text.

    It matters because the mixed folder is the normal one — an operator drops a deck, a price list
    and a screenshot of a competitor's page in together. An image has no text by design (nothing is
    invented for one; the file itself travels to a model that can see it), so it must contribute no
    headings at all rather than an empty section that would take a line in every prompt's map.
    """
    (drop / "brief.md").write_text("# Pricing\nThe annual toggle lowered conversion.\n", "utf-8")
    (drop / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)

    docs = documents.load("acme", max_chars=0)
    assert {d.kind for d in docs} == {"text", "image"}, "the fixture has to hold both kinds"

    parts = documents.sections(docs)
    assert [s.title for s in parts] == ["Pricing"]
    assert all("shot.png" not in s.label for s in parts), "an image reached the map"
