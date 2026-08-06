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
import threading
from pathlib import Path

from ..kernel import dotenv, paths
from . import store_layer

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
BOOTSTRAP = (
    "CORP_DATA_PATH",
    "CORP_LOG_LEVEL",
    "CORP_UI_HOST",
    "CORP_UI_PORT",
    "CORP_UI_TOKEN",
    "CORP_UI_ALLOWED_HOSTS",
    "CORP_SECRET_KEY",
)

_lock = threading.RLock()

_dotenv_path: Path = ROOT / ".env"
_dotenv_cache: dict[str, str] | None = None
_dotenv_stamp: tuple | None = None

# The parser moved to `kernel/dotenv.py`, next to the writer whose refusals it mirrors.
# The name stays here because this is where callers look for it — a settings module is a
# reasonable place to ask "what does a .env say", and `doctor` does exactly that.
parse_dotenv = dotenv.parse


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
    """Layer 2, from `config/store_layer.py`.

    Two arguments, both resolved from the layers *below* the store: where the database is,
    and the passphrase that opens any encrypted value in it. Neither can come from the
    store — you cannot ask the database where the database is, and a key inside the box it
    opens is not a key.
    """
    return store_layer.read(
        _bootstrap("CORP_DATA_PATH", paths.default_data_dir()),
        _bootstrap("CORP_SECRET_KEY").strip(),
    )


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
    global _dotenv_cache, _dotenv_stamp
    with _lock:
        _dotenv_cache, _dotenv_stamp = None, None
    store_layer.forget()
