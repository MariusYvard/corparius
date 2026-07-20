"""Where things live on disk.

`<data_path>/sites/<slug>` was spelled out in nine places across the CLI, the
tools, the console and the MCP server. Nine chances to disagree about where a
company's site is, and the operator finds out by getting a 404 on a site that
was built somewhere else.

This module is also the one place that knows the difference between two kinds of
location, a distinction that only matters once corparius ships as a frozen
binary (PyInstaller), where the code lives in a read-only bundle:

  * resource_dir()  read-only files shipped *with* the program: webui.html, the
                    example company, .env.example. Under a frozen build this is
                    the extraction dir (sys._MEIPASS); from a source checkout it
                    is the repository root.
  * user_home()     the writable place for the operator's own state: the SQLite
                    store, .env, the companies they create, backups. Frozen, it
                    is a per-OS application-data directory; from a checkout it is
                    the repository root, so nothing about running from source
                    changes.

Precedence for user_home(): the CORP_HOME environment variable wins (an explicit
override, e.g. to point a fresh binary at an existing checkout's data); then, for
a frozen build, the per-OS directory; otherwise the repository root. Because a
source checkout resolves to the repository root, every default is byte-identical
to the pre-packaging behavior, and the test suite is unaffected.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The repository root when running from source (app/paths.py -> app -> root).
_REPO_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """True inside a PyInstaller (or similar) one-file/one-dir bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Root of the read-only files shipped with the program."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _REPO_ROOT


def _platform_home() -> Path:
    """The per-OS application-data directory for a frozen install."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "corparius"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "corparius"
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "corparius"


def user_home() -> Path:
    """Writable base for the operator's own state. See the module docstring for
    the precedence. In a source checkout this is the repository root, so running
    from source is unchanged."""
    override = os.environ.get("CORP_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    if is_frozen():
        return _platform_home()
    return _REPO_ROOT


def default_data_dir() -> str:
    """Default for CORP_DATA_PATH when the operator has not set it. Kept as the
    cwd-relative "./data" from a source checkout (unchanged, and never reached by
    the tests, which always set CORP_DATA_PATH), and an absolute per-OS path once
    frozen or when CORP_HOME points somewhere explicit."""
    if is_frozen() or os.environ.get("CORP_HOME", "").strip():
        return str(user_home() / "data")
    return "./data"


def companies_dir() -> Path:
    """Where the operator's companies live (writable)."""
    return user_home() / "companies"


def dotenv_file() -> Path:
    """The .env the console writes and app/cfg.py reads as its lowest layer."""
    return user_home() / ".env"


def page_file() -> Path:
    """The single-file operator console HTML (a shipped resource)."""
    return resource_dir() / "app" / "webui.html"


def example_company_src() -> Path:
    """The bundled example company, copied into a fresh writable companies dir
    on first run (see app/company.seed_examples)."""
    return resource_dir() / "companies" / "example"


def site_dir(data_path: str, slug: str) -> Path:
    return Path(data_path) / "sites" / (slug or "company")


def site_index(data_path: str, slug: str) -> Path:
    return site_dir(data_path, slug) / "index.html"


def published_dir(site_dir_path: str) -> str:
    """Default target of the local deploy provider: a sibling of the built site."""
    return os.path.join(os.path.dirname(str(site_dir_path).rstrip("/\\")), "published")
