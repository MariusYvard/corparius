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


def _never_crash_on_a_character() -> None:
    """Let output degrade to `?` rather than raise on the machine's codepage.

    A frozen build writes to stdout in the platform's ANSI encoding, and the
    bootloader initialises Python before PYTHONUTF8 or PYTHONIOENCODING could
    change that — verified: both are ignored. On a Western Windows every
    character corparius prints happens to encode, but the em dash and the
    accented French strings do not exist in a Cyrillic or a Japanese codepage,
    and a redirected `corparius doctor --lang fr` would die there with a
    UnicodeEncodeError instead of printing.

    `errors="replace"` changes nothing where encoding already succeeds; it only
    replaces a crash with a question mark. A diagnostic command that cannot
    survive being redirected to a file is not a diagnostic command.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass  # not a text stream, or already closed: nothing to harden


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
    _never_crash_on_a_character()
    _prepare_home()
    # A subcommand runs the CLI; nothing, or only flags, serves the console.
    #
    # This used to look at argv for exactly one string, `--no-browser`, and
    # serve the console whatever else was there. So `corparius doctor` started
    # the console, and every command the docs tell an operator to run — `apps
    # serve`, `skills install starter`, `bench`, `claude` — did not exist for
    # anyone who downloaded the binary, which is the install path the README
    # puts first. The files were even bundled: the starter skill pack rides
    # inside the executable with nothing able to ask for it.
    argv = sys.argv[1:]
    if argv and not argv[0].startswith("-"):
        from corparius.cli import main as cli_main

        cli_main(argv)  # commands that fail raise SystemExit themselves
        return 0

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
