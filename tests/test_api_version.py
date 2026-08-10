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

import pathlib

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


# The endpoints offered under **both** spellings, and what each pair must satisfy. An operation a
# client can reach two ways is what "the legacy paths stay for a version" means — but only if both
# ways do the same thing, so each entry names the service both handlers must reach.
#
# The first version of this guard forbade the overlap outright, and it was right to fail when these
# appeared: two handlers for one operation is exactly how the console and the terminal came to
# disagree about deciding an approval. The answer is not to allow the overlap, it is to require
# **one service underneath it** — which is `tests/test_two_callers_agree.py`'s idea applied to the
# two versions of one API.
ALIASED = {
    ("POST", "approvals"): "app_approvals.decide",
    ("POST", "inbox"): "app_inbox.answer",
    ("POST", "tasks"): "app_tasks.edit",
    ("POST", "memory"): "app_memory.decide",
    ("POST", "drafts"): "app_drafts.set_state",
    # The read too, because both spellings answer the same four keys and the count that gates the
    # agent is one of them: `queued` is `draft` **and** `queued` together, so two spellings of that
    # sum are two chances for one to become just one state. Written out twice, identically, until the
    # v1 pair was added; `adapters.drafts_payload` is the one copy now.
    ("GET", "drafts"): "adapters.drafts_payload(",
    # The four documents endpoints. Not an `app_*` service either, and for a reason worth stating:
    # `documents.py` is rank 4 and already host-free — it takes a slug and a `Path` and no `Store`,
    # no `Settings`, no `Ctx` — so it *is* the service. Extracting an `app/documents.py` that forwarded
    # to it would be the pure indirection the plan's "what not to do" list names.
    ("GET", "documents"): "documents.inventory(",
    ("POST", "documents"): "documents.save(",
    ("POST", "documents/delete"): "documents.remove(",
    # Not an `app_*` service, and audited rather than assumed. Revoking a standing rule is one store
    # call with nothing that belongs beside it: nothing is parked on a rule — revoking means the tool
    # asks again next time — so the two-calls-one-caller-forgets shape that produced the approvals
    # divergence cannot arise. A service here would be pure indirection, so the invariant is the
    # weaker true one: both spellings reach `drop_rule`.
    ("POST", "rules"): "drop_rule(",
    # Not an `app_*` service, and the invariant is "one function underneath" rather than "a rank-5
    # one": listing the companies is `company.list_slugs()` behind a one-line reader, and both
    # handlers reach it. The v1 payload omits `templates`, which belongs to the creation wizard.
    ("GET", "companies"): "state.companies()",
    # The providers tab. `adapters.providers_payload` is the console's half of the read and both
    # spellings answer with it; `adapters.set_env` is the write, and it is the function that carried
    # the sixth divergence — its own `key in WRITABLE` check instead of `app_settings.validate`, so a
    # registry field written through it was stored with no coercion at all. One function underneath is
    # what makes that fix cover both spellings rather than one.
    ("GET", "providers"): "adapters.providers_payload()",
    ("POST", "providers"): "adapters.set_env(",
    ("POST", "tiers/recommend"): "recommended_routing(",
    ("POST", "claude/setup"): "adapters.claude_setup(",
    ("POST", "preflight"): "preflight.run(",
    # The two whose legacy spelling differs only in the noun's position, and which are the same call.
    ("GET", "ollama"): "ollama_setup.status(",
    # The durable pair. Both spellings claim through `app_setup.start_pull` / `start_sweep`, which is
    # what puts the "already running" guard in the store instead of in this process's memory — the
    # thing that let a sweep left behind by a crashed console be invisible to the next one.
    ("POST", "ollama/pull"): "app_setup.start_pull(",
    ("POST", "preflight/sweep"): "app_setup.start_sweep(",
}

# The third category, and it needed naming: an endpoint whose **v1 path is a different spelling**.
# `ALIASED` finds pairs by suffix intersection, so a renamed one is invisible to it — the guard would
# have reported both halves as unpaired and asserted nothing about either.
#
# `/api/document/text` is singular because the shipped page reads one document; in v1 it is
# `/api/v1/documents/text`, a sub-resource of the collection, which is what it actually is. Renaming
# it is the whole reason v1 exists, and it must not also become a second implementation.
#
# (method, legacy suffix, v1 suffix) -> the function both handlers must reach.
RENAMED = {
    ("GET", "document/text", "documents/text"): "documents.full_text(",
    # The providers tab moved two nouns into their collection. `/api/provider/models` and
    # `/api/test/provider` were shaped by the page's own JavaScript; a sub-resource of `providers` is
    # what they are, and `probe` says what the call costs — one real request on the operator's account.
    ("POST", "provider/models", "providers/models"): "adapters.provider_models(",
    ("POST", "test/provider", "providers/probe"): "provider_check.check(",
    # `GET /api/preflight/sweep` answered "how is the sweep going, and what is proved". In v1 it is
    # `GET /api/v1/machine`, which answers that for **both** long operations — the pull and the sweep —
    # because they are one question an operator asks: what is this machine busy with. A rename rather
    # than an alias, and the noun changed because the resource did.
    ("GET", "preflight/sweep", "machine"): "app_setup.view(",
}


def test_every_endpoint_offered_twice_goes_through_one_service():
    """The property that makes an alias an alias rather than a second implementation.

    `POST /api/approvals` and `POST /api/v1/approvals` differ in the shape of a refusal — flat
    sentence against envelope — and that is what versioning *is*. They must not differ in what
    happens, and the only way to be sure of that is for both to be one call into the same `app_*`
    function.
    """
    import ast

    v1, legacy = _by_version()
    both = sorted(v1 & legacy)
    undeclared = [pair for pair in both if pair not in ALIASED]
    assert not undeclared, (
        f"these answer the same method under both spellings and are not declared: {undeclared}. "
        "Either the legacy one goes, or say which service both reach."
    )
    missing = sorted(pair for pair in ALIASED if pair not in both)
    assert not missing, f"declared as aliased and no longer offered twice: {missing}"

    # Both handlers, and both must call the named service. Read from the source, because the
    # question is whether the *code paths* meet — not whether the payloads happen to match today.
    source = ast.parse(pathlib.Path("corparius/api/handlers.py").read_text(encoding="utf-8"))
    bodies = {n.name: ast.unparse(n) for n in source.body if isinstance(n, ast.FunctionDef)}
    for (method, suffix), service in sorted(ALIASED.items()):
        names = [
            r.handler.__name__
            for r in routes.ALL_ROUTES
            if r.method == method and r.path.removeprefix(V1).removeprefix("/api/") == suffix
        ]
        assert len(names) == 2, f"{method} {suffix}: expected two handlers, found {names}"
        for handler in names:
            assert service in bodies[handler], (
                f"{handler} does not call {service}, so the two spellings of {method} {suffix} "
                "are two implementations rather than one operation offered twice"
            )


def test_every_renamed_endpoint_still_meets_its_old_spelling():
    """The same property for the paths whose v1 name differs, which the suffix intersection cannot see.

    Both halves have to exist — a rename that quietly dropped the legacy path is a client broken
    without a version bump — and both have to reach one function, or the rename shipped a second
    implementation under a tidier name.
    """
    import ast

    source = ast.parse(pathlib.Path("corparius/api/handlers.py").read_text(encoding="utf-8"))
    bodies = {n.name: ast.unparse(n) for n in source.body if isinstance(n, ast.FunctionDef)}
    for (method, was, now), service in sorted(RENAMED.items()):
        found = {
            r.path: r.handler.__name__
            for r in routes.ALL_ROUTES
            if r.method == method and r.path in (f"/api/{was}", f"{V1}{now}")
        }
        assert len(found) == 2, f"{method} {was} -> {now}: expected both spellings, found {found}"
        for handler in found.values():
            assert service in bodies[handler], (
                f"{handler} does not call {service}: the rename produced a second implementation"
            )


# The reads that moved to v1 ahead of their writes. Declared, because it is the one place a client
# meets the migration: it polls `GET /api/v1/tasks` and still posts a decision to
# `POST /api/tasks`. Reads moved first because that is where the cost was — `/api/overview` was
# 48 530 bytes every five seconds — and the writes move when a v1 client needs to make one.
#
# `companies` is here for the opposite reason: the v1 read exists and the legacy one carries
# `templates` as well, which belongs to the creation wizard and not to a list of companies. It
# becomes its own v1 resource when that wizard is rebuilt.
SPLIT_NOUNS = {
    "tasks",
    "memory",
    "approvals",
    "inbox",
    "companies",
    "drafts",
    "rules",
    "documents",
    "documents/delete",
    # `document/text` and `documents/text` are deliberately **not** here: the suffixes differ, so
    # they never appear in the intersection this set describes. `RENAMED` above is what holds them,
    # and it exists because without it the guard reported both halves as unpaired and asserted
    # nothing about either.
    #
    # The providers tab. `providers` is split on the method rather than half-migrated — both spellings
    # answer GET and POST — and the other four are single operations offered twice.
    "providers",
    "ollama",
    "preflight",
    "tiers/recommend",
    "claude/setup",
    # The two long operations. `preflight/sweep` answers both a GET and a POST under each spelling;
    # `ollama/pull` is a POST only.
    "preflight/sweep",
    "ollama/pull",
}


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
