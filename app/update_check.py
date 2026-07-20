"""Optional, opt-in version check.

Off by default (CORP_UPDATE_CHECK=false): corparius makes no network call unless
the operator turns this on, which honors the project's no-unconsented-network
rule. When on, it performs a single GET to the public GitHub releases API at
startup, never downloads anything, and only reports whether a newer tag exists so
the launcher and the console can show a link. Every failure is swallowed: a
version check must never keep the console from starting.
"""

from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import cfg

RELEASES_API = "https://api.github.com/repos/MariusYvard/corparius/releases/latest"
RELEASES_URL = "https://github.com/MariusYvard/corparius/releases/latest"


def current_version() -> str:
    import app

    return app.__version__


def enabled() -> bool:
    return cfg.get_bool("CORP_UPDATE_CHECK", "false")


def _parse(tag: str) -> tuple:
    """Loose semver tuple; unparsable parts count as 0 rather than raising."""
    out = []
    for part in tag.lstrip("vV").split("."):
        num = ""
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        out.append(int(num) if num else 0)
    return tuple(out)


def latest(timeout: float = 4.0) -> str | None:
    """The newest release tag, or None if unreachable. Single request, no auth."""
    try:
        req = Request(
            RELEASES_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "corparius-update-check",
            },
        )
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https URL)
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name")
        return tag or None
    except (URLError, ValueError, OSError):
        return None


def check(timeout: float = 4.0) -> dict:
    """A small dict the launcher and the console render. Never raises, never
    downloads. When disabled it makes NO network call and says so."""
    current = current_version()
    if not enabled():
        return {"enabled": False, "current": current}
    tag = latest(timeout)
    if not tag:
        return {"enabled": True, "reachable": False, "current": current}
    return {
        "enabled": True,
        "reachable": True,
        "current": current,
        "latest": tag.lstrip("vV"),
        "update_available": _parse(tag) > _parse(current),
        "url": RELEASES_URL,
    }
