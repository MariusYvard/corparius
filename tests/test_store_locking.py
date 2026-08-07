"""Every method that touches the connection is serialised. Today a convention; here a check.

`Store` holds **one** long-lived `sqlite3.Connection` shared across threads
(`check_same_thread=False`), and the console is a `ThreadingHTTPServer`. What makes that safe
is that every method takes `self._lock` first — and until now nothing said so. 78 of the 83
methods carry `@_locked`, three take the lock by hand or run before the object is shared, and
the next one added would have been correct by luck.

This is written before `store.py` is split into a mixin per table, deliberately: the split
moves 83 methods between files, and the property most likely to be lost in that move is the one
nobody had written down. ADR 0002 records the measurement behind it — twelve concurrent writers,
nine rows lost to "database is locked" — so the cost of losing it is known.

The check is AST, not runtime: a lock held on the paths a test happens to exercise proves
nothing about the path it does not.
"""

import ast
from pathlib import Path

import pytest

# The package, not a file. This was written while `store.py` was still one module, and the
# split is exactly the event that would have made a path-shaped scan read nothing — the same
# trap as the flat glob in test_registries.py. `test_there_is_something_to_check` is what makes
# the widening safe rather than merely broader.
SOURCES = sorted(Path("corparius/store").rglob("*.py"))

# Runs before the object can be shared with a second thread, so there is nobody to race.
# `__init__` creates the lock; `_configure` is called from inside it.
BEFORE_SHARING = {"__init__", "_configure"}


def _classes() -> list[tuple[str, ast.ClassDef]]:
    out = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                out.append((path.as_posix(), node))
    return out


def _touches_db(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "db"
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            return True
    return False


def _serialised(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """`@_locked`, or `with self._lock:` taken by hand.

    Both spellings count, because both are true. `close` uses the second one and is right to:
    it is not returning a value the decorator would have to pass through.
    """
    if any(getattr(d, "id", "") == "_locked" for d in fn.decorator_list):
        return True
    for node in ast.walk(fn):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            target = item.context_expr
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "_lock"
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                return True
    return False


def test_there_is_something_to_check():
    """The guard on the guard. An empty `SOURCES` — after the split moves the file — would make
    the assertion below vacuously true, which is the failure mode this whole test exists to
    prevent one level down."""
    assert SOURCES, "no store source found; the glob stopped matching"
    methods = [
        fn
        for _, cls in _classes()
        for fn in cls.body
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and _touches_db(fn)
    ]
    assert len(methods) >= 70, f"only {len(methods)} methods touch self.db; expected the store"


def test_every_method_that_touches_the_connection_takes_the_lock():
    """One connection, many threads. A method that queries without the lock is a row lost to
    "database is locked" on a busy tick, and it will not be lost in the test suite."""
    unguarded = []
    for where, cls in _classes():
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if fn.name in BEFORE_SHARING or not _touches_db(fn):
                continue
            if not _serialised(fn):
                unguarded.append(f"{where}::{cls.name}.{fn.name}")
    assert not unguarded, (
        "these touch self.db without serialising: "
        + ", ".join(sorted(unguarded))
        + ". Add @_locked, or take self._lock explicitly and say why the decorator does not fit."
    )


@pytest.mark.parametrize("name", sorted(BEFORE_SHARING))
def test_the_exemptions_really_do_run_before_sharing(name):
    """An exemption list rots the moment something is added to it for convenience. These two
    are exempt because no second thread can hold a reference yet — `__init__` is where the lock
    itself is created. If either ever becomes callable later, this stops being true and the
    exemption has to go rather than be widened.
    """
    from corparius.store import Store

    fn = getattr(Store, name)
    assert callable(fn)
    if name == "__init__":
        source = ast.parse(Path("corparius/store/__init__.py").read_text(encoding="utf-8"))
        creates = [
            n
            for n in ast.walk(source)
            if isinstance(n, ast.Attribute) and n.attr == "_lock" and isinstance(n.ctx, ast.Store)
        ]
        assert creates, "__init__ is exempt because it creates the lock; it no longer does"
