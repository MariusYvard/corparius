#!/usr/bin/env python3
"""One-command start for corparius: creates a virtualenv, installs the
dependencies, builds the console if it can, prepares .env and the example company,
then serves the console and opens it in your browser. Works on Windows, Linux and macOS.

    python start.py            # first run and every run after
    python start.py --no-browser
    python start.py --no-build   # skip the console build, serve whatever is there
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(ROOT, ".venv")
IS_WIN = os.name == "nt"
PY = os.path.join(VENV, "Scripts" if IS_WIN else "bin", "python.exe" if IS_WIN else "python")


def step(msg: str) -> None:
    print(f"[corparius] {msg}")


def resolved() -> dict:
    """Ask the venv interpreter what the settings actually resolve to. Asking it
    rather than reading .env here is the point: .env is only one of the layers
    (see corparius/cfg.py), so this is the only honest way to know the real mode and
    port before announcing them."""
    code = (
        "import json; from corparius.config import Settings; s = Settings();"
        "print(json.dumps({'port': s.ui_port, 'mock': s.llm_mock,"
        " 'cloud': s.cloud_enabled, 'claude_code': s.claude_code_enabled}))"
    )
    r = subprocess.run([PY, "-c", code], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


WEB = os.path.join(ROOT, "web")
SHELL = os.path.join(ROOT, "corparius", "api", "static", "index.html")
# What a rebuild watches. Everything the bundle is made of and nothing that only changes when
# somebody edits Python, so a normal launch does not pay for a build it does not need.
BUILD_INPUTS = ("src", "i18n", "index.html", "package.json", "vite.config.js")
# The one version told to somebody who has to go and install it. A test asserts `engines` accepts
# it, so this cannot become advice the build then rejects.
NODE_ADVICE = "24"


def node_requirement() -> str:
    """The Node version the build needs, read from `web/package.json` rather than written here.

    Two places naming a version is how they drift, and this one is told to a person who is about to
    install something. `engines` is what npm itself checks, so the message and the requirement are
    the same string by construction.
    """
    try:
        with open(os.path.join(WEB, "package.json"), encoding="utf-8") as handle:
            return str(json.load(handle)["engines"]["node"])
    except (OSError, ValueError, KeyError):
        return "22 or newer"


def newest(path: str) -> float:
    """The most recent mtime at or under `path`, or 0 if it is not there."""
    if os.path.isfile(path):
        return os.path.getmtime(path)
    latest = 0.0
    for folder, _dirs, files in os.walk(path):
        for name in files:
            latest = max(latest, os.path.getmtime(os.path.join(folder, name)))
    return latest


def build_console() -> str:
    """Build the console when Node is here, and say plainly what will be served when it is not.

    This is a **checkout** entry point — it makes a virtualenv and pip-installs — so running npm
    here breaks no rule. The rule the plan states is about the *product*: the wheel and the frozen
    binary must serve the console with no Node installed, which they do because CI builds it and
    the assets ship inside the package. Nothing in this function runs from either of those.

    Node absent is not a failure. `/` falls back to the single-file page, which is a whole working
    console, so the honest thing is one line saying which one you are about to look at rather than
    an error about a tool this program does not require.
    """
    if not os.path.isdir(WEB):
        return "shipped"  # an installed wheel: no sources, and the bundle already inside it
    npm = shutil.which("npm")
    if not npm:
        if os.path.isfile(SHELL):
            return "built-stale"
        step("Node is not installed, so the console you get is the single-file page.")
        # One number to act on, and the real range underneath it. The range alone —
        # `^20.19 || ^22.12 || >=24` — is what npm enforces and is unreadable to somebody who is
        # here because they double-clicked a file; a round "Node 20+" is readable and wrong, because
        # Vite 7 refuses 20.0. So: say 24, and print what is actually accepted next to it.
        step(f"  For the new one: install Node {NODE_ADVICE}, then run this again.")
        step(f"  (any of: {node_requirement()})")
        return "shipped"
    if not os.path.isdir(os.path.join(WEB, "node_modules")):
        # Not captured, unlike the build below: this one takes about a minute, and a double-click
        # with a silent minute in it reads as a hang.
        step("installing the console's build tools (first run only, about a minute)")
        if subprocess.run([npm, "ci"], cwd=WEB).returncode != 0:
            step("npm ci failed; serving the single-file console instead.")
            return "shipped" if not os.path.isfile(SHELL) else "built-stale"
    stale = max((newest(os.path.join(WEB, p)) for p in BUILD_INPUTS), default=0.0)
    if os.path.isfile(SHELL) and os.path.getmtime(SHELL) >= stale:
        # Distinct from "built" so the line printed does not claim a build that did not happen. It
        # is the same console either way; the difference is whether the operator is owed the word
        # "just now", and a launcher that says it every time teaches you not to read it.
        return "current"
    step("building the console")
    if subprocess.run([npm, "run", "build"], cwd=WEB, capture_output=True).returncode != 0:
        # Deliberately not fatal, and deliberately not silent. A broken front-end build must not
        # stop someone from reaching a console that works.
        step("the console build failed. Run `npm run build` in web/ to see why.")
        step("  starting anyway; you will get the console that is already there.")
        return "built-stale" if os.path.isfile(SHELL) else "shipped"
    return "built"


def console_line(state: str) -> str:
    return {
        "built": "console: the new one (Svelte, built just now)",
        "current": "console: the new one (Svelte, already up to date)",
        "built-stale": "console: the new one (Svelte, from an earlier build, not rebuilt)",
        "shipped": "console: the single-file page (the new one needs Node to build)",
    }[state]


def mode_line(info: dict) -> str:
    if info.get("mock", True):
        return "mode: mock (offline, deterministic; no network, no keys, no spend)"
    if not info.get("cloud") and not info.get("claude_code"):
        return "mode: live, local only (Ollama serves every tier; no remote spend)"
    return (
        "mode: LIVE with remote providers enabled. Real calls, real spend. "
        "Flip it in the console (Providers) or set CORP_LLM_MOCK=true."
    )


def main() -> int:
    if sys.version_info < (3, 10):
        step(
            f"Python 3.10+ required, you run {sys.version.split()[0]}. Install a newer Python first."
        )
        return 1
    if not os.path.isfile(PY):
        step("creating the virtual environment (.venv)")
        try:
            venv.create(VENV, with_pip=True)
        except Exception as exc:
            # Debian/Ubuntu often ship Python without venv/ensurepip.
            step(f"could not create the virtual environment: {exc}")
            step("on Debian/Ubuntu run: sudo apt install python3-venv, then try again.")
            return 1
    if not os.path.isfile(PY):
        step("the virtual environment is missing its Python; delete the .venv folder and retry.")
        return 1
    step("installing dependencies (first run can take a minute)")
    r = subprocess.run(
        [PY, "-m", "pip", "install", "-q", "-r", os.path.join(ROOT, "requirements.txt")]
    )
    if r.returncode != 0:
        step(
            "dependency install failed. Check your internet connection and run this again; "
            "if you are behind a proxy, set HTTPS_PROXY first."
        )
        return r.returncode
    # `--no-build` cannot claim the bundle is current: it skipped the check that would know.
    console = "built-stale" if os.path.isfile(SHELL) else "shipped"
    if "--no-build" not in sys.argv:
        console = build_console()
    env_file = os.path.join(ROOT, ".env")
    if not os.path.isfile(env_file):
        shutil.copyfile(os.path.join(ROOT, ".env.example"), env_file)
        step("created .env from .env.example (offline mock mode by default)")
    example = os.path.join(ROOT, "companies", "example", "company.yaml")
    if os.path.isfile(example):
        subprocess.run(
            [PY, "-m", "corparius.cli", "init", "--company", example], cwd=ROOT, capture_output=True
        )
    step("running the doctor (python -m corparius.cli doctor for details any time)")
    subprocess.run([PY, "-m", "corparius.cli", "doctor", "--quiet"], cwd=ROOT)
    info = resolved()
    step(mode_line(info))
    step(console_line(console))
    # The one thing worth saying unprompted on a first run: someone holding a
    # Claude subscription and the CLI is one command away from running every
    # tier on a login they already have, and would otherwise never find out.
    if shutil.which("claude") and not info.get("claude_code"):
        step(
            "you have the `claude` CLI: `corparius claude` runs every tier on your "
            "subscription, no API key"
        )
    port = info.get("port", 8600)
    url = f"http://127.0.0.1:{port}"
    step(f"console starting on {url} (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return subprocess.run([PY, "-m", "corparius.cli", "ui"], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
