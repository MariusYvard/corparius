#!/usr/bin/env python3
"""One-command start for corparius: creates a virtualenv, installs the
dependencies, prepares .env and the example company, then serves the operator
console and opens it in your browser. Works on Windows, Linux and macOS.

    python start.py            # first run and every run after
    python start.py --no-browser
"""
from __future__ import annotations
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


def main() -> int:
    if sys.version_info < (3, 10):
        step(f"Python 3.10+ required, you run {sys.version.split()[0]}. Install a newer Python first.")
        return 1
    if not os.path.isfile(PY):
        step("creating the virtual environment (.venv)")
        venv.create(VENV, with_pip=True)
    step("installing dependencies (first run can take a minute)")
    r = subprocess.run([PY, "-m", "pip", "install", "-q", "-r",
                        os.path.join(ROOT, "requirements.txt")])
    if r.returncode != 0:
        step("dependency install failed; check your network and retry")
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
    port = os.environ.get("CORP_UI_PORT", "8600")
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
