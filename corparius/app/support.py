"""Opening the store this installation's settings point at. Rank 5.

One line of logic and the last import cycle in the package. `cli._store()` was the only place
that resolved a data path and constructed a `Store`, so `appcli` and `secretscli` reached back
into `cli` to get it — and `cli` imports all four sub-CLIs in `main()` to register their
parsers. `{appcli, cli, secretscli}`, the fifth and last of the cycles the restructuring
started with, held together by a two-line function.

Rank 5 rather than the `cli/support.py` the plan named, for a practical reason: the CLI is not
a package yet, and turning it into one is stage 7's own work. Four rank-6 modules need this,
and a rank-5 home serves all four without creating a folder to hold one function.

`Settings()` rather than a module-level snapshot, and that distinction has a measured history.
The snapshot is taken at import. In a real run the two agree, because that is microseconds
earlier; **in a test they do not** — the snapshot predates the hermetic fixture, so a test
calling a `cmd_*` function wrote to the developer's own store. `cmd_ceo` reached the real
network the same way earlier in this restructuring.
"""

from __future__ import annotations

from ..config.settings import Settings
from ..store import Store


def open_store() -> Store:
    """A store for a short-lived, single-threaded process.

    Deliberately not the console's arrangement. `UiState.store()` keeps **one** connection for
    the life of the server, because twelve concurrent writers against per-request connections
    lost nine rows to "database is locked" (ADR 0002). A CLI command exits right after, so there
    is no connection to share and nothing to close — but keeping the construction in one place
    means a future argument or pragma lands in exactly one spot rather than four.
    """
    return Store(Settings().data_path)
