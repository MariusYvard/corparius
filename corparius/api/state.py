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
        # `pulls`, `sweep` and `chats` were all here. All three are gone: two became `jobs` rows and
        # the conversation became `chat_turns`. Between them they were everything in this object that
        # a restart silently lost and everything a second client could not see — a phone could not
        # read what the console had said, and closing the console lost the exchanges in which the CEO
        # paused a role.
        #
        # `runs` is what is left, and it is genuinely per-process: a `threading.Event` for this
        # console's own stop button, a signal that means nothing outside the process that made it.
        # The durable half of stopping is `cancel_requested`, a column, which is what lets anybody
        # else stop a run.
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
