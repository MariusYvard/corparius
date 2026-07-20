"""Buying-signal watcher across interchangeable sources with fallback. A local
file source is always available; a headless browser source can watch a public
page. Same responsibility as lead research: respect each source's terms and the
applicable law, and prefer public data.
"""

from __future__ import annotations

import os

from . import cfg, leadsource


def _match(text: str, keywords: list[str]) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in keywords if k)


def _local(keywords: list[str], limit: int) -> list[str]:
    path = cfg.get("CORP_SIGNALS_FILE", "")
    if not path or not os.path.isfile(path):
        return []
    hits: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip() and _match(line, keywords):
                hits.append(line.strip())
            if len(hits) >= limit:
                break
    return hits


def _browser(keywords: list[str], limit: int) -> list[str]:
    url = cfg.get("CORP_SIGNALS_URL", "")
    if not url:
        return []
    try:
        import playwright  # noqa: F401
    except ImportError:
        return []
    hits: list[str] = []
    for line in leadsource.render_page_text(url).splitlines():
        if line.strip() and _match(line, keywords):
            hits.append(line.strip())
        if len(hits) >= limit:
            break
    return hits


_SOURCES = {"local": _local, "browser": _browser}


def find_signals(keywords: list[str], limit: int = 5) -> list[str]:
    """Try each configured source in order, return the first non-empty result."""
    order = cfg.get("CORP_SIGNAL_SOURCES", "browser,local")
    for name in [x.strip() for x in order.split(",") if x.strip()]:
        fn = _SOURCES.get(name)
        if fn is None:
            continue
        try:
            hits = fn(keywords, limit)
        except Exception:  # a flaky source must not break the chain
            continue
        if hits:
            return hits
    return []
