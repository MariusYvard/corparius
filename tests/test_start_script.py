"""`start.py` — the double-click entry point, and the only place that builds the console.

It is not part of the package: no test imported it until this file, and nothing measured it. That
was tolerable while it only made a venv and pip-installed, because a failure there is loud. Building
the console is different — **its failure mode is serving an old bundle forever**, which looks
exactly like the code not having changed, so the staleness comparison is worth a test.

Why it may run npm at all, since the plan forbids Node at runtime: this is a *checkout* entry point.
It creates a virtualenv and installs from `requirements.txt`, neither of which a wheel or a frozen
binary does. The rule is about the product, and the product's console is built by CI and ships
inside the package. Nothing here runs from either.
"""

import importlib.util
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _start():
    """Load `start.py` by path. It is a script at the repository root, not a module on the path,
    and it must stay that way — `python start.py` is the instruction printed on the box."""
    spec = importlib.util.spec_from_file_location("corparius_start", ROOT / "start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


start = _start()


# --- what it announces ----------------------------------------------------------


def test_every_state_the_build_can_report_has_a_line():
    """Both ends of the wire, on the smallest registry in the project. `console_line` indexes a
    dict, so a state returned with no entry is a `KeyError` on the last line before the server
    starts — after the venv, the install and the doctor, on somebody's first run."""
    import ast

    source = (ROOT / "start.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    build = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_console"
    )
    returned = {
        node.value.value
        for node in ast.walk(build)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant)
    }
    assert returned, "build_console returns no literal state; this test has gone blind"
    for state in returned:
        assert start.console_line(state), state

    # And the other end: a line nobody can reach is a message that will never be read.
    main = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    reachable = returned | {
        node.value
        for node in ast.walk(main)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    lines = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "console_line"
    )
    declared = {
        key.value
        for node in ast.walk(lines)
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant)
    }
    assert declared <= reachable, f"unreachable console states: {sorted(declared - reachable)}"


def test_each_line_says_which_console_and_never_lies_about_freshness():
    assert "Svelte" in start.console_line("built")
    assert "just now" in start.console_line("built")
    # The one that matters: `--no-build` skipped the check that would know, so it must not claim
    # the bundle is current.
    assert "just now" not in start.console_line("built-stale")
    assert "just now" not in start.console_line("current"), "no build ran; do not claim one did"
    assert "single-file" in start.console_line("shipped")
    assert "Node" in start.console_line("shipped")


# --- staleness ------------------------------------------------------------------


def test_newest_is_the_deepest_mtime_and_zero_when_absent(tmp_path):
    assert start.newest(str(tmp_path / "nothing-here")) == 0.0
    tree = tmp_path / "src" / "deep"
    tree.mkdir(parents=True)
    old, new = tree / "a.js", tree / "b.js"
    old.write_text("a", encoding="utf-8")
    new.write_text("b", encoding="utf-8")
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))
    assert start.newest(str(tmp_path / "src")) == pytest.approx(2_000)
    # A file, not only a directory: `index.html` and `package.json` are watched directly.
    assert start.newest(str(new)) == pytest.approx(2_000)


def test_a_file_deep_in_the_tree_is_what_triggers_a_rebuild(tmp_path):
    """The comparison the whole thing rests on, written the way the failure happens: somebody edits
    one `.svelte` file five directories down, and the launcher has to notice. A shallow scan — or a
    comparison against the wrong side — serves the previous bundle with no complaint."""
    shell = tmp_path / "static" / "index.html"
    shell.parent.mkdir()
    shell.write_text("<!doctype html>", encoding="utf-8")
    os.utime(shell, (2_000, 2_000))

    src = tmp_path / "web" / "src"
    src.mkdir(parents=True)
    (src / "App.svelte").write_text("<h1/>", encoding="utf-8")
    os.utime(src / "App.svelte", (1_000, 1_000))
    assert os.path.getmtime(shell) >= start.newest(str(src)), "an untouched source is not stale"

    os.utime(src / "App.svelte", (3_000, 3_000))
    assert os.path.getmtime(shell) < start.newest(str(src)), "an edited source must rebuild"


def test_what_it_watches_is_everything_the_bundle_is_made_of():
    """Named rather than globbed, so this asserts the list against the directory. A source folder
    missing from it is the silent case: edits there would never trigger a rebuild."""
    assert set(start.BUILD_INPUTS) >= {"src", "i18n", "index.html", "package.json"}
    for entry in start.BUILD_INPUTS:
        assert (ROOT / "web" / entry).exists(), f"{entry} is watched and is not there"
    # The other direction: nothing in `web/` that feeds the bundle is left out. `node_modules` is
    # excluded because npm owns its mtimes, and a lockfile change lands in package.json's folder.
    ignored = {"node_modules", "README.md", "package-lock.json"}
    for entry in sorted(os.listdir(ROOT / "web")):
        assert entry in ignored or entry in start.BUILD_INPUTS, (
            f"web/{entry} is neither watched nor declared ignorable"
        )


# --- the decision itself --------------------------------------------------------


@pytest.fixture()
def fake_web(tmp_path, monkeypatch):
    """A `web/` and a shell, with npm replaced by a recorder. The comparison inside
    `build_console` is the load-bearing line, and the tests above only exercise its two halves —
    an inverted operator passes every one of them and never rebuilds again."""
    web = tmp_path / "web"
    (web / "src").mkdir(parents=True)
    (web / "i18n").mkdir()
    (web / "node_modules").mkdir()
    for name in ("index.html", "package.json", "vite.config.js"):
        (web / name).write_text("{}", encoding="utf-8")
    (web / "src" / "App.svelte").write_text("<h1/>", encoding="utf-8")
    shell = tmp_path / "static" / "index.html"
    shell.parent.mkdir()

    calls: list[list[str]] = []
    code = {"rc": 0}

    class Result:
        def __init__(self, rc):
            self.returncode = rc

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if code["rc"] == 0 and cmd[1:] == ["run", "build"]:
            shell.write_text("<!doctype html>", encoding="utf-8")
            os.utime(shell, (9_000, 9_000))
        return Result(code["rc"])

    monkeypatch.setattr(start, "WEB", str(web))
    monkeypatch.setattr(start, "SHELL", str(shell))
    monkeypatch.setattr(
        start.shutil, "which", lambda name: "/usr/bin/npm" if name == "npm" else None
    )
    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start, "step", lambda message: None)
    return {"web": web, "shell": shell, "calls": calls, "code": code}


def test_a_missing_shell_is_built(fake_web):
    assert start.build_console() == "built"
    assert ["/usr/bin/npm", "run", "build"] in fake_web["calls"]


def test_an_edited_source_rebuilds(fake_web):
    fake_web["shell"].write_text("old", encoding="utf-8")
    os.utime(fake_web["shell"], (2_000, 2_000))
    os.utime(fake_web["web"] / "src" / "App.svelte", (3_000, 3_000))
    assert start.build_console() == "built"
    assert ["/usr/bin/npm", "run", "build"] in fake_web["calls"]


def test_an_untouched_tree_is_not_rebuilt(fake_web):
    """The other half, and the reason a normal launch is not slower than it was: nothing changed,
    so npm is never invoked. Without this, `build_console` could satisfy every other test here by
    building unconditionally."""
    fake_web["shell"].write_text("current", encoding="utf-8")
    os.utime(fake_web["shell"], (9_000, 9_000))
    for entry in ("src", "i18n", "index.html", "package.json", "vite.config.js"):
        target = fake_web["web"] / entry
        for path in [target, *(target.rglob("*") if target.is_dir() else [])]:
            os.utime(path, (1_000, 1_000))
    assert start.build_console() == "current"
    assert fake_web["calls"] == [], "npm ran for a build that was already current"


def test_a_failed_build_serves_what_is_there_and_does_not_stop_the_launch(fake_web):
    """A broken front-end build must not stand between an operator and a console that works."""
    fake_web["code"]["rc"] = 1
    assert start.build_console() == "shipped"
    fake_web["shell"].write_text("an earlier build", encoding="utf-8")
    os.utime(fake_web["shell"], (2_000, 2_000))
    os.utime(fake_web["web"] / "src" / "App.svelte", (3_000, 3_000))
    assert start.build_console() == "built-stale"


def test_no_node_is_not_an_error(fake_web, monkeypatch):
    monkeypatch.setattr(start.shutil, "which", lambda name: None)
    assert start.build_console() == "shipped"
    fake_web["shell"].write_text("built elsewhere", encoding="utf-8")
    assert start.build_console() == "built-stale", (
        "a wheel or a binary arrives with the bundle already in it and no npm anywhere"
    )
    assert fake_web["calls"] == []


def test_the_build_tools_are_installed_only_when_they_are_missing(fake_web):
    (fake_web["web"] / "node_modules").rmdir()
    start.build_console()
    assert ["/usr/bin/npm", "ci"] == fake_web["calls"][0]
    fake_web["calls"].clear()
    (fake_web["web"] / "node_modules").mkdir()
    fake_web["shell"].unlink()
    start.build_console()
    assert ["/usr/bin/npm", "ci"] not in fake_web["calls"]


def test_nothing_it_prints_is_non_ascii():
    """This script prints before anything exists — no venv, no settings, no logging — straight to
    whatever console a double-click opened. On a French Windows install that console is cp850, and
    while `print` reaches a real console window through `WriteConsoleW` and copes, a **redirected**
    one (`start.py > log.txt`, which is what somebody does when asked for output) encodes with the
    locale and raises `UnicodeEncodeError`. Crashing the launcher over a typographic dash is a
    ridiculous way to fail, so the rule is that every printed string is ASCII.

    Docstrings and comments are exempt and stay as they are: they are read in an editor, never
    written to a stream.
    """
    printed: list[str] = []
    for line in (ROOT / "start.py").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not ("step(" in line or '"console:' in line):
            continue
        printed.append(line)
    assert printed, "no printed lines found; this test has gone blind"
    offenders = [line.strip() for line in printed if any(ord(c) > 127 for c in line)]
    assert not offenders, f"non-ASCII in what the launcher prints: {offenders}"


def test_the_node_version_it_names_is_the_one_npm_enforces():
    """The message is read by somebody about to install something, so it must not be a round number
    of my own invention. It is `engines` from `web/package.json` — what npm itself checks — and Vite
    7 refuses Node 20.0, so "Node 20+" would have sent them to a version that installs and then
    cannot build."""
    import json as jsonlib

    package = jsonlib.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    assert start.node_requirement() == package["engines"]["node"]
    assert start.node_requirement() != "22 or newer", "the fallback fired; engines is unreadable"

    # The one number an operator is told to go and install has to be one the build accepts. `>=24`
    # in the range is what makes "install Node 24" true, and 23 is exactly the trap: it is newer
    # than 22 and the range excludes it.
    assert f">={start.NODE_ADVICE}" in package["engines"]["node"], (
        f"start.py advises Node {start.NODE_ADVICE} and engines does not accept it"
    )

    installed = jsonlib.loads(
        (ROOT / "web" / "node_modules" / "vite" / "package.json").read_text(encoding="utf-8")
    )
    for floor in ("20.19", "22.12"):
        assert floor in installed["engines"]["node"], (
            f"vite no longer requires {floor}; package.json's engines is now a guess"
        )
        assert floor in package["engines"]["node"], "engines is looser than the tool it installs"


def test_the_shell_it_watches_for_is_the_one_the_server_serves():
    """Two files naming the same path is how they drift. `start.py` cannot import corparius — it
    runs before the venv exists — so it spells the path out, and this is what keeps the two equal."""
    from corparius.kernel import paths

    assert pathlib.Path(start.SHELL).parts[-3:] == ("api", "static", "index.html")
    assert pathlib.Path(start.SHELL).name == (paths.console_dir() / "index.html").name
    assert pathlib.Path(start.SHELL).parent.name == paths.console_dir().name


def test_it_asks_the_venv_for_the_settings_rather_than_reading_dotenv():
    """Not new, and worth pinning while a test finally imports this file: `.env` is one layer of
    four, so the announced port and mode have to come from the interpreter that will serve them."""
    source = (ROOT / "start.py").read_text(encoding="utf-8")
    assert "from corparius.config import Settings" in source
    assert sys.executable not in source
