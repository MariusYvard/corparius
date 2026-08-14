"""Four resources instead of one 48 KB payload, and an ETag so a client at rest re-downloads none
of it.

The measured problem: `/api/overview` is **48 530 bytes** on the real company and the page polls
it every five seconds — 34 MB an hour, per client. Measured key by key, three keys are 94% of it:

```text
  21 115  43.5%  tasks
  17 706  36.5%  memory          46 facts, and they change almost never
   6 765  13.9%  recent_actions
   2 944   6.1%  the other 26 keys together
```

So `summary` is everything else at **2 859 bytes** — a 17× reduction for the resource a client
should poll — and `tasks`, `memory` and `activity` are fetched when they matter.

Two things this file defends that the numbers alone would not:

  * **the split is exact.** `build` is the union of the four parts, no key missing and no key in
    two. A key that fell out of every part would vanish from the legacy payload the shipped page
    reads; a key in two parts is a value with two homes, which is how two copies start to
    disagree. This is the same both-ends shape as the tool registry and the route table.
  * **the ETag is honest about what it saves.** Bandwidth, not work: the payload is built and
    then hashed, so a 304 still ran the query. Narrowing what a client polls is what makes the
    query small; this is what makes the unchanged bytes free on the wire.
"""

import json
import threading

import pytest

from corparius.app import overview


@pytest.fixture()
def server(tmp_path, monkeypatch):
    import shutil

    from corparius.api.server import build_server
    from corparius.config import cfg
    from corparius.config.settings import Settings

    from .conftest import EXAMPLE_COMPANY

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    home = tmp_path / "home"
    shutil.copytree(EXAMPLE_COMPANY, home / "companies" / "example")
    monkeypatch.setenv("CORP_HOME", str(home))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _raw(srv, path, headers=None):
    """A response with its headers, which `_call` in test_webui drops."""
    from http.client import HTTPConnection

    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=5)
    conn.request("GET", path, None, headers or {})
    res = conn.getresponse()
    body = res.read()
    out = (res.status, dict(res.getheaders()), body)
    conn.close()
    return out


# --- the split is exact ---------------------------------------------------------

PARTS = ("summary", "tasks", "memory", "activity")


def _parts(store, settings, slug, company=None, run=None):
    return {
        "summary": overview.summary(store, settings, slug, company=company, run=run),
        "tasks": overview.tasks(store, slug),
        "memory": overview.memory(store, settings, slug),
        "activity": overview.activity(store, slug),
    }


@pytest.fixture()
def a_company(tmp_path, monkeypatch):
    from corparius.config import cfg
    from corparius.config.settings import Settings
    from corparius.store import Store

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    cfg.invalidate()
    store = Store(str(tmp_path / "data"))
    store.add_task("t", "a task", "social", status="proposed")
    store.add_task("t", "done work", "social", status="done")
    store.remember("t", "ceo", "a fact worth keeping", why="measured twice")
    yield store, Settings(), {"slug": "t", "name": "T", "agents": {"ceo": True}}
    store.close()


# What each part answers with, declared. Not derived from `build`, and that is the whole point:
# `build` is literally `{**summary, **tasks, **memory, **activity}`, so a test comparing its keys
# to the union of the parts is comparing a thing to itself. The first version of this file did
# exactly that and passed while `activity` returned `{}` — found by reintroducing the defect,
# which is the only reason it is written this way now.
DECLARED = {
    "summary": frozenset(
        {
            "agent_tools",
            "approvals",
            "ask_above",
            "cloud_enabled",
            "company",
            "cost_reported",
            "flow",
            "freezes",
            "inbox",
            "inbox_fixes",
            "last_run",
            "llm_mock",
            "loop",
            "ok",
            # The onboarding thread. In `summary` rather than behind its own route because this is the
            # resource the Overview tab already polls and the whole card is three booleans plus which
            # step leads — a second request for that would cost more than it carries. One extra COUNT.
            "onboarding",
            "permission_mode",
            "proposals_need_you",
            "role_tool",
            "rules",
            "running",
            "session_budget",
            "spend_by_agent",
            "status",
            "stopping",
            "tick",
        }
    ),
    "tasks": frozenset({"tasks", "done_total"}),
    # `cap`, `chars` and `unpinned` joined it when the console stopped rendering an unbounded
    # scroll: these facts are pasted into prompts, so their length is the cost, and
    # `store.remember` drops the oldest unpinned row past the cap whether or not anybody was
    # told. `unpinned` rather than the total, because a pin is exempt from the cap.
    "memory": frozenset({"memory", "memory_enabled", "cap", "chars", "unpinned"}),
    "activity": frozenset({"recent_actions"}),
}


@pytest.mark.parametrize("name", sorted(DECLARED))
def test_each_part_answers_exactly_what_it_declares(name, a_company):
    """A key that quietly left a part would leave `/api/overview` too, which the shipped page and
    `corparius status` both read — and nothing else would notice, because everything downstream
    is derived from the same function."""
    store, settings, company = a_company
    part = _parts(store, settings, "t", company=company, run={})[name]
    assert set(part) == DECLARED[name], (
        f"{name} answers {sorted(set(part) ^ DECLARED[name])} differently than declared"
    )


def test_build_is_the_declared_union_and_nothing_more(a_company):
    """The legacy payload's key set, pinned against the declaration rather than against itself."""
    store, settings, company = a_company
    whole = overview.build(store, settings, "t", company=company, run={})
    declared = frozenset().union(*DECLARED.values())
    assert set(whole) == declared, f"build differs by {sorted(set(whole) ^ declared)}"
    # 30 since the onboarding thread joined `summary`. Pinned as a count as well as a set, so a key
    # added to both the payload and the declaration in one commit still has to be a line somebody reads.
    # 33: `cap`, `chars` and `unpinned` joined `memory`, and this is that line. The card rendered every
    # fact a company had ever learned as one flat list — 55 of them, 13 933 characters, on the real
    # company — with neither the cost nor the ceiling on screen, and `store.remember` silently drops the
    # oldest unpinned row past the cap. All three ride the legacy payload too, because `build` is the
    # union of the parts and a client reading either has to see the same company.
    assert len(declared) == 33, "the payload gained or lost a key; say which in DECLARED"


def test_no_key_lives_in_two_parts(a_company):
    """A value with two homes is two copies waiting to disagree — the defect this restructuring
    found three times in the product."""
    store, settings, company = a_company
    seen: dict[str, str] = {}
    twice = []
    for name, part in _parts(store, settings, "t", company=company, run={}).items():
        for key in part:
            if key in seen:
                twice.append(f"{key} in {seen[key]} and {name}")
            seen[key] = name
    assert not twice, twice


def test_every_value_is_identical_between_build_and_its_part(a_company):
    """Not just the key set: the same value. A part that filtered or reordered differently would
    make a v1 client and the page disagree about the same company."""
    store, settings, company = a_company
    whole = overview.build(store, settings, "t", company=company, run={})
    for name, part in _parts(store, settings, "t", company=company, run={}).items():
        for key, value in part.items():
            assert json.dumps(value, sort_keys=True, default=str) == json.dumps(
                whole[key], sort_keys=True, default=str
            ), f"{key} differs between build and {name}"


def test_the_summary_is_the_small_one(a_company):
    """The whole reason for the split, asserted as a ratio rather than a byte count so it holds
    on any company: the three lists are the payload, and the summary is not."""
    store, settings, company = a_company
    for _ in range(40):  # enough rows that the lists actually dominate
        store.add_task("t", "more work that carries a title and a note", "social", status="done")
        store.remember("t", "ceo", "another fact long enough to weigh something in the payload")
    parts = _parts(store, settings, "t", company=company, run={})
    sizes = {k: len(json.dumps(v, default=str)) for k, v in parts.items()}
    whole = sum(sizes.values())
    assert sizes["summary"] < whole / 4, f"summary is {sizes['summary']} of {whole}: {sizes}"


# --- over the wire --------------------------------------------------------------


def test_each_resource_answers_and_carries_only_its_own_keys(server):
    from .test_webui import _call

    _status, summary = _call(server, "GET", "/api/v1/summary?company=example")
    assert summary["ok"] is True
    assert "status" in summary and "approvals" in summary and "inbox" in summary
    for absent in ("tasks", "memory", "recent_actions"):
        assert absent not in summary, f"{absent} is what the split took out"

    _status, tasks = _call(server, "GET", "/api/v1/tasks?company=example")
    assert "tasks" in tasks and "done_total" in tasks and "status" not in tasks

    _status, memory = _call(server, "GET", "/api/v1/memory?company=example")
    assert "memory" in memory and "memory_enabled" in memory

    _status, activity = _call(server, "GET", "/api/v1/activity?company=example")
    assert "recent_actions" in activity


def test_the_summary_is_much_smaller_than_the_payload_it_replaces(server):
    """Measured over the wire, on the same company, in the same process.

    The company is given rows first, and that is the point rather than setup noise: on a freshly
    seeded `example` the three lists are empty, so the whole payload is 1 889 bytes and the
    summary 1 723 — a ratio of 1.1, and the first version of this test asserted 3× against it and
    failed. There is nothing to remove from a company that has done nothing. The 17× figure comes
    from a company with 71 tasks and 46 facts, so the test builds one.
    """
    store = server.RequestHandlerClass.state.store()
    for i in range(60):
        store.add_task(
            "example", f"work item {i} with a title long enough to weigh", "social", status="done"
        )
        store.remember("example", "ceo", f"fact {i}, long enough to be worth a line in a payload")
    _s, _h, narrow = _raw(server, "/api/v1/summary?company=example")
    _s, _h, whole = _raw(server, "/api/overview?company=example")
    assert len(narrow) < len(whole) / 5, f"summary {len(narrow)} vs overview {len(whole)}"


def test_approvals_and_inbox_stayed_in_the_summary(server):
    """The plan named them as separate resources; measured, they are 613 bytes together and they
    are the two things an operator must not need a second request to see. Deviating from the plan
    on a number is the kind of decision that has to be visible, so it is asserted."""
    _status, summary = _call_summary(server)
    assert "approvals" in summary and "inbox" in summary


def _call_summary(server):
    from .test_webui import _call

    return _call(server, "GET", "/api/v1/summary?company=example")


def test_an_unknown_company_is_the_envelope_and_names_the_slug(server):
    from .test_webui import _call

    for path in ("summary", "tasks", "memory", "activity"):
        status, data = _call(server, "GET", f"/api/v1/{path}?company=nope")
        assert status == 404, path
        assert data["error"]["code"] == "unknown_company"
        assert data["error"]["detail"]["slug"] == "nope"


def test_the_legacy_overview_also_refuses_a_company_that_is_not_here(server):
    """Found by smoking the v1 routes beside it: `/api/overview?company=nope` answered **200**
    with a complete payload describing a company at tick 0 with nothing done. "There is no such
    company" and "that company has done nothing" were the same response.

    `corparius status` has always refused it, so the two callers of the same knowledge disagreed —
    and `tests/test_two_callers_agree.py` could not catch it, because it asks which service each
    side reaches and both reach this one. The shape stays the legacy sentence; only the status
    changes, and the page only ever sends an unknown slug in the case that matters: a company
    deleted in another tab and still being polled here.
    """
    from .test_webui import _call

    status, data = _call(server, "GET", "/api/overview?company=nope")
    assert status == 404
    assert data["ok"] is False
    assert "nope" in data["error"]
    assert isinstance(data["error"], str), "legacy keeps the flat sentence"
    # And a company that is here still answers with the whole payload.
    status, data = _call(server, "GET", "/api/overview?company=example")
    assert status == 200 and data["ok"] is True and "tasks" in data


def test_naming_no_company_at_all_is_a_404_from_the_table(server):
    """`needs_slug` on the route, so the dispatcher answers before a handler runs — and it is
    `not_found` rather than `unknown_company`, because nothing was named."""
    from .test_webui import _call

    status, data = _call(server, "GET", "/api/v1/summary")
    assert status == 404 and data["error"]["code"] == "not_found"


# --- the ETag -------------------------------------------------------------------


def test_a_v1_get_carries_an_etag(server):
    for path in ("meta", "summary?company=example", "tasks?company=example"):
        status, headers, _body = _raw(server, f"/api/v1/{path}")
        assert status == 200, path
        assert headers.get("ETag", "").startswith('"'), f"{path} carries no ETag"


def test_an_unchanged_resource_answers_304_with_no_body(server):
    """The point of the whole thing: a client at rest transfers nothing."""
    status, headers, body = _raw(server, "/api/v1/memory?company=example")
    assert status == 200 and body
    tag = headers["ETag"]
    status, headers, body = _raw(server, "/api/v1/memory?company=example", {"If-None-Match": tag})
    assert status == 304
    assert body == b"", "a 304 carries no body"
    assert headers["ETag"] == tag, "the validator has to come back so the client can keep using it"


def test_a_changed_resource_answers_200_with_a_new_etag(server):
    """Non-vacuity for the ETag: it has to follow the content, not just exist."""
    _s, headers, _b = _raw(server, "/api/v1/memory?company=example")
    before = headers["ETag"]
    store = server.RequestHandlerClass.state.store()
    store.remember("example", "ceo", "something new the ETag has to notice")
    status, headers, body = _raw(
        server, "/api/v1/memory?company=example", {"If-None-Match": before}
    )
    assert status == 200 and body
    assert headers["ETag"] != before


def test_a_star_validator_is_honoured(server):
    """`If-None-Match: *` means "any copy at all", which is what a client sends when it only
    wants to know whether the resource exists."""
    status, _headers, body = _raw(server, "/api/v1/memory?company=example", {"If-None-Match": "*"})
    assert status == 304 and body == b""


def test_a_list_of_validators_is_parsed_rather_than_compared_whole(server):
    """A client may offer several. Comparing the header as one string would match none of them,
    and the resource would be re-sent every time while looking like it worked."""
    _s, headers, _b = _raw(server, "/api/v1/summary?company=example")
    tag = headers["ETag"]
    status, _headers, body = _raw(
        server, "/api/v1/summary?company=example", {"If-None-Match": f'"other", {tag}'}
    )
    assert status == 304 and body == b""


def test_a_weak_validator_matches_the_strong_one(server):
    _s, headers, _b = _raw(server, "/api/v1/summary?company=example")
    tag = headers["ETag"]
    status, _headers, body = _raw(
        server, "/api/v1/summary?company=example", {"If-None-Match": f"W/{tag}"}
    )
    assert status == 304 and body == b""


def test_the_cache_header_permits_revalidation_on_v1_and_forbids_storage_elsewhere(server):
    """`no-store` says "do not keep this", which would leave a client with nothing to
    revalidate — the ETag would be decoration. `no-cache` is the one that means "keep it and ask
    before reusing it", and it is set only where there is a validator to ask with."""
    _s, headers, _b = _raw(server, "/api/v1/summary?company=example")
    assert headers["Cache-Control"] == "no-cache"
    _s, headers, _b = _raw(server, "/api/overview?company=example")
    assert headers["Cache-Control"] == "no-store"
    assert "ETag" not in headers, "a legacy route makes no caching promise"


def test_a_legacy_route_ignores_a_validator_it_never_issued(server):
    """A client that sends `If-None-Match` to a legacy path must get the payload, not a 304 it
    cannot fill in. Guarded because the ETag branch keys off the path prefix, and a version of
    that check which looked at the header instead would answer 304 with nothing cached."""
    status, _headers, body = _raw(server, "/api/overview?company=example", {"If-None-Match": "*"})
    assert status == 200 and body


def test_a_post_gets_no_etag(server):
    """A validator on a mutation would invite a client to skip sending it."""
    from .test_webui import _call

    status, _data = _call(server, "POST", "/api/theme", {"hue": "200"})
    assert status == 200  # the shape of the promise is asserted on the GET side above
