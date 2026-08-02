"""What the company knows, in the files it already has.

A company's real knowledge is rarely in `company.yaml`. It is in a pitch deck,
a spec, a price list, a screenshot of a competitor's page. Until now none of it
could reach an agent: the only ways in were the config, a skill somebody wrote
by hand, and whatever the model happened to remember.

So: a folder per company. Drop a PDF, a Word file, a spreadsheet, a Markdown
note or a photo into `companies/<slug>/documents/` and it becomes context the
agents can use.

**Text is extracted, images are not described.** Extraction is done here with
the standard library and the two dependencies this project already has — a PDF
and a .docx are both zip containers with readable parts, and a CSV is a CSV.
Images are a different promise: describing one needs a multimodal call, so an
image is offered to the models that accept images and skipped by the ones that
do not, rather than being silently dropped or silently invented.

Nothing is uploaded anywhere. The files stay on disk, the extraction happens in
this process, and what reaches a provider is the text the operator put there.
"""

from __future__ import annotations

import csv
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import paths

log = logging.getLogger("corparius.documents")

# Extensions with a real extractor behind them. Anything else is listed but not
# read, which is a more useful answer than pretending a .zip is prose.
TEXT_SUFFIXES = {".md", ".txt", ".markdown", ".rst", ".log"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
RICH_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx", ".csv"}

# One document must not swallow the prompt. A pitch deck is thirty pages and an
# agent turn has a token budget the operator set on purpose.
MAX_CHARS = 4000


@dataclass
class Document:
    path: Path
    kind: str  # text | image | unreadable
    text: str = ""
    note: str = ""

    @property
    def name(self) -> str:
        return self.path.name

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "chars": len(self.text),
            "note": self.note,
        }


def folder(slug: str) -> Path:
    return paths.companies_dir() / slug / "documents"


def _from_pdf(data: bytes) -> str:
    """Text out of a PDF without a PDF library.

    Deliberately modest: it reads the uncompressed text operators that most
    exporters emit, and returns nothing rather than garbage when a file is
    fully compressed or scanned. A wrong extraction is worse than none — it
    would put invented words in an agent's context and look like knowledge.
    """
    out = []
    for match in re.finditer(rb"BT(.*?)ET", data, re.S):
        for chunk in re.findall(rb"\((?:\\.|[^\\()])*\)", match.group(1)):
            piece = chunk[1:-1]
            piece = re.sub(rb"\\([()\\])", rb"\1", piece)
            try:
                out.append(piece.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001 - one bad run is not a failed file
                continue
    return " ".join(" ".join(out).split())


def _from_ooxml(path: Path, inner: tuple[str, ...]) -> str:
    """docx / pptx / xlsx: zip containers with XML inside.

    No dependency needed, and it is the same three lines for all three formats —
    which is why they are all here rather than only the one that seemed easiest.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if any(n.startswith(p) for p in inner)]
            parts = []
            for name in sorted(names)[:60]:
                raw = zf.read(name).decode("utf-8", "replace")
                # Paragraph and cell boundaries become spaces, or the whole
                # document arrives as one run-on word.
                raw = re.sub(r"</(w:p|a:p|c|si)>", " ", raw)
                parts.append(re.sub(r"<[^>]+>", "", raw))
        return " ".join(" ".join(parts).split())
    except (zipfile.BadZipFile, OSError, KeyError) as exc:
        log.info("%s could not be read: %s", path.name, exc)
        return ""


def _from_csv(path: Path) -> str:
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.reader(fh))
    except OSError:
        return ""
    # The header and a sample: a thousand rows in a prompt is noise, and the
    # shape of the data is what an agent can actually use.
    keep = rows[:15]
    return "\n".join(", ".join(cell for cell in row if cell) for row in keep if any(row))


def read(path: Path) -> Document:
    """One file, extracted as far as it honestly can be."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return Document(
            path,
            "image",
            note="offered to models that accept images; not described here",
        )
    text = ""
    if suffix in TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return Document(path, "unreadable", note=str(exc))
    elif suffix == ".pdf":
        try:
            text = _from_pdf(path.read_bytes())
        except OSError as exc:
            return Document(path, "unreadable", note=str(exc))
        if not text:
            return Document(
                path,
                "unreadable",
                note="compressed or scanned; no text layer this build can read",
            )
    elif suffix == ".docx":
        text = _from_ooxml(path, ("word/",))
    elif suffix == ".pptx":
        text = _from_ooxml(path, ("ppt/slides/",))
    elif suffix == ".xlsx":
        text = _from_ooxml(path, ("xl/sharedStrings", "xl/worksheets/"))
    elif suffix == ".csv":
        text = _from_csv(path)
    else:
        return Document(path, "unreadable", note=f"no extractor for {suffix or 'this file'}")

    text = " ".join(text.split())
    if not text:
        return Document(path, "unreadable", note="no text found")
    note = ""
    if len(text) > MAX_CHARS:
        # Said, not hidden: an agent reasoning about a truncated document should
        # know it was truncated.
        note = f"first {MAX_CHARS} of {len(text)} characters"
        text = text[:MAX_CHARS]
    return Document(path, "text", text=text, note=note)


def load(slug: str) -> list[Document]:
    """Every document a company has dropped, newest first."""
    base = folder(slug)
    if not base.is_dir():
        return []
    # Recursive: what the agents wrote lives in a subfolder, and it is context
    # exactly as much as what the operator dropped in.
    files = [p for p in base.rglob("*") if p.is_file() and not p.name.startswith(".")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [read(p) for p in files]


def context(slug: str, budget: int = 6000) -> str:
    """The company's own documents, as a block for an agent prompt.

    Bounded, because this rides on every prompt of the agents that ask for it
    and the operator already learned what an unscoped 3 815-character skill
    costs. Newest first, so a document dropped this morning displaces one from
    last month rather than never being reached.
    """
    docs = [d for d in load(slug) if d.kind == "text" and d.text]
    if not docs:
        return ""
    lines, used = [], 0
    for doc in docs:
        entry = f"--- {doc.name}" + (f" ({doc.note})" if doc.note else "") + f" ---\n{doc.text}"
        if used + len(entry) > budget:
            break
        lines.append(entry)
        used += len(entry)
    if not lines:
        return ""
    return "What this company has put on file:\n" + "\n\n".join(lines)


def images(slug: str) -> list[Path]:
    """Image paths, for a caller that can actually send them to a model."""
    return [d.path for d in load(slug) if d.kind == "image"]


# Written by the company, not only read by it. Kept apart from what the operator
# drops in so a sweep of one never deletes the other, and so the provenance of a
# file is visible from its path.
WRITTEN = "written"


def write(slug: str, name: str, text: str, kind: str = WRITTEN) -> Path:
    """Persist something an agent produced, and return where it went.

    Four tools were producing real deliverables and throwing them away:
    `draft_design_brief`, `update_pricing`, `scan_competitors` and
    `write_eod_summary` each generated prose and kept the first 120 characters
    as a log line. The rest was discarded on the spot — a design brief the
    design agent had just written could not be read by anyone, including the
    design agent on its next turn.

    Same folder the operator drops files into, so a brief written on Monday is
    context on Tuesday without anybody moving it.
    """
    from . import company as company_mod

    base = folder(slug) / kind
    base.mkdir(parents=True, exist_ok=True)
    stem = company_mod._slugify(name) or "note"
    path = base / f"{stem}.md"
    body = " ".join(str(text or "").split())
    if not body:
        return path
    # Overwritten rather than appended: the latest design brief replaces the
    # previous one, because a folder of nineteen near-identical briefs is the
    # queue-of-drafts problem again in another costume.
    path.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    return path
