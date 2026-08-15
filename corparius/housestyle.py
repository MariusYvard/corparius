"""The company's editorial rules, and the half of them a machine can enforce. Rank 4, pure.

Text and a rule set in, violations and a corrected text out. No model, no store, no disk. That is
what lets the rules be measured in a unit test instead of behind a fixture, the same argument
`docindex` makes for itself.

## Why any of this is code rather than a line in a prompt

An editorial charter splits into two halves that do not behave alike.

One half is judgment: encyclopedic rather than promotional, no closing paragraph about legacy and
impact, vary the length of a list instead of always writing three things. A model is the only thing
that can apply those, so they belong in the prompt.

The other half is mechanical: a character that must not appear, a phrase that is banned, a comma
before the final "and". Asking a model to obey those makes them advisory. A model that emits an em
dash once in ten generations is caught by nobody, and the violation reaches a published page. This
codebase already has a name for a guard that does not run.

So the mechanical half is checked here, and the checking is not a matter of opinion.

## Fix, or only report

A rule declares its own answer, and most of them cannot fix anything.

Curly quotation marks become straight ones by substitution, with no reading required. That is the
whole set of safe fixes, and it is deliberately small: replacing an em dash needs the sentence, since
it becomes a comma, a colon or a pair of brackets depending on what follows it, and a banned word
needs a rewrite rather than a synonym. Those are reported and left alone. A checker that guessed
would be a checker that quietly changes what an agent meant.

## Whose rules

`DEFAULT` is what corparius ships. It is a starting point and not a position: a company writing for a
market that wants warmth should not be told by its own tooling that "crucial" is banned. An operator
replaces the set, and `style.load` reads theirs when there is one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import yaml

from .kernel import paths

log = logging.getLogger("corparius.housestyle")


@dataclass(frozen=True)
class Rule:
    """One editorial rule that a machine can check.

    `find` is a regular expression. `fix` is a replacement when the correction needs no reading of
    the sentence, and empty when it does: the checker reports those and changes nothing, because a
    guess about what an author meant is worse than the violation.
    """

    name: str
    find: str
    why: str
    fix: str | None = None

    def hits(self, text: str) -> list[tuple[int, str]]:
        """Every violation, as (offset, the text that violates). Offsets so a caller can point."""
        return [(m.start(), m.group(0)) for m in re.finditer(self.find, text)]


@dataclass
class Style:
    """A charter: prose for the model, rules for the checker."""

    voice: str = ""
    rules: list[Rule] = field(default_factory=list)


# The set corparius ships. Each rule names the thing it forbids rather than a category, so a report
# reads as a sentence and an operator can delete the one they disagree with.
DEFAULT_RULES: list[Rule] = [
    Rule(
        "em-dash",
        r"[—–]",
        "an em or en dash: use brackets or commas",
        # No fix on purpose. It becomes a comma when the clause merely continues, a colon when the
        # second half explains the first, and brackets when it is an aside. Only the sentence knows.
    ),
    Rule(
        "curly-quote",
        r"[“”‘’]",
        "a curly quotation mark: use straight ones",
        fix="STRAIGHT",  # resolved per character below; see `apply`
    ),
    Rule(
        "oxford-comma",
        r",\s+(?:and|or|et|ou)\s+\S",
        "a comma before the final conjunction",
        # Reported, not fixed: `, and` also introduces a genuine second clause ("she left, and it
        # rained"), and stripping that comma changes the sentence rather than its punctuation.
    ),
    Rule(
        "presents-itself-as",
        r"\b(?:se pr[ée]sente comme|positions itself as|stands as)\b",
        "a verb standing in for `is`",
    ),
    Rule(
        "puffery",
        r"\b(?:pivotal|crucial|cruciale?|embl[ée]matique|emblematic|incontournables?|"
        r"visionnaire|r[ée]volutionnaire|revolutionary|game.?chang\w+)\b",
        "a promotional adjective",
    ),
    Rule(
        "landscape",
        r"(?:fa[çc]onner le paysage|shape[sd]? the landscape|riche tapisserie|rich tapestry|"
        r"t[ée]moigne de|testifies to|souligne l|underscores the|refl[èe]te l)",
        "a stock phrase that says nothing",
    ),
]

# Straight equivalents, one per character the curly-quote rule matches.
_STRAIGHT = {"“": '"', "”": '"', "‘": "'", "’": "'"}

DEFAULT_VOICE = (
    "Write plainly. Neutral and factual, never promotional. State a precise fact or say nothing. "
    "No preamble about what you are about to write and no closing paragraph about impact, legacy "
    "or the future. Prefer `is` to `presents itself as`. Vary how many things you list: not always "
    "three. Straight quotation marks and apostrophes. No em dashes; use brackets or commas."
)

DEFAULT = Style(voice=DEFAULT_VOICE, rules=DEFAULT_RULES)


def check(text: str, style: Style | None = None) -> list[dict]:
    """Every violation in `text`, as data.

    Data rather than a formatted string because two callers want it: one records it beside the
    action, one puts it in front of a model. A sentence would make the second one parse prose.
    """
    style = style or DEFAULT
    found: list[dict] = []
    for rule in style.rules:
        for where, what in rule.hits(text or ""):
            found.append(
                {
                    "rule": rule.name,
                    "at": where,
                    "text": what,
                    "why": rule.why,
                    "fixable": bool(rule.fix),
                }
            )
    return sorted(found, key=lambda hit: hit["at"])


def apply(text: str, style: Style | None = None) -> tuple[str, list[dict]]:
    """Fix what can be fixed without reading the sentence; return the rest.

    The returned violations are the ones a person or a model still has to answer for. A caller that
    ignores them has still improved the text; a caller that acts on them is what makes the charter
    real.
    """
    style = style or DEFAULT
    out = text or ""
    for rule in style.rules:
        if not rule.fix:
            continue
        if rule.fix == "STRAIGHT":
            out = "".join(_STRAIGHT.get(ch, ch) for ch in out)
        else:
            out = re.sub(rule.find, rule.fix, out)
    return out, check(out, style)


def instruction(style: Style | None = None) -> str:
    """The charter as one block for a prompt: the voice, then the rules a model should not need to
    be told twice.

    The mechanical rules are stated here as well as checked, which is not duplication. Checking
    catches what a model does; saying it is what stops the model doing it, and the cheapest violation
    is the one that never happened.
    """
    style = style or DEFAULT
    lines = [style.voice.strip()] if style.voice.strip() else []
    if style.rules:
        lines.append("Never: " + "; ".join(rule.why for rule in style.rules) + ".")
    return "\n".join(lines)


# --- whose rules ------------------------------------------------------------------
#
# A charter belongs to a company, not to corparius. `DEFAULT` is a starting point, and an operator
# writing for a market that wants warmth should be able to delete "crucial" from the banned list
# without editing the product.
#
# The file sits beside the other things a company owns (`company.yaml`, `skills/`, `documents/`) and
# has the same property they do: it is read when it is there, and its absence is not an error.

STYLE_FILE = "style.yaml"


def parse(raw: dict) -> Style:
    """A charter from the mapping a YAML file parses to.

    Every field is optional and a broken one is dropped rather than fatal: this is read on the way
    into a prompt, on a file an operator hand-edits, and a run that dies because a rule has no
    pattern would be the charter taking the company down with it.

    `voice: replace` is the one flag that changes shape rather than content. Without it the operator
    is *adding* to the shipped rules, which is what somebody who wrote three lines about tone almost
    always means; with it they get exactly what they wrote and nothing else.
    """
    rules: list[Rule] = []
    for entry in raw.get("rules") or []:
        if not isinstance(entry, dict):
            continue
        find = str(entry.get("find") or "").strip()
        if not find:
            continue
        try:
            re.compile(find)
        except re.error:
            continue
        rules.append(
            Rule(
                name=str(entry.get("name") or find[:24]),
                find=find,
                why=str(entry.get("why") or "against this company's style"),
                fix=str(entry["fix"]) if entry.get("fix") is not None else None,
            )
        )
    voice = str(raw.get("voice") or "").strip()
    if str(raw.get("replace") or "").strip().lower() in ("true", "yes", "1"):
        return Style(voice=voice, rules=rules)
    # Added to the shipped set, and the operator's own rules come first so a report leads with what
    # they cared enough to write down.
    return Style(voice=(voice + "\n" + DEFAULT_VOICE).strip(), rules=rules + DEFAULT_RULES)


def load(slug: str) -> Style:
    """This company's charter, or the shipped one.

    Read on the way into a prompt and on the way out of a draft, so it must never raise: a missing
    file, a broken one, a folder that will not open, all mean "the default", because a charter is a
    preference and a run that dies over a preference has its priorities backwards.
    """
    path = paths.companies_dir() / (slug or "company") / STYLE_FILE
    if not path.is_file():
        return DEFAULT
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        # Said, not swallowed. Falling back to the shipped rules is right (a preference must not
        # take a run down) and doing it in silence is not: an operator who mistyped their charter
        # would watch the agents ignore it with nothing anywhere to explain why. Measured while
        # testing this: a file holding one stray escape parsed to nothing and looked like a charter.
        log.warning("%s: style.yaml could not be read, using the shipped rules (%s)", slug, exc)
        return DEFAULT
    if not isinstance(raw, dict):
        log.warning("%s: style.yaml is not a mapping, using the shipped rules", slug)
        return DEFAULT
    return parse(raw)


def add_rule(slug: str, rule: Rule) -> bool:
    """Write one deterministic rule into this company's charter. False if it was already there.

    **The counterpart to `write_skill`, and the same idea.** An agent that sees the same wording
    corrected three times has learned something a sentence in a prompt cannot hold: a rule. Prose
    tells the next model what to avoid and is re-read from scratch every turn; this is checked, for
    nothing, on every draft forever.

    Idempotent on the pattern, because an agent that files the same rule every day turns a charter
    into a log. And it appends rather than rewrites: the operator's own file is theirs, and a tool
    that reformats it while adding a line is a tool they stop trusting with it.
    """
    path = paths.companies_dir() / (slug or "company") / STYLE_FILE
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.is_file() else {}
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(raw, dict):
        return False
    existing = [r for r in (raw.get("rules") or []) if isinstance(r, dict)]
    if any(str(r.get("find") or "") == rule.find for r in existing):
        return False
    raw["rules"] = existing + [
        {"name": rule.name, "find": rule.find, "why": rule.why}
        | ({"fix": rule.fix} if rule.fix else {})
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    except OSError:
        return False
    return True
