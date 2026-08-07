"""Schema versioning: a fresh store is at the current version, and an older
store is migrated in place rather than needing a manual backup-and-recreate."""

import sqlite3

from corparius.store import Store
from corparius.store.schema import SCHEMA_VERSION


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
    # v6 added the measured machine profile.
    assert store.load_machine() is None
    store.save_machine({"tokens_per_second": 8.6, "placement": "cpu", "model": "gemma:2b"})
    assert store.load_machine()["placement"] == "cpu"


def test_migration_is_idempotent(tmp_path):
    Store(str(tmp_path))
    # Reopening an already-current store must not raise or change the version.
    store = Store(str(tmp_path))
    assert store.schema_version() == SCHEMA_VERSION


def test_an_older_build_opening_a_newer_store_says_so(tmp_path, caplog):
    """`_migrate` only walks forward, so a store a newer corparius migrated was
    opened, run and written to in complete silence. Rolling back to the previous
    build is the recovery path when an update goes wrong, so it still opens —
    but an old build writing where a later schema means something else is how
    data gets quietly wrong, and quiet is the one thing this store does not do.
    """
    import logging
    import sqlite3

    Store(str(tmp_path)).close()
    db = sqlite3.connect(tmp_path / "corparius.sqlite")
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 3}")
    db.commit()
    db.close()

    with caplog.at_level(logging.WARNING, logger="corparius.store"):
        store = Store(str(tmp_path))
    assert store.schema_version() == SCHEMA_VERSION + 3, "it still opens: rollback needs that"
    store.close()
    said = caplog.text
    assert "newer corparius" in said
    assert "restore the backup" in said


def test_the_doctor_fails_on_a_store_from_the_future(tmp_path, monkeypatch):
    import sqlite3

    from corparius import doctor
    from corparius.config.settings import Settings

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    Store(str(tmp_path)).close()
    db = sqlite3.connect(tmp_path / "corparius.sqlite")
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    db.commit()
    db.close()
    store = Store(str(tmp_path))
    try:
        level, name, message = doctor._check_store(Settings(), store)
    finally:
        store.close()
    assert (level, name) == ("fail", "store")
    assert "newer corparius" in message and "restore the backup" in message


def test_the_doctor_is_quiet_about_a_store_at_the_right_version(tmp_path, monkeypatch):
    from corparius import doctor
    from corparius.config.settings import Settings

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    store = Store(str(tmp_path))
    try:
        level, _, message = doctor._check_store(Settings(), store)
    finally:
        store.close()
    assert level == "ok" and "writable" in message


def test_a_populated_v14_store_keeps_its_tasks_and_gains_why(tmp_path):
    """v15 splits the agent's reason out of `note`, which every status change
    overwrites. A store with a backlog in it has to reach the new shape by being
    migrated, with the backlog intact."""
    path = tmp_path / "corparius.sqlite"
    db = sqlite3.connect(str(path))
    db.executescript(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT,"
        " title TEXT, target TEXT, priority INTEGER, status TEXT, created_by TEXT,"
        " note TEXT, ts REAL, tool TEXT);"
        "PRAGMA user_version = 14;"
    )
    db.execute(
        "INSERT INTO tasks (company, title, target, priority, status, created_by, note, ts, tool)"
        " VALUES ('t','Idea from support','support',2,'approved','support','validated by CEO',"
        " 1.0,'draft_support_reply')"
    )
    db.commit()
    db.close()

    store = Store(str(tmp_path))
    assert store.schema_version() == SCHEMA_VERSION
    assert "why" in _columns(store.db, "tasks")
    kept = store.list_tasks("t", "approved")[0]
    assert kept["title"] == "Idea from support" and kept["note"] == "validated by CEO"
    assert kept["why"] is None, "an old row has no reason to show, and does not invent one"
    store.close()
