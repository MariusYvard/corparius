"""Layer 2 of settings resolution: the table the console writes. Rank 1, declared exception.

This is the one module at rank 1 allowed to touch `sqlite3` — the other is `store/**`, and
`tests/test_layers.py` names both. The reason is the sentence in `cfg`'s docstring: you
cannot ask the database where the database is. Locating the store needs the environment and
.env first, so the layer that reads the store has to sit *inside* the settings resolver
rather than above it.

It was inside `cfg.py`, which meant a 200-line four-layer resolver with a database
connection, a lock, a cache and a `PRAGMA data_version` poll in the middle of it. Two
concerns, and only one of them is about precedence.

**Read-only, and never creating anything.** The connection is opened `mode=ro` through a URI
so that merely *reading* a setting cannot create the data directory. `Store()` would create
it at import time, and `cfg` is imported by thirty modules — including ones that run before
an operator has decided where their data lives.

`cfg` imports this module directly. That is deliberate: the alternative considered was a
layer registry with self-registration, which introduces a failure mode this design does not
have — if registration silently did not happen, every setting saved from the console would
stop being read and **the application would keep working** on defaults. There is exactly one
store layer and there will only ever be one, so a plain import says so and cannot half-fail.
"""

from __future__ import annotations

import os
import sqlite3
import threading

from ..kernel import crypto

_lock = threading.RLock()

_conn: sqlite3.Connection | None = None
_conn_path: str | None = None
_cache: dict[str, str] = {}
_version: int | None = None


def read(data_path: str, passphrase: str) -> dict[str, str]:
    """The settings table as a dict, or an empty layer when there is no database yet.

    `passphrase` is passed in rather than resolved here, and that is what keeps this module
    a leaf: values may be encrypted at rest (opt-in, CORP_SECRET_KEY), and the key that opens
    them is a bootstrap setting — it resolves from the environment or .env, never from the
    table being decrypted. Asking `cfg` for it from inside here is the import cycle that
    `secretbox` used to have.
    """
    global _conn, _conn_path, _cache, _version
    path = os.path.join(data_path, "corparius.sqlite")
    with _lock:
        if path != _conn_path:
            close()
            _conn_path = path
        if _conn is None:
            if not os.path.isfile(path):
                _cache = {}
                return _cache
            try:
                _conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
            except sqlite3.Error:
                _cache = {}
                return _cache
            _version = None
        try:
            # data_version changes when another connection commits, which is exactly how the
            # console's writes reach this read-only view — and how a *different process*
            # writing the store is seen at all. tests/test_cfg.py proves that across a real
            # subprocess boundary, because a fixture cannot.
            version = _conn.execute("PRAGMA data_version").fetchone()[0]
            if version != _version:
                rows = _conn.execute("SELECT key, value FROM settings").fetchall()
                # decrypt_safe leaves plaintext untouched and never raises: one unreadable
                # value must not bring down a whole settings load. The doctor reports it.
                _cache = {k: crypto.decrypt_safe(v, passphrase) for k, v in rows}
                _version = version
        except sqlite3.Error:
            # No settings table yet (older database), or the file went away.
            close()
            _cache = {}
        return _cache


def close() -> None:
    global _conn, _version
    if _conn is not None:
        try:
            _conn.close()
        except sqlite3.Error:
            pass
    _conn, _version = None, None


def forget() -> None:
    """Drop the cache and the connection. `cfg.invalidate()` calls this."""
    global _cache
    with _lock:
        _cache = {}
        close()
