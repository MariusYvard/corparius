"""The API contract, from the first route that has one.

The 56 routes this console grew are the *internal shape of a page*: they changed whenever the
page did, which was fine while the page was the only client. A second client freezes them — the
plan's words — so the rule from here is that a new route is `/api/v1/` and the unprefixed ones
are a **declared** legacy set.

Declared rather than described, because a set nobody asserts is a wish. The count is pinned:
adding a route outside v1 has to be a deliberate line in this file, and it will be read.

`/api/v1/meta` is the first, and it is the one a thin client cannot do without. Versions so it
can refuse a core too old for it, rather than failing one request at a time; capabilities so it
hides a button instead of discovering a 404.
"""

import pytest

from corparius.api import routes
from corparius.api.server import build_server
from corparius.app import meta

V1 = "/api/v1/"

# Every route that predates the contract. They are the console's own shape and they stay for a
# version — the plan says so — but the list only ever shortens, and nothing joins it.
LEGACY_COUNT = 54  # unchanged by the v1 additions: nothing left the legacy set


def _paths() -> list[str]:
    return [r.path for r in routes.ALL_ROUTES]


def _legacy() -> list[str]:
    return sorted(p for p in _paths() if p.startswith("/api/") and not p.startswith(V1))


# --- the contract ---------------------------------------------------------------


def test_the_legacy_set_is_exactly_what_it_was():
    """A ratchet, not a description. If this number goes up, a route was added outside the
    contract; if it goes down, one moved and the line should say so."""
    found = _legacy()
    assert len(found) == LEGACY_COUNT, (
        f"{len(found)} unversioned /api routes, expected {LEGACY_COUNT}. A new route belongs "
        f"under {V1}; if one moved there, lower the count and say which."
    )


def test_at_least_one_route_is_versioned():
    """The guard on the guard: a contract with no members would make the rule vacuous."""
    assert [p for p in _paths() if p.startswith(V1)], "no v1 route at all"


def _by_version():
    """Every endpoint as `(method, suffix)`, split by which side of the contract it is on."""
    v1, legacy = set(), set()
    for r in routes.ALL_ROUTES:
        if r.path.startswith(V1):
            v1.add((r.method, r.path.removeprefix(V1)))
        elif r.path.startswith("/api/"):
            legacy.add((r.method, r.path.removeprefix("/api/")))
    return v1, legacy


def test_no_endpoint_is_both_versioned_and_not():
    """`GET /api/v1/meta` and `GET /api/meta` would be two routes an operator would reasonably
    expect to be the same, and nothing would say which won.

    On `(method, suffix)` rather than the suffix alone, and the distinction is real: `tasks` and
    `memory` now have a v1 **GET** and a legacy **POST**, which are different operations on the
    same noun and HTTP says so. The suffix-only version of this failed on exactly that; relaxing
    it to pass would have been wrong on its own, so the pairs it used to catch are declared below
    where a reader sees them.
    """
    v1, legacy = _by_version()
    both = sorted(v1 & legacy)
    assert not both, f"these answer the same method under both spellings: {both}"


# The reads that moved to v1 ahead of their writes. Declared, because it is the one place a client
# meets the migration: it polls `GET /api/v1/tasks` and still posts a decision to
# `POST /api/tasks`. Reads moved first because that is where the cost was — `/api/overview` was
# 48 530 bytes every five seconds — and the writes move when a v1 client needs to make one.
SPLIT_NOUNS = {"tasks", "memory"}


def test_the_nouns_split_across_versions_are_declared():
    """A ratchet on the migration debt, so "reads on v1, writes not" stays a decision rather than
    becoming the accidental shape of the API."""
    v1, legacy = _by_version()
    split = {s for _m, s in v1} & {s for _m, s in legacy}
    assert split == SPLIT_NOUNS, (
        f"nouns split across versions are {sorted(split)}, declared {sorted(SPLIT_NOUNS)}"
    )


# --- what meta says -------------------------------------------------------------


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from corparius.config import cfg
    from corparius.config.settings import Settings

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    import threading

    srv = build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_meta_answers_without_a_token(server, monkeypatch):
    """Public on purpose, like `/api/session`: a client has to learn what it is talking to
    before it can authenticate to it. It names no secret, no company and no setting value."""
    from corparius.config import cfg

    from .test_webui import _call

    monkeypatch.setenv("CORP_UI_TOKEN", "s3cret")
    cfg.invalidate()
    status, data = _call(server, "GET", "/api/v1/meta")
    assert status == 200 and data["ok"] is True


def test_meta_carries_three_versions_that_are_not_interchangeable(server):
    from .test_webui import _call

    _status, data = _call(server, "GET", "/api/v1/meta")
    assert data["api_version"] == meta.API_VERSION
    assert data["app_version"], "the build has to be identifiable"
    # The store's own stamp, not the constant this build expects. An upgrade migrates in place,
    # so what a client needs is what the database *is* at.
    from corparius.store.schema import SCHEMA_VERSION

    assert data["schema_version"] == SCHEMA_VERSION


def test_the_schema_version_comes_from_the_database(tmp_path):
    """Stated separately because reading the constant would be the easy mistake and would report
    the version this build expects rather than the one it found."""
    import inspect

    source = inspect.getsource(meta.describe)
    assert "store.schema_version()" in source
    assert "SCHEMA_VERSION" not in source, "that would be the constant, not the store"


def test_no_capability_is_declared_rather_than_resolved(server):
    """Measured beats declared, and here it is the difference between a client that works and
    one that offers what the operator never set up."""
    from .test_webui import _call

    _status, data = _call(server, "GET", "/api/v1/meta")
    caps = data["capabilities"]
    assert isinstance(caps, dict) and caps, "no capabilities at all"
    assert all(isinstance(v, bool) for v in caps.values()), "a capability is yes or no"


def test_durable_jobs_is_reported_as_a_yes_or_no_and_is_now_yes(server):
    """This read `is False` for one commit, and the assertion it carried was the important half:
    reported, not omitted — a client told *no* does not have to guess from an absent key.

    Schema 19 made it true. A run is a row in `jobs`, so it survives a restart of the console, and
    one the console was holding when it died reads back as `interrupted` rather than as silence.
    The flag stays asserted rather than deleted, because "the key is there and it is a boolean" is
    the promise, and the day it goes back to false a client must still find it.
    """
    from .test_webui import _call

    _status, data = _call(server, "GET", "/api/v1/meta")
    assert data["capabilities"]["durable_jobs"] is True


def test_the_capabilities_open_no_socket(tmp_path, monkeypatch):
    """The rule this file nearly broke. This endpoint is meant to be polled, and the ban on a
    network probe from a polled point was written after `/api/providers` opened one on every
    refresh. The first draft of `capabilities` called `stripe_check()`, which reads the live
    Stripe balance.

    The service is called directly rather than over HTTP, and that is the point: the first
    version of this test went through the test client and caught **the request itself** — a
    request *is* a socket, so it was measuring the trip rather than the handler.
    """
    import socket

    from corparius.config.settings import Settings
    from corparius.store import Store

    def refuse(*a, **k):
        raise AssertionError("resolving capabilities opened a socket")

    store = Store(str(tmp_path / "data"))
    try:
        monkeypatch.setattr(socket.socket, "connect", refuse)
        caps = meta.capabilities(Settings(), store)
        assert caps, "it has to answer something"
    finally:
        monkeypatch.undo()
        store.close()


def test_a_capability_follows_the_setting_it_reports(server, monkeypatch):
    """Non-vacuity for the whole idea: turn a thing off and the answer changes."""
    from corparius.config import cfg

    from .test_webui import _call

    _status, before = _call(server, "GET", "/api/v1/meta")
    assert before["capabilities"]["skills"] is True
    monkeypatch.setenv("CORP_SKILLS_ENABLED", "false")
    cfg.invalidate()
    _status, after = _call(server, "GET", "/api/v1/meta")
    assert after["capabilities"]["skills"] is False
