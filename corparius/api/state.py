"""What the console keeps between requests. Rank 6.

`UiState` is the whole of it, and every field is in-process memory: the in-flight run per
company, the chat ring, the Ollama pull and the catalogue sweep. **Nothing here survives a
restart**, which is the plan's stage 8 and the reason a phone cannot be given this yet — a
client that reconnects to a restarted console finds its run gone with no record it existed.

The store is the exception and deliberately not per-request; the measurement is in
`UiState.store`.
"""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path

from .. import company as company_mod
from ..config.settings import Settings
from ..store import Store


def fresh_settings() -> Settings:
    """Settings are read from the environment at construction time, so a new
    instance picks up keys and toggles saved from the page."""
    return Settings()


def companies() -> list[str]:
    return company_mod.list_slugs()


def load_company(slug: str) -> dict | None:
    # `slug in companies()` is the path-traversal guard: only names the glob
    # actually produced are ever opened.
    if slug not in companies():
        return None
    try:
        return company_mod.load(company_mod.path_for(slug), slug)
    except (FileNotFoundError, ValueError):
        return None


class UiState:
    """Mutable server-side state shared across requests."""

    def __init__(self, settings: Settings, env_file: Path):
        self.settings = settings
        self.env_file = env_file
        self.runs: dict[str, dict] = {}
        self.chats: dict[str, deque] = {}
        self.pulls: dict = {"running": False}  # Ollama model pull, background
        # A full catalogue sweep across every configured provider. Background
        # for the same reason as a pull: it is hundreds of real calls and would
        # time out any request that waited for it.
        self.sweep: dict = {"running": False}
        self.lock = threading.Lock()
        self._store: Store | None = None

    def store(self) -> Store:
        """One connection for the process, not one per request.

        This used to return Store(...) fresh on every call, so a single
        /api/overview poll paid for a makedirs, a connect, the whole SCHEMA
        script, two chmods and a migration check - and never closed the handle.
        Worse, the resulting per-thread connections contended: twelve concurrent
        writers lost nine to `database is locked`.

        Store guards its own connection with an RLock, so sharing it is safe;
        sharing it *without* that lock is not, and was measured losing most of
        its rows silently. The double-check keeps two first requests from
        opening two connections.
        """
        if self._store is None:
            with self.lock:
                if self._store is None:
                    self._store = Store(self.settings.data_path)
        return self._store

    def close(self) -> None:
        with self.lock:
            if self._store is not None:
                self._store.close()
                self._store = None
