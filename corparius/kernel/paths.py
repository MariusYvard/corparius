"""Where things live on disk.

`<data_path>/sites/<slug>` was spelled out in nine places across the CLI, the
tools, the console and the MCP server. Nine chances to disagree about where a
company's site is, and the operator finds out by getting a 404 on a site that
was built somewhere else.

This module is also the one place that knows the difference between two kinds of
location, a distinction that only matters once corparius ships as a frozen
binary (PyInstaller), where the code lives in a read-only bundle:

  * resource_dir()  read-only files shipped *with* the program: webui.html, the
                    built console under corparius/api/static/, the example
                    company, .env.example. Under a frozen build this is
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
#
# Two `.parent` calls, not one, and the count is load-bearing: this file lives in
# `corparius/kernel/`, so the package directory is its grandparent. When it moved down one
# level every shipped resource — the example skills, webui.html, the seeded companies —
# resolved one directory too deep, and twelve tests said so at once. Anchoring on the
# *package* rather than on this file is what keeps that from depending on where the
# resolver happens to sit; see `_PACKAGE_DIR.name` below, which asserts it.
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PACKAGE_DIR.parent

assert _PACKAGE_DIR.name == "corparius", (
    f"paths.py resolved the package directory to {_PACKAGE_DIR}, which is not the package. "
    "Every shipped resource is found relative to it, and a wrong answer here is silent: "
    "files simply are not there."
)


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


def skills_dir() -> Path:
    """Skills that apply to every company (writable). Per-company skills live in
    `companies/<slug>/skills/` instead, next to the config they belong to."""
    return user_home() / "skills"


def company_skills_dir(slug: str) -> Path:
    return companies_dir() / (slug or "company") / "skills"


def company_site_dir(slug: str) -> Path:
    """A site the company owns, checked in next to its config.

    The generator writes one page under `data/sites/<slug>/` from `company.yaml`.
    That is the right thing for a company that has no site, and it is the wrong
    thing for one that has outgrown it — and nothing here could tell the
    difference. Measured on the owner's own install: `companies/vigil/site/`
    held six hand-built pages, a stylesheet, a serverless function, robots.txt
    and sitemap.xml, versioned in the company's own git repository — while the
    design agent regenerated a single page from four config fields every turn
    and `deploy_site` published *that*. The operator's site was invisible to the
    product that was supposedly maintaining it.

    So this is looked for first. `netlify.toml` and its `publish` key are
    honoured, because a company that wrote one has already said which folder is
    the site.
    """
    return companies_dir() / (slug or "company") / "site"


def company_apps_dir(slug: str) -> Path:
    """Apps that use the company's LLM providers for something other than the
    roster. Next to its skills and its config, for the same reason: an operator
    writes them, versions them, and expects them where the company lives."""
    return companies_dir() / (slug or "company") / "apps"


def dotenv_file() -> Path:
    """The .env the console writes and corparius/cfg.py reads as its lowest layer."""
    return user_home() / ".env"


def page_file() -> Path:
    """The single-file operator console HTML (a shipped resource).

    Served at `/legacy`, and at `/` when the built console is absent. It stays shipped because it is
    the one console that needs no build step, which is exactly what makes it the fallback.
    """
    return _resource("corparius", "webui.html")


def console_dir() -> Path:
    """The built console: a **directory** of assets, not one file.

    Stage 9's only packaging change, and it needs no new machinery for the same reason `webui.html`
    needs none: the build writes **inside the package**, at `corparius/api/static/`, so
    `_resource("corparius", "api", "static")` resolves in all three distribution modes — beside the
    package from a checkout, under `sys._MEIPASS` when frozen, inside site-packages from a wheel.
    Writing it beside the package instead would have needed the `_data/` fallback that `companies/`
    and `plugins/` need, for nothing.

    It can be **absent**, and that is a supported state rather than an error: the directory only
    exists after `npm run build`, and a source checkout that has never run it still has a working
    console — `/` falls back to `webui.html`. `console_built()` is the question a caller should ask,
    and since the switch it is what decides which console `/` serves at all.
    """
    return _resource("corparius", "api", "static")


def console_built() -> bool:
    """Whether the built console is present.

    The entry point is the thing checked, not the directory: an empty or half-written `static/`
    would pass a `is_dir()` test and then serve a 404 for the page itself, which reads to an
    operator as the console being broken rather than as not built.
    """
    return (console_dir() / "index.html").is_file()


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


def owned_site(slug: str) -> Path | None:
    """The company's own publishable folder, or None if it has no site of its own.

    Honours `netlify.toml`'s `publish` key when there is one: a company that
    wrote `publish = "public"` has already said which folder is the site, and
    publishing the repository root instead would push its config files and its
    serverless sources to the web.
    """
    base = company_site_dir(slug)
    if not base.is_dir():
        return None
    toml = base / "netlify.toml"
    if toml.is_file():
        try:
            for line in toml.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "publish":
                    named = base / value.strip().strip("'\"").rstrip("/")
                    if named.is_dir():
                        return named
        except OSError:
            pass
    for guess in ("public", "dist", "build", "_site"):
        if (base / guess).is_dir():
            return base / guess
    return base if any(base.glob("*.html")) else None


def published_dir(site_dir_path: str) -> str:
    """Default target of the local deploy provider: a sibling of the built site."""
    return os.path.join(os.path.dirname(str(site_dir_path).rstrip("/\\")), "published")
