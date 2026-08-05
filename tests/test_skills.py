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
    from corparius.kernel import paths

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
    from corparius.kernel import paths
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

    from corparius import skillcli
    from corparius.kernel import paths

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


# --- a skill that really is meant for every prompt ---------------------------


def _front(name, *extra):
    """Frontmatter with no allowed-tools, so the skill applies to every tool."""
    return "---\n" + "\n".join([f"name: {name}", *extra]) + "\n---\n"


def test_a_skill_can_declare_that_it_belongs_in_every_prompt(tmp_path):
    """The doctor treats "no allowed-tools" as an omission, and usually it is. A
    guardrail that opens with "applies to every output of every agent, without
    exception" is not — and there was no way to say so, so the only way to quiet
    the warning was to narrow the rule, which is the opposite of what it is for."""
    sk = parse(_write(tmp_path, "promesse", "No diagnosis.", _front("promesse", "always: true")))
    assert sk.always is True
    assert sk.unscoped is True, "it still applies to every tool; that is the point"
    assert sk.undeclared_unscoped is False, "and it is no longer somebody's mistake"


def test_forgetting_to_scope_a_skill_is_still_a_mistake(tmp_path):
    sk = parse(_write(tmp_path, "notes", "Background.", _front("notes")))
    assert sk.always is False and sk.undeclared_unscoped is True


def test_a_string_that_is_not_a_yes_is_a_no(tmp_path):
    """YAML hands "false" over as a truthy string, so `always: "false"` must not
    turn a skill always-on by accident."""
    no = parse(_write(tmp_path, "n", "x", _front("n", 'always: "false"')))
    yes = parse(_write(tmp_path, "y", "x", _front("y", 'always: "yes"')))
    assert no.always is False and yes.always is True


def test_declaring_it_does_not_change_which_tools_it_applies_to(tmp_path):
    """It changes who is told they made a mistake, not how the skill behaves."""
    front = _front("s", "always: true", "allowed-tools: send_outreach")
    scoped = parse(_write(tmp_path, "s", "x", front))
    assert scoped.applies_to("send_outreach") and not scoped.applies_to("build_sales_site")


def test_the_doctor_stops_calling_it_an_omission_but_still_prices_it(tmp_path, monkeypatch):
    from corparius import doctor
    from corparius.config import Settings
    from corparius.kernel import paths

    base = tmp_path / "companies"
    (base / "c").mkdir(parents=True)
    (base / "c" / "company.yaml").write_text("slug: c\n", encoding="utf-8")
    _write(base / "c" / "skills", "promesse", "R" * 400, _front("promesse", "always: true"))
    monkeypatch.setattr(paths, "companies_dir", lambda: base)

    level, name, message = doctor._check_skills(Settings())
    assert (level, name) == ("ok", "skills"), message
    assert "whole body on every prompt" in message, message
    assert "400 characters" in message, "declared is not free, and the price must be said"


def test_an_undeclared_one_still_warns(tmp_path, monkeypatch):
    from corparius import doctor
    from corparius.config import Settings
    from corparius.kernel import paths

    base = tmp_path / "companies"
    (base / "c").mkdir(parents=True)
    (base / "c" / "company.yaml").write_text("slug: c\n", encoding="utf-8")
    _write(base / "c" / "skills", "notes", "R" * 400, _front("notes"))
    monkeypatch.setattr(paths, "companies_dir", lambda: base)

    level, _, message = doctor._check_skills(Settings())
    assert level == "warn"
    assert "always: true" in message, "the warning has to name the way out of it"


# --- a rule everywhere, its material in scope ----------------------------------


def test_a_skill_can_put_a_short_rule_everywhere_and_its_body_in_scope(tmp_path):
    """`promesse-clinique` must constrain every output — its own first line says so —
    and it is 3 815 characters, measured at roughly half of one real session's
    tokens. Its relevance is wildly uneven: `reconcile_stripe` cannot make a medical
    claim and `write_site_content` can make five.

    Scoping the whole file would have meant narrowing a safety rule to save tokens.
    Summarising it would have meant an unreviewed paraphrase deciding what a health
    product may claim. So the author writes the universal part themselves."""
    front = (
        "---\nname: p\nalways: >-\n  Never claim a diagnosis.\nallowed-tools: send_outreach\n---\n"
    )
    sk = parse(_write(tmp_path, "p", "The whole long rulebook.", front))
    assert sk.always is True and sk.always_text == "Never claim a diagnosis."
    assert sk.core_for("send_outreach") == "The whole long rulebook."
    assert sk.core_for("reconcile_stripe") == "Never claim a diagnosis."


def test_always_true_still_means_the_whole_body_everywhere(tmp_path):
    """Nothing that exists changes."""
    sk = parse(_write(tmp_path, "p", "Body.", "---\nname: p\nalways: true\n---\n"))
    assert sk.always is True and sk.always_text == ""
    assert sk.core_for("anything") == "Body."


def test_the_words_are_checked_rather_than_the_truthiness(tmp_path):
    """YAML hands "false" over as a truthy string, so a string has to be read as a
    word before it can be read as a rule."""
    for word in ("false", "no", "0", "off"):
        sk = parse(
            _write(tmp_path, "n" + word, "B", f'---\nname: n{word}\nalways: "{word}"\n---\n')
        )
        assert sk.always is False and sk.always_text == "", word
    for word in ("true", "yes", "on"):
        sk = parse(
            _write(tmp_path, "y" + word, "B", f'---\nname: y{word}\nalways: "{word}"\n---\n')
        )
        assert sk.always is True and sk.always_text == "", word


def test_a_skill_with_no_always_contributes_nothing_out_of_scope(tmp_path):
    sk = parse(_write(tmp_path, "s", "B", "---\nname: s\nallowed-tools: send_outreach\n---\n"))
    assert sk.core_for("send_outreach") == "B" and sk.core_for("reconcile_stripe") == ""


def test_the_loader_carries_the_rule_to_a_tool_out_of_scope(tmp_path):
    front = "---\nname: p\nalways: >-\n  The rule.\nallowed-tools: send_outreach\n---\n"
    _write(tmp_path, "p", "The material.", front)
    loader = _loader(tmp_path)
    assert "The material." in loader.context_for("send_outreach")
    out = loader.context_for("reconcile_stripe")
    assert "The rule." in out and "The material." not in out


def test_the_rule_survives_a_budget_the_material_does_not(tmp_path):
    """A claims guardrail truncated to make room for "what is true and sufficient to
    sell" would be exactly the wrong way round."""
    # Scoped away from this tool, so only its always-on text applies — which is
    # precisely the case where a rule competes with somebody else's bulk.
    _write(
        tmp_path,
        "rule",
        "R" * 50,
        "---\nname: rule\nalways: >-\n  KEEPME\nallowed-tools: draft_social_post\n---\n",
    )
    _write(tmp_path, "bulk", "B" * 4000, "---\nname: bulk\n---\n")
    out = _loader(tmp_path, max_chars=200).context_for("send_outreach")
    assert "KEEPME" in out, "the rule lost its place to the material"
    assert "[truncated]" in out, "and the material is the thing that got cut"


def test_the_doctor_prices_the_two_kinds_apart(tmp_path, monkeypatch):
    from corparius import doctor
    from corparius.config import Settings
    from corparius.kernel import paths

    base = tmp_path / "companies"
    (base / "c").mkdir(parents=True)
    (base / "c" / "company.yaml").write_text("slug: c\n", encoding="utf-8")
    _write(
        base / "c" / "skills",
        "split",
        "M" * 3000,
        "---\nname: split\nalways: >-\n  short rule\nallowed-tools: send_outreach\n---\n",
    )
    monkeypatch.setattr(paths, "companies_dir", lambda: base)
    level, _, message = doctor._check_skills(Settings())
    assert level == "ok", message
    assert "rule on every prompt, body in scope" in message
    assert "10 of 3000" in message, "both numbers, or the measurement is a fiction"
    assert "10 characters ride" in message


def test_a_split_skill_is_not_reported_as_unscoped(tmp_path):
    front = "---\nname: p\nalways: >-\n  R\nallowed-tools: send_outreach\n---\n"
    sk = parse(_write(tmp_path, "p", "B", front))
    assert sk.unscoped is False and sk.undeclared_unscoped is False
