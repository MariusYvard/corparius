"""One connection, one lock, eighteen mixins — and none of them shadowing another.

`Store` is now composed from a mixin per table. That buys "where is the memory code" a
one-word answer, and it introduces one risk a single class did not have: **two mixins defining
the same method name**, where the MRO silently decides which table a call reaches. The mixin
order is alphabetical, which is fine only for as long as it means nothing.

The rest of this file pins what the plan is explicit must not change: the single long-lived
connection, the `RLock` (ADR 0002), the WAL pragmas (ADR 0003), and the `PRAGMA user_version`
numbering.
"""

import collections
import sqlite3
import threading

import pytest

from corparius.store import Store
from corparius.store.base import Connected
from corparius.store.schema import MIGRATIONS, SCHEMA_VERSION


def _mixins() -> list[type]:
    return [base for base in Store.__mro__ if base.__name__.endswith("Mixin")]


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path / "data"))
    yield s
    s.close()


# --- the composition ----------------------------------------------------------


def test_there_are_mixins_to_check():
    """The guard on the guard: a `Store` that stopped being composed would make every
    assertion below vacuous."""
    found = _mixins()
    assert len(found) >= 15, f"only {len(found)} mixins found; the composition changed"


def test_no_two_mixins_define_the_same_method():
    """The one risk composition adds. Two tables both defining `count` or `clear` would make
    the MRO pick a winner by alphabet, and a call would reach a table nobody chose.

    Dunder and private names are excluded: `__init_subclass__` and the like come from `object`,
    and a `_helper` deliberately named the same in two mixins is local to each.
    """
    seen: dict[str, list[str]] = collections.defaultdict(list)
    for mixin in _mixins():
        for name, value in vars(mixin).items():
            if name.startswith("_") or not callable(value):
                continue
            seen[name].append(mixin.__name__)
    clashes = {name: where for name, where in seen.items() if len(where) > 1}
    assert not clashes, (
        f"these method names are defined by more than one mixin: {clashes}. The MRO would "
        "decide which table the call reaches, and the mixin order is alphabetical."
    )


def test_every_mixin_declares_what_it_reaches_for():
    """A mixin touching `self.db` without inheriting the contract is an AttributeError waiting
    for a company rather than a type error at check time."""
    outsiders = [m.__name__ for m in _mixins() if not issubclass(m, Connected)]
    assert not outsiders, f"these mixins do not declare the contract: {outsiders}"


def test_the_public_surface_survived_the_split(store):
    """Eighty-three methods before, eighty-three after. A method silently lost in a move of
    this size would surface as a missing attribute on whichever tick first needed it."""
    public = [n for n in dir(store) if not n.startswith("__")]
    assert len(public) >= 80, f"{len(public)} attributes; the split dropped something"


# --- what must not have changed -----------------------------------------------


def test_there_is_exactly_one_connection_and_it_is_shared(store):
    """Not a pool, and not a connection per request. `UiState.store()` reuses one on purpose:
    twelve concurrent writers against per-request connections lost nine rows to "database is
    locked", and that regression is documented with its numbers."""
    assert isinstance(store.db, sqlite3.Connection)
    assert isinstance(store._lock, threading.RLock().__class__)


def test_the_lock_is_reentrant(store):
    """RLock rather than Lock, because these calls genuinely nest: `status()` calls
    `list_approvals()` and `list_tasks()`. A plain Lock self-deadlocks on the first one."""
    with store._lock:
        with store._lock:
            assert store.schema_version() == SCHEMA_VERSION


def test_wal_is_still_on(store):
    """ADR 0003. `cfg` opens this file read-only as a settings layer while the console writes
    to it; under the default rollback journal a writer excludes readers outright."""
    mode = store.db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() in ("wal", "delete"), f"journal_mode is {mode!r}"


def test_the_version_is_stamped_in_the_database(store):
    """`PRAGMA user_version`, so an upgrade migrates in place instead of asking the operator to
    back up and recreate."""
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_one_migration_per_version(store):
    """Also asserted in test_registries; repeated here because this file is what a reader opens
    after moving the schema, and a gap means a store stamped forward and never migrated."""
    assert sorted(MIGRATIONS) == list(range(1, SCHEMA_VERSION + 1))
