"""Skills: what a company knows, written in prose.

Plugins already extend corparius, but they extend it with *code* — seven Python
seams, an allow-list, a SHA-256 check. A micro-company produces something else
from its first day: how its own outreach is worded, which objection its market
actually raises, the tone its founder wants. None of that is code, and asking
for a Python package to carry it is asking for it not to be written down.

A skill is a folder holding a SKILL.md: YAML frontmatter naming it, describing
it, and listing the tools it applies to, then a body of instructions.

The loading rule is where this departs from OpenWorker's skills/base.py, which
it is otherwise modelled on (see docs/reverse-engineering/openworker.md). There,
a catalogue of names and descriptions is injected and the agent calls a
`load_skill` tool when it judges one relevant. Corparius has no tool-calling
loop and does not want one, so relevance is decided by the code: a skill is in
scope when the tool about to run is named in its `allowed-tools`.

That makes the catalogue itself unnecessary in the prompt — the model has no way
to ask for a skill it was not given, so listing the others would be tokens spent
on an offer nothing can take up. It is still built, for the console. The result
is cheaper than progressive disclosure, not merely as cheap: a turn pays for the
skills that apply to it and for nothing else.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("corparius.skills")

FRONTMATTER = "---"
DEFAULT_MAX_CHARS = 4000

# Directories contributed by plugins through PluginAPI.register_skill_dir.
# Searched before the operator's own, so a company skill of the same name still
# replaces a packaged one: the person running the business gets the last word.
EXTRA_DIRS: list[str] = []


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    instructions: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    scope: str = "global"  # global | <company slug>, for display only

    def applies_to(self, tool_name: str) -> bool:
        """No `allowed-tools` means the skill is background knowledge about the
        company rather than instructions for one job, so it applies to every
        tool. Listing tools narrows it."""
        return not self.allowed_tools or tool_name in self.allowed_tools

    @property
    def unscoped(self) -> bool:
        """Applies to every tool of every agent. Legitimate for a short note
        about the company, and a mistake for a long document — which is exactly
        what a skill written for another host looks like when dropped in here.
        Nothing showed this, so it failed silently in the direction that costs
        the most: every prompt, every turn."""
        return not self.allowed_tools


def _split(text: str) -> tuple[str, str]:
    """(frontmatter, body). A file with no frontmatter is all body, which keeps
    a hand-written note usable before its author has read any of this."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER:
        return "", text
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER:
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    return "", text


def parse(path: Path, scope: str = "global") -> Skill | None:
    """Never raises. A malformed skill is skipped with a warning, exactly as a
    plugin that fails to import is: one bad file in a folder must not stop a
    company from running."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("cannot read %s: %s", path, exc)
        return None
    head, body = _split(raw)
    meta: dict = {}
    if head.strip():
        try:
            loaded = yaml.safe_load(head)
            meta = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError as exc:
            log.warning("%s has invalid frontmatter, skipped: %s", path, exc)
            return None
    name = str(meta.get("name", "") or path.parent.name).strip()
    if not name:
        return None
    tools_in = meta.get("allowed-tools", meta.get("allowed_tools", ""))
    if isinstance(tools_in, str):
        tools = [t.strip() for t in tools_in.split(",") if t.strip()]
    elif isinstance(tools_in, list):
        tools = [str(t).strip() for t in tools_in if str(t).strip()]
    else:
        tools = []
    return Skill(
        name=name,
        description=str(meta.get("description", "")).strip(),
        path=path,
        instructions=body.strip(),
        allowed_tools=tools,
        scope=scope,
    )


class SkillLoader:
    """Discovery happens once, at construction, and reads the files whole.

    A loader is built per run, not per turn, and these are notes an operator
    typed by hand; the alternative — reading frontmatter now and bodies later —
    would buy a few kilobytes at the cost of a file that can change out from
    under a run halfway through."""

    def __init__(self, dirs: list[tuple[Path, str]] | None = None, max_chars: int | None = None):
        self.max_chars = DEFAULT_MAX_CHARS if max_chars is None else max_chars
        self.skills: list[Skill] = []
        for directory, scope in dirs or []:
            self._discover(Path(directory), scope)

    @classmethod
    def for_company(cls, slug: str, max_chars: int | None = None) -> SkillLoader:
        from . import paths

        dirs: list[tuple[Path, str]] = [(Path(d), "plugin") for d in EXTRA_DIRS]
        dirs.append((paths.skills_dir(), "global"))
        dirs.append((paths.company_skills_dir(slug), slug or "company"))
        return cls(dirs, max_chars=max_chars)

    def _discover(self, directory: Path, scope: str) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*/SKILL.md")):
            skill = parse(path, scope)
            if skill is None:
                continue
            # A company skill of the same name replaces the global one rather
            # than stacking with it: two sets of instructions for the same job,
            # both in context, is how a model gets told to do opposite things.
            self.skills = [s for s in self.skills if s.name != skill.name]
            self.skills.append(skill)

    def catalog(self) -> list[dict]:
        return [
            {"name": s.name, "description": s.description, "scope": s.scope} for s in self.skills
        ]

    def always_on_chars(self) -> int:
        """How many characters ride on *every* prompt, whatever the tool. This
        is the number that matters and the one nothing displayed: a folder of
        unscoped skills is a permanent tax on the token budget."""
        return sum(len(s.instructions) for s in self.skills if s.unscoped)

    def warnings(self) -> list[dict]:
        """What the operator would want to know before wondering why their
        budget went. Returned as data rather than logged, so the doctor and the
        console say the same thing."""
        out: list[dict] = []
        for skill in self.skills:
            if skill.unscoped:
                out.append(
                    {
                        "skill": skill.name,
                        "kind": "unscoped",
                        "chars": len(skill.instructions),
                    }
                )
            if len(skill.instructions) > self.max_chars:
                out.append(
                    {
                        "skill": skill.name,
                        "kind": "truncated",
                        "chars": len(skill.instructions),
                        "cap": self.max_chars,
                    }
                )
        return out

    def for_tool(self, tool_name: str) -> list[Skill]:
        return [s for s in self.skills if s.applies_to(tool_name)]

    def context_for(self, tool_name: str) -> str:
        """The block injected into the agent's prompt, or "" when the company
        has written no skills — which is the default, and must cost nothing."""
        applicable = self.for_tool(tool_name)
        if not applicable:
            return ""
        parts = []
        budget = self.max_chars
        for skill in applicable:
            body = skill.instructions
            if not body:
                continue
            if len(body) > budget:
                # Truncated rather than dropped: the opening of a skill is where
                # its author puts the rule that matters. Cut mid-sentence and
                # say so, instead of silently sending half a page as if whole.
                body = body[: max(0, budget)].rstrip() + "\n[truncated]"
            budget -= len(body)
            parts.append(f"## {skill.name}\n{body}")
            if budget <= 0:
                break
        return "\n\n".join(parts)
