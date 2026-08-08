"""SQLite persistence: one connection, one lock, and a mixin per table.

`Store` was 1 672 lines holding the schema, sixteen migrations and eighty-three accessors for
eighteen tables. Nothing about that was wrong — coverage sat at 95 % — but "where is the memory
code" had no answer shorter than a search, and a per-file coverage floor could not see one
table's queries rot while the total held.

So: `schema.py` for the shape, `base.py` for the lock and what a mixin may assume, one file per
table named after the table, and `reports.py` for the three reads that span tables and
therefore belong to none.

**`Store` is defined here, not re-exported.** Ninety-seven call sites say
`from corparius.store import Store` and they are still correct — this is where the class is. The
three that wanted `SCHEMA_VERSION` or `MIGRATIONS` now say `from corparius.store.schema import
...`, because the schema is a real module and pointing at it is not a facade.

What did **not** change, and the plan is explicit that it must not: the single long-lived
connection, the `RLock` that serialises it (ADR 0002 — twelve concurrent writers, 414 of 3 200
rows silently kept without it), the WAL pragmas (ADR 0003), and the `PRAGMA user_version`
numbering. `tests/test_store_locking.py` was written before this split to hold the one property
a move of eighty-three methods was most likely to lose.
"""

from __future__ import annotations

import os
import sqlite3
import threading

from .actions import ActionsMixin
from .approvals import ApprovalsMixin
from .base import Connected, _locked, log
from .decisions import DecisionsMixin
from .directives import DirectivesMixin
from .drafts import DraftsMixin
from .inbox import InboxMixin
from .machine import MachineMixin
from .memory import MemoryMixin
from .model_catalogue import ModelCatalogueMixin
from .model_probes import ModelProbesMixin
from .outreach import OutreachMixin
from .reports import ReportsMixin
from .rules import RulesMixin
from .schema import MIGRATIONS, SCHEMA, SCHEMA_VERSION
from .settings import SettingsMixin
from .skill_usage import SkillUsageMixin
from .state import StateMixin
from .tasks import TasksMixin
from .token_usage import TokenUsageMixin


class Store(
    ActionsMixin,
    ApprovalsMixin,
    DecisionsMixin,
    DirectivesMixin,
    DraftsMixin,
    InboxMixin,
    MachineMixin,
    MemoryMixin,
    ModelCatalogueMixin,
    ModelProbesMixin,
    OutreachMixin,
    ReportsMixin,
    RulesMixin,
    SettingsMixin,
    SkillUsageMixin,
    StateMixin,
    TasksMixin,
    TokenUsageMixin,
):
    """The facade. Holds the connection and the lock; every query lives in a mixin.

    The mixin order is alphabetical and carries no meaning: no two of them define the same
    method, which `tests/test_store_mixins.py` asserts — an overridden accessor would make the
    MRO decide which table a call reaches, and that is not a thing to leave to alphabet.
    """

    def __init__(self, data_path: str):
        os.makedirs(data_path, exist_ok=True)
        try:  # the store holds API keys in the clear; keep the dir owner-only
            if os.name != "nt":
                os.chmod(data_path, 0o700)  # effective on POSIX, a no-op on Windows
        except OSError:
            pass
        self._lock = threading.RLock()
        self.path = os.path.join(data_path, "corparius.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._configure()
        self.db.executescript(SCHEMA)
        self.db.commit()
        try:  # the settings table holds API keys in the clear; owner only
            os.chmod(self.path, 0o600)  # effective on POSIX, a no-op on Windows
        except OSError:
            pass
        self._migrate()

    def _configure(self) -> None:
        """Connection pragmas.

        WAL is the one that matters across connections: corparius/cfg.py opens the
        store read-only as its settings layer, and the CLI can run while the
        console is up. Under the default rollback journal a writer excludes
        readers outright, and SQLite returns BUSY immediately rather than
        invoking the busy handler when two connections try to upgrade a lock at
        once, so waiting longer does not help. WAL is recorded in the database
        header, so it is set once and persists.

        It is not available everywhere: some network filesystems refuse the
        shared-memory sidecar WAL needs. A Docker volume on an odd backend
        should degrade to the old behaviour rather than refuse to start, so the
        failure is swallowed deliberately.
        """
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")  # safe under WAL, one less fsync
        except sqlite3.Error:
            pass
        # Python's sqlite3 already applies a 5s busy timeout via connect(timeout=5.0);
        # setting it explicitly keeps that from silently changing under us.
        self.db.execute("PRAGMA busy_timeout=5000")

    @_locked
    def _migrate(self) -> None:
        """Bring the store from its recorded version up to SCHEMA_VERSION, one
        step at a time, recording progress so an interrupted upgrade resumes."""
        current = self.db.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            # An older build opening a store a newer one migrated. The loop
            # below is a no-op here, so this used to open, run and write in
            # complete silence — and silence is the one thing this store does
            # not do. It stays openable on purpose: rolling back to the
            # previous build is the recovery path when an update goes wrong,
            # and refusing would strand exactly the person who needs it. But an
            # old build writing to a column a later version repurposed is how
            # data gets quietly wrong, so it says so, and the doctor fails on it.
            log.warning(
                "this store was written by a newer corparius (schema %s, this build knows %s). "
                "Update again, or restore the backup taken before the update. Running an older "
                "build against it can write values a newer schema means differently.",
                current,
                SCHEMA_VERSION,
            )
        for version in range(current + 1, SCHEMA_VERSION + 1):
            MIGRATIONS[version](self.db)
            self.db.execute(f"PRAGMA user_version = {int(version)}")
            self.db.commit()

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @_locked
    def schema_version(self) -> int:
        return self.db.execute("PRAGMA user_version").fetchone()[0]

    @_locked
    def company_tables(self) -> list[str]:
        """Every table that records something *about a company*, asked of the schema.

        Derived rather than listed, and that is the fix rather than a nicety. The list was six
        names in `purge_company` and the schema had grown to **thirteen**, so a purge that says
        it drops everything left seven tables behind: the company's durable `memory`, every
        `draft` it wrote, the CEO's `decisions`, the operator's own `directives`, its `inbox`,
        its `skill_usage` — and its `rules`.

        `rules` is the one that mattered. It holds "approve, and stop asking", so a company
        purged and recreated under the same slug inherited standing authorisations the operator
        gave a different company, on tools up to WRITE_REMOTE. A permission surviving the thing
        it was granted about.

        A hardcoded thirteen would rot exactly as the six did. `tests/test_purge.py` asserts
        this against the schema so the next table is covered the day it exists.
        """
        tables = [
            row["name"]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return sorted(
            name
            for name in tables
            if any(
                col["name"] == "company" for col in self.db.execute(f"PRAGMA table_info({name})")
            )
        )

    @_locked
    def purge_company(self, company) -> dict[str, int]:
        """Drop everything recorded for one company. Only ever called with an
        explicit confirmation from the operator; the config itself is moved to
        companies/.trash rather than deleted."""
        removed = {}
        for table in self.company_tables():
            cur = self.db.execute(f"DELETE FROM {table} WHERE company=?", (company,))
            removed[table] = cur.rowcount
        self.db.commit()
        return removed


__all__ = ["MIGRATIONS", "SCHEMA", "SCHEMA_VERSION", "Connected", "Store", "log"]
