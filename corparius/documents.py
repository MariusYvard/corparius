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
import os
import re
import time
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
    # A stable code behind `note`. The console shows a document's state in two
    # languages and `note` is an English sentence, because that sentence rides
    # into a prompt where English is the language. A payload of prose cannot be
    # translated; a code can.
    reason: str = ""  # "" | cut | image | no-text-layer | no-extractor | empty | os-error
    # Characters before MAX_CHARS cut them. Zero when nothing was cut.
    total: int = 0
    # Path inside the company's documents folder, posix-style. Set by `load`,
    # which is the only caller that knows where the folder starts; `read` on a
    # loose path leaves it empty and falls back to the file name. Computed once
    # here because the prompt and the console both need it, and two derivations
    # of the same path is how they come to disagree.
    rel: str = ""

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def label(self) -> str:
        """What names this document to a person or a model."""
        return self.rel or self.name

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "chars": len(self.text),
            # The real length, as a number. It existed only inside `note` as
            # prose, so anything reading this payload saw 4 000 characters and
            # had no way to learn the document was three times that.
            "total": self.total or len(self.text),
            "note": self.note,
            "reason": self.reason,
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
            reason="image",
        )
    text = ""
    if suffix in TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return Document(path, "unreadable", note=str(exc), reason="os-error")
    elif suffix == ".pdf":
        try:
            text = _from_pdf(path.read_bytes())
        except OSError as exc:
            return Document(path, "unreadable", note=str(exc), reason="os-error")
        if not text:
            return Document(
                path,
                "unreadable",
                note="compressed or scanned; no text layer this build can read",
                reason="no-text-layer",
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
        return Document(
            path,
            "unreadable",
            note=f"no extractor for {suffix or 'this file'}",
            reason="no-extractor",
        )

    text = " ".join(text.split())
    if not text:
        return Document(path, "unreadable", note="no text found", reason="empty")
    note, total = "", len(text)
    if total > MAX_CHARS:
        # Said, not hidden: an agent reasoning about a truncated document should
        # know it was truncated.
        note = f"first {MAX_CHARS} of {total} characters"
        text = text[:MAX_CHARS]
    return Document(
        path,
        "text",
        text=text,
        note=note,
        reason="cut" if note else "",
        total=total,
    )


def load(slug: str) -> list[Document]:
    """Every document a company has dropped, newest first."""
    base = folder(slug)
    if not base.is_dir():
        return []
    # Recursive: what the agents wrote lives in a subfolder, and it is context
    # exactly as much as what the operator dropped in.
    # Any dot-prefixed segment, not just the file name. The test was on `p.name`
    # alone, so a hidden *folder* was walked into and everything under it read: a
    # `.git`, a `.obsidian`, or — once removal existed — the `.trash` this module
    # moves documents to, which would have gone straight back into the prompt the
    # operator had just taken it out of.
    files = [
        p
        for p in base.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(base).parts)
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    docs = []
    for path in files:
        doc = read(path)
        doc.rel = path.relative_to(base).as_posix()
        docs.append(doc)
    return docs


# The prompt budget, named. It was a default argument and nothing else, so
# nobody outside this module could say what a document had been measured
# against without writing the number down a second time.
CONTEXT_BUDGET = 6000


def _block(doc: Document) -> str:
    """One document as it appears in a prompt.

    Named by its path inside the folder, not by its bare file name. Two files
    called `design-brief.md` — one dropped in, one written by the design agent —
    were two identical headings in the same prompt, with nothing for a model to
    tell them apart by. The relative path separates them and says which of the
    two the company wrote itself, at no cost.
    """
    return f"--- {doc.label}" + (f" ({doc.note})" if doc.note else "") + f" ---\n{doc.text}"


def _selected(docs: list[Document], budget: int) -> tuple[list[Document], int]:
    """The prefix of `docs` that fits the budget, and what it costs.

    One implementation, two callers: `context` builds the prompt out of it and
    `inventory` tells the operator which documents it left behind. Written twice
    these would drift, and the console would then vouch for a document no agent
    has ever seen — which is the failure this whole surface exists to end.
    """
    chosen: list[Document] = []
    used = 0
    for doc in docs:
        size = len(_block(doc))
        if used + size > budget:
            # Newest first, so stopping here keeps the freshest documents rather
            # than whichever ones happened to be small.
            break
        chosen.append(doc)
        used += size
    return chosen, used


def context(slug: str, budget: int = CONTEXT_BUDGET) -> str:
    """The company's own documents, as a block for an agent prompt.

    Bounded, because this rides on every prompt of the agents that ask for it
    and the operator already learned what an unscoped 3 815-character skill
    costs. Newest first, so a document dropped this morning displaces one from
    last month rather than never being reached.
    """
    chosen, _ = _selected([d for d in load(slug) if d.kind == "text" and d.text], budget)
    if not chosen:
        return ""
    return "What this company has put on file:\n" + "\n\n".join(_block(d) for d in chosen)


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


# What the console accepts from a browser: exactly the formats something here can
# read. Anything else is refused with the reason named rather than stored — a file
# no extractor can open is not context, it is a row that will read "no extractor"
# for as long as the folder exists.
UPLOAD_SUFFIXES = TEXT_SUFFIXES | IMAGE_SUFFIXES | RICH_SUFFIXES

# One file. The console's per-route body ceiling is what stops a flood; this is
# what stops a single 200 MB database export from being the thing that hits it.
MAX_UPLOAD = 6 << 20


class Refused(Exception):
    """A drop that will not be stored, carrying a code the console translates.

    Refusing is a normal answer here, not an error: `ok` qualifies the request,
    and a well-formed request to store an unreadable file is a well-formed
    request. The caller reports `stored: False` with this reason, and the
    operator learns which of their file it was and why.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def save(slug: str, name: str, data: bytes) -> tuple[Path, bool]:
    """Store a file the operator dropped on the console. Returns where it went,
    and whether it replaced one that was already there.

    It lands in the folder root, never in `written/`. Provenance is read from the
    path everywhere else in this module, so putting an operator's file into the
    folder the agents write to would make the console's own badge lie about who
    produced it.
    """
    # A browser is not the only thing that can POST here, and "../../.env" is a
    # perfectly ordinary file name right up until it is not. Backslashes are
    # folded first: a Windows browser can send one, and it is a legal character
    # in a POSIX file name, so `Path.name` alone would keep it.
    clean = Path(str(name or "").replace("\\", "/")).name.strip()
    if not clean or clean.startswith("."):
        # A dotfile would be written and then skipped by `load` forever: stored,
        # invisible, and never context. That is the worst of the three answers.
        raise Refused("bad-name")
    suffix = Path(clean).suffix.lower()
    if suffix not in UPLOAD_SUFFIXES:
        raise Refused("no-extractor", suffix or clean)
    if not data:
        raise Refused("empty-file")
    if len(data) > MAX_UPLOAD:
        raise Refused("too-large", str(len(data)))

    base = folder(slug)
    path = base / clean
    replaced = path.is_file()
    try:
        base.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        # A full disk, a read-only mount, or a name Windows reserves whatever the
        # extension. The operator gets told which file and what the OS said.
        raise Refused("write-failed", str(exc)) from exc
    return path, replaced


# Where a removed document goes. Moved aside rather than deleted, the same answer
# `company.trash` gives for a company: the operator's files are not ours to
# destroy, and a misread row should be recoverable. Dot-prefixed so `load` walks
# past it — which is a property this module only actually had once the walk
# started testing every segment of a path instead of the file name alone.
TRASH = ".trash"


def remove(slug: str, rel: str) -> Path:
    """Move one document out of the folder, and say where it went.

    An upload surface with no way back is a folder that only grows. The path
    arrives in a request body, so it is resolved and checked against the folder
    rather than trusted for having come from our own page a moment earlier.
    """
    base = folder(slug).resolve()
    target = (base / str(rel or "")).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise Refused("outside") from None
    if target == base or not target.is_file():
        raise Refused("no-such-document")

    dest_dir = base / TRASH
    stamp = int(time.time())
    dest = dest_dir / f"{target.stem}-{stamp}{target.suffix}"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        os.replace(target, dest)
    except OSError as exc:
        raise Refused("write-failed", str(exc)) from exc
    return dest


# How many documents the console is handed at once. A folder is a folder and
# somebody will put four hundred files in one; extracting all of them for a
# single card is work nobody asked for. The real count travels with the payload,
# because a list that stops at sixty while claiming to be everything is the
# truncation this project keeps finding and refusing.
INVENTORY_MAX = 60


def inventory(slug: str, budget: int = CONTEXT_BUDGET) -> dict:
    """Every document, and whether an agent actually sees it.

    The folder worked and nothing showed it. A brief the design agent wrote on
    Monday was on disk, was in context, and was invisible to the person paying
    for it — the same shape as the four deliverables that used to be cut to a
    log line, one floor up.

    The number that matters here is not how many files exist, it is how many
    reach a prompt. `context` stops at the budget, so a company holding twelve
    documents can be feeding two of them to its agents while the other ten sit
    there looking like knowledge. Nothing said so before this.

    Not for a polled path: it opens and extracts every file it lists.
    """
    docs = load(slug)
    readable = [d for d in docs if d.kind == "text" and d.text]
    chosen, used = _selected(readable, budget)
    reaching = {d.path for d in chosen}
    base = folder(slug)

    listed = []
    for doc in docs[:INVENTORY_MAX]:
        entry = doc.as_dict()
        entry["path"] = doc.label
        # Provenance from the path, which is why `write` puts its output in a
        # subfolder rather than dropping it in beside the operator's files.
        entry["written"] = WRITTEN in doc.label.split("/")
        entry["reaches"] = doc.path in reaching
        entry["text"] = doc.text
        if doc.kind == "text" and not entry["reaches"]:
            # Readable, on file, and past the budget. The one state the product
            # had no way of saying out loud.
            entry["reason"] = "budget"
        elif doc.kind == "text" and not entry["reason"]:
            entry["reason"] = "prompt"
        try:
            entry["mtime"] = doc.path.stat().st_mtime
        except OSError:
            # Deleted between the walk and here. A missing timestamp is not a
            # reason to fail the whole card.
            entry["mtime"] = None
        listed.append(entry)

    return {
        "folder": str(base),
        "documents": listed,
        "total": len(docs),
        "reaching": len(chosen),
        "budget": budget,
        "used": used,
        # What the drop zone may accept, from the one place that decides it. The
        # page states these limits to the operator before they drag a file, and a
        # second copy of them in the HTML would be a promise the server breaks.
        "accepts": sorted(UPLOAD_SUFFIXES),
        "max_upload": MAX_UPLOAD,
    }
