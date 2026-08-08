"""Naming the tools a skill applies to. Rank 5.

The fix for the most expensive skill mistake there is, and it was console-only. An unscoped
skill — one with no `allowed-tools` — lands in **every prompt of every agent, every turn**. On
the owner's own company `promesse-clinique` was 3 815 characters riding on every call, forever.

`corparius skills list` already *reported* it: it prints `EVERY TOOL` next to the skill and
totals the characters that ride everywhere. So a terminal could tell an operator exactly what it
was costing them and offer nothing to do about it, which is a worse shape than not knowing. The
only fix was the console's skills panel, or finding the file and hand-editing YAML.

`skills.scope_to` does the work and returns an error string; this raises it as a `Refused`
instead, so the console can turn it into a 400 and a terminal can print it. Only the frontmatter
is rewritten — the body is the operator's prose and goes back byte for byte.
"""

from __future__ import annotations

from .. import skills as skills_mod
from .errors import Refused


def scope(slug: str, name: str, tools: list[str], settings) -> dict:
    """Write `allowed-tools` onto one skill. Returns what it named.

    Refuses a tool that does not exist, because a skill scoped to a name nobody has never
    applies — silently, which is worse than the tax it was meant to fix. Refuses an empty list
    for the same reason stated the other way: naming nothing leaves the skill on every prompt,
    so accepting it would look like a fix and be none.
    """
    if not getattr(settings, "skills_enabled", True):
        raise Refused("skills are off (CORP_SKILLS_ENABLED=false)")
    name = str(name).strip()
    loader = skills_mod.SkillLoader.for_company(
        slug or "", max_chars=getattr(settings, "skill_max_chars", None)
    )
    skill = next((sk for sk in loader.skills if sk.name == name), None)
    if skill is None:
        known = ", ".join(sorted(sk.name for sk in loader.skills)) or "none"
        raise Refused(f"no skill named {name!r}. Known: {known}")
    clean = [str(t).strip() for t in tools if str(t).strip()]
    error = skills_mod.scope_to(skill.path, clean)
    if error:
        raise Refused(error)
    return {"name": name, "tools": clean, "path": str(skill.path), "scope": skill.scope}


def unscoped(slug: str, settings) -> list[dict]:
    """The skills that ride every prompt, and what each one costs.

    Split out so a caller can ask "what is this costing me" without being the console's skills
    panel. `always_on_chars()` is the total; this is the breakdown, which is what an operator
    needs in order to decide *which* one to scope first.
    """
    loader = skills_mod.SkillLoader.for_company(
        slug or "", max_chars=getattr(settings, "skill_max_chars", None)
    )
    return [
        {"name": sk.name, "chars": len(sk.instructions), "declared": sk.always, "scope": sk.scope}
        for sk in loader.skills
        if sk.unscoped
    ]
