"""Layer 2 of settings resolution, across a real process boundary.

Extracting the SQLite layer out of `cfg` creates a failure mode worth naming: if the layer
stopped being consulted, **every setting saved from the console would quietly stop being
read and the application would keep working** on its defaults. Nothing would crash. The
operator would change a value on the page, see it saved, and watch nothing happen.

A fixture cannot catch that, which is the point of this file. The round trip below writes
through `Store` in *this* process and reads through `cfg.get` in a **fresh subprocess** —
so an import-order mistake, a layer that is never reached, or a connection that caches
across a commit shows up as a wrong string rather than as nothing at all.

`PRAGMA data_version` is the mechanism under test. It is how a read-only connection notices
that another connection committed, and it had no test of its own.
"""

import json
import subprocess
import sys

from corparius.config import cfg, store_layer
from corparius.store import Store


def _read_in_a_fresh_process(data_path, keys, env_extra=None):
    """What `cfg.get` answers for `keys` in an interpreter that has just started.

    Deliberately a subprocess and not `importlib.reload`: a reload keeps the parent's
    `sys.modules`, so a module that only works because something else imported it first
    still passes. A new interpreter has to do the whole resolution itself.
    """
    code = (
        "import json, sys;"
        "from corparius.config import cfg;"
        f"print(json.dumps({{k: cfg.get(k) for k in {keys!r}}}))"
    )
    env = {
        "CORP_DATA_PATH": str(data_path),
        "PATH": "",
        "SYSTEMROOT": "C:\\Windows",  # Windows needs it to start an interpreter at all
        **(env_extra or {}),
    }
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr[-800:]
    return json.loads(out.stdout.strip())


def test_a_setting_written_by_the_store_is_read_by_a_new_process(tmp_path, monkeypatch):
    """The whole contract, end to end. If the store layer is not consulted, this returns
    "" and the assertion says so — which is exactly the silence the extraction risked."""
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    store = Store(str(tmp_path))
    try:
        store.set_setting("CORP_TICK_SECONDS", "77")
    finally:
        store.close()
    got = _read_in_a_fresh_process(tmp_path, ["CORP_TICK_SECONDS"])
    assert got["CORP_TICK_SECONDS"] == "77", (
        "a value saved through Store did not reach cfg.get in a new process: "
        "the store layer is not being read"
    )


def test_the_environment_still_outranks_the_store(tmp_path, monkeypatch):
    """Layer 1 over layer 2, proved in the process where it matters. The docstring in `cfg`
    promises the deployer's explicit `environment:` entries win, and the console badges
    anything resolved from env as read-only on the strength of it."""
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    store = Store(str(tmp_path))
    try:
        store.set_setting("CORP_TICK_SECONDS", "77")
    finally:
        store.close()
    got = _read_in_a_fresh_process(tmp_path, ["CORP_TICK_SECONDS"], {"CORP_TICK_SECONDS": "5"})
    assert got["CORP_TICK_SECONDS"] == "5"


def test_reading_a_setting_never_creates_the_data_directory(tmp_path):
    """`mode=ro` through a URI, and it is load-bearing: `cfg` is imported by thirty modules,
    some of which run before an operator has decided where their data lives. `Store()` would
    create the directory at import time."""
    absent = tmp_path / "not-yet"
    got = _read_in_a_fresh_process(absent, ["CORP_TICK_SECONDS"])
    assert got["CORP_TICK_SECONDS"] == ""
    assert not absent.exists(), "merely reading a setting created the data directory"


def test_a_later_commit_is_seen_without_reopening(tmp_path, monkeypatch):
    """`PRAGMA data_version`, in this process. The read-only connection is long-lived, so
    without this it would answer from a snapshot taken before the console's write — which is
    the bug shape that makes a settings page look like it does nothing."""
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    store = Store(str(tmp_path))
    try:
        store.set_setting("CORP_TICK_SECONDS", "11")
        cfg.invalidate()
        assert cfg.get("CORP_TICK_SECONDS") == "11"
        # No invalidate this time: the version poll alone has to notice.
        store.set_setting("CORP_TICK_SECONDS", "22")
        assert cfg.get("CORP_TICK_SECONDS") == "22"
    finally:
        store.close()
        cfg.invalidate()


def test_a_file_that_is_not_a_database_is_an_empty_layer_not_a_crash(tmp_path, monkeypatch):
    """An operator's stray file, or a half-written one. Resolution has to degrade to the
    layers below rather than take the process down."""
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    (tmp_path / "corparius.sqlite").write_text("not a database", encoding="utf-8")
    store_layer.forget()
    try:
        assert cfg.get("CORP_TICK_SECONDS", "fallback") == "fallback"
    finally:
        store_layer.forget()
