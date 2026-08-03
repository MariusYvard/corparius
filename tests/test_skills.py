"""Skills carry what a company knows, in prose.

The properties worth pinning: a skill reaches only the tools it names, a company
overrides a shared one instead of stacking with it, a malformed file is skipped
rather than fatal, and the injected block is bounded — a note nobody reads must
not become the largest line in the token budget.
"""

import types

import pytest

from corparius.agents import ROSTER, _messages, language_line
from corparius.models import AgentRole
from corparius.skills import Skill, SkillLoader, parse
from corparius.tools import TOOLS


def _write(base, name, body="Say less.", front=None, tools="send_outreach"):
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    if front is None:
        front = f"---\nname: {name}\ndescription: d\nallowed-tools: {tools}\n---\n"
    (folder / "SKILL.md").write_text(front + body, encoding="utf-8")
    return folder / "SKILL.md"


def _loader(*dirs, max_chars=None):
    return SkillLoader([(d, "global") for d in dirs], max_chars=max_chars)


def test_a_skill_reaches_only_the_tools_it_names(tmp_path):
    _write(tmp_path, "voice", tools="send_outreach")
    loader = _loader(tmp_path)
    assert "Say less." in loader.context_for("send_outreach")
    assert loader.context_for("draft_social_post") == ""


def test_a_skill_with_no_tool_list_applies_to_every_tool(tmp_path):
    _write(tmp_path, "about-us", front="---\nname: about-us\ndescription: d\n---\n")
    loader = _loader(tmp_path)
    assert loader.context_for("draft_social_post")
    assert loader.context_for("review_kpis")


def test_a_company_skill_replaces_the_shared_one_of_the_same_name(tmp_path):
    """Two sets of instructions for the same job, both in context, is how a
    model gets told to do opposite things."""
    shared, company = tmp_path / "shared", tmp_path / "company"
    _write(shared, "voice", body="Be formal.")
    _write(company, "voice", body="Be blunt.")
    loader = SkillLoader([(shared, "global"), (company, "acme")])
    assert len(loader.skills) == 1
    out = loader.context_for("send_outreach")
    assert "Be blunt." in out and "Be formal." not in out


def test_a_comma_list_and_a_yaml_list_mean_the_same_thing(tmp_path):
    _write(tmp_path, "a", tools="send_outreach, schedule_post")
    b = tmp_path / "b"
    b.mkdir()
    (b / "SKILL.md").write_text(
        "---\nname: b\ndescription: d\nallowed-tools:\n  - send_outreach\n  - schedule_post\n---\nx",
        encoding="utf-8",
    )
    loader = _loader(tmp_path)
    assert all(s.allowed_tools == ["send_outreach", "schedule_post"] for s in loader.skills)


def test_broken_frontmatter_is_skipped_not_fatal(tmp_path):
    """One bad file in a folder must not stop a company from running, exactly as
    a plugin that fails to import does not."""
    _write(tmp_path, "good")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: [unclosed\n---\nbody", encoding="utf-8")
    loader = _loader(tmp_path)
    assert [s.name for s in loader.skills] == ["good"]


def test_a_file_with_no_frontmatter_is_all_body(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "SKILL.md").write_text("Just a note somebody typed.", encoding="utf-8")
    loader = _loader(tmp_path)
    assert loader.skills[0].name == "notes"
    assert "Just a note" in loader.context_for("review_kpis")


def test_the_injected_block_is_capped_and_says_it_was_cut(tmp_path):
    _write(tmp_path, "long", body="x" * 5000)
    out = _loader(tmp_path, max_chars=100).context_for("send_outreach")
    assert "[truncated]" in out
    assert len(out) < 400, "the cap did not hold"


def test_a_second_skill_past_the_cap_does_not_smuggle_more_in(tmp_path):
    _write(tmp_path, "a", body="a" * 90)
    _write(tmp_path, "b", body="b" * 90)
    out = _loader(tmp_path, max_chars=100).context_for("send_outreach")
    assert out.count("a" * 90) == 1
    assert "b" * 90 not in out


def test_no_skills_costs_nothing(tmp_path):
    assert _loader(tmp_path).context_for("send_outreach") == ""


def test_the_prompt_is_unchanged_when_no_skill_applies(tmp_path):
    """The default path for every company that has written none. A blank block,
    a trailing newline or a header would still be tokens spent on nothing."""
    _write(tmp_path, "voice", tools="send_outreach")
    ctx = types.SimpleNamespace(
        company={"name": "T", "offer": {}}, memory=[], skills=_loader(tmp_path)
    )
    spec = ROSTER[AgentRole.SOCIAL]
    system = _messages(spec, ctx, TOOLS["draft_social_post"])[0]["content"]
    # Still exact equality, against a baseline that now includes the one
    # unconditional line every prompt carries: the company's language. The
    # property under test is that nothing *else* is added, so weakening this
    # to a substring check would have retired the test rather than updated it.
    assert system == f"{spec.system_prompt}\n\n{language_line(ctx.company)}"


def test_an_applicable_skill_reaches_the_system_prompt(tmp_path):
    _write(tmp_path, "voice", body="Never promise a callback rate.")
    ctx = types.SimpleNamespace(
        company={"name": "T", "offer": {}}, memory=[], leads=[], skills=_loader(tmp_path)
    )
    spec = ROSTER[AgentRole.OUTREACH]
    system = _messages(spec, ctx, TOOLS["send_outreach"])[0]["content"]
    assert spec.system_prompt in system
    assert "Never promise a callback rate." in system


def test_an_agent_with_no_loader_is_unaffected():
    """RunContext.skills is None when skills are off, and every existing caller
    that builds a context by hand leaves it unset."""
    ctx = types.SimpleNamespace(company={"name": "T", "offer": {}}, memory=[])
    spec = ROSTER[AgentRole.SOCIAL]
    # Still exact equality, against a baseline that now includes the one
    # unconditional line every prompt carries: the company's language. The
    # property under test is that nothing *else* is added, so weakening this
    # to a substring check would have retired the test rather than updated it.
    assert _messages(spec, ctx, TOOLS["draft_social_post"])[0]["content"] == (
        f"{spec.system_prompt}\n\n{language_line(ctx.company)}"
    )


def test_the_shipped_example_skill_names_real_tools():
    """A skill naming a tool nobody has is read, parsed, and then never applies.
    Shipping one like that would teach the wrong thing by example."""
    from corparius import paths

    # The shipped source, not whatever an operator's home happens to hold. This
    # asked companies_dir() and skipped when it came up empty, so the moment the
    # suite stopped pointing that at the checkout the test went quiet instead of
    # failing — a claim about what ships has to read what ships.
    path = paths.example_company_src() / "skills" / "outreach-voice" / "SKILL.md"
    skill = parse(path)
    assert isinstance(skill, Skill)
    assert skill.allowed_tools
    assert [t for t in skill.allowed_tools if t not in TOOLS] == []


def test_a_skill_with_no_allowed_tools_is_reported_as_unscoped(tmp_path):
    """The failure a third-party skill library creates by default. Its SKILL.md
    files declare no allowed-tools, so every one of them lands in every prompt
    of every agent — silently, in the direction that costs most."""
    _write(tmp_path, "everywhere", front="---\nname: everywhere\ndescription: d\n---\n")
    loader = _loader(tmp_path)
    assert loader.skills[0].unscoped is True
    kinds = [w["kind"] for w in loader.warnings()]
    assert "unscoped" in kinds


def test_a_scoped_skill_raises_no_warning(tmp_path):
    _write(tmp_path, "voice", tools="send_outreach")
    assert _loader(tmp_path).warnings() == []


def test_the_always_on_weight_is_counted(tmp_path):
    """The number nothing displayed: what a folder of unscoped skills costs on
    every single prompt, whatever the tool."""
    _write(tmp_path, "a", body="x" * 100, front="---\nname: a\ndescription: d\n---\n")
    _write(tmp_path, "b", body="y" * 50, tools="send_outreach")
    assert _loader(tmp_path).always_on_chars() == 100


def test_an_oversized_skill_is_reported_as_truncated(tmp_path):
    """context_for already marks [truncated] inside the prompt, where only the
    model sees it. The operator never did."""
    _write(tmp_path, "long", body="x" * 5000, tools="send_outreach")
    warnings = _loader(tmp_path, max_chars=100).warnings()
    assert [w["kind"] for w in warnings] == ["truncated"]
    assert warnings[0]["chars"] == 5000 and warnings[0]["cap"] == 100


def test_both_failures_at_once_are_both_reported(tmp_path):
    """Exactly what dropping in a skill written for another host produces."""
    _write(tmp_path, "big", body="x" * 9000, front="---\nname: big\ndescription: d\n---\n")
    assert {w["kind"] for w in _loader(tmp_path, max_chars=4000).warnings()} == {
        "unscoped",
        "truncated",
    }


def test_every_shipped_example_skill_is_well_formed():
    """The example company is what an operator copies. A skill that shipped
    unscoped, oversized, or naming a tool nobody has would teach exactly the
    mistakes the doctor now warns about."""
    from corparius import paths
    from corparius.skills import DEFAULT_MAX_CHARS, SkillLoader

    # The shipped source, for the same reason as above.
    base = paths.example_company_src() / "skills"
    loader = SkillLoader([(base, "example")])
    assert len(loader.skills) >= 3
    for skill in loader.skills:
        assert skill.allowed_tools, f"{skill.name} declares no allowed-tools"
        assert [t for t in skill.allowed_tools if t not in TOOLS] == [], skill.name
        assert len(skill.instructions) <= DEFAULT_MAX_CHARS, f"{skill.name} is over the cap"
    assert loader.warnings() == []
    assert loader.always_on_chars() == 0


def test_the_shipped_template_is_well_formed():
    """It is copied verbatim as the starting point, so it has to pass the same
    bar it teaches."""
    from pathlib import Path

    from corparius.skills import parse

    path = Path("packaging/skill-template/SKILL.md")
    if not path.is_file():
        pytest.skip("a wheel install without packaging/")
    skill = parse(path)
    assert skill is not None and skill.allowed_tools
    assert not skill.unscoped


def test_the_starter_pack_passes_the_bar_it_teaches():
    """It is what `corparius skills install starter` copies into a fresh
    install, so it is the first prose most operators will ever read here. One
    unscoped skill in it would put its whole body on every prompt of every
    agent — the tax the loader was hardened to expose, shipped by us."""
    from pathlib import Path

    from corparius.skills import DEFAULT_MAX_CHARS, SkillLoader

    base = Path("packaging/skill-pack-starter/skills")
    if not base.is_dir():
        pytest.skip("a wheel install without packaging/")
    loader = SkillLoader([(base, "starter")])
    # Counted from the folders on disk, not written here as a literal. A literal
    # has to be edited every time a skill is added — it already broke twice —
    # and each edit is a chance to change the number without looking at why. This
    # still fails on the thing that matters: a skill present but not loading.
    shipped = sorted(p.parent.name for p in base.glob("*/SKILL.md"))
    assert sorted(s.name for s in loader.skills) == shipped
    assert len(shipped) >= 6, "the starter pack lost skills"
    for skill in loader.skills:
        assert skill.allowed_tools, f"{skill.name} declares no allowed-tools"
        assert [t for t in skill.allowed_tools if t not in TOOLS] == [], skill.name
        assert len(skill.instructions) <= DEFAULT_MAX_CHARS, f"{skill.name} is over the cap"
        assert skill.description, f"{skill.name} has no description"
    assert loader.warnings() == []
    assert loader.always_on_chars() == 0


def test_the_starter_pack_covers_jobs_that_had_nothing():
    """The three example skills cover ads, outreach and pricing. The pack exists
    for the tools that had no prose at all, starting with the two most frequent
    tiers in the roster: social every 2h, support every 3h."""
    from pathlib import Path

    from corparius.skills import SkillLoader

    base = Path("packaging/skill-pack-starter/skills")
    if not base.is_dir():
        pytest.skip("a wheel install without packaging/")
    loader = SkillLoader([(base, "starter")])
    for tool in ("draft_social_post", "triage_inbox", "reconcile_stripe", "scan_competitors"):
        assert loader.for_tool(tool), f"nothing covers {tool}"


def test_the_starter_pack_credits_where_it_came_from():
    """Apache-2.0 with a LICENSE.txt per skill upstream. Adapted prose is still
    derived prose, and the frontmatter is where it costs nothing to say so.

    This used to require one upstream by name. It no longer does, because the
    pack no longer has one: `landing-craft` is adapted from the owner's own
    NullToHero plugin. What has to hold is that every skill names *a* source and
    a licence, not that they all name the same one."""
    from pathlib import Path

    base = Path("packaging/skill-pack-starter/skills")
    if not base.is_dir():
        pytest.skip("a wheel install without packaging/")
    for path in base.glob("*/SKILL.md"):
        head = path.read_text(encoding="utf-8")
        source = next((ln for ln in head.splitlines() if ln.startswith("source:")), "")
        assert source.removeprefix("source:").strip(), f"{path} credits nobody"
        assert "Apache-2.0" in head, path


def test_the_starter_pack_is_found_through_the_one_resource_resolver():
    """It shipped only to people who had cloned the repository.

    `skills install starter` rolled its own lookup — repo root, then _MEIPASS —
    and a wheel has neither: the files ride inside the package under _data/.
    Everyone on a wheel got "the starter pack is not in this install". Going
    through paths._resource is what makes the three layouts one question.
    """
    from pathlib import Path

    from corparius import paths, skillcli

    found = skillcli._starter_dir()
    assert found is not None, "the pack must be found from a source checkout"
    assert (found / "support-triage" / "SKILL.md").is_file()
    assert found == paths._resource("packaging", "skill-pack-starter", "skills")
    assert Path("packaging/skill-pack-starter/skills").resolve() == found.resolve()


def test_the_wheel_and_the_frozen_build_are_told_to_carry_it():
    """A resolver that looks in the right place finds nothing if the build does
    not put it there. Both manifests name it."""
    from pathlib import Path

    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"packaging/skill-pack-starter" = "corparius/_data/' in pyproject
    assert '"/packaging/skill-pack-starter",' in pyproject
    spec = Path("packaging/corparius.spec").read_text(encoding="utf-8")
    assert "skill-pack-starter" in spec
