"""Schema versioning: a fresh store is at the current version, and an older
store is migrated in place rather than needing a manual backup-and-recreate."""

import sqlite3

from app.store import SCHEMA_VERSION, Store


def _columns(db, table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def test_fresh_store_is_at_current_version(tmp_path):
    store = Store(str(tmp_path))
    assert store.schema_version() == SCHEMA_VERSION
    assert "tool" in _columns(store.db, "tasks")


def test_old_store_is_migrated_in_place(tmp_path):
    # Simulate a pre-migration DB: a tasks table without the `tool` column and
    # user_version left at 0.
    path = tmp_path / "corparius.sqlite"
    db = sqlite3.connect(str(path))
    db.executescript(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT,"
        " title TEXT, target TEXT, priority INTEGER, status TEXT, created_by TEXT,"
        " note TEXT, ts REAL);"
    )
    db.commit()
    assert db.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "tool" not in _columns(db, "tasks")
    db.close()

    store = Store(str(tmp_path))  # opening it runs the migration
    assert store.schema_version() == SCHEMA_VERSION
    assert "tool" in _columns(store.db, "tasks")


def test_migration_is_idempotent(tmp_path):
    Store(str(tmp_path))
    # Reopening an already-current store must not raise or change the version.
    store = Store(str(tmp_path))
    assert store.schema_version() == SCHEMA_VERSION
