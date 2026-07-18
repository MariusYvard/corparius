#!/usr/bin/env python3
"""One-command start for corparius: creates a virtualenv, installs the
dependencies, prepares .env and the example company, then serves the operator
console and opens it in your browser. Works on Windows, Linux and macOS.

    python start.py            # first run and every run after
    python start.py --no-browser
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
    (see app/cfg.py), so this is the only honest way to know the real mode and
    port before announcing them."""
    code = (
        "import json; from app.config import Settings; s = Settings();"
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


def mode_line(info: dict) -> str:
    if info.get("mock", True):
        return "mode: mock (offline, deterministic; no network, no keys, no spend)"
    if not info.get("cloud") and not info.get("claude_code"):
        return "mode: live, local only (Ollama serves every tier; no remote spend)"
    return ("mode: LIVE with remote providers enabled. Real calls, real spend. "
            "Flip it in the console (Providers) or set CORP_LLM_MOCK=true.")


def main() -> int:
    if sys.version_info < (3, 10):
        step(f"Python 3.10+ required, you run {sys.version.split()[0]}. Install a newer Python first.")
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
    r = subprocess.run([PY, "-m", "pip", "install", "-q", "-r",
                        os.path.join(ROOT, "requirements.txt")])
    if r.returncode != 0:
        step("dependency install failed. Check your internet connection and run this again; "
             "if you are behind a proxy, set HTTPS_PROXY first.")
        return r.returncode
    env_file = os.path.join(ROOT, ".env")
    if not os.path.isfile(env_file):
        shutil.copyfile(os.path.join(ROOT, ".env.example"), env_file)
        step("created .env from .env.example (offline mock mode by default)")
    example = os.path.join(ROOT, "companies", "example", "company.yaml")
    if os.path.isfile(example):
        subprocess.run([PY, "-m", "app.cli", "init", "--company", example],
                       cwd=ROOT, capture_output=True)
    step("running the doctor (python -m app.cli doctor for details any time)")
    subprocess.run([PY, "-m", "app.cli", "doctor", "--quiet"], cwd=ROOT)
    info = resolved()
    step(mode_line(info))
    port = info.get("port", 8600)
    url = f"http://127.0.0.1:{port}"
    step(f"console starting on {url} (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return subprocess.run([PY, "-m", "app.cli", "ui"], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
