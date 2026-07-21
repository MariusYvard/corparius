"""Tiny bilingual helper for server-side messages the console shows.

The console is FR/EN; a diagnosis returned in English inside a French UI is a
papercut the operator hits right after wiring a provider. `pick` keeps both
strings side by side at the call site, so the message and its translation never
drift apart. The CLI passes no lang and gets English.
"""

from __future__ import annotations


def normalize(lang) -> str:
    return "fr" if str(lang or "").lower().startswith("fr") else "en"


def pick(lang, en: str, fr: str) -> str:
    return fr if normalize(lang) == "fr" else en
