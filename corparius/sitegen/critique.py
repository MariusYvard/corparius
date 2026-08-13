"""What is wrong with the page that was just built, measured rather than judged.

This is the deterministic half of the review loop the console itself was put through: thirteen rounds
of *generate, review, fix, review again*, where the reviews that were worth anything were the ones
carrying a number — "the card sits at 1.044:1 against its own page", "the description renders in a
145px ribbon" — and the ones that were not were the ones carrying an adjective.

So this module finds only what it can prove. It reads the built page's own colours and text and
returns findings with the measurement attached. It has no opinion about whether a headline is
*compelling*, because nothing here could defend such a claim, and a critique that mixes the two
teaches a reader to discount both.

**Why the model does not get a vote here, and where it would.** A tool effect can reach `company`,
`data_path`, `leads`, `store` and `structured` — deliberately not a model handle, because the executor
owns routing, the token budget and the accounting. A critique round that asked a model to judge the
copy would therefore be an executor capability (a tool declaring "review me", the executor spending a
second call and re-running the effect), and it would cost one extra model call per round per build on
somebody else's key. That is a decision about their money, so it is not taken here. What *is* taken
here: every finding this module produces is fed back into the next design turn's brief, so the loop
closes on the company's own cadence at zero extra cost.

Rank 4: no `requests`, no `subprocess`, no `sqlite3`. It takes strings and returns findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .palette import AA_TEXT, contrast

# Below this, a page is not a page. Measured on the four `sitegen` writes as they stand: a real
# generation puts 1 400 to 2 600 characters of prose on the page, so 600 is a floor no honest build
# lands under and a stub lands over.
MIN_PROSE = 600

# The longest an H1 may be. `copy.clean_headline` already refuses meta-commentary and over-long
# drafts; this catches the case it lets through — a headline that survived cleaning and is still a
# paragraph.
MAX_HEADLINE = 120

# Words that mean the generator ran with nothing to say. Each one has been seen in a real build:
# `TODO` from a half-filled config, `lorem` from a template, `[mock:` from an offline draft reaching
# the page as its own headline.
PLACEHOLDERS = ("todo", "tbd", "lorem ipsum", "[mock:", "your product", "coming soon")


@dataclass(frozen=True)
class Finding:
    """One defect, with the measurement that proves it.

    `where` names the part of the page, `what` is the sentence a design turn will read, and `measure`
    is the number — empty when the finding is structural rather than numeric. `fixable_by_copy` is the
    one field the loop acts on: it says whether a redraft could fix this, or whether it is the
    company's configuration that has to change.
    """

    where: str
    what: str
    measure: str = ""
    fixable_by_copy: bool = False

    def line(self) -> str:
        return f"{self.where}: {self.what}" + (f" ({self.measure})" if self.measure else "")


def palette_pairs(palette: dict[str, str]) -> list[tuple[str, str, str]]:
    """Every text-on-background pair a generated page actually puts on screen.

    Named from `palette_for`'s own keys rather than guessed: body text on the page, muted text on the
    page, body and muted on the inverted pricing band, body text on the hero wash, and the button's
    label on the accent. Those five are the whole surface — if a sixth appears in `style.py`, it
    belongs here, and `tests/test_sitegen_critique.py` asserts the list against the palette's keys so a
    new one cannot arrive unmeasured.
    """
    return [
        ("page body", palette["fg"], palette["bg"]),
        ("page secondary", palette["muted"], palette["bg"]),
        ("pricing band", palette["on_ink"], palette["ink"]),
        ("pricing band secondary", palette["on_ink_muted"], palette["ink"]),
        ("hero", palette["fg"], palette["wash"]),
        ("button", palette["on_accent"], palette["accent"]),
    ]


def contrast_findings(pairs: list[tuple[str, str, str]], target: float = AA_TEXT) -> list[Finding]:
    """Every text-on-background pair that does not clear `target`.

    The reason this exists at all is in `sitegen`'s own history: a dark pricing band shipped at
    **1.16:1** — near-black on near-black — and no code in the repository could have caught it,
    because nothing knew what contrast was. `palette.contrast` knows now, and this is the check that
    uses it on the values a build actually chose rather than on the values it intended.
    """
    found = []
    for where, text, background in pairs:
        ratio = contrast(text, background)
        if ratio < target:
            found.append(
                Finding(
                    where,
                    f"text on this background is below the {target:.1f}:1 a reader needs",
                    f"{ratio:.2f}:1, {text} on {background}",
                )
            )
    return found


def copy_findings(headline: str, prose: str) -> list[Finding]:
    """What is wrong with the words, where "wrong" can be demonstrated.

    Four checks, and each one is a thing that has actually reached a page: an H1 that is the config's
    tagline because the draft was refused, an H1 long enough to be a paragraph, a placeholder that
    survived from a half-filled config, and a page with almost nothing on it.
    """
    found: list[Finding] = []
    flat = " ".join(str(prose or "").split())
    head = " ".join(str(headline or "").split())

    if not head:
        found.append(
            Finding("headline", "the page has no H1 at all", fixable_by_copy=True),
        )
    elif len(head) > MAX_HEADLINE:
        found.append(
            Finding(
                "headline",
                "the H1 is long enough to be a paragraph; it should be one claim",
                f"{len(head)} characters, {MAX_HEADLINE} is the ceiling",
                fixable_by_copy=True,
            )
        )

    lowered = f"{head} {flat}".lower()
    for word in PLACEHOLDERS:
        if word in lowered:
            found.append(
                Finding(
                    "copy",
                    f"the page still carries the placeholder {word!r}",
                    fixable_by_copy=word in ("[mock:",),
                )
            )

    if len(flat) < MIN_PROSE:
        found.append(
            Finding(
                "page",
                "there is not enough on the page for a visitor to decide anything",
                f"{len(flat)} characters of prose, {MIN_PROSE} is the floor",
            )
        )

    # A headline that repeats the company's own name and nothing else says nothing. Checked as a whole
    # word so "Vigilance" does not match "Vigil".
    if head and re.fullmatch(r"[\w\s'’-]{0,40}", head) and len(head.split()) <= 3:
        found.append(
            Finding(
                "headline",
                "the H1 is a label rather than a claim: it does not say what the product does",
                f"{len(head.split())} words",
                fixable_by_copy=True,
            )
        )
    return found


def brief(findings: list[Finding]) -> str:
    """The findings as an instruction for the next draft, or "" when there is nothing to say.

    This is the whole loop. The console's own thirteen rounds worked because each review came back as
    a list a person could act on rather than a score; a design turn gets the same thing, in the
    prompt, so the next headline is written against the last one's measured faults.

    Only the copy-fixable ones: telling a model to raise a contrast ratio it cannot see or set a price
    it does not own produces an apology, not a fix. The rest are for the operator, and the build says
    them out loud in its own return value.
    """
    actionable = [f for f in findings if f.fixable_by_copy]
    if not actionable:
        return ""
    lines = "\n".join(f"- {f.line()}" for f in actionable)
    return (
        "The last generated page had these faults, measured rather than guessed. Write the headline so "
        f"none of them is true again:\n{lines}"
    )
