"""Scoping a skill from a terminal — the fix for the most expensive skill mistake there is.

An unscoped skill, one with no `allowed-tools`, lands in **every prompt of every agent, every
turn**. On the owner's own company `promesse-clinique` was 3 815 characters riding on every call.

`corparius skills list` already *reported* it: `EVERY TOOL` next to the skill, and a total of the
characters that ride everywhere. So a terminal could tell an operator exactly what it cost them
and offer nothing to do about it — which is a worse shape than not knowing, because the only fix
was the console's panel or finding the file and hand-editing YAML.

The guards worth having are the two `scope_to` already stated and one nobody had asserted from
this side: **the body is the operator's prose and comes back byte for byte.** This rewrites a
header; it does not reformat somebody's file.
"""

import pytest

from corparius.app import skills as app_skills
from corparius.app.errors import Refused
from corparius.config.settings import Settings

BODY = "Ne jamais promettre ce que le produit ne fait pas.\nDeuxième ligne, gardée telle quelle.\n"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    from corparius.config import cfg

    cfg.invalidate()
    return tmp_path


def _skill(home, name="tout-partout", tools=""):
    folder = home / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    scope = f"allowed-tools: {tools}\n" if tools else ""
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: une règle maison\n{scope}---\n{BODY}", encoding="utf-8"
    )
    return folder / "SKILL.md"


# --- finding the cost -----------------------------------------------------------


def test_an_unscoped_skill_is_listed_with_what_it_costs(home):
    """The breakdown, not just the total. `always_on_chars()` says how much rides everywhere;
    an operator deciding *which* one to scope first needs it per skill."""
    _skill(home)
    rows = app_skills.unscoped("", Settings())
    assert [r["name"] for r in rows] == ["tout-partout"]
    assert rows[0]["chars"] == len(BODY.strip())


def test_a_scoped_skill_is_not_listed(home):
    _skill(home, tools="write_site_content")
    assert app_skills.unscoped("", Settings()) == []


def test_a_declared_always_skill_is_still_listed_but_marked(home):
    """`always: true` is an author saying "this really does belong everywhere". It is not a
    mistake, and the doctor stopped calling it one — but it still costs, so hiding it from a
    cost breakdown would be the wrong kind of politeness."""
    folder = home / "skills" / "regle"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: regle\ndescription: d\nalways: true\n---\n{BODY}", encoding="utf-8"
    )
    rows = app_skills.unscoped("", Settings())
    assert rows and rows[0]["declared"] is True


# --- the fix --------------------------------------------------------------------


def test_scoping_writes_the_tools(home):
    path = _skill(home)
    out = app_skills.scope(
        "", "tout-partout", ["write_site_content", "draft_social_post"], Settings()
    )
    assert out["tools"] == ["write_site_content", "draft_social_post"]
    written = path.read_text(encoding="utf-8")
    assert "write_site_content" in written and "draft_social_post" in written
    assert app_skills.unscoped("", Settings()) == [], "it no longer rides every prompt"


def test_the_operators_prose_comes_back_byte_for_byte(home):
    """The guard nobody had asserted from this side. This rewrites a header; a version that
    reformatted the file would silently edit what the operator wrote."""
    path = _skill(home)
    app_skills.scope("", "tout-partout", ["write_site_content"], Settings())
    written = path.read_text(encoding="utf-8")
    assert written.endswith(BODY.strip() + "\n") or BODY.strip() in written
    for line in BODY.strip().splitlines():
        assert line in written, f"a line of the body changed: {line!r}"


def test_a_tool_that_does_not_exist_is_refused(home):
    """A skill scoped to a name nobody has never applies — silently, which is a worse outcome
    than the tax it was meant to fix."""
    path = _skill(home)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(Refused, match="unknown tool"):
        app_skills.scope("", "tout-partout", ["pas-un-outil"], Settings())
    assert path.read_text(encoding="utf-8") == before, "nothing may have been written"


def test_naming_nothing_is_refused(home):
    """Accepting an empty list would look like a fix and be none: the skill stays on every
    prompt."""
    _skill(home)
    with pytest.raises(Refused, match="at least one tool"):
        app_skills.scope("", "tout-partout", [], Settings())


def test_a_skill_that_is_not_there_says_what_is(home):
    """An operator who mistypes a name needs the list, not a 404. There are rarely more than a
    handful."""
    _skill(home, name="voix-vigil")
    with pytest.raises(Refused, match="voix-vigil"):
        app_skills.scope("", "voix-vigl", ["write_site_content"], Settings())


def test_it_refuses_when_skills_are_off(home, monkeypatch):
    monkeypatch.setenv("CORP_SKILLS_ENABLED", "false")
    from corparius.config import cfg

    cfg.invalidate()
    _skill(home)
    with pytest.raises(Refused, match="skills are off"):
        app_skills.scope("", "tout-partout", ["write_site_content"], Settings())


# --- the command ----------------------------------------------------------------


def test_the_command_scopes_and_says_where(home, capsys):
    _skill(home)
    from corparius import cli

    assert cli.main(["skills", "scope", "tout-partout", "--tools", "write_site_content"]) == 0
    said = capsys.readouterr().out
    assert "now applies to: write_site_content" in said
    assert "SKILL.md" in said, "the file it edited has to be named"


def test_the_command_exits_non_zero_on_a_refusal(home, capsys):
    _skill(home)
    from corparius import cli

    assert cli.main(["skills", "scope", "tout-partout", "--tools", "pas-un-outil"]) == 1
    assert "unknown tool" in capsys.readouterr().out


def test_the_command_lists_what_rides_everywhere(home, capsys):
    _skill(home)
    from corparius import cli

    assert cli.main(["skills", "scope", "--list-unscoped"]) == 0
    said = capsys.readouterr().out
    assert "tout-partout" in said
    assert "corparius skills scope NAME --tools" in said, "say how to fix what was just reported"


def test_listing_says_so_when_there_is_nothing_to_fix(home, capsys):
    _skill(home, tools="write_site_content")
    from corparius import cli

    assert cli.main(["skills", "scope", "--list-unscoped"]) == 0
    assert "nothing to scope" in capsys.readouterr().out
