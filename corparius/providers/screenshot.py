"""What a page actually looks like. Rank 3.

The design agent reviewed sites it had never seen. `review_site` strips the tags and sends the
visible text, which is the right thing to send a model asked about wording and is the wrong thing
entirely to send one asked whether a page reads well: contrast, hierarchy, whether the first screen
says what the company sells, whether two boxes overlap. This project has already paid for that
distinction — the console's own tab bug was found by a screenshot and not by reading the CSS, and a
blind design review of a generated page scored what it could not see.

## Why not Playwright

It is the obvious answer and it was measured against the alternative rather than assumed. Playwright
means a Python package **plus** `playwright install chromium`, which is a ~150 MB download per
machine and an installation step. Corparius starts by double-clicking a file, and a design review
that only works for people who ran two commands in a terminal is a feature most operators will never
have.

**A Chromium-family browser already on the machine does the same job**, because it is the same job:
Playwright's screenshot drives Chromium's DevTools protocol, and Chromium's own `--headless
--screenshot` drives it too. Measured here: 1.2 seconds, a 10 KB PNG, fonts and colours and rounded
corners exactly as a visitor sees them, no install and no new dependency.

## What "every user" honestly means

  * **Windows** — Edge ships with the operating system. There is always a browser.
  * **macOS** — Safari ships and cannot do this; Chrome, Edge, Brave and Chromium can and are
    common. Usually present, not guaranteed.
  * **Linux** — nothing is guaranteed, and a headless server often has none.

So the rule is: find one without being told, and when there is none, **say so and let the review go
on with the text**. Nothing here is ever a reason for a turn to fail, and nothing asks the operator
to install anything. `CORP_BROWSER_PATH` exists for the unusual case of a browser in an unusual
place, and it is a setting nobody needs to touch to get this working.

## What is captured

The first screen, at 1280x800, which is what a visitor sees before scrolling and the single most
useful image of a sales page. Chromium's `--screenshot` captures the viewport, in both the old and
the new headless modes — measured, because the old one used to capture the full page and the
documentation still says so in places. A caller that wants more of a long page asks for a taller
viewport; there is no full-page flag to have.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from ..config import cfg
from ..kernel import proc

log = logging.getLogger("corparius.screenshot")

# Chromium-family binaries, by the name they answer to on PATH. Firefox and Safari are absent on
# purpose: neither takes a screenshot from the command line, so listing them would produce a browser
# that is found and then cannot do the job, which is worse than finding none.
ON_PATH = (
    "chrome",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "msedge",
    "microsoft-edge",
    "brave",
    "brave-browser",
)

# Where they install themselves when they are not on PATH, which on Windows and macOS is the normal
# case. Edge first on Windows because it is the one that is always there.
KNOWN = {
    "nt": (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ),
    "posix": (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
        "/snap/bin/chromium",
    ),
}

WIDTH = 1280
HEIGHT = 800
TIMEOUT = 45


def browser() -> str:
    """A Chromium-family browser on this machine, or "".

    The setting wins, then PATH, then the places browsers install themselves. PATH before the known
    list so an operator who put a specific build first in their PATH gets that one, and the known
    list at all because on Windows and macOS a browser is almost never on PATH.
    """
    named = cfg.get("CORP_BROWSER_PATH", "").strip()
    if named:
        # Not silently ignored when it is wrong. Somebody who set this is telling the product where
        # to look, and falling back without a word would leave them believing it was used.
        if Path(named).is_file():
            return named
        log.warning("CORP_BROWSER_PATH points at %r, which is not a file; looking elsewhere", named)
    for name in ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    for candidate in KNOWN.get(os.name, ()):
        if Path(candidate).is_file():
            return candidate
    return ""


def available() -> bool:
    return bool(browser())


def _target(page: str) -> str:
    """A URL as given, a local file as a `file://` URI.

    `Path.as_uri` rather than string concatenation, because a Windows path has a drive letter and
    backslashes and an operator's company folder is under `C:\\Users\\<name>` where the name may
    contain a space or an accent.
    """
    if page.startswith(("http://", "https://", "file://")):
        return page
    return Path(page).resolve().as_uri()


def capture(
    page: str,
    out: Path | str,
    width: int = WIDTH,
    height: int = HEIGHT,
    timeout: int = TIMEOUT,
) -> dict:
    """Render one page and write a PNG. Returns `{ok, path, error}` and never raises.

    Never raising is the contract that matters: this runs inside a turn that has other work to do,
    and a browser that hung, crashed or is not installed must cost the review its picture and
    nothing else.

    The flags are the minimum that produce a correct render unattended. `--disable-gpu` because a
    headless box has no GPU and the fallback path is slower than not asking; `--hide-scrollbars`
    because a scrollbar in the corner of every capture is a thing a model will eventually comment
    on; `--no-sandbox` because the sandbox needs privileges a container often refuses, and this
    renders a page the operator's own company published.
    """
    exe = browser()
    if not exe:
        return {
            "ok": False,
            "path": "",
            "error": "no Chromium-family browser found on this machine",
        }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # A stale file from a previous run would otherwise be reported as this run's picture, which is
    # the quietest way to review yesterday's page and believe it is today's.
    if out.exists():
        out.unlink()
    cmd = [
        exe,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        f"--window-size={int(width)},{int(height)}",
        f"--screenshot={out}",
        _target(page),
    ]
    try:
        done = proc.run(cmd, timeout=timeout)
    except proc.ProcError as exc:
        return {"ok": False, "path": "", "error": f"could not run the browser: {exc}"}
    if not _settled(out, timeout):
        # **The process exiting is not the signal, and this cost a wrong answer to find.** Measured
        # on Windows with Edge and with Chrome, both already running: the launcher hands the request
        # to the instance that is open, returns in 0.1 to 0.3 seconds, and the picture is written by
        # the other process about three seconds later. A dedicated `--user-data-dir` does not change
        # it. So a check the moment `proc.run` returns reports "the browser wrote no image" about a
        # browser that is writing the image — which is what the first version of this did, on a page
        # that had rendered perfectly.
        #
        # The exit code is no help either: Chromium exits 0 on pages it failed to render. The file
        # is the only honest signal, so it is what is waited on.
        said = (done.stderr or done.stdout or "").strip()[:200] or "no output"
        return {"ok": False, "path": "", "error": f"the browser wrote no image: {said}"}
    return {"ok": True, "path": str(out), "error": ""}


def _settled(out: Path, timeout: int) -> bool:
    """Wait for the file to appear and stop growing. True when there is a whole image there.

    Two reads of the same size rather than one of a non-zero size: a PNG being written is a file
    that exists and is not empty, and handing a truncated one to a model is worse than handing it
    none — it is a picture of half a page, reported as the page.
    """
    deadline = time.monotonic() + timeout
    last = -1
    while time.monotonic() < deadline:
        size = out.stat().st_size if out.is_file() else 0
        if size and size == last:
            return True
        last = size
        # The third `time.sleep` in the package, and named in `tests/test_layers.py` beside
        # `providers/sitecheck` for the same reason it gives: this is rank 3 waiting for its own
        # outside world, not a loop floor and not a retry backoff. `clock.pace` deliberately does not
        # absorb it — its docstring says a poll interval belongs to whoever owns the poll.
        time.sleep(0.25)
    return False


@contextlib.contextmanager
def _served(root: Path):
    """Serve `root` on loopback for as long as the block runs, yielding its base URL.

    **A site has to be fetched, not opened**, and this cost a wrong answer to learn. Real pages link
    their assets absolutely — vigil's is `<link rel="stylesheet" href="/assets/style.css">`, which is
    how anything served from a web root is written — and over `file://` a leading slash resolves to
    the root of the *disk*. Measured on the real site: the page rendered with every rule of its
    stylesheet missing, a wall of unstyled serif. Handing that to a design agent is worse than
    handing it nothing, because it would report confidently that the design is broken.

    Bound to 127.0.0.1 on a port the OS picks, up for the seconds the captures take. Nothing is
    published: `directory=` roots the handler at the folder, so the URL space is the site and
    nothing above it.
    """

    class Quiet(http.server.SimpleHTTPRequestHandler):
        """Silent, and a subclass rather than an attribute on a `functools.partial`.

        The first version set `log_message` on the partial, which is an object the handler never
        consults — so every asset still printed a line to stderr and an operator's console filled
        with `GET /assets/style.css 200` for a picture they did not ask about. Measured, then fixed.
        """

        def log_message(self, *args, **kwargs) -> None:
            return

    handler = functools.partial(Quiet, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def capture_all(
    pages: list[str],
    into: Path | str,
    limit: int = 4,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> list[str]:
    """Render several pages of one site, returning the captures that worked.

    Served rather than opened, from the folder the pages share, so each renders with its stylesheet,
    its fonts and its images exactly as a visitor gets them. **Every caller that wants a picture of a
    company's site goes through here for that reason**, including the ones rendering a single page:
    `capture` takes a URL or a file and opening a file is what loses the stylesheet.

    Bounded, and the bound is stated rather than silent: a site with forty pages would otherwise
    spend forty seconds and hand a model forty images to pay for. Four is the first screen of the
    four pages a sales site usually has, and the ones dropped are logged.
    """
    into = Path(into)
    wanted = [Path(p) for p in pages[:limit]]
    if not wanted:
        return []
    if len(pages) > limit:
        log.info(
            "screenshot: %d page(s) past the limit of %d were not captured",
            len(pages) - limit,
            limit,
        )
    root = wanted[0].parent
    made = []
    with _served(root) as base:
        for page in wanted:
            # A page outside the root is unreachable over this server, and there is no such case in
            # the product: `_site_pages_for` globs one folder. Said rather than skipped in silence,
            # because that looks exactly like a browser that failed.
            try:
                where = page.relative_to(root).as_posix()
            except ValueError:
                log.info("screenshot: %s is outside %s, not captured", page.name, root)
                continue
            shot = capture(
                f"{base}/{where}", into / (page.stem + ".png"), width=width, height=height
            )
            if shot["ok"]:
                made.append(shot["path"])
            else:
                log.info("screenshot: %s not captured (%s)", page.name, shot["error"])
    return made
