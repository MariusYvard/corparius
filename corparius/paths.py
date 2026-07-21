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
                    store, .env, the companies they create, backups. From a
                    source checkout it is the repository root, so nothing about
                    running from source changes; frozen or pip-installed, it is a
                    per-OS application-data directory.

There are three distribution modes and this module is what tells them apart:

  * source checkout - resources sit beside the package (companies/, plugins/) or
    inside it (corparius/webui.html); writable state lives at the repo root.
    Detected by pyproject.toml next to the package. This is what the tests run,
    and its behaviour is byte-identical to before packaging.
  * frozen binary (PyInstaller) - resources under sys._MEIPASS, state per-OS.
  * pip-installed wheel - the package lives in site-packages with no sibling
    companies/ or plugins/, so those resources ride along inside the package
    under _data/ and are found there as a fallback; state goes to the per-OS
    directory, never into site-packages.

Precedence for user_home(): CORP_HOME wins; then, unless this is a source
checkout, the per-OS directory; otherwise the repository root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The package directory (corparius/) and its parent. In a source checkout the
# parent is the repository root; in a wheel it is site-packages.
_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent


def is_frozen() -> bool:
    """True inside a PyInstaller (or similar) one-file/one-dir bundle."""
    return bool(getattr(sys, "frozen", False))


def _is_source_checkout() -> bool:
    """A checkout carries pyproject.toml beside the package; a wheel in
    site-packages does not. This is the marker that keeps source-mode behaviour
    (and the test suite) unchanged while letting an install route resources and
    state correctly."""
    return (_REPO_ROOT / "pyproject.toml").is_file()


def resource_dir() -> Path:
    """Root of the read-only files shipped with the program (repo root from a
    checkout, the extraction dir when frozen). See _resource() for the installed
    case, where the files live inside the package instead."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _REPO_ROOT


def _resource(*parts: str) -> Path:
    """A read-only shipped file, found across all three distribution modes.

    Source and frozen use the repo-root/_MEIPASS layout via resource_dir(). A
    wheel has no sibling companies/ or plugins/ in site-packages, so the same
    files are force-included inside the package under _data/ at build time and
    picked up there when the primary location is absent. webui.html needs no
    fallback: it already lives inside the package, so resource_dir()/corparius/
    resolves to it in every mode."""
    primary = resource_dir().joinpath(*parts)
    if primary.exists():
        return primary
    return _PACKAGE_DIR.joinpath("_data", *parts)


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
    if is_frozen() or not _is_source_checkout():
        # Frozen or pip-installed: writing state next to the code is wrong (a
        # read-only bundle, or site-packages), so use the per-OS directory.
        return _platform_home()
    return _REPO_ROOT


def default_data_dir() -> str:
    """Default for CORP_DATA_PATH when the operator has not set it. Kept as the
    cwd-relative "./data" from a source checkout (unchanged, and never reached by
    the tests, which always set CORP_DATA_PATH), and an absolute per-OS path once
    frozen, pip-installed, or when CORP_HOME points somewhere explicit."""
    if is_frozen() or not _is_source_checkout() or os.environ.get("CORP_HOME", "").strip():
        return str(user_home() / "data")
    return "./data"


def companies_dir() -> Path:
    """Where the operator's companies live (writable)."""
    return user_home() / "companies"


def dotenv_file() -> Path:
    """The .env the console writes and corparius/cfg.py reads as its lowest layer."""
    return user_home() / ".env"


def page_file() -> Path:
    """The single-file operator console HTML (a shipped resource)."""
    return _resource("corparius", "webui.html")


def example_company_src() -> Path:
    """The bundled example company, copied into a fresh writable companies dir
    on first run (see corparius/company.seed_examples)."""
    return _resource("companies", "example")


def plugin_registry_file() -> Path:
    """The curated plugin allow-list shipped with the program."""
    return _resource("plugins", "registry.json")


def site_dir(data_path: str, slug: str) -> Path:
    return Path(data_path) / "sites" / (slug or "company")


def site_index(data_path: str, slug: str) -> Path:
    return site_dir(data_path, slug) / "index.html"


def published_dir(site_dir_path: str) -> str:
    """Default target of the local deploy provider: a sibling of the built site."""
    return os.path.join(os.path.dirname(str(site_dir_path).rstrip("/\\")), "published")
