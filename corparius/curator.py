"""Archive the skills the company wrote for itself and nothing reads. Rank 4.

The maintenance half of the learning loop, and it is not optional. Hermes Agent's curator names
the failure mode in its own docstring — without it you get "hundreds of narrow skills where
each one captures one session's specific bug" instead of a library
(docs/reverse-engineering/hermes-agent.md). Here it would be worse than a cluttered folder:
skills go into prompts, so an unread one is not clutter, it is spend. Shipping `write_skill`
without this would have been building a leak next to its own gauge.

**Deterministic, and no model is called.** Hermes has an LLM consolidation pass and ships it
disabled by default; that is the right default and this does not have the pass at all. Merging
two skills is the one operation here that can lose meaning, and nothing about a folder growing
justifies a model rewriting what the company decided.

Four rules, three of them about not touching things:

  * **Only what the company wrote.** An operator's own skill has no `author: corparius` marker
    and is never considered — not stale, not archived, not counted. The person running the
    business keeps the last word by construction, the same promise `EXTRA_DIRS` already makes.
  * **Never deletes.** Archived means moved to `skills/.archive/`, where the loader cannot see
    it (`_discover` globs `*/SKILL.md`, one level) and an operator can.
  * **A skill that has never run gets a grace period.** `write_skill` scopes a skill to the
    tool that failed, and that tool may not come round for weeks. Archiving it for never
    having been used would delete the answer before the question was asked again.
  * **One notice, not one per skill.** Same lesson as `Executor._stood_down`: a warning
    repeated every day is a warning nobody reads.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from . import inbox
from .kernel import paths
from .tools.effects import AGENT_AUTHOR

log = logging.getLogger("corparius.curator")

# Unused for this long and it goes. Thirty days is Hermes' `stale_after_days`, and it is the
# right order of magnitude for a reason that has nothing to do with them: the CEO turn that
# writes these runs twice a day, so thirty days is sixty chances for the tool it is scoped to
# to have come round.
STALE_AFTER_DAYS = 30

# A skill that has never been used at all. Longer than STALE_AFTER_DAYS would be kinder and
# also wrong: a skill scoped to a tool that never runs is exactly the dead weight this exists
# to remove, and thirty days is already sixty CEO turns of nothing.
GRACE_DAYS = 30

ARCHIVE = ".archive"

DAY = 86400.0


def _authored(folder: Path) -> bool:
    """Did the company write this one? Read from the frontmatter, not from the location.

    An operator may well keep their own skills in the same folder, and those are not this
    module's to touch. `parse` ignores the `author` key, so it costs the loader nothing.
    """
    try:
        return (
            f"author: {AGENT_AUTHOR}"
            in (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")[:400]
        )
    except OSError:
        return False


def _age_days(stamp: float, now: float) -> float:
    return max(0.0, (now - stamp) / DAY)


def sweep(store, slug: str, now: float | None = None) -> dict:
    """Archive what nothing reads. Returns what it did, as data.

    A report rather than a log line, for the same reason `SkillLoader.warnings()` returns data:
    the doctor, the console and the CLI all want to say this, and three renderings of one log
    string is how they come to disagree.
    """
    stamp = time.time() if now is None else now
    folder = paths.company_skills_dir(slug)
    report: dict = {"archived": [], "kept": [], "waiting": [], "theirs": 0}
    if not folder.is_dir():
        return report

    try:
        usage = store.skill_usage(slug)
    except Exception:  # noqa: BLE001 - a sweep that cannot read usage must archive nothing
        log.warning("could not read skill usage for %s; archiving nothing", slug)
        return report

    for path in sorted(folder.glob("*/SKILL.md")):
        skill = path.parent
        if not _authored(skill):
            report["theirs"] += 1
            continue
        seen = usage.get(skill.name) or {}
        last = float(seen.get("last_used") or 0.0)
        if last:
            idle = _age_days(last, stamp)
            if idle < STALE_AFTER_DAYS:
                report["kept"].append(skill.name)
                continue
            why = f"unread for {idle:.0f} days"
        else:
            try:
                written = _age_days(skill.stat().st_mtime, stamp)
            except OSError:
                report["kept"].append(skill.name)
                continue
            if written < GRACE_DAYS:
                # Not yet. The tool it is scoped to may not have come round.
                report["waiting"].append(skill.name)
                continue
            why = f"never used in {written:.0f} days"
        if _archive(skill, slug, stamp):
            report["archived"].append({"name": skill.name, "why": why})
            _forget(store, slug, skill.name)

    if report["archived"]:
        _notify(store, slug, report)
    return report


def _archive(skill: Path, slug: str, stamp: float) -> bool:
    """Move, never delete. A name already in the archive gets a suffix rather than clobbering
    what is there: the archive is the operator's record of what their company decided, and two
    versions of one skill are both part of it."""
    destination = paths.company_skills_dir(slug) / ARCHIVE / skill.name
    if destination.exists():
        destination = destination.with_name(f"{skill.name}-{int(stamp)}")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(skill), str(destination))
        return True
    except OSError as exc:
        log.warning("could not archive %s for %s: %s", skill.name, slug, exc)
        return False


def _forget(store, slug: str, name: str) -> None:
    """Drop the usage row with the skill.

    Otherwise a skill written again under the same name inherits a `last_used` from before it
    was archived, and the next sweep archives it immediately — a loop where the company keeps
    answering a question and keeps having the answer taken away.
    """
    try:
        store.forget_skill_use(slug, name)
    except Exception:  # noqa: BLE001 - bookkeeping, and the move already happened
        log.debug("could not clear usage for %s", name)


def _notify(store, slug: str, report: dict) -> None:
    lines = "\n".join(f"  {a['name']} — {a['why']}" for a in report["archived"])
    inbox.notify(
        store,
        slug,
        "curator",
        "Skills your company wrote were archived",
        f"{len(report['archived'])} skill(s) it wrote for itself had stopped being read, so "
        f"they were moved out of the way rather than kept in every prompt that names their "
        f"tool:\n{lines}\n\nNothing was deleted — they are in "
        f"skills/{ARCHIVE}/, and your own skills were not touched.",
    )
