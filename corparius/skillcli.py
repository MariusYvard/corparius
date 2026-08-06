"""`corparius skills ...` — see what a company knows, and bring in more of it.

Skills had no command at all: they were written by hand into a folder, and the
only places that said anything about them were the doctor and the console. An
operator driving corparius from a terminal could not see what was loaded, what
rode on every prompt, or what was being cut. See docs/skills.md.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import NoReturn

from . import skillimport, skills
from .config.settings import Settings
from .kernel import paths


def _fail(msg: str) -> NoReturn:
    """NoReturn, unlike plugincli's: the callers here go on to use the value the
    guard just proved present, and mypy has to know the guard is terminal."""
    sys.exit(f"error: {msg}")


def _loader(slug: str) -> skills.SkillLoader:
    s = Settings()
    return skills.SkillLoader.for_company(slug, max_chars=s.skill_max_chars)


def _dest(slug: str) -> Path:
    return paths.company_skills_dir(slug) if slug else paths.skills_dir()


def cmd_list(args) -> None:
    loader = _loader(args.company)
    if not loader.skills:
        print("no skills. `corparius skills install starter` gives you six to start from.")
        return
    for skill in loader.skills:
        scope = ", ".join(skill.allowed_tools) if skill.allowed_tools else "EVERY TOOL"
        print(f"  {skill.name:22} [{skill.scope}] {len(skill.instructions):>6} chars  {scope}")
    always = loader.always_on_chars()
    if always:
        # The number nothing displayed, and the one that costs the most: an
        # unscoped skill is paid for on every prompt of every agent, every turn.
        print(f"\n{always} characters ride on EVERY prompt (skills with no allowed-tools).")
    for warn in loader.warnings():
        if warn["kind"] == "truncated":
            print(f"  {warn['skill']}: {warn['chars']} chars, cut to {warn['cap']} at run time")


def cmd_import(args) -> None:
    result = skillimport.inspect(args.path, max_chars=Settings().skill_max_chars)
    if not result["ok"]:
        _fail(result["detail"])
    tools = [t.strip() for t in (args.tools or "").split(",") if t.strip()]
    tools = tools or result["suggested_tools"]
    print(f"{result['name']}: {result['chars']} chars (cap {result['cap']})")
    if result["over_cap"]:
        # Show the arithmetic rather than a verdict, the same bargain as
        # `corparius bench`: an operator can disagree with a cap, not with a cut.
        print(f"  {result['cut_pct']}% of it will be cut at run time. Trim it after importing.")
    if tools:
        print(f"  allowed-tools: {', '.join(tools)}")
    else:
        print(
            "  NO allowed-tools: nothing here does that job, so this would apply to every\n"
            "  tool of every agent, on every turn. Name them with --tools, or leave it and\n"
            "  edit the file — an invented scope points prose at the wrong agent silently."
        )
    unknown = [t for t in tools if t not in _tool_names()]
    if unknown:
        _fail(f"unknown tool(s): {', '.join(unknown)}. A skill naming one never applies.")
    if args.dry_run:
        print("\n--- would write ---")
        print(skillimport.render(result, tools, result["path"]))
        return
    try:
        written = skillimport.write(result, _dest(args.company), tools, source=result["path"])
    except FileExistsError as exc:
        _fail(f"{exc} already exists; delete it or import under another name")
    print(f"\nwritten: {written}")


def cmd_install(args) -> None:
    if args.pack != "starter":
        _fail(f"unknown pack '{args.pack}'; only 'starter' ships with corparius")
    src = _starter_dir()
    if src is None:
        _fail("the starter pack is not in this install")
    dest = _dest(args.company)
    dest.mkdir(parents=True, exist_ok=True)
    copied, skipped = [], []
    for folder in sorted(src.glob("*/SKILL.md")):
        target = dest / folder.parent.name
        if target.exists():
            skipped.append(folder.parent.name)
            continue
        shutil.copytree(folder.parent, target)
        copied.append(folder.parent.name)
    for name in copied:
        print(f"  installed {name}")
    for name in skipped:
        print(f"  kept your own {name}")
    print(f"\n{len(copied)} skill(s) into {dest}")
    if copied:
        print("They are a starting point, not a policy: edit them to say what YOUR company does.")


def _starter_dir() -> Path | None:
    """Where the shipped pack lives, in all three distribution modes.

    This hand-rolled its own lookup and found the pack only in a source
    checkout, so `skills install starter` answered "not in this install" to
    everyone on a wheel or a frozen binary — that is, to everyone who did not
    clone the repository. paths._resource is the one place that knows the three
    layouts; using anything else is how a shipped file goes missing.
    """
    found = paths._resource("packaging", "skill-pack-starter", "skills")
    return found if found.is_dir() else None


def _tool_names() -> set[str]:
    from .tools import TOOLS

    return set(TOOLS)


def add_parser(sub) -> None:
    """Wire the `skills` command and its sub-actions into the CLI."""
    pp = sub.add_parser("skills", help="list, import and install what your company knows")
    psub = pp.add_subparsers(dest="skills_cmd", required=True)

    sp = psub.add_parser("list", help="what is loaded, and what rides on every prompt")
    sp.add_argument("--company", default="", help="a company slug (default: shared skills)")
    sp.set_defaults(fn=cmd_list)

    sp = psub.add_parser("import", help="adapt a SKILL.md written for another host")
    sp.add_argument("path", help="a SKILL.md, or the folder holding one")
    sp.add_argument("--company", default="", help="import into that company instead of shared")
    sp.add_argument(
        "--tools", default="", help="comma-separated allowed-tools, overriding the guess"
    )
    sp.add_argument("--dry-run", action="store_true", help="print what would be written")
    sp.set_defaults(fn=cmd_import)

    sp = psub.add_parser("install", help="copy a skill pack shipped with corparius")
    sp.add_argument("pack", nargs="?", default="starter")
    sp.add_argument("--company", default="", help="install into that company instead of shared")
    sp.set_defaults(fn=cmd_install)
