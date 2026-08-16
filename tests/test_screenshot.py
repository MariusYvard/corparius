"""Showing the design agent the page it is reviewing.

It never saw one. `review_site` strips the tags and sends the visible text, which is the right input
for a question about wording and says nothing at all about contrast, hierarchy, or whether the first
screen names what is being sold. This project has already paid for that distinction twice: its own
tab bug was found in a screenshot and not in the CSS, and a blind design review scored a page it
could not see.

**Not Playwright, and that was measured rather than assumed.** Playwright means a Python package
plus `playwright install chromium`, a ~150 MB download and an installation step, on a product that
starts by double-clicking a file. A Chromium-family browser already on the machine does the same
job — it *is* the same job, since Playwright drives Chromium too — in about two seconds, with no
dependency and nothing to install. Windows always has Edge; macOS and Linux usually have one of the
five this looks for; and where there is none the review carries on with the text it always had.

The one thing that had to be learned by measuring, and that a first version got wrong:

```text
    launcher returns   0.1 - 0.3s      Edge and Chrome, both already running
    picture written    about 3s later  by the instance the request was handed to
```

The process exiting is not the signal. A dedicated `--user-data-dir` does not change it. So `capture`
waits for the *file* to appear and stop growing, and the first version — which checked the moment
`proc.run` returned — reported "the browser wrote no image" about a page that had rendered
perfectly.
"""

import pathlib

import pytest

from corparius.config import cfg
from corparius.providers import screenshot

needs_browser = pytest.mark.skipif(
    not screenshot.available(), reason="no Chromium-family browser on this machine"
)

PAGE = (
    "<!doctype html><meta charset='utf-8'>"
    "<style>body{background:#0b1020;color:#eef;font:16px system-ui;margin:0;padding:40px}"
    "h1{font-size:48px;margin:0}</style><h1>Vigil</h1><p>Un check-in vocal de 90 secondes.</p>"
)


@pytest.fixture
def clean(monkeypatch, tmp_path):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.delenv("CORP_BROWSER_PATH", raising=False)
    cfg.invalidate()
    return tmp_path


def _png_size(path) -> tuple[int, int]:
    """Width and height straight out of the IHDR, so the assertion is about the image rather than
    about the file being non-empty."""
    import struct

    head = pathlib.Path(path).read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", head[16:24])


# --- finding a browser without being told -----------------------------------------


def test_a_browser_is_found_with_no_configuration(clean):
    """The property the whole feature rests on. An operator who has to name a path before the design
    agent can see anything has a feature most operators will never have."""
    found = screenshot.browser()
    if not found:
        pytest.skip("no Chromium-family browser here; the fallback is asserted below")
    assert pathlib.Path(found).is_file()


def test_a_named_browser_wins_over_the_search(clean, monkeypatch, tmp_path):
    fake = tmp_path / "my-chromium"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("CORP_BROWSER_PATH", str(fake))
    cfg.invalidate()
    assert screenshot.browser() == str(fake)


def test_a_named_browser_that_is_not_there_is_said_out_loud(clean, monkeypatch, caplog):
    """Falling back in silence would leave somebody who set this believing it was used, which is the
    class of quiet wrongness this codebase keeps finding in itself."""
    monkeypatch.setenv("CORP_BROWSER_PATH", str(clean / "nowhere.exe"))
    cfg.invalidate()
    with caplog.at_level("WARNING"):
        screenshot.browser()
    assert any("CORP_BROWSER_PATH" in r.message for r in caplog.records)


def test_no_browser_is_a_sentence_and_never_an_exception(clean, monkeypatch, tmp_path):
    """A headless Linux box has no browser and must still run a design review. This is the path
    every such machine takes, so it is asserted rather than assumed."""
    monkeypatch.setattr(screenshot, "browser", lambda: "")
    out = screenshot.capture("about:blank", tmp_path / "x.png")
    assert out["ok"] is False and "no Chromium-family browser" in out["error"]
    assert out["path"] == ""


# --- rendering ---------------------------------------------------------------------


@needs_browser
def test_a_page_becomes_a_picture_of_that_page(clean, tmp_path):
    """The whole feature, once. A data URI rather than a file so this asserts the rendering and not
    the path handling, which has its own test below."""
    out = tmp_path / "shot.png"
    result = screenshot.capture("data:text/html," + PAGE, out, width=1280, height=800)

    assert result["ok"] is True, result["error"]
    assert _png_size(out) == (1280, 800)
    # A rendered page is tens of kilobytes; a blank one is a few hundred bytes. The threshold is
    # loose on purpose — this is asserting "something was drawn", not a byte count.
    assert out.stat().st_size > 2000, "the browser produced a blank image"


@needs_browser
def test_a_local_file_is_reached_through_a_file_uri(clean, tmp_path):
    """The real case: a company's site is a file on disk, under a Windows path with a drive letter,
    backslashes and often a space or an accent in the user's name."""
    page = tmp_path / "un dossier accentué" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text(PAGE, encoding="utf-8")

    result = screenshot.capture(str(page), tmp_path / "file.png")
    assert result["ok"] is True, result["error"]
    assert _png_size(tmp_path / "file.png") == (screenshot.WIDTH, screenshot.HEIGHT)


@needs_browser
def test_a_stale_picture_is_never_reported_as_this_run_s(clean, tmp_path):
    """The quietest way to review yesterday's page and believe it is today's. The output is removed
    before the browser runs, so a failure cannot leave the previous capture in place to be picked up
    as a success."""
    out = tmp_path / "shot.png"
    out.write_bytes(b"an old picture from a previous run")
    screenshot.capture("data:text/html," + PAGE, out)
    assert b"an old picture" not in out.read_bytes()


@needs_browser
def test_several_pages_are_bounded_and_the_bound_is_said(clean, tmp_path, caplog):
    """A site with forty pages would otherwise spend forty seconds and hand a model forty images to
    pay for. "No silent truncation" applies to a page left out exactly as it applies to a document."""
    pages = []
    for i in range(6):
        page = tmp_path / f"p{i}.html"
        page.write_text(PAGE, encoding="utf-8")
        pages.append(str(page))

    with caplog.at_level("INFO"):
        made = screenshot.capture_all(pages, tmp_path / "shots", limit=2)
    assert len(made) == 2
    assert any("past the limit" in r.message for r in caplog.records)


@needs_browser
def test_a_page_that_is_not_there_renders_the_browser_s_own_error_page(clean, tmp_path):
    """The limit of what this can know, asserted rather than wished away.

    A missing file does not make Chromium fail: it renders *its* page about the missing file, and
    `capture` reports success because a picture was genuinely produced. So `ok` means "the browser
    drew something", not "the browser drew your site", and nothing here can tell the two apart —
    detecting an error page would mean matching browser chrome text in whatever language the machine
    is set to, which is the kind of guess that goes wrong quietly.

    Acceptable because of who calls it: `capture_all` is given paths that `_site_pages_for` just
    globbed off disk, so "the file is not there" is not an input this can receive in the product. A
    caller that could pass an arbitrary URL would need its own check.
    """
    result = screenshot.capture(
        "file:///definitely/not/here.html", tmp_path / "missing.png", timeout=20
    )
    assert result["ok"] is True, result["error"]
    assert (tmp_path / "missing.png").stat().st_size > 0


@needs_browser
def test_a_browser_that_writes_nothing_is_reported_and_never_raised(clean, tmp_path, monkeypatch):
    """The failure that must not take a turn down. Induced by pointing the executable at something
    that is not a browser, which is what a stale `CORP_BROWSER_PATH` amounts to."""
    not_a_browser = tmp_path / "nope.exe"
    not_a_browser.write_text("", encoding="utf-8")
    monkeypatch.setenv("CORP_BROWSER_PATH", str(not_a_browser))
    cfg.invalidate()

    result = screenshot.capture("data:text/html,<h1>x</h1>", tmp_path / "out.png", timeout=6)
    assert result["ok"] is False and result["path"] == ""
    assert result["error"], "a failure with no sentence is a failure nobody can act on"


# --- what the executor does with it ------------------------------------------------


def test_the_review_tools_ask_for_a_picture_and_the_others_do_not():
    """The flag is on the two tools whose subject is a rendered page, and on nothing else. A design
    brief is helped by a competitor's screenshot the operator dropped in; it has no business making
    corparius launch a browser."""
    from corparius.tools.registry import TOOLS

    assert TOOLS["review_site"].shoots_site is True
    assert TOOLS["review_generated_site"].shoots_site is True
    assert TOOLS["draft_design_brief"].shoots_site is False
    assert TOOLS["reconcile_stripe"].sees_images is False


def test_a_text_only_model_never_pays_for_a_capture(monkeypatch, tmp_path):
    """The ordering that makes this cheap, and the reason it is asserted rather than left to reading.

    A capture costs a couple of seconds of browser per page. Taking one and then discovering the
    model cannot read images would be the exact waste `sees_images` was written to avoid, one step
    later in the same function — so the model is established first and the browser is never launched.
    """
    import types

    from corparius.kernel.records import AgentRole
    from corparius.roster import ROSTER
    from corparius.tools.registry import TOOLS

    from .test_images import _executor

    ex = _executor(monkeypatch)
    monkeypatch.setattr(ex, "_model_reads_images", lambda *a, **k: False)
    monkeypatch.setattr(
        screenshot, "capture_all", lambda *a, **k: pytest.fail("a browser was launched anyway")
    )
    ctx = types.SimpleNamespace(
        company={"slug": "t"}, store=None, images=[], data_path=str(tmp_path)
    )

    assert ex._pictures_for(TOOLS["review_site"], ROSTER[AgentRole.DESIGN], ctx) == []


def test_the_review_still_runs_on_a_machine_with_no_browser(monkeypatch, tmp_path):
    """The claim the whole feature rests on: **nothing here is ever a reason for a turn to fail.**

    A headless Linux box has no Chromium of any kind, and a design review there has to produce
    exactly what it produced before this existed — findings drawn from the page text. So the picture
    is absent, one line says why, and the turn is otherwise untouched.
    """
    import types

    from corparius.kernel.records import AgentRole
    from corparius.roster import ROSTER
    from corparius.tools.registry import TOOLS

    from .test_images import _executor

    ex = _executor(monkeypatch)
    monkeypatch.setattr(ex, "_model_reads_images", lambda *a, **k: True)
    monkeypatch.setattr(screenshot, "browser", lambda: "")
    ctx = types.SimpleNamespace(
        company={"slug": "t", "name": "T", "offer": {}},
        store=None,
        images=[],
        data_path=str(tmp_path),
    )

    assert ex._pictures_for(TOOLS["review_site"], ROSTER[AgentRole.DESIGN], ctx) == []
    # And the tool is still askable, which is what "the review runs" means at this level: its prompt
    # renders without a model and without a picture.
    assert TOOLS["review_site"].draft_prompt(ctx)


def test_a_capture_never_lands_in_the_operator_s_documents(monkeypatch, tmp_path):
    """Where the pictures go, and where they must not.

    `documents/` is the operator's list and `documents/written/` is synced to the company
    repository, so a PNG per page per run would be both a folder nobody can read and a commit per
    run of a file nobody wants. They go to a dotted directory beside them instead.
    """
    import types

    from corparius.kernel.records import AgentRole
    from corparius.roster import ROSTER
    from corparius.tools.registry import TOOLS

    from .test_images import _executor

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cfg.invalidate()
    seen = {}
    ex = _executor(monkeypatch)
    monkeypatch.setattr(ex, "_model_reads_images", lambda *a, **k: True)
    monkeypatch.setattr(screenshot, "available", lambda: True)
    monkeypatch.setattr(
        screenshot, "capture_all", lambda pages, into, **k: seen.setdefault("into", into) and []
    )

    page = tmp_path / "companies" / "t" / "site" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text("<h1>x</h1>", encoding="utf-8")
    ctx = types.SimpleNamespace(
        company={"slug": "t"}, store=None, images=[], data_path=str(tmp_path)
    )
    ex._pictures_for(TOOLS["review_site"], ROSTER[AgentRole.DESIGN], ctx)

    where = str(seen.get("into", ""))
    assert ".shots" in where, where
    assert "documents" not in where, "screenshots were written into the operator's document folder"


def _one_pixel_png() -> bytes:
    """A PNG that is actually a PNG.

    `llm.read_images` sniffs the bytes, so a text file with a `.png` name is dropped and a test built
    on one passes for the wrong reason — which is what the first version of this did. Built rather
    than pasted so it is readable: signature, IHDR, one compressed pixel, IEND, each with its CRC.
    """
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes([0, 255, 255, 255]))
    magic = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    return magic + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_the_pages_are_rendered_and_handed_to_the_model(monkeypatch, tmp_path):
    """The path a design turn actually takes, with the browser stood in for.

    Asserted end to end rather than on `capture_all` alone: between the capture and the model sit
    `read_images`, a size limit and a log line, and a picture that was taken and then dropped on the
    way is the failure this would otherwise look exactly like.
    """
    import types

    from corparius.kernel.records import AgentRole
    from corparius.roster import ROSTER
    from corparius.tools.registry import TOOLS

    from .test_images import _executor

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cfg.invalidate()
    own = tmp_path / "companies" / "t" / "site"
    own.mkdir(parents=True)
    (own / "index.html").write_text(PAGE, encoding="utf-8")

    ex = _executor(monkeypatch)
    monkeypatch.setattr(ex, "_model_reads_images", lambda *a, **k: True)
    monkeypatch.setattr(screenshot, "available", lambda: True)

    def fake_capture_all(pages, into, **kw):
        made = []
        for page in pages:
            shot = pathlib.Path(into) / (pathlib.Path(page).stem + ".png")
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(_one_pixel_png())
            made.append(str(shot))
        return made

    monkeypatch.setattr(screenshot, "capture_all", fake_capture_all)
    ctx = types.SimpleNamespace(
        company={"slug": "t"}, store=None, images=[], data_path=str(tmp_path)
    )

    sent = ex._pictures_for(TOOLS["review_site"], ROSTER[AgentRole.DESIGN], ctx)
    assert sent, "the pages were rendered and none of them reached the model"


def test_a_render_that_produces_nothing_is_not_an_empty_picture(monkeypatch, tmp_path):
    """A browser that ran and wrote no file must hand back no picture rather than a broken one. The
    turn then proceeds on the page text, which is what it had before any of this existed."""
    import types

    from corparius.kernel.records import AgentRole
    from corparius.roster import ROSTER
    from corparius.tools.registry import TOOLS

    from .test_images import _executor

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cfg.invalidate()
    own = tmp_path / "companies" / "t" / "site"
    own.mkdir(parents=True)
    (own / "index.html").write_text(PAGE, encoding="utf-8")

    ex = _executor(monkeypatch)
    monkeypatch.setattr(ex, "_model_reads_images", lambda *a, **k: True)
    monkeypatch.setattr(screenshot, "available", lambda: True)
    monkeypatch.setattr(screenshot, "capture_all", lambda pages, into, **kw: [])
    ctx = types.SimpleNamespace(
        company={"slug": "t"}, store=None, images=[], data_path=str(tmp_path)
    )

    assert ex._pictures_for(TOOLS["review_site"], ROSTER[AgentRole.DESIGN], ctx) == []
