"""What every mixin may assume, and the lock that makes it safe.

`Store` is one long-lived connection shared across threads, composed from a mixin per table.
That composition needs three things in one place: the attributes a mixin is allowed to reach
for, the decorator that serialises access to them, and the word-normaliser two of them share.

ADR 0002 carries the measurement behind the lock, and `tests/test_store_locking.py` is the
check that every method touching the connection still takes it — written before this split
precisely because that is the property a 83-method move is most likely to lose.
"""

from __future__ import annotations

import functools
import logging
import sqlite3
import threading

log = logging.getLogger("corparius.store")


class Connected:
    """The contract between a mixin and the class it is mixed into.

    Declared rather than assumed, so a mixin reaching for something the facade does not provide
    is a type error instead of an AttributeError on a live company. `Store` sets all three in
    `__init__`; nothing else assigns them.
    """

    db: sqlite3.Connection
    _lock: threading.RLock
    path: str

    # Two reads that `reports.py` composes rather than owns. A report spanning tables has to
    # reach the accessors of the tables it spans, and after composition those genuinely are
    # part of the object — which is what this class describes. Declared here so the call is
    # type-checked instead of discovered on a live company.
    #
    # `NotImplementedError`, not a stub returning None: if a mixin is ever dropped from the
    # facade, that has to be loud. The same reasoning refused a registry for the settings store
    # layer — a silent half-composition is worse than an import that cannot half-fail.
    def list_tasks(self, company: str, status: str | None = None) -> list[dict]:
        raise NotImplementedError("TasksMixin provides this")

    def list_approvals(self, company: str, status: str = "pending") -> list[dict]:
        raise NotImplementedError("ApprovalsMixin provides this")


_PUNCT = str.maketrans({c: " " for c in ".,;:!?()[]\"'`—–-"})


def _words(text: str) -> str:
    """Strip what a restatement changes and meaning does not. Without this the
    memory deduplicator compares tokens like `renew,` against `renew` and calls
    one sentence two facts."""
    return text.lower().translate(_PUNCT)


def _locked(method):
    """Serialise every statement pair against the shared connection.

    One Store is shared by the console's per-request threads and the background
    run loop. sqlite3 serialises individual C calls, but not the execute/commit
    pair each method below performs: without this, two threads land inside each
    other's implicit transaction. Measured on twelve concurrent writers, that
    raised `cannot start a transaction within a transaction` and silently kept
    414 of 3200 rows, so the lock is load-bearing, not defensive.

    RLock rather than Lock because these are genuinely re-entrant: status()
    calls list_approvals() and list_tasks(), flow_metrics() calls both status()
    and list_tasks(). A plain Lock self-deadlocks on the first status() call.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper
