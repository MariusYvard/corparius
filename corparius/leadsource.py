"""Lead research across interchangeable sources, tried in order with fallback,
so lead generation never depends on a single source. A local dataset is always
available and works offline. A browser source (headless Chromium) can pull
candidate leads from a public page you configure.

Responsibility: you are the operator. Respect each source's terms of use and the
applicable data-protection law (GDPR). Prefer public data and official APIs.
"""

from __future__ import annotations

import csv
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from . import cfg

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@dataclass
class Lead:
    name: str = ""
    company: str = ""
    title: str = ""
    email: str = ""
    source: str = ""

    def label(self) -> str:
        return self.email or self.company or self.name or "lead"


class LeadSource(ABC):
    name = "base"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def find(self, query: str, limit: int) -> list[Lead]: ...


class LocalDatasetSource(LeadSource):
    """Read leads from a local CSV (columns: name, company, title, email). Always
    available; the offline default and the fallback for every other source."""

    name = "local"

    def available(self) -> bool:
        return True

    def find(self, query: str, limit: int) -> list[Lead]:
        path = cfg.get("CORP_LEADS_CSV", "")
        if not path or not os.path.isfile(path):
            return []
        q = query.lower()
        out: list[Lead] = []
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if not q or q in " ".join(row.values()).lower():
                    out.append(
                        Lead(
                            row.get("name", ""),
                            row.get("company", ""),
                            row.get("title", ""),
                            row.get("email", ""),
                            "local",
                        )
                    )
                if len(out) >= limit:
                    break
        return out


def render_page_text(url: str, timeout_ms: int = 30000) -> str:
    """Fetch a URL with headless Chromium and return the rendered body text.
    Requires Playwright. Always headless. Shared by lead and signal sources."""
    from playwright.sync_api import sync_playwright

    ua = cfg.get("CORP_BROWSER_UA", "Mozilla/5.0 (compatible; corparius/0.1)")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)  # always headless
        try:
            page = browser.new_context(user_agent=ua).new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            return page.inner_text("body")
        finally:
            browser.close()


class BrowserSource(LeadSource):
    """Pull candidate leads from a public page rendered by headless Chromium.
    Set CORP_LEADS_URL (use {query} as a placeholder). Needs Playwright
    installed (`pip install playwright && playwright install chromium`). The
    browser always runs headless. Point it only at sources whose terms allow it."""

    name = "browser"

    def available(self) -> bool:
        if not cfg.get("CORP_LEADS_URL"):
            return False
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    def find(self, query: str, limit: int) -> list[Lead]:
        raw = cfg.get("CORP_LEADS_URL")
        if not raw:
            raise RuntimeError("CORP_LEADS_URL is not set")
        url = raw.replace("{query}", query)
        text = render_page_text(url)
        leads: list[Lead] = []
        seen: set[str] = set()
        for email in EMAIL_RE.findall(text):
            key = email.lower()
            if key in seen:
                continue
            seen.add(key)
            leads.append(Lead(email=email, source="browser"))
            if len(leads) >= limit:
                break
        return leads


REGISTRY: dict[str, LeadSource] = {s.name: s for s in [LocalDatasetSource(), BrowserSource()]}


def _order() -> list[str]:
    raw = cfg.get("CORP_LEAD_SOURCES", "browser,local")
    return [x.strip() for x in raw.split(",") if x.strip()]


def find_leads(query: str = "", limit: int = 5) -> list[Lead]:
    """Try each configured source in order, return the first non-empty result.
    The local dataset is always available, so this never raises."""
    for name in _order():
        source = REGISTRY.get(name)
        if source is None or not source.available():
            continue
        try:
            leads = source.find(query, limit)
        except Exception:  # a flaky source must not break the chain
            continue
        if leads:
            return leads
    return []
