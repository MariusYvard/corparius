"""Importing is not fitting.

There is a lot of good prose about knowledge work in the open — anthropics/
knowledge-work-plugins publishes 141 SKILL.md files under Apache-2.0 — and none
of it drops in. Measured on those files: no `allowed-tools` at all (their
frontmatter is name/description/argument-hint), a median around 12 KB against a
4000-character cap, and bodies that tell the model to ask a human who is not
there.

So the properties worth pinning are the ones that stop an import from becoming
the silent failure the loader was hardened against three days earlier: it never
invents a scope, and it always says how much of the body will be cut.
"""

import pytest

from corparius import skillimport, skills

# The real shape, copied from customer-support/skills/draft-response/SKILL.md:
# no allowed-tools, and an argument-hint corparius has no use for.
FOREIGN = """---
name: draft-response
description: Draft a professional customer-facing response.
argument-hint: "<situation description>"
---

# /draft-response

Match the customer's register. Lead with what you will do, not with an apology.
"""

UNKNOWN_JOB = """---
name: sox-testing
description: Walk a SOX control through its test of design.
---

Pull the control matrix, sample twenty five items, document each exception.
"""


def _write(tmp_path, text, folder="incoming"):
    d = tmp_path / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d / "SKILL.md"


def test_a_known_job_gets_the_tools_that_do_it(tmp_path):
    out = skillimport.inspect(_write(tmp_path, FOREIGN))
    assert out["ok"] and out["name"] == "draft-response"
    assert out["suggested_tools"] == ["draft_support_reply"]
    assert out["unscoped"] is False


def test_an_unknown_job_never_gets_a_guessed_scope(tmp_path):
    """Half of those 141 are for work this roster has never done. A mapping
    invented for one of them points prose at the wrong agent, silently — worse
    than not importing it."""
    out = skillimport.inspect(_write(tmp_path, UNKNOWN_JOB))
    assert out["ok"] and out["suggested_tools"] == []
    assert out["unscoped"] is True


def test_a_declared_tool_list_wins_over_the_guess(tmp_path):
    """A file that already names corparius tools was written for corparius."""
    text = FOREIGN.replace("argument-hint:", "allowed-tools: triage_inbox\nargument-hint:")
    out = skillimport.inspect(_write(tmp_path, text))
    assert out["declared_tools"] == ["triage_inbox"]
    assert out["suggested_tools"] == ["triage_inbox"]


def test_the_cut_is_reported_as_arithmetic_before_anything_is_written(tmp_path):
    """Their median skill is ~12 KB against a 4000-character cap for the whole
    injected block. A command that swallows that and says nothing recreates the
    failure the loader now warns about."""
    body = "x" * 14000
    out = skillimport.inspect(_write(tmp_path, FOREIGN + body), max_chars=4000)
    assert out["over_cap"] is True
    assert out["chars"] > 14000
    assert 70.0 < out["cut_pct"] < 75.0, out["cut_pct"]


def test_a_skill_that_fits_reports_no_cut(tmp_path):
    out = skillimport.inspect(_write(tmp_path, FOREIGN), max_chars=4000)
    assert out["over_cap"] is False and out["cut_pct"] == 0.0


def test_a_folder_is_accepted_as_well_as_the_file(tmp_path):
    path = _write(tmp_path, FOREIGN)
    assert skillimport.inspect(path.parent)["name"] == "draft-response"


def test_an_unreadable_file_is_a_refusal_not_a_crash(tmp_path):
    out = skillimport.inspect(tmp_path / "nothing" / "SKILL.md")
    assert out["ok"] is False and "readable" in out["detail"]


def test_the_written_file_is_loadable_by_the_loader(tmp_path):
    """The whole point: what comes out must be a corparius skill, scoped, that
    the existing loader picks up for the right tool and no other."""
    out = skillimport.inspect(_write(tmp_path, FOREIGN))
    dest = tmp_path / "skills"
    written = skillimport.write(out, dest, out["suggested_tools"], source="upstream/draft-response")
    loader = skills.SkillLoader([(dest, "global")])
    assert [s.name for s in loader.for_tool("draft_support_reply")] == ["draft-response"]
    assert loader.for_tool("send_outreach") == []
    assert loader.always_on_chars() == 0, "an import must not land unscoped"
    assert "upstream/draft-response" in written.read_text(encoding="utf-8")
    assert "Apache-2.0" in written.read_text(encoding="utf-8")


def test_the_body_is_copied_verbatim(tmp_path):
    """Not summarised, not reflowed. Trimming 12 KB down to something useful is
    a judgement about the company, and the operator is the one who has it."""
    out = skillimport.inspect(_write(tmp_path, FOREIGN))
    written = skillimport.write(out, tmp_path / "skills", ["draft_support_reply"])
    assert "Lead with what you will do, not with an apology." in written.read_text(encoding="utf-8")


def test_an_import_never_overwrites_a_skill(tmp_path):
    """A skill is something its author edited. Replacing one with an import
    throws away exactly the trimming that made the import usable."""
    out = skillimport.inspect(_write(tmp_path, FOREIGN))
    dest = tmp_path / "skills"
    skillimport.write(out, dest, ["draft_support_reply"])
    with pytest.raises(FileExistsError):
        skillimport.write(out, dest, ["draft_support_reply"])


def test_render_shows_what_write_would_produce(tmp_path):
    """--dry-run has to be the same text, or it is a different command."""
    out = skillimport.inspect(_write(tmp_path, FOREIGN))
    shown = skillimport.render(out, ["draft_support_reply"], "upstream")
    written = skillimport.write(out, tmp_path / "skills", ["draft_support_reply"], "upstream")
    assert shown == written.read_text(encoding="utf-8")


def test_every_hinted_tool_exists(tmp_path):
    """A skill naming a tool nobody has is read, parsed and then never applied.
    The doctor catches it for hand-written skills; the mapping must not be able
    to produce one in the first place."""
    from corparius.tools.registry import TOOLS

    for name, tools in skillimport.TOOL_HINTS.items():
        unknown = [t for t in tools if t not in TOOLS]
        assert not unknown, f"{name} maps to missing tool(s): {unknown}"


def test_the_mapping_only_claims_jobs_this_roster_does():
    """A guard against the mapping growing into a wish list: bio-research,
    Zoom SDKs, contract redlines and PDF signing have no tool here, and giving
    them one would be inventing a job rather than naming one."""
    for name in ("instrument-data-to-allotrope", "review-contract", "onboarding", "view-pdf"):
        assert skillimport.suggest_tools(name) == []


def test_the_announced_cut_is_what_the_loader_actually_cuts(tmp_path):
    """The promise of this module is one number, so the number has to be right.

    It was 0.5 points off at first: the attribution line sat in the body, so it
    was both paid for on every prompt and counted in a cut it caused. It lives
    in the frontmatter now, where `skills.parse` ignores it.
    """
    body = "y" * 14000
    src = _write(tmp_path, FOREIGN + body)
    out = skillimport.inspect(src, max_chars=4000)
    dest = tmp_path / "skills"
    skillimport.write(out, dest, ["draft_support_reply"], source="upstream")

    loader = skills.SkillLoader([(dest, "global")], max_chars=4000)
    reloaded = loader.for_tool("draft_support_reply")[0]
    assert len(reloaded.instructions) == out["chars"], "the frontmatter must cost nothing"

    context = loader.context_for("draft_support_reply")
    kept = len(context) - len("## draft-response\n") - len("\n[truncated]")
    actual = 100.0 * (out["chars"] - kept) / out["chars"]
    assert abs(actual - out["cut_pct"]) < 0.1, (actual, out["cut_pct"])
