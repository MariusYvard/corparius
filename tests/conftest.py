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

import hashlib
import socket
from pathlib import Path

import pytest

from corparius import cfg

# The checkout's own companies/, and the one company inside it that git tracks.
# The rest of that directory is gitignored, which is exactly why nobody noticed
# the `d`, `m` and `t` accumulating beside the example — every one of them
# written by a test, and invisible to git by design.
CHECKOUT_COMPANIES = Path(__file__).resolve().parent.parent / "companies"
EXAMPLE_COMPANY = CHECKOUT_COMPANIES / "example"


def _checkout_digest() -> dict[str, str]:
    """Every file under the checkout's companies/, hashed.

    The whole directory, not just the tracked example. Watching `example` alone is
    how `companies/d`, `companies/m` and `companies/t` went on being written run
    after run: `companies/*` is gitignored apart from the example, so nothing —
    not git, not the guard — was looking at them.
    """
    if not CHECKOUT_COMPANIES.is_dir():
        return {}
    return {
        p.relative_to(CHECKOUT_COMPANIES).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(CHECKOUT_COMPANIES.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="session", autouse=True)
def guard_the_checkout():
    """Fail the run if a test wrote into the checkout's companies/ directory.

    A backstop, not the defence: `hermetic_settings` gives every test an empty
    private home, so nothing should reach here at all. It exists because the
    setting that aims those writes has been wrong in two different directions
    already — at the developer's real installation, then at the working tree —
    and because both times the evidence was a file nobody was looking at.

    One pass over ten small files per session, against 768 ms a test for the
    copy-based alternative.
    """
    before = _checkout_digest()
    yield
    after = _checkout_digest()
    touched = sorted(set(before) ^ set(after)) + sorted(
        k for k in before.keys() & after.keys() if before[k] != after[k]
    )
    assert not touched, (
        f"a test wrote into the checkout's companies/: {touched}. "
        "Give the fixture its own CORP_HOME."
    )


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
    # An empty private home, which is neither of the two places this setting has
    # already been wrong.
    #
    # CORP_HOME is what `companies/`, `skills/` and .env hang off, and it is set
    # on the machine of anyone actually running corparius: left alone, tests wrote
    # into a real installation. Deleting it fixed that and aimed them at the
    # checkout instead, which is also writable — so tests calling tools with the
    # slugs `t`, `d` and `m` left companies/t, companies/d and companies/m sitting
    # in the working tree, gitignored and therefore unnoticed, while a real
    # orchestrator tick rewrote the tracked companies/example/company.yaml.
    #
    # Empty and not a copy: copying companies/ into each home closes the same hole
    # and measured 768 ms a test, three times the suite's whole runtime. The few
    # fixtures that need the bundled company copy it themselves, which is also the
    # honest shape — a test that runs a company should say which company.
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CORP_HOME", str(home))
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
