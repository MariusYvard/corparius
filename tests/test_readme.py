"""The README is the first thing anyone reads, and it had gone quietly out of date.

An audit found: the whole documents capability absent — no section, no module in
the layout, no `docs/documents.md`, nothing in `docs/console.md` — `corparius
preflight` unmentioned though it is the headline of a release, 13 of 28 CLI
commands missing, "12 free tiers" printed three times against a registry holding
14, one provider prefix undocumented, the HITL default naming two tools where the
code names three, and a claim that console-saved keys sit in the clear written
after `corparius secrets on` existed to encrypt them.

None of that could fail. Documentation drift is invisible by construction, so
these tests are the part that is not: each one compares the README against the
code it describes, in the direction that rots.
"""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from corparius.company import DEFAULT_HITL
from corparius.providers.llm import OPENAI_COMPAT_PROVIDERS

README = Path("README.md")
DOCS = Path("docs")

pytestmark = pytest.mark.skipif(not README.is_file(), reason="a wheel install without the README")


def _readme() -> str:
    return README.read_text(encoding="utf-8")


# --- documentation both ways -------------------------------------------------


def test_every_doc_the_readme_points_at_exists():
    """A dead link in the one file newcomers read costs more than a missing page:
    it says the project does not know what it ships."""
    missing = [
        ref
        for ref in sorted(set(re.findall(r"docs/[\w.-]+\.md", _readme())))
        if not Path(ref).is_file()
    ]
    assert not missing, f"the README links to files that are not there: {missing}"


def test_every_doc_that_exists_is_reachable_from_the_readme():
    """`docs/versionnement.md` existed and the README never named it, so the one
    index a reader has did not lead there. A page nobody can find is a page
    nobody wrote."""
    text = _readme()
    orphans = [p.as_posix() for p in sorted(DOCS.glob("*.md")) if p.as_posix() not in text]
    assert not orphans, f"docs the README never mentions: {orphans}"


# --- the CLI -----------------------------------------------------------------


def _cli_commands() -> set[str]:
    """The commands argparse actually offers, read off the parser rather than
    kept in a second list here — which would rot the same way the README did."""
    from corparius import cli

    out = io.StringIO()
    with pytest.raises(SystemExit), redirect_stdout(out):
        cli.main(["--help"])
    usage = re.search(r"\{([a-z,]+)\}", out.getvalue())
    assert usage, "could not read the command list out of --help"
    return set(usage.group(1).split(","))


def test_the_readme_names_every_cli_command():
    """It listed 12 of 28. `preflight`, `secrets`, `repo`, `memory` and `rules`
    are capabilities in their own right, and an operator who never sees the name
    cannot run it."""
    text = _readme()
    missing = sorted(c for c in _cli_commands() if not re.search(rf"`{re.escape(c)}`", text))
    assert not missing, f"CLI commands the README never names: {missing}"


# --- the LLM registry --------------------------------------------------------


def _free_tier_targets() -> set[str]:
    """Everything in the registry except the paid one and the bring-your-own
    gateway. `openai:` bills from the first call, so it does not belong in a
    count of free tiers; `custom:` is not a provider."""
    return set(OPENAI_COMPAT_PROVIDERS) - {"openai", "custom"}


def test_every_provider_prefix_is_documented_in_the_readme():
    """`alibaba:` was in the registry, in `docs/llm-providers.md`, and absent
    from the README — so the one table a reader consults said the target did not
    exist."""
    text = _readme()
    missing = sorted(f"{n}:" for n in OPENAI_COMPAT_PROVIDERS if f"`{n}:`" not in text)
    assert not missing, f"targets the README does not list: {missing}"


def test_the_free_tier_count_matches_the_registry():
    """It said 12, three times, while the table below it listed 13 and the
    registry held 14. A number in prose is a claim; this is what checks it."""
    expected = len(_free_tier_targets())
    # Every phrasing the README has used for this count. "12 free-tier providers"
    # was one of the three wrong ones and the first version of this pattern did
    # not match it, which would have left a third of the claim unchecked.
    claims = re.findall(
        r"(\d+) (?:free tiers|free-tier providers|OpenAI-compatible providers|free OpenAI)",
        _readme(),
    )
    assert claims, "the README no longer states how many providers there are"
    wrong = sorted({c for c in claims if int(c) != expected})
    assert not wrong, f"the README claims {wrong} free providers; the registry has {expected}"


# --- defaults that live in code ----------------------------------------------


def test_the_readme_names_every_tool_held_at_the_human_gate_by_default():
    """It named two of the three. The gate is the point of the product, and a
    default it under-reports is the one kind of surprise that cannot be a
    pleasant one."""
    text = _readme()
    missing = [t for t in DEFAULT_HITL if f"`{t}`" not in text]
    assert not missing, f"CORP_HITL_TOOLS defaults the README omits: {missing}"


# --- the sections a reader navigates by --------------------------------------


def test_every_contents_link_lands_on_a_real_heading():
    """The Contents list is the map. It pointed at #documents before that section
    existed, and omitted five sections that did."""
    text = _readme()
    slugs = {
        re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
        for h in re.findall(r"^## (.+)$", text, re.M)
    }
    broken = [f for f in re.findall(r"\]\(#([\w-]+)\)", text) if f not in slugs]
    assert not broken, f"Contents links with no heading: {broken}"


def test_every_section_is_listed_in_the_contents():
    """The direction that actually rotted. Nothing was broken — Plugins, Skills,
    Company apps, Support and License simply existed while the map above them did
    not say so, which is how a reader concludes a project has no plugins.
    """
    text = _readme()
    listed = set(re.findall(r"\]\(#([\w-]+)\)", text))
    unlisted = [
        h
        for h in re.findall(r"^## (.+)$", text, re.M)
        if h != "Contents" and re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") not in listed
    ]
    assert not unlisted, f"sections missing from the Contents list: {unlisted}"


def test_the_screenshot_is_a_matched_light_and_dark_pair():
    """GitHub picks one by the reader's theme, so a shot refreshed in one theme and
    not the other leaves half the readers looking at the previous release. Same
    pixel size is the cheap proxy for "taken from the same session"."""
    import struct

    shots = [Path("docs/screenshots/console.png"), Path("docs/screenshots/console-dark.png")]
    missing = [str(p) for p in shots if not p.is_file()]
    assert not missing, f"the themed pair is incomplete: {missing}"

    text = _readme()
    assert all(p.as_posix() in text for p in shots), "both shots must be wired into the <picture>"

    sizes = {}
    for path in shots:
        head = path.read_bytes()[:24]
        sizes[path.name] = struct.unpack(">II", head[16:24])
    assert len(set(sizes.values())) == 1, f"the pair does not match: {sizes}"


def test_the_console_tabs_are_all_described_somewhere():
    """A tab nobody documents is a feature nobody finds. The Documents tab
    shipped and neither the README nor docs/console.md mentioned it."""
    page = Path("corparius/webui.html")
    if not page.is_file():
        pytest.skip("a wheel install without the console page")
    tabs = {
        m for m in re.findall(r'aria-controls="tab-([a-z]+)"', page.read_text(encoding="utf-8"))
    }
    prose = (_readme() + Path("docs/console.md").read_text(encoding="utf-8")).lower()
    missing = sorted(t for t in tabs if t not in prose)
    assert not missing, f"console tabs described nowhere: {missing}"
