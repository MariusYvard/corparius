"""Test isolation for the settings resolver.

corparius/cfg.py resolves settings from the process environment, then the SQLite
settings table, then the .env file. All three are real, machine-local state, so
without this fixture the suite would read whatever the developer happens to
have configured: a .env carrying CORP_LLM_MOCK=false would put every test in
live mode and send them to the network.

So: point the .env layer at a file that does not exist, point the store layer at
a throwaway directory, and pin mock mode. Tests that want a different value set
it with monkeypatch.setenv, which lands in layer 1 and outranks all of this.
"""

import socket

import pytest

from corparius import cfg


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
    from corparius import store as store_mod

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
        except Exception:  # a test may already have closed or corrupted it
            pass


@pytest.fixture(autouse=True)
def hermetic_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    # Removed, not pinned. CORP_HOME is what `companies/`, `skills/` and .env
    # hang off, and it is set on the machine of anyone actually running
    # corparius — so on a developer's own box three tests failed and any test
    # writing under user_home() reached into their real installation. Deleting
    # it gives every test the same answer a clean checkout gives; the tests that
    # need a home set their own, which still wins over this.
    monkeypatch.delenv("CORP_HOME", raising=False)
    cfg.set_dotenv_path(tmp_path / "absent.env")
    cfg.invalidate()
    yield
    cfg.set_dotenv_path(cfg.ROOT / ".env")
    cfg.invalidate()


# A test that reaches the network fails for reasons that have nothing to do with
# the code it is testing: a provider being slow, a rate limit, a laptop on a
# train. One did — `test_routing_check_is_green_when_every_tier_resolves` set a
# provider key, which made the doctor's catalogue check dial a real endpoint —
# and it was invisible because it passed.
#
# Loopback stays open: several tests start the real console and talk to it, and
# that is the point of them.
_real_connect = socket.socket.connect


def _refuse_the_network(self, address):
    host = address[0] if isinstance(address, tuple) else str(address)
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise AssertionError(
            f"this test reached the network ({address}). Stub the call: a suite that "
            "depends on a third party fails for reasons unrelated to the code."
        )
    return _real_connect(self, address)


socket.socket.connect = _refuse_the_network
