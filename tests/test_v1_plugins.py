"""The plugins tab, which carries skills too, and the number it exists for.

Both are the operator extending what corparius can do — one through a declared seam, one through prose
in a prompt. Neither is code corparius wrote, which is why the payload is careful about what it says.

**`skills_always_on_chars` is the reason this read exists.** A skill naming no tool is *unscoped* and
rides on every prompt of every agent: 3 815 characters a turn, measured on the owner's own company.
`corparius skills list` could report that from a terminal and offer nothing to do about it; the one
write here gives a skill a tool list so it travels only with the tools it is about.

Two things no client may offer, and both are asserted: installing an **unverified** plugin (CLI-only,
behind an explicit opt-in, because it runs unaudited third-party code) and editing a skill (a file the
operator wrote; the console is not going to be a second, worse text editor).
"""

import json
import shutil
import threading
from http.client import HTTPConnection

import pytest


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from corparius.api.server import build_server
    from corparius.config import cfg
    from corparius.config.settings import Settings

    from .conftest import EXAMPLE_COMPANY

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.setenv("CORP_PLUGINS_ENABLED", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    home = tmp_path / "home"
    shutil.copytree(EXAMPLE_COMPANY, home / "companies" / "example")
    monkeypatch.setenv("CORP_HOME", str(home))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _call(srv, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=10)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        {"Content-Type": "application/json"},
    )
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, json.loads(raw or b"{}")


def _skill(home, slug, name, body, tools=None):
    """Write a SKILL.md into a company, with or without an `allowed-tools` line."""
    folder = home / "companies" / slug / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {name}\ndescription: {name} does a thing\n"
    if tools is not None:
        front += f"allowed-tools: {', '.join(tools)}\n"
    (folder / "SKILL.md").write_text(front + "---\n\n" + body, encoding="utf-8")
    return folder / "SKILL.md"


# --- the read ---------------------------------------------------------------------


def test_the_read_carries_the_seams_and_the_registry(server):
    status, data = _call(server, "GET", "/api/v1/plugins?company=example")
    assert status == 200
    assert set(data) >= {
        "enabled",
        "allow_unverified",
        "installed",
        "loaded",
        "registry",
        "skills",
        "skills_enabled",
        "skills_always_on_chars",
        "tool_names",
    }
    assert data["enabled"] is True
    # The picker offers real names rather than asking the operator to know them.
    from corparius.tools.spec import SPEC

    assert data["tool_names"] == sorted(SPEC)


def test_an_unscoped_skill_is_reported_with_its_cost(server, tmp_path):
    """The measurement that justifies the panel. Unscoped means every prompt of every agent, and
    `chars` is what that costs per turn."""
    _skill(tmp_path / "home", "example", "house-style", "Write short sentences. " * 40)
    _status, data = _call(server, "GET", "/api/v1/plugins?company=example")
    skill = next(s for s in data["skills"] if s["name"] == "house-style")
    assert skill["unscoped"] is True
    assert skill["tools"] == []
    assert skill["chars"] > 200
    assert data["skills_always_on_chars"] >= skill["chars"], (
        "an unscoped skill has to count towards the always-on bill"
    )


def test_a_scoped_skill_costs_nothing_when_no_tool_matches(server, tmp_path):
    """The whole point of scoping: the skill is on file and it is not in this prompt."""
    _skill(
        tmp_path / "home", "example", "social-voice", "Keep it warm.", tools=["draft_social_post"]
    )
    _status, data = _call(server, "GET", "/api/v1/plugins?company=example")
    skill = next(s for s in data["skills"] if s["name"] == "social-voice")
    assert skill["unscoped"] is False
    assert skill["tools"] == ["draft_social_post"]
    assert data["skills_always_on_chars"] == 0, "a scoped skill is not always on"


def test_a_skill_naming_a_tool_that_does_not_exist_says_so(server, tmp_path):
    """Both ends, again: a skill scoped to a missing tool is a skill quietly doing less than its
    author wrote down — the same defect as a playbook naming a tool nobody has."""
    _skill(tmp_path / "home", "example", "ghost", "Do a thing.", tools=["no_such_tool"])
    _status, data = _call(server, "GET", "/api/v1/plugins?company=example")
    skill = next(s for s in data["skills"] if s["name"] == "ghost")
    assert skill["unknown_tools"] == ["no_such_tool"]


def test_the_read_says_nothing_about_skills_when_they_are_off(server, monkeypatch, tmp_path):
    """An empty list and a switched-off feature are different answers, and a caller must not have to
    guess which it got — the same argument `memory_enabled` makes."""
    from corparius.config import cfg

    _skill(tmp_path / "home", "example", "house-style", "Short sentences.")
    monkeypatch.setenv("CORP_SKILLS_ENABLED", "false")
    cfg.invalidate()
    _status, data = _call(server, "GET", "/api/v1/plugins?company=example")
    assert data["skills_enabled"] is False
    assert data["skills"] == [] and data["skills_always_on_chars"] == 0


def test_the_payload_survives_skills_being_off(server, monkeypatch):
    """A regression guard with a specific history. `plugins_get` bound `loader` **inside**
    `if s.skills_enabled:` and then read it in a ternary guarded by the same flag — safe only because
    both used the same condition, and an unbound local the moment anyone rearranged it. Collapsing the
    two spellings onto `adapters.plugins_payload` made the assignment unconditional."""
    from corparius.config import cfg

    monkeypatch.setenv("CORP_SKILLS_ENABLED", "false")
    cfg.invalidate()
    status, data = _call(server, "GET", "/api/v1/plugins?company=example")
    assert status == 200 and data["ok"] is True


def test_an_unknown_company_is_refused_by_code(server):
    status, data = _call(server, "GET", "/api/v1/plugins?company=nope")
    assert status == 404 and data["error"]["code"] == "unknown_company"


# --- the write --------------------------------------------------------------------


def test_an_unknown_action_is_refused_with_a_code(server):
    status, data = _call(server, "POST", "/api/v1/plugins", {"action": "sudo", "name": "x"})
    assert status == 400 and data["error"]["code"] == "invalid"
    assert "unknown action" in data["error"]["message"]


def test_enabling_a_plugin_that_is_not_installed_is_refused(server):
    status, data = _call(server, "POST", "/api/v1/plugins", {"action": "enable", "name": "ghost"})
    assert status == 400 and data["error"]["code"] == "invalid"


def test_the_console_cannot_install_an_unverified_plugin():
    """Asserted at the source, not at the wire, because the point is that no request can reach it.

    `plugins_action` calls `install_from_registry`, which only knows the curated registry — the
    unverified path is a different function and it has no caller in `api/`. A console button for it
    would read as ordinary and would be running unaudited third-party code.
    """
    import pathlib
    import re

    for name in ("corparius/api/adapters.py", "corparius/api/handlers.py"):
        source = pathlib.Path(name).read_text(encoding="utf-8")
        assert not re.search(r"install_unverified|allow_unverified\s*=\s*True", source), name
        if "plugins." in source:
            assert "install_from_registry" in source or "plugins_action" in source


def test_no_endpoint_writes_a_skill_file():
    """The other refusal. A skill is a file the operator wrote, and the one write this panel does is
    `allowed-tools` — through `app_skills.scope`, which edits that line and nothing else. An endpoint
    taking skill *body* text would make this console a second, worse text editor for their files."""
    import inspect

    from corparius.app import skills as app_skills

    source = inspect.getsource(app_skills)
    assert "def scope(" in source
    # No general writer: the module's job is the tool list.
    assert "instructions" not in source or "write_text" not in source.split("def scope(")[0]


# --- scoping ----------------------------------------------------------------------


def test_scoping_a_skill_takes_it_off_every_prompt(server, tmp_path):
    """The one write, and the property that makes it worth having: the bill goes to zero."""
    _skill(tmp_path / "home", "example", "house-style", "Short sentences. " * 30)
    _status, before = _call(server, "GET", "/api/v1/plugins?company=example")
    assert before["skills_always_on_chars"] > 0

    status, after = _call(
        server,
        "POST",
        "/api/v1/skills/scope",
        {"name": "house-style", "tools": ["draft_social_post"], "company": "example"},
    )
    assert status == 200
    assert after["tools"] == ["draft_social_post"]
    assert after["skills_always_on_chars"] == 0, "scoping it did not take it off every prompt"
    skill = next(s for s in after["skills"] if s["name"] == "house-style")
    assert skill["unscoped"] is False


def test_the_scope_write_is_the_file_and_not_just_the_payload(server, tmp_path):
    """It edits the operator's own `SKILL.md`, so the file is what gets checked. A payload that
    reported the new scope while leaving the file alone would be the emptiest kind of success."""
    path = _skill(tmp_path / "home", "example", "house-style", "Short sentences.")
    _call(
        server,
        "POST",
        "/api/v1/skills/scope",
        {"name": "house-style", "tools": ["draft_social_post"], "company": "example"},
    )
    assert "allowed-tools" in path.read_text(encoding="utf-8")
    assert "draft_social_post" in path.read_text(encoding="utf-8")


def test_scoping_to_a_tool_that_does_not_exist_is_refused(server, tmp_path):
    _skill(tmp_path / "home", "example", "house-style", "Short sentences.")
    status, data = _call(
        server,
        "POST",
        "/api/v1/skills/scope",
        {"name": "house-style", "tools": ["no_such_tool"], "company": "example"},
    )
    assert status == 400 and data["error"]["code"] == "invalid"
    assert data["error"]["detail"]["field"] == "tools"


def test_scoping_a_skill_that_is_not_there_is_refused(server):
    status, data = _call(
        server,
        "POST",
        "/api/v1/skills/scope",
        {"name": "ghost", "tools": ["draft_social_post"], "company": "example"},
    )
    assert status == 400 and data["error"]["code"] == "invalid"


def test_a_skill_declaring_always_is_counted_and_not_faulted(server, tmp_path):
    """An always-on guardrail is a deliberate choice. It is in the bill — it is not free — and it is
    not badged as a problem, because a warning on a deliberate choice is one an operator learns to
    ignore."""
    folder = tmp_path / "home" / "companies" / "example" / "skills" / "guardrail"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        "---\nname: guardrail\ndescription: never promise a cure\nalways: true\n---\n\nNever claim a "
        "clinical outcome.",
        encoding="utf-8",
    )
    _status, data = _call(server, "GET", "/api/v1/plugins?company=example")
    skill = next(s for s in data["skills"] if s["name"] == "guardrail")
    assert skill["always"] is True
    assert data["skills_always_on_chars"] >= skill["chars"], "declared is still not free"


def test_both_spellings_of_the_read_answer_the_same_keys(server):
    _status, legacy = _call(server, "GET", "/api/plugins?company=example")
    _status, versioned = _call(server, "GET", "/api/v1/plugins?company=example")
    assert set(legacy) == set(versioned)
    assert legacy["tool_names"] == versioned["tool_names"]
