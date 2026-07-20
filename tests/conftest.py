"""Test isolation for the settings resolver.

app/cfg.py resolves settings from the process environment, then the SQLite
settings table, then the .env file. All three are real, machine-local state, so
without this fixture the suite would read whatever the developer happens to
have configured: a .env carrying CORP_LLM_MOCK=false would put every test in
live mode and send them to the network.

So: point the .env layer at a file that does not exist, point the store layer at
a throwaway directory, and pin mock mode. Tests that want a different value set
it with monkeypatch.setenv, which lands in layer 1 and outranks all of this.
"""
import pytest

from app import cfg


@pytest.fixture(autouse=True)
def close_stores(monkeypatch):
    """Close every Store a test opens, wherever it opened it.

    A Store now holds its sqlite connection for its whole life instead of one
    per call, so a test that constructs one and drops it leaks the handle. On
    Windows that is not cosmetic: the file stays locked and tmp_path cleanup
    fails, which is the same lifetime issue the console had. Tracking the class
    rather than a fixture catches direct `Store(...)` calls too, so no test has
    to remember. close() is idempotent, so a test that closes its own is fine.
    """
    from app import store as store_mod
    opened = []
    original_init = store_mod.Store.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        opened.append(self)

    monkeypatch.setattr(store_mod.Store, "__init__", tracking_init)
    yield
    for store in opened:
        try:
            store.close()
        except Exception:   # a test may already have closed or corrupted it
            pass


@pytest.fixture(autouse=True)
def hermetic_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    cfg.set_dotenv_path(tmp_path / "absent.env")
    cfg.invalidate()
    yield
    cfg.set_dotenv_path(cfg.ROOT / ".env")
    cfg.invalidate()
