"""A table of contents over the company's files, and the sections a particular turn should read.

## The defect this exists for

`documents.context(slug)` takes the **newest documents whole** until 6 000 characters are gone, and
`orchestrator` builds that block **once per tick** with no query — so every agent in a tick receives
the same prefix, chosen by modification time. Two consequences, both measured on the real corpus:

* a design agent building a sales page and a finance agent reviewing spend read the identical 6 000
  characters, because nothing about the block knows what either is about to do;
* a long document dropped last month is **invisible**. Not truncated — invisible. Nothing in the
  prompt says it exists, so no agent can ask for it and no operator can tell it was skipped.

The second is the sharper one. The Documents tab already says "anything past it is on disk and
nothing reads it", which is honest and is also an admission that the retrieval is a `head -c 6000`.

And the inconsistency sits inside a single function: `agents._recall` ranks *memory* against
`tool.draft_prompt(ctx)`, four lines above the document block that ignores it entirely.

## What this does instead, and where the idea comes from

PageIndex (github.com/VectifyAI/PageIndex) makes the case better than a paraphrase would: build a
table of contents over a document, then let the model reason down the tree, rather than embedding
chunks and hoping similarity means relevance. Read end to end before writing this — and **not
vendored**, for two reasons that are about this codebase rather than about that one:

* it needs nine runtime dependencies (`litellm`, `openai`, `PyPDF2`, `pypdfium2`, `python-dotenv`,
  `regex`, `sortedcontainers`, …) against this project's two, and the two-dependency rule is what
  makes installing corparius trivial and auditing it possible;
* its retrieval is **agentic** — `browse_documents` then `get_document_structure` then
  `get_page_content`, 2–4 model calls per question. A tool effect here gets **one** draft call and
  cannot loop, so that shape would need a new executor capability, not a new module.

What is worth taking is the part that needs neither: **structure first, content second**. A heading
tree is cheap, deterministic, and dependency-free — PageIndex's own markdown path is a regex over
`^#{1,6}\\s+` and a stack. So:

1. every document contributes its **headings** to the prompt, always, whatever the budget. A map of
   the whole corpus costs a few hundred characters and ends the invisibility;
2. the remaining budget buys the **sections that match this turn**, ranked by the same
   `kernel.vectors` cosine that already ranks memory — one machinery, two corpora.

Zero new dependencies and zero extra model calls: the ranking is arithmetic over a bag of tokens, and
`store.recall`'s docstring already argues why that is the right instrument for a whole prompt as the
query rather than for keywords.

Rank 4. Pure text in, pure text out — no disk, no network, no store.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .kernel.vectors import cosine, hash_embed

# What counts as a heading. High precision on purpose: a false heading splits a paragraph in half and
# puts a sentence fragment in front of a model as though it were a titled section.
#
#   `## Pricing`            markdown, the agents' own writing
#   `**Pricing**`           a bold line alone, which is how extracted DOCX marks a heading
#   `3.1 Pricing`           a numbered heading, which is how most PDFs mark one
#
# Deliberately **not** "a short line in capitals": on the real corpus that matched table headers,
# addresses and the word IMPORTANT inside body text. A missed heading costs a section boundary; an
# invented one costs the reader's trust in every boundary.
_MARKDOWN = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*$")
_BOLD = re.compile(r"^\*\*(\S.{0,78}?)\*\*:?$")
_NUMBERED = re.compile(r"^((?:\d+\.){1,3}\d*)\s+(\S.{0,78}?)$")
_FENCE = re.compile(r"^\s*(```|~~~)")


# A section with no body is a heading and nothing else — a running header, a page number, a title
# above a title. It belongs on the map, because it is structure; there is simply no text to quote.
#
# **This was a character threshold and that was wrong, twice.** It started at "a titled section under
# 40 characters is not worth the budget", which sounds reasonable and quietly dropped real content:
# first a whole file whose text was 26 characters ("Founder price is nine euro"), then an agent's own
# note under its `# Weekly review` heading. Both were caught by tests, and the second one only because
# the first fix — exempting the untitled lead — did not go far enough.
#
# The honest rule has no number in it. A short section is cheap by definition, so the only thing worth
# excluding is a section with nothing in it at all.
def _worth_quoting(section: Section) -> bool:
    """Whether a section has a body to quote. Structure without text goes on the map, not in it."""
    return bool(section.text.strip())


# Said out loud when the corpus outgrows the prompt, and counted against the budget rather than added
# after it.
_TRUNCATED = "\n  … map truncated"

# 256, and it was measured rather than chosen. `hash_embed` defaults to 64 dimensions, which is ample
# for what it was written for — catching an agent repeating itself, where the two texts are long and
# nearly identical. Sections are short, and at 64 buckets they collide: on a seven-question labelled
# set over a realistic corpus, accuracy@1 was **2/7 at dim 64 and 5/7 at dim 256**. Above 256 nothing
# improves (1024 and 4096 both measured 5/7), because what is left is not collision but the
# bag-of-tokens model itself.
#
# Where it stands: **recall@3 is 6/7**, and the score spread on a single query runs 0.283 to 0.000 —
# it selects rather than shuffles, which is the same property `tests/test_memory_store.py` pins for
# `store.recall`. The one miss is honest and worth naming: "what time should cold emails go out"
# does not retrieve a section reading "replies stop entirely for messages sent before nine in the
# morning", because the two share no tokens. A bag of words cannot bridge that, and pretending
# otherwise is what the FTS5 measurement in `store.recall` already refused to do.
#
# **That miss is the argument for the map.** The model still sees that a section called `Outreach`
# exists, so it can say "the outreach notes would answer this" instead of inventing an answer. The
# ranking finds what it can; the table of contents covers what it cannot.
#
# **IDF weighting was tried and is not here.** The obvious complaint about counting a bag of tokens is
# that "a" and "the" weigh as much as "seat", and the obvious fix is to weight each token by
# log(N/df) over the sections — corpus-derived, so no hand-kept stop list, which is the thing the
# FTS5 measurement in `store.recall` refused. Measured on the same labelled set: **accuracy@1 5/7 and
# recall@3 6/7, identical to plain counts.** It buys nothing here, because doubling the title already
# does the work IDF would have done and the sections are short enough that stop words wash out
# symmetrically. Written down so the next person tempted by it can skip the experiment rather than
# repeat it.
EMBED_DIM = 256


@dataclass(frozen=True)
class Section:
    """One heading and the text under it, up to the next heading of any level."""

    doc: str
    title: str
    level: int
    text: str
    line: int

    @property
    def label(self) -> str:
        """How this section is named in a prompt, and in the console."""
        return f"{self.doc} › {self.title}" if self.title else self.doc


def outline(text: str, doc: str = "") -> list[Section]:
    """The heading tree of one document, flattened in reading order.

    Flat rather than nested, and that is a decision rather than a shortcut: what a prompt needs is
    "this section, and where it sits", which `level` already carries. A nested structure would have to
    be walked and re-flattened by every caller, and the one thing a tree buys — descending it a level
    at a time — is exactly the agentic loop a tool effect here cannot run.

    The text before the first heading is a section too, with an empty title. Losing it would drop the
    opening of every document that leads with a paragraph, which is most of them.
    """
    lines = text.split("\n")
    marks: list[tuple[int, int, str]] = []  # (line index, level, title)
    fenced = False
    for index, raw in enumerate(lines):
        if _FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced:
            # A `# comment` inside a code block is not a heading, and the agents write code blocks.
            continue
        line = raw.strip()
        if not line:
            continue
        if found := _MARKDOWN.match(line):
            marks.append((index, len(found.group(1)), found.group(2)))
        elif found := _BOLD.match(line):
            marks.append((index, 1, found.group(1)))
        elif found := _NUMBERED.match(line):
            marks.append((index, found.group(1).count(".") + 1, found.group(2)))

    bounds = [(0, 0, "")] + marks if not marks or marks[0][0] > 0 else marks
    out: list[Section] = []
    for position, (start, level, title) in enumerate(bounds):
        end = bounds[position + 1][0] if position + 1 < len(bounds) else len(lines)
        body = "\n".join(lines[start + (1 if title else 0) : end]).strip()
        if not title and not body:
            continue
        out.append(Section(doc=doc, title=title, level=level, text=body, line=start + 1))
    return out


def toc(sections: list[Section], per_doc: int = 12) -> str:
    """The map: every document and its headings, indented by level.

    `per_doc` bounds a pathological file rather than the corpus — a 200-heading contract would
    otherwise spend the whole budget on its own table of contents and leave nothing for anyone else's.
    What is cut is said out loud, because a silently shortened map is the invisibility this module
    exists to end, one level up.
    """
    lines: list[str] = []
    for doc in dict.fromkeys(s.doc for s in sections):
        titled = [s for s in sections if s.doc == doc and s.title]
        lines.append(doc)
        for section in titled[:per_doc]:
            lines.append(f"{'  ' * min(section.level, 4)}- {section.title}")
        if len(titled) > per_doc:
            lines.append(f"  … {len(titled) - per_doc} more sections")
        if not titled:
            lines.append("  (no headings)")
    return "\n".join(lines)


def rank(sections: list[Section], query: str, limit: int = 6) -> list[Section]:
    """The sections worth putting in front of *this* prompt, best first.

    The same instrument as `store.recall`: cosine over `kernel.vectors.hash_embed`, a bag of tokens,
    against the whole prompt rather than against extracted keywords. `store.recall`'s docstring holds
    the measurement that settled it — FinanceBench-style keyword matching under-fills the top k on
    real prompts, and there is no labelled data here to say a different ranking would be better.

    The title is weighted by being scored twice: a section called "Pricing" should beat one that
    happens to say the word once in a footnote, and doubling the title is the cheapest way to say so
    without inventing a second similarity.
    """
    if not query.strip():
        return []
    target = hash_embed(query, EMBED_DIM)
    scored = [
        (cosine(target, hash_embed(f"{s.title} {s.title} {s.text}", EMBED_DIM)), index, s)
        # `index` breaks ties by reading order, so the same corpus and the same prompt always produce
        # the same block — a prompt that changes between identical turns is a cache that never hits.
        for index, s in enumerate(sections)
        if _worth_quoting(s)
    ]
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [s for _score, _index, s in scored[:limit]]


def select(
    sections: list[Section], query: str, budget: int, overhead: int = 0
) -> tuple[str, list[Section]]:
    """What this turn should read: the map, and the sections to quote under it.

    Returns the two apart rather than one rendered string, and that is a security decision rather
    than a style one. **Each section is fenced individually by the caller, with its `--- label ---`
    outside the fence.** The first version returned one block and `documents.context` wrapped the
    whole thing in a single fence, which loses a property the per-file form had:
    `tests/test_untrusted_blocks.py` calls it "one fence per file, not one for the block", and the
    reason is that a header outside a fence cannot be forged from inside one. Under a single fence a
    supplier's price list could write `--- pricing.md › Discounts ---` into its own body and attribute
    its text to another document.

    `documents` owns the markers and the sentence that explains them, so `documents` does the
    fencing; this decides only what goes in. `overhead` is what the caller's rendering costs per
    section — the header, the two markers, the separators — so the budget it is given is the budget
    that comes back.

    **The map is paid first, in full.** An earlier version gave it a share of the budget — 35% — and a
    tight-budget test caught what that does: the map was truncated to fit its share *and* a body was
    admitted with the room freed, so three documents fell off the map to make space for one section of
    a fourth. That is exactly the invisibility this module exists to end, restored by the arithmetic
    meant to prevent it. Only if the map alone exceeds the whole budget is it cut, and then it says so.
    """
    if not sections:
        return "", []
    head = toc(sections)
    if len(head) > budget:
        # The suffix is part of the result, so it comes out of the allowance *before* the cut. Cutting
        # to `budget` and then appending is how a 120-character ceiling returned 132 characters — the
        # second time this arithmetic was wrong, and the reason the invariant is its own test rather
        # than something checked by hand after each edit.
        head = head[: max(0, budget - len(_TRUNCATED))].rsplit("\n", 1)[0] + _TRUNCATED
        head = head[:budget]
    room = max(0, budget - len(head))

    # With nothing to rank against, reading order. Not "no bodies": a caller without a prompt — the
    # console's own read, a plugin's, a tool whose draft prompt could not be built — should still get
    # as much of the corpus as the budget holds, and the first sections of a document are the ones
    # that say what it is. This is what makes the index the *only* retrieval rather than an
    # alternative to the recency block it replaced, which matters more than it sounds: while both
    # existed, `inventory` reported the map's answer and `context` returned recency's, so the console
    # marked a document as reaching the agents while the prompt left it out.
    chosen = (
        rank(sections, query, limit=12)
        if query.strip()
        else [s for s in sections if _worth_quoting(s)]
    )

    keep: list[Section] = []
    used = 0
    for section in chosen:
        cost = len(section.label) + len(section.text) + overhead
        if used + cost > room:
            continue
        used += cost
        keep.append(section)
    return head, keep
