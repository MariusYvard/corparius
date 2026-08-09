"""`robots.txt` and `sitemap.xml`, which are files and not tags. Rank 4.

Separate from `head` because their lifetime is different: they belong to a *folder*, are written
beside the page rather than inside it, and `companions_for_folder` exists so a publish can
produce them for a site whose pages it did not generate.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import esc
from .sections import extra_pages

log = logging.getLogger("corparius.sitegen.companions")


def companions(company: dict) -> dict[str, str]:
    """robots.txt and sitemap.xml, keyed by filename.

    Both need an absolute address, so both are absent until `site.url` is set —
    a sitemap listing `/` with no host tells a crawler nothing, and a robots.txt
    pointing at a sitemap that is not there is worse than none.
    """
    url = str((company.get("site") or {}).get("url") or "").rstrip("/")
    if not url:
        return {}
    return {
        "robots.txt": f"User-agent: *\nAllow: /\n\nSitemap: {url}/sitemap.xml\n",
        "sitemap.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{esc(url)}/</loc><changefreq>weekly</changefreq>"
            "<priority>1.0</priority></url>\n"
            # Every secondary page too: one that no sitemap lists is one no
            # crawler is told about, which is most of the point of having it.
            + "".join(
                f"  <url><loc>{esc(url)}/{pg['slug']}.html</loc>"
                "<changefreq>monthly</changefreq><priority>0.6</priority></url>\n"
                for pg in extra_pages(company)
            )
            + "</urlset>\n"
        ),
    }


def _disallowed(base) -> set[str]:
    """Paths an existing robots.txt keeps out, so the sitemap can agree with it."""
    path = Path(base) / "robots.txt"
    if not path.is_file():
        return set()
    out = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "disallow" and value.strip() not in ("", "/"):
                out.add(value.strip().lstrip("/"))
    except OSError:
        return set()
    return out


def _robots_with_sitemap(base, url: str) -> str:
    """The site's own robots.txt with its `Sitemap:` line corrected, or a new one.

    Only that line. Regenerating the file would have deleted a real decision: the
    owner's robots.txt allows GPTBot, ClaudeBot, PerplexityBot and Google-Extended,
    with a comment explaining why. Overwriting that to fix a hostname would be the
    product throwing away the operator's SEO policy.
    """
    path = Path(base) / "robots.txt"
    line = f"Sitemap: {url}/sitemap.xml"
    fresh = "User-agent: *\nAllow: /\n\n" + line + "\n"
    if not path.is_file():
        return fresh
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fresh
    kept = [ln for ln in text.splitlines() if not ln.strip().lower().startswith("sitemap:")]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join([*kept, "", line, ""])


def companions_for_folder(site_dir, url: str) -> dict[str, str]:
    """robots.txt and sitemap.xml for a site the company owns, from its real files.

    `companions` above builds them from `company.yaml`'s pages, which is right for a
    generated site and wrong for one with its own: the pages on disk are the pages
    that exist. Empty when there is no absolute address, for the same reason
    `companions` is — a sitemap listing a host nobody owns tells a crawler to index
    somebody else.
    """
    base = Path(site_dir)
    url = str(url or "").rstrip("/")
    if not url or not base.is_dir():
        return {}
    # A page the site itself keeps out of the index has no business in its sitemap.
    # Measured: `merci.html` is noindex and disallowed in robots.txt, and the first
    # version of this listed it anyway — a sitemap that contradicts the robots.txt
    # beside it is a defect a crawler reports back.
    blocked = _disallowed(base)
    pages = []
    for path in sorted(base.rglob("*.html")):
        rel = path.relative_to(base).as_posix()
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
        if rel in blocked or "noindex" in head:
            continue
        if rel == "index.html":
            pages.append(("", "1.0"))
        elif rel.endswith("/index.html"):
            pages.append((rel[: -len("index.html")], "0.6"))
        else:
            pages.append((rel, "0.8"))
    if not pages:
        return {}
    entries = "".join(
        f"  <url><loc>{esc(url)}/{loc}</loc><changefreq>monthly</changefreq>"
        f"<priority>{pri}</priority></url>\n"
        for loc, pri in pages
    )
    return {
        "robots.txt": _robots_with_sitemap(base, url),
        "sitemap.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + entries
            + "</urlset>\n"
        ),
    }
