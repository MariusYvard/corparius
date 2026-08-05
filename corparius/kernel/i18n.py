"""Tiny bilingual helper for server-side messages the console shows.

The console is FR/EN; a diagnosis returned in English inside a French UI is a
papercut the operator hits right after wiring a provider. `pick` keeps both
strings side by side at the call site, so the message and its translation never
drift apart. The CLI passes no lang and gets English.
"""

from __future__ import annotations


def normalize(lang: object) -> str:
    """`object`, not `str | None`: callers hand this an Accept-Language header, a query
    parameter, a stored preference or nothing at all, and it stringifies whatever it gets."""
    return "fr" if str(lang or "").lower().startswith("fr") else "en"


def pick(lang: object, en: str, fr: str) -> str:
    return fr if normalize(lang) == "fr" else en
