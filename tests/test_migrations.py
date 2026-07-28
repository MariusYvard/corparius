"""Schema versioning: a fresh store is at the current version, and an older
store is migrated in place rather than needing a manual backup-and-recreate."""

import sqlite3

from corparius.store import SCHEMA_VERSION, Store


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


def test_a_populated_v1_store_gains_the_rules_table_without_losing_data(tmp_path):
    """The upgrade an existing operator actually performs. Standing permission
    rules arrived at v2, and a store with real history in it has to reach the
    new shape by being migrated, not by being recreated."""
    path = tmp_path / "corparius.sqlite"
    db = sqlite3.connect(str(path))
    db.executescript(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT,"
        " title TEXT, target TEXT, priority INTEGER, status TEXT, created_by TEXT,"
        " note TEXT, ts REAL, tool TEXT);"
        "CREATE TABLE approvals (id TEXT PRIMARY KEY, company TEXT, agent TEXT,"
        " tool TEXT, parameters TEXT, status TEXT, note TEXT, ts REAL);"
        "PRAGMA user_version = 1;"
    )
    db.execute(
        "INSERT INTO tasks (company, title, target, priority, status, created_by, note, ts, tool)"
        " VALUES ('t','Ship it','coder',2,'approved','ceo','',1.0,'generate_code')"
    )
    db.commit()
    db.close()

    store = Store(str(tmp_path))
    assert store.schema_version() == SCHEMA_VERSION
    assert store.list_tasks("t", "approved")[0]["title"] == "Ship it"
    store.add_rule("t", "generate_code", "always")
    assert store.find_rule("t", "generate_code") == "always"
    # v3 arrived with durable memory and v4 with the typed inbox; the same
    # store must reach both.
    assert store.remember("t", "ceo", "Coaches renew.")
    assert store.recall("t")[0]["fact"] == "Coaches renew."
    ident = store.add_inbox("t", "design", "question", "Where should it be published?")
    assert store.resolve_inbox(ident, "netlify") is True
    # v5 added the cost column; an existing usage row keeps 0, which the console
    # reads as "not reported" rather than "free".
    assert store.cost_reported("t") is False
    store.record_usage("t", "ceo", 10, 5, 0.002)
    assert store.cost_reported("t") is True


def test_migration_is_idempotent(tmp_path):
    Store(str(tmp_path))
    # Reopening an already-current store must not raise or change the version.
    store = Store(str(tmp_path))
    assert store.schema_version() == SCHEMA_VERSION
