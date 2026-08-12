"""The built console: where it is found, how it is served, and what happens when it is not there.

Stage 9's packaging step, done before any tab is rebuilt because it is the only part of the front
end with real risk. `paths.page_file()` has always resolved **one file** across three distribution
modes; this resolves a **directory**, and getting that wrong is silent — the files simply are not
there, and the console renders as a blank page.

The answer needed no new machinery, and that is the point worth defending: the build writes
**inside the package**, at `corparius/api/static/`, so the existing `_resource("corparius", ...)`
finds it beside the package from a checkout, under `sys._MEIPASS` when frozen, and inside
site-packages from a wheel. Writing it beside the package would have needed the `_data/` fallback
that `companies/` and `plugins/` need, for nothing.

**Absent is a supported state.** The directory exists only after `npm run build`. A checkout that
has never run it, and a wheel built without it, still have a working console at `/` — so the route
says "not built" and names the command, rather than serving an empty page or failing to start.

Verified by hand at the commit that added this, because a test cannot install a wheel cheaply: the
wheel was built, installed into a clean venv, and `/app/` served from site-packages with **no Node
installed** — 200 for the shell, the script, the stylesheet and the French chunk. The tests below
hold the parts of that a suite can hold.
"""

import json
import pathlib
import shutil
import threading
from http.client import HTTPConnection

import pytest

from corparius.kernel import paths

STATIC = pathlib.Path("corparius/api/static")
WEB = pathlib.Path("web")


# --- the source the bundle is built from ----------------------------------------


def test_the_front_end_source_is_here_and_declares_its_tools():
    """The build is a development and CI step, never a runtime one. This asserts the source exists
    and that nothing in it has crept into the package's own dependencies."""
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["build"] == "vite build"
    assert set(package["devDependencies"]) >= {"svelte", "vite"}
    assert "dependencies" not in package or not package["dependencies"], (
        "the console has no runtime npm dependencies; everything is bundled at build time"
    )
    assert (WEB / "src" / "App.svelte").is_file()
    assert (WEB / "src" / "api.js").is_file()
    assert (WEB / "src" / "i18n.js").is_file()


def test_the_dev_server_proxies_the_api_to_a_running_core():
    """`web/README.md` promised this from the day the folder existed and the config never had it, so
    `npm run dev` served the console and sent every `/api/...` call to Vite, which answered its own
    404 page — the console rendered and then said it could not reach the core.

    A test rather than a corrected sentence, because the failure is a *missing* line: nothing in a
    build, a lint or a suite notices config that was never written. Verified by hand at the commit
    that added it, against a core on a port of its own: `/api/v1/meta` through the dev server
    answered `schema_version 21` and `/api/companies` listed only the test home's company.
    """
    config = (WEB / "vite.config.js").read_text(encoding="utf-8")
    assert 'proxy: { "/api": CORE, "/site": CORE }' in config
    assert "process.env.CORP_UI_PORT || 8600" in config, (
        "the port must be the setting's, not a constant; a core on 9000 is a normal configuration"
    )
    # `/site` too: the Sales-site card renders the generated site in an iframe, and a preview that
    # 404s in development is the kind of thing that gets 'fixed' in the component instead.
    assert '"/site"' in config


def test_the_mark_is_the_brand_s_own_geometry():
    """The mark is drawn, and its four fills are **sampled from the brand file** rather than picked.

    It was the shipped page's 213x136 raster wordmark scaled to 46px behind a glow, and a blind design
    review called it the first thing a stranger sees and a dev placeholder — correctly: the art was
    being downscaled to a third of its size and the word *corparius* was baked into the bitmap, so the
    brand's own name rendered as four illegible pixels.

    This asserts the redraw did not invent a logo. The colours are the ones in
    `docs/icons/logo-corparius-mark.png`; if that file changes, this fails and somebody re-samples.
    """
    mark = (WEB / "src" / "Mark.svelte").read_text(encoding="utf-8")
    for fill in ("#51b436", "#f8d509", "#fb7f25", "#318ada"):
        assert fill in mark, f"{fill} is one of the brand mark's four fills"
    assert 'stroke="currentColor"' in mark, (
        "the rule follows the text colour so it holds on both themes"
    )
    assert not (WEB / "src" / "wordmark.png").exists(), (
        "the raster is gone; it must not ship as well"
    )
    # And the name is a string the operator's font renders, not pixels.
    shell = (WEB / "src" / "App.svelte").read_text(encoding="utf-8")
    assert '<span class="name">corparius</span>' in shell


def test_the_build_writes_inside_the_package():
    """The decision the whole packaging story rests on. `outDir` pointing anywhere else would need
    a per-mode fallback, and the mode it would break is the installed wheel — the one hardest to
    notice from a checkout."""
    config = (WEB / "vite.config.js").read_text(encoding="utf-8")
    assert 'outDir: "../corparius/api/static"' in config
    assert 'base: "/app/"' in config, (
        "the shell is served from both / and /app/, so its assets must be named absolutely; a "
        "relative base resolves them against whichever path was asked for and 404s from one of them"
    )


def test_the_wheel_and_the_frozen_build_both_declare_the_directory():
    """Two packaging paths, and a resource missing from either is invisible until someone installs
    it. The frozen one is guarded because PyInstaller fails the whole build on a datas entry that
    does not exist, and a binary without the new console is a working product."""
    import tomllib

    pyproject = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
    artifacts = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"]
    assert "corparius/api/static/**" in artifacts
    spec = pathlib.Path("packaging/corparius.spec").read_text(encoding="utf-8")
    assert '"corparius/api/static"' in spec
    assert '"index.html").is_file()' in spec, "the entry must be guarded, not unconditional"


# --- resolution -----------------------------------------------------------------


def test_the_directory_resolves_through_the_same_resolver_as_the_page():
    """Not a second mechanism. `console_dir()` is `_resource("corparius", "api", "static")`, which
    is `page_file()`'s path with a different tail — so a mode that finds one finds the other."""
    assert paths.console_dir() == paths.resource_dir() / "corparius" / "api" / "static" or (
        paths.console_dir().parts[-4:] == ("corparius", "api", "static")[-3:] + ()
    )
    assert paths.console_dir().name == "static"
    assert paths.console_dir().parent.name == "api"
    assert paths.console_dir().parent.parent == paths.page_file().parent


def test_built_is_the_entry_point_and_not_the_directory(tmp_path, monkeypatch):
    """An empty or half-written `static/` would pass an `is_dir()` test and then 404 the page
    itself, which reads to an operator as the console being broken rather than as not built."""
    monkeypatch.setattr(paths, "console_dir", lambda: tmp_path / "static")
    assert paths.console_built() is False
    (tmp_path / "static").mkdir()
    assert paths.console_built() is False, "a directory with nothing in it is not a built console"
    (tmp_path / "static" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    assert paths.console_built() is True


# --- over the wire --------------------------------------------------------------


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from corparius.api.server import build_server
    from corparius.config import cfg
    from corparius.config.settings import Settings

    from .conftest import EXAMPLE_COMPANY

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    home = tmp_path / "home"
    shutil.copytree(EXAMPLE_COMPANY, home / "companies" / "example")
    monkeypatch.setenv("CORP_HOME", str(home))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _fetch(srv, path):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=10)
    conn.request("GET", path)
    res = conn.getresponse()
    body = res.read()
    out = (res.status, res.getheader("Content-Type", ""), body)
    conn.close()
    return out


built = pytest.mark.skipif(
    not paths.console_built(), reason="the console is not built here; run `npm run build` in web/"
)


@built
def test_the_shell_is_served_with_its_assets(server):
    status, kind, body = _fetch(server, "/app/")
    assert status == 200 and "text/html" in kind
    assert b'<div id="app">' in body
    # Absolutely, because the same shell is served from `/` as well — see the base test above.
    assert b'src="/app/console.js"' in body
    for asset, expected in (("console.js", "javascript"), ("console.css", "text/css")):
        status, kind, body = _fetch(server, f"/app/{asset}")
        assert status == 200 and expected in kind, asset
        assert body, asset


@built
def test_the_french_table_is_a_separate_chunk(server):
    """English is in the bundle because it is the fallback for every key in every language; French
    is fetched only when chosen. Measured when both were inlined: 91 132 bytes, of which 57 325 were
    the two tables — 63%, half of it a language most operators never select."""
    status, _kind, body = _fetch(server, "/app/console-fr.js")
    assert status == 200 and len(body) > 10_000
    _status, _kind, main = _fetch(server, "/app/console.js")
    assert b"Cannot reach the corparius server" in main, "English travels with the bundle"
    assert b"Impossible de joindre" not in main, "French does not"


@built
def test_slash_serves_the_built_console(server):
    """The flag's job is over. The plan kept the old page at `/` "until the new bundle passes the
    i18n key-set equality test"; it passes, all seven tabs are rebuilt, and so `/` is the new
    console — which is what somebody gets from `start-windows.bat` without typing a path.

    Both, and the asset with them, because serving a shell whose `src` 404s is a 200 that renders
    a blank page — the exact failure an absolute base exists to prevent.
    """
    status, kind, body = _fetch(server, "/")
    assert status == 200 and "text/html" in kind
    assert b'<div id="app">' in body
    assert len(body) < 2_000, "that is the single-file page, not the new shell"
    assert _fetch(server, "/app/console.js")[0] == 200, "the shell's own script must resolve"


def test_slash_falls_back_to_the_shipped_page_when_nothing_is_built(server, monkeypatch):
    """The state of a fresh clone, and it is a fact about the checkout rather than a setting: there
    is no shell to serve, so `/` serves the page that needs no build. Neither state is broken, and
    nothing has to be configured to get either."""
    monkeypatch.setattr(paths, "console_built", lambda: False)
    status, kind, body = _fetch(server, "/")
    assert status == 200 and "text/html" in kind
    assert b"corparius console" in body and len(body) > 200_000


def test_the_shipped_page_keeps_a_path_of_its_own(server):
    """The way back, and unconditional — a path rather than an environment variable, because an
    operator who hits a bug in the new console needs somewhere to click, not something to set and
    a restart to do it. It answers the same whether a build exists or not."""
    status, kind, body = _fetch(server, "/legacy")
    assert status == 200 and "text/html" in kind
    assert len(body) > 200_000
    assert body == paths.page_file().read_bytes()


@built
@pytest.mark.parametrize(
    "path",
    [
        "/app/../../.env",
        "/app/..%2f..%2fwebui.html",
        "/app/%2e%2e/%2e%2e/pyproject.toml",
    ],
)
def test_nothing_outside_the_directory_is_served(server, path):
    """Resolve, then check the resolved path is still inside the root — the same guard the site
    preview uses, and checked on the resolved path rather than on the text of the URL."""
    status, _kind, body = _fetch(server, path)
    assert status == 404, f"{path} was served"
    assert b"CORP_" not in body and b"[project]" not in body


@built
def test_only_the_extensions_a_build_produces_are_served(server):
    """Narrower than the site preview's list on purpose: this directory is produced by
    `npm run build` and nothing else, so a `.py` or a `.sqlite` appearing in it means the build
    changed shape and somebody should look."""
    from corparius.api.handlers import CONSOLE_TYPES

    assert ".py" not in CONSOLE_TYPES and ".sqlite" not in CONSOLE_TYPES
    assert set(CONSOLE_TYPES) >= {".html", ".js", ".css"}
    (paths.console_dir() / "notes.txt").write_text("not an asset", encoding="utf-8")
    try:
        status, _kind, _body = _fetch(server, "/app/notes.txt")
        assert status == 404
    finally:
        (paths.console_dir() / "notes.txt").unlink()


def test_an_unbuilt_console_says_so_and_names_the_command(server, monkeypatch):
    """The state a fresh checkout is in, and it must not look like a broken installation."""
    monkeypatch.setattr(paths, "console_built", lambda: False)
    status, kind, body = _fetch(server, "/app/")
    assert status == 404 and "json" in kind
    payload = json.loads(body)
    assert "npm run build" in payload["error"]
    assert "/legacy" in payload["error"], "it has to point at the console that does work"


# The absolute URLs the bundle is allowed to contain, and why each one is not a request:
#
#   * the XHTML namespace, which is an identifier the DOM compares against and never fetches;
#   * `svelte.dev/e/<code>` links, which appear inside `console.warn` strings pointing a developer
#     at the explanation of a runtime warning.
#
# Declared rather than pretended away. The first version of the test below asserted that no
# absolute URL appears at all, which failed on both of these — a string containing a URL is not a
# request, and an assertion that cannot tell them apart teaches you to loosen it.
ALLOWED_ABSOLUTE = ("http://www.w3.org/1999/xhtml", "https://svelte.dev/e/")


@built
def test_the_console_fetches_nothing_from_outside_this_core():
    """A console that pulled a font or a script from a CDN would need the internet to render, on a
    product whose whole shape is that it does not — and on a machine whose console is deliberately
    on loopback behind a tunnel.

    Checked on what actually causes a request rather than on what looks like a URL: the two `fetch`
    call sites are this client and Svelte's own preload of a dynamic-import chunk, both same-origin
    by construction; there is no `XMLHttpRequest`, no `Worker`, no `importScripts`; and the shell
    names no absolute `src` or `href`.
    """
    import re

    bundle = (paths.console_dir() / "console.js").read_text(encoding="utf-8", errors="replace")
    shell = (paths.console_dir() / "index.html").read_text(encoding="utf-8")

    for mechanism in ("XMLHttpRequest", "importScripts", "new Worker", "eval("):
        assert mechanism not in bundle, f"the bundle uses {mechanism}"
    assert not re.findall(r'(?:src|href)="https?://', shell), "the shell names an absolute URL"

    # Every absolute URL that is in there has to be one of the two known non-requests. A new one
    # appearing is a dependency reaching out, and that is the thing worth failing on.
    found = set(re.findall(r"https?://[a-zA-Z0-9./_-]+", bundle))
    unexpected = sorted(u for u in found if not u.startswith(ALLOWED_ABSOLUTE))
    assert not unexpected, f"the bundle carries absolute URLs nobody declared: {unexpected}"


@built
def test_the_only_host_the_client_talks_to_is_the_one_that_served_it():
    """`api.js` builds every path as a root-relative string, so the console talks to whichever core
    served it and cannot be pointed elsewhere by a build-time constant."""
    source = (WEB / "src" / "api.js").read_text(encoding="utf-8")
    import re

    for call in re.findall(r"fetch\(([^,)]+)", source):
        assert "http" not in call, f"fetch target {call!r} is not relative"
    assert 'get("/api/v1/meta")' in (WEB / "src" / "App.svelte").read_text(encoding="utf-8")
