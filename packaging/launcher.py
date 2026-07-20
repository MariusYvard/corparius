#!/usr/bin/env python3
"""Entry point for the standalone (frozen) corparius build.

Unlike start.py it does not create a virtualenv or install anything: the
dependencies are baked into the binary. It prepares the writable home (a per-OS
application-data folder, resolved by corparius/paths.py), seeds .env and the example
company on first run, runs the doctor, then serves the operator console and
opens the browser. From the user's point of view it behaves exactly like
`python start.py`:

    corparius              # first run and every run after
    corparius --no-browser
"""

from __future__ import annotations

import shutil
import sys
import webbrowser


def _log(msg: str) -> None:
    print(f"[corparius] {msg}")


def _prepare_home() -> None:
    from corparius import company as company_mod
    from corparius import paths

    home = paths.user_home()
    home.mkdir(parents=True, exist_ok=True)
    env = paths.dotenv_file()
    if not env.is_file():
        src = paths.resource_dir() / ".env.example"
        if src.is_file():
            shutil.copyfile(src, env)
            _log(f"created {env}")
            _log("offline mock mode by default: no network, no keys, no spend")
    company_mod.seed_examples()


def _announce_update() -> None:
    """Only calls out when the operator has turned CORP_UPDATE_CHECK on."""
    from corparius import update_check

    info = update_check.check()
    if info.get("enabled") and info.get("update_available"):
        _log(
            f"a newer version is available: {info['latest']} "
            f"(you run {info['current']}). Download: {info['url']}"
        )


def main() -> int:
    _prepare_home()
    from corparius.config import Settings
    from corparius.doctor import main as doctor_main
    from corparius.webui import serve

    _log("running the doctor (see the Settings tab for details any time)")
    doctor_main(quiet=True)
    _announce_update()
    s = Settings()
    if s.llm_mock:
        _log("mode: mock (offline, deterministic; no network, no keys, no spend)")
    url = f"http://{s.ui_host}:{s.ui_port}"
    _log(f"console starting on {url} (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return serve(s)


if __name__ == "__main__":
    raise SystemExit(main())
