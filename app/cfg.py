"""Settings resolution across four layers, highest wins:

    1. os.environ   the real process environment (shell, systemd, docker
                    `environment:` and `env_file:`, pytest monkeypatch)
    2. SQLite       the settings table, written by the operator console
    3. .env         the file, parsed into a private dict
    4. default      whatever the caller passes

The .env file is deliberately NOT loaded into os.environ: that would promote it
to layer 1 and silently outrank anything saved from the console. Under docker
compose, `env_file:` does inject .env into the real environment, which is why
docker-compose.yml mounts .env instead (see docs) — the deployer's explicit
`environment:` entries still win, and the console says so rather than pretending
otherwise.

Bootstrap keys (BOOTSTRAP) resolve from layers 1, 3 and 4 only. They must be
readable before SQLite can be opened — you cannot ask the database where the
database is — so console writes to them go to .env instead.

`get(name, default)` is a drop-in for `os.environ.get(name, default)`. Reading
never creates a file: the store is opened read-only and a missing database is
simply an empty layer.
"""
from __future__ import annotations
import os
import sqlite3
import threading
from pathlib import Path

from . import paths

# The writable home. In a source checkout this is the repository root, so the
# default .env location below is unchanged; frozen, it is a per-OS directory.
# Kept as a module attribute because tests (and the console teardown) reference
# `cfg.ROOT / ".env"`.
ROOT = paths.user_home()

# Keys that must resolve before the store can be opened. Console writes to
# these go to .env, and they only take effect on restart.
# CORP_UI_ALLOWED_HOSTS belongs here, not in the settings registry: BOOTSTRAP
# keys resolve from the environment and .env only, never from the store. As an
# ordinary setting, a successful cross-site write to /api/settings could add the
# attacker's own host to the allow-list and disable the defence permanently. A
# security control must not be writable through the surface it protects.
BOOTSTRAP = ("CORP_DATA_PATH", "CORP_LOG_LEVEL", "CORP_UI_HOST", "CORP_UI_PORT",
             "CORP_UI_TOKEN", "CORP_UI_ALLOWED_HOSTS", "CORP_SECRET_KEY")

_lock = threading.RLock()

_dotenv_path: Path = ROOT / ".env"
_dotenv_cache: dict[str, str] | None = None
_dotenv_stamp: tuple | None = None

_db_conn: sqlite3.Connection | None = None
_db_conn_path: str | None = None
_db_cache: dict[str, str] = {}
_db_version: int | None = None


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_dotenv(text: str) -> dict[str, str]:
    """KEY=value lines. Comments, blanks and malformed lines are skipped;
    `export KEY=value` and quoted values are accepted."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if key:
            out[key] = _unquote(value)
    return out


def _dotenv_layer() -> dict[str, str]:
    global _dotenv_cache, _dotenv_stamp
    with _lock:
        try:
            st = _dotenv_path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            _dotenv_cache, _dotenv_stamp = {}, None
            return {}
        if _dotenv_cache is None or stamp != _dotenv_stamp:
            try:
                _dotenv_cache = parse_dotenv(_dotenv_path.read_text(encoding="utf-8"))
            except OSError:
                _dotenv_cache = {}
            _dotenv_stamp = stamp
        return _dotenv_cache


def _bootstrap(name: str, default: str = "") -> str:
    """Layers 1 > 3 > 4. Used for BOOTSTRAP keys and to locate the store."""
    value = os.environ.get(name)
    if value is not None:
        return value
    return _dotenv_layer().get(name, default)


def _db_layer() -> dict[str, str]:
    """The settings table, or an empty layer when there is no database yet.
    Opened read-only so that merely reading configuration never creates the
    data directory (Store() would, at import time)."""
    global _db_conn, _db_conn_path, _db_cache, _db_version
    data_path = _bootstrap("CORP_DATA_PATH", paths.default_data_dir())
    path = os.path.join(data_path, "corparius.sqlite")
    with _lock:
        if path != _db_conn_path:
            _close_db()
            _db_conn_path = path
        if _db_conn is None:
            if not os.path.isfile(path):
                _db_cache = {}
                return _db_cache
            try:
                _db_conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                                           check_same_thread=False)
            except sqlite3.Error:
                _db_cache = {}
                return _db_cache
            _db_version = None
        try:
            # data_version changes when another connection commits, which is
            # exactly how the console's writes reach this read-only view.
            version = _db_conn.execute("PRAGMA data_version").fetchone()[0]
            if version != _db_version:
                rows = _db_conn.execute("SELECT key, value FROM settings").fetchall()
                # Values may be encrypted at rest (opt-in, CORP_SECRET_KEY);
                # decrypt_safe leaves plaintext untouched and never raises.
                from . import secretbox
                _db_cache = {k: secretbox.decrypt_safe(v) for k, v in rows}
                _db_version = version
        except sqlite3.Error:
            # No settings table yet (older database), or the file went away.
            _close_db()
            _db_cache = {}
        return _db_cache


def _close_db() -> None:
    global _db_conn, _db_version
    if _db_conn is not None:
        try:
            _db_conn.close()
        except sqlite3.Error:
            pass
    _db_conn, _db_version = None, None


def get(name: str, default: str = "") -> str:
    """Resolve a setting. Drop-in for os.environ.get(name, default)."""
    value = os.environ.get(name)
    if value is not None:
        return value
    if name not in BOOTSTRAP:
        value = _db_layer().get(name)
        if value is not None:
            return value
    return _dotenv_layer().get(name, default)


def source(name: str) -> str:
    """Which layer answers for this key: env, db, dotenv or default. The
    console badges anything resolved from "env" as read-only, so that a value
    the operator cannot change from the page is never silently ignored."""
    if os.environ.get(name) is not None:
        return "env"
    if name not in BOOTSTRAP and _db_layer().get(name) is not None:
        return "db"
    if _dotenv_layer().get(name) is not None:
        return "dotenv"
    return "default"


def get_bool(name: str, default: str = "false") -> bool:
    return get(name, default).strip().lower() == "true"


def get_int(name: str, default: int) -> int:
    try:
        return int(get(name, str(default)).strip())
    except ValueError:
        return default


def get_float(name: str, default: float) -> float:
    try:
        return float(get(name, str(default)).strip())
    except ValueError:
        return default


def get_csv(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in get(name, default).split(",") if v.strip()]


def dotenv_path() -> Path:
    return _dotenv_path


def set_dotenv_path(path: Path) -> None:
    """Point the .env layer somewhere else (the console's --env-file, tests)."""
    global _dotenv_path, _dotenv_cache, _dotenv_stamp
    with _lock:
        _dotenv_path = Path(path)
        _dotenv_cache, _dotenv_stamp = None, None


def invalidate() -> None:
    """Drop every cached layer. Called after a write and by the test fixture."""
    global _dotenv_cache, _dotenv_stamp, _db_cache
    with _lock:
        _dotenv_cache, _dotenv_stamp = None, None
        _db_cache = {}
        _close_db()
