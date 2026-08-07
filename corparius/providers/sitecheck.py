"""Did the publish actually land? One bounded look at the live URL.

Reverse-engineered from the NanoCorp worker logs (see
docs/reverse-engineering/nanocorp.md). Their `vercel-deploy-verify` skill has a
shape worth copying exactly:

    push → one fixed wait → **one** check against production → report whether it
    is fresh or still cached → stop either way

The log shows the worker narrating that discipline out loud — *"I'm in the
required 90-second wait window"*, *"I'll keep it to one agent-browser open
sequence"*, *"I'll stop there whether it's fresh or still cached"* — and it is
the reason those runs converge. It also shows what the check is worth: on one
task it caught that the route was deployed but Vercel did not have the API key,
so production answered with an error while the push had "succeeded".

Corparius had nothing here. `deploy_site` reported `Site published: netlify ->
<url>` on the provider's say-so and never fetched the address. A provider that
accepts an upload and serves something else — an old cache, a 404, a build
error page — was indistinguishable from a working publish.

Two house rules shape this module. *Prove it, don't ask to be believed*: the
verdict comes from a real response, and every field says where it came from.
*Never a network probe from a polled endpoint*: this is called after a deploy,
by the tool that deployed, never from the doctor or the console's status poll.
"""

from __future__ import annotations

import logging
import re
import time

import requests

from ..config import cfg

log = logging.getLogger("corparius.sitecheck")

# The wait before looking, and the ceiling on it. NanoCorp's skill fixes 90
# seconds; that number is theirs, measured against Vercel's build queue, and it
# is a setting here rather than a constant because Netlify, S3 and rsync do not
# share it — an rsync target is live the moment the copy returns.
DEFAULT_WAIT = 20
MAX_WAIT = 180

# One request, one short timeout. A verification that hangs turns a publish into
# a stalled turn, and the answer "I could not tell" is a perfectly good answer.
TIMEOUT = 15

FRESH = "fresh"  # the marker we published is on the live page
STALE = "stale"  # the page answered, but it is not what we just published
UNREACHABLE = "unreachable"  # nothing answered, or it answered with an error
UNVERIFIED = "unverified"  # no address to check, so no claim either way


def wait_seconds() -> int:
    """How long to wait before the single check. 0 disables the wait entirely."""
    return max(0, min(cfg.get_int("CORP_DEPLOY_VERIFY_WAIT", DEFAULT_WAIT), MAX_WAIT))


def marker_of(html: str) -> str:
    """A short, stable fingerprint of a page: its <title>.

    Deliberately not a hash of the bytes. A generated page carries a build
    timestamp, so a hash differs on every build and every check would read
    "stale". The title changes when the copy changes, which is the thing an
    operator is asking about when they ask whether the deploy landed.
    """
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return " ".join(match.group(1).split())[:120] if match else ""


def verify(url: str, expect_html: str = "", wait: int | None = None) -> dict:
    """Look once, and report what was actually served.

    `expect_html` is the local page that was just published; its title is the
    marker. With no local page to compare against, a 200 is reported as `fresh`
    only if something HTML-shaped came back — the weaker claim, said as such.
    """
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return {
            "state": UNVERIFIED,
            "url": url,
            "detail": "no absolute site.url to check, so nothing was verified",
            "waited": 0,
            "status": 0,
            "measured": False,
        }
    pause = wait_seconds() if wait is None else max(0, min(wait, MAX_WAIT))
    if pause:
        log.info("waiting %ds before the single deploy check of %s", pause, url)
        time.sleep(pause)
    want = marker_of(expect_html)
    try:
        # No retry, on purpose. One check, then stop either way: a loop of
        # reloads against a CDN teaches nothing and spends the turn.
        resp = requests.get(url, timeout=TIMEOUT, headers={"Cache-Control": "no-cache"})
    except requests.RequestException as exc:
        return {
            "state": UNREACHABLE,
            "url": url,
            "detail": f"{type(exc).__name__}: {exc}"[:200],
            "waited": pause,
            "status": 0,
            "measured": True,
        }
    body = resp.text if resp.headers.get("content-type", "").startswith("text/html") else ""
    got = marker_of(body)
    if resp.status_code >= 400:
        return {
            "state": UNREACHABLE,
            "url": url,
            "detail": f"HTTP {resp.status_code} from the live address",
            "waited": pause,
            "status": resp.status_code,
            "measured": True,
        }
    if want and got:
        same = want.lower() == got.lower()
        return {
            "state": FRESH if same else STALE,
            "url": url,
            "detail": (
                f"live title is {got!r}, which is what was published"
                if same
                else f"live title is {got!r}, but {want!r} was published — "
                "the host may still be serving a cached build"
            ),
            "waited": pause,
            "status": resp.status_code,
            "measured": True,
        }
    if not body:
        return {
            "state": STALE,
            "url": url,
            "detail": f"HTTP {resp.status_code}, but the response is not HTML",
            "waited": pause,
            "status": resp.status_code,
            "measured": True,
        }
    return {
        "state": FRESH,
        "url": url,
        "detail": (
            f"HTTP {resp.status_code} and an HTML page came back"
            + (f", titled {got!r}" if got else "")
            + ". Nothing local to compare it against, so this says the address "
            "answers, not that it carries this build."
        ),
        "waited": pause,
        "status": resp.status_code,
        "measured": True,
    }


# Tokens that are never intentional in published copy. Deliberately short: a long
# list of guesses would refuse real sentences, and a check that cries wolf is a
# check somebody switches off. Each of these exists only as a marker left for a
# human to replace.
#
# `packaging/skill-template` and this project's own site README write markers like
# these on purpose, and say so: "ils sont volontairement voyants".
PLACEHOLDERS = (
    "REMPLACER",
    "À REMPLIR",
    "TON-DOMAINE",
    "YOUR-DOMAIN",
    "YOUR_DOMAIN",
    "TODO:",
    "FIXME",
    "lorem ipsum",
    "example.com",
)

_TEXT_SUFFIXES = {".html", ".htm", ".txt", ".xml", ".css", ".js", ".json", ".webmanifest"}
_HOST = re.compile(r"https?://([a-z0-9.-]+\.[a-z]{2,})", re.I)

# Where an address really is an instruction to a crawler: a `<loc>` in a sitemap
# and a `Sitemap:` line in robots.txt. Nowhere else.
#
# The first version of this read every URL in those two files and reported
# `www.sitemaps.org` — the XML namespace, which is in every sitemap ever written.
# That is the "cries wolf" failure the comment above warns about, found by running
# it against a real site rather than by reading it back.
_SITEMAP_LOC = re.compile(r"<loc>\s*(https?://[^<\s]+)", re.I)
_ROBOTS_SITEMAP = re.compile(r"^\s*sitemap\s*:\s*(https?://\S+)", re.I | re.M)
_CRAWLER_ADDRESSES = {"sitemap.xml": _SITEMAP_LOC, "robots.txt": _ROBOTS_SITEMAP}


def _host_of(url: str) -> str:
    found = _HOST.search(url or "")
    return found.group(1).lower() if found else ""


def placeholders(site_dir, site_url: str = "") -> list[str]:
    """What would go live that should not. Empty list means nothing found.

    Two kinds, and both are about publishing something the operator did not mean:

    - a marker left for a human to replace. Measured on the owner's own install,
      Vigil's site carried `REMPLACER@TON-DOMAINE.fr` twice in `index.html` — the
      contact address on the live page would have been the placeholder.
    - a crawler instruction naming a different host than `site.url`. `robots.txt`
      and `sitemap.xml` are read as authority: on the same install they pointed at
      `vigil-hq.fr`, five times in the sitemap, while the site was about to be
      published elsewhere. This is the reasoning `sitegen` already applies to the
      canonical link — guessing a host is worse than having none, because it tells
      a crawler to index somebody else.

    Prose is left alone. A blog post that mentions a domain in a sentence is not a
    defect, so the host comparison only reads the two files a crawler obeys.
    """
    from pathlib import Path

    base = Path(site_dir)
    if not base.is_dir():
        return []
    want_host = _host_of(site_url)
    found: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(base).as_posix()
        low = text.lower()
        for token in PLACEHOLDERS:
            count = low.count(token.lower())
            if count:
                found.append(f"{rel}: {token} ({count}x)")
        pattern = _CRAWLER_ADDRESSES.get(path.name.lower())
        if want_host and pattern is not None:
            others = sorted({_host_of(u) for u in pattern.findall(text)} - {want_host, ""})
            if others:
                found.append(
                    f"{rel}: points crawlers at {', '.join(others)}, but site.url is {want_host}"
                )
    return found


def line(result: dict) -> str:
    """One sentence for the action log, which is where an operator reads this."""
    state = result.get("state", UNVERIFIED)
    if state == UNVERIFIED:
        return "Not verified: " + result["detail"]
    waited = f" after {result['waited']}s" if result.get("waited") else ""
    label = {
        FRESH: "Verified live",
        STALE: "Published, but not live yet",
        UNREACHABLE: "Published, and the address does not answer",
    }[state]
    return f"{label}{waited}: {result['url']} — {result['detail']}"
