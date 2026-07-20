"""The console is a ThreadingHTTPServer and the run loop writes from a
background thread, so reads and writes genuinely overlap.

Three facts, each measured on this suite rather than assumed, drive the design
in app/store.py:

1. Separate connections per thread (what app/webui.py did: a new Store per HTTP
   request) raise `database is locked` under load. Twelve writers lost nine.
2. Sharing one connection *without* a lock is worse, not better: threads land
   inside each other's implicit transaction, raising `cannot start a transaction
   within a transaction` and silently keeping 414 of 3200 rows.
3. One shared connection behind an RLock loses nothing.

A longer busy timeout does not help (1): SQLite returns BUSY immediately,
without calling the busy handler, when two connections try to upgrade a lock at
once. Python already applies a 5s timeout, and the failure happened anyway.
"""

import threading

from app.store import Store

# Twelve writers is what reliably reproduced the lost-row failure before the fix.
# The overlap test below runs shorter on purpose: flow_metrics re-reads the whole
# task table, so a long writer loop turns it quadratic and the test spends its
# time benchmarking that scan rather than exercising the overlap.
WRITERS, ROUNDS = 12, 300
OVERLAP_READERS, OVERLAP_ROUNDS = 4, 40


def _run(workers):
    """Run every worker concurrently and return the exceptions they raised."""
    errors: list[BaseException] = []
    lock = threading.Lock()

    def guard(fn, *args):
        try:
            fn(*args)
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=guard, args=(fn, *args)) for fn, *args in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_shared_store_keeps_every_concurrent_write(tmp_path):
    """The console's shape: one Store, many request threads. This is the
    regression proof for the lock. Without it the count comes back short, which
    is the failure mode that matters most: no exception reaches the operator,
    the action log simply loses entries."""
    with Store(str(tmp_path / "data")) as store:

        def writer(n):
            for i in range(ROUNDS):
                store.record_action("t", f"agent{n}", "tool", {"i": i}, "out", True)

        errors = _run([(writer, n) for n in range(WRITERS)])
        assert not errors, f"concurrent writes raised: {errors[:3]}"
        assert store.status("t")["actions"] == WRITERS * ROUNDS


def test_shared_store_survives_overlapping_reads_and_writes(tmp_path):
    """A background run recording actions while the console polls
    /api/overview, which reads status and the flow metrics on every tick."""
    with Store(str(tmp_path / "data")) as store:

        def writer(n):
            for i in range(OVERLAP_ROUNDS):
                store.record_usage("t", f"agent{n}", 10, 5)
                store.add_task("t", f"task {n}-{i}", "social", tool="draft_social_post")

        def reader():
            for _ in range(OVERLAP_ROUNDS):
                store.status("t")
                store.flow_metrics("t")

        workers = [(writer, n) for n in range(WRITERS)] + [
            (reader,) for _ in range(OVERLAP_READERS)
        ]
        errors = _run(workers)
        assert not errors, f"overlapping reads and writes raised: {errors[:3]}"
        assert store.status("t")["tokens"] == WRITERS * OVERLAP_ROUNDS * 15


def test_reentrant_reads_do_not_deadlock(tmp_path):
    """status() calls list_approvals() and list_tasks(); flow_metrics() calls
    status(). A plain Lock would hang here rather than fail, so this test would
    time out rather than report - which is itself the signal."""
    with Store(str(tmp_path / "data")) as store:
        store.add_task("t", "task", "social")
        assert store.flow_metrics("t")["wip"] == 1


def test_a_second_connection_sees_committed_rows(tmp_path):
    """app/cfg.py opens the store read-only as its settings layer, so a
    console-saved setting a second connection cannot see would silently do
    nothing. WAL changes when that becomes visible, so it is worth pinning."""
    data = str(tmp_path / "data")
    with Store(data) as writer:
        writer.set_setting("CORP_TEST_KEY", "value")
    with Store(data) as reader:
        assert reader.get_setting("CORP_TEST_KEY") == "value"


def test_wal_is_enabled(tmp_path):
    """Set once and recorded in the database header. It is what lets the CLI
    read while the console writes, and it is allowed to fail on filesystems
    that cannot host the sidecar - hence the read-back rather than a bare
    assertion that the pragma was issued."""
    with Store(str(tmp_path / "data")) as store:
        mode = store.db.execute("PRAGMA journal_mode").fetchone()[0].lower()
        assert mode == "wal"
        assert store.db.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000


def test_close_is_idempotent_and_frees_the_file(tmp_path):
    """Windows will not delete a file that is still open, so a Store left open
    by a test breaks tmp_path cleanup rather than the test itself."""
    data = str(tmp_path / "data")
    store = Store(data)
    store.record_action("t", "a", "tool", {}, "out", True)
    store.close()
    with Store(data) as reopened:
        assert reopened.status("t")["actions"] == 1
