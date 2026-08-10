"""The writes the Operations tab needs: the board, the rules, the memory, the drafts.

Each is one call into a service, and three of the four gained that service here — which is the
point. Writing them is what surfaced the divergence in `corparius memory`: it took `--pin` and
`--forget` and had no `--unpin`, so a fact pinned by mistake from a terminal could only be undone
from the browser. Two thirds of a vocabulary is the shape a shared service exists to prevent.

`rules` deliberately has no service, and that is audited rather than overlooked: revoking a standing
rule is one store call with nothing that belongs beside it. Nothing is parked on a rule — revoking
means the tool asks again next time — so the two-calls-one-caller-forgets shape cannot arise.
"""

import json
import shutil
import threading
from http.client import HTTPConnection

import pytest

from corparius.kernel.records import ApprovalRequest


@pytest.fixture()
def server(tmp_path, monkeypatch):
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


def _call(srv, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=10)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        {"Content-Type": "application/json"},
    )
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, json.loads(raw or b"{}")


def _store(srv):
    return srv.RequestHandlerClass.state.store()


# --- the board ------------------------------------------------------------------


def test_approving_from_the_board_attaches_the_tool_that_makes_it_executable(server):
    """The first live divergence of this restructuring, still asserted at the new spelling.

    A task approved with no tool closes "done (no tool mapped)" having done nothing — and because
    nothing happened, the condition that produced it is still there next tick, so the agent proposes
    it again. Measured on one company: 24 tasks for a role, 22 like that.
    """
    from corparius.tools.spec import ROLE_TOOL

    task = _store(server).add_task(
        "example", "Remove the unverified badge", "design", status="proposed"
    )
    status, data = _call(server, "POST", "/api/v1/tasks", {"id": task, "decision": "approved"})
    assert status == 200 and data["decision"] == "approved"
    assert _store(server).get_task(task)["tool"] == ROLE_TOOL["design"]


def test_a_tool_the_operator_chose_survives_the_approval(server):
    task = _store(server).add_task("example", "A", "support", status="proposed")
    status, _data = _call(
        server,
        "POST",
        "/api/v1/tasks",
        {"id": task, "decision": "approved", "tool": "write_site_content"},
    )
    assert status == 200
    assert _store(server).get_task(task)["tool"] == "write_site_content"


def test_reassigning_reports_which_fields_moved(server):
    """`changed` is what lets a client say what it did instead of re-reading the row."""
    task = _store(server).add_task("example", "A", "support", status="approved")
    status, data = _call(
        server,
        "POST",
        "/api/v1/tasks",
        {"id": task, "target": "design", "tool": "write_site_content", "priority": 3},
    )
    assert status == 200
    assert data["changed"] == ["priority", "target", "tool"]
    assert data["decision"] == "", "nothing was decided, and saying otherwise would be a lie"


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({}, "task id"),
        ({"id": "nope"}, "task id"),
        ({"id": 1}, "nothing to change"),
        ({"id": 1, "decision": "sideways"}, "decision must be"),
        ({"id": 1, "target": "nobody"}, "unknown agent"),
        ({"id": 1, "tool": "no_such_tool"}, "unknown tool"),
        ({"id": 1, "title": "  "}, "cannot be empty"),
    ],
)
def test_the_board_refuses_with_a_code_and_a_sentence(server, body, says):
    """`invalid` for the client to branch on, the sentence for the person.

    No `field` here, and that is on purpose: the service refuses across six of them and knowing
    which is its business, not the transport's. A guessed `field` would be a machine-readable lie,
    which is worse than an absent key.
    """
    status, data = _call(server, "POST", "/api/v1/tasks", body)
    assert status == 400, data
    assert data["error"]["code"] == "invalid"
    assert says in data["error"]["message"], data["error"]["message"]


def test_the_board_read_carries_the_true_completed_count(server):
    """`done_total`, not the row count. The column is bounded because this payload is polled, so a
    header reading 60 for a company that finished three hundred is the failure the field prevents —
    and it travels with the rows because it can only be checked next to them."""
    store = _store(server)
    for i in range(3):
        store.set_task_status(store.add_task("example", f"t{i}", "design"), "done", "x")
    status, data = _call(server, "GET", "/api/v1/tasks?company=example")
    assert status == 200
    assert data["done_total"] == 3
    assert set(data["tasks"]) >= {"proposed", "approved", "in_progress", "waiting", "done"}


# --- standing rules -------------------------------------------------------------


def test_revoking_a_rule_answers_with_what_is_left(server):
    """The list comes back, because a client that just changed it should not have to ask again — and
    because the rules live in `summary`, which it would otherwise poll for up to five seconds to find
    out whether the button worked."""
    store = _store(server)
    store.add_rule("example", "draft_social_post", "always", "granted by the operator")
    store.add_rule("example", "write_site_content", "always", "granted by the operator")
    status, data = _call(
        server, "POST", "/api/v1/rules", {"tool": "draft_social_post", "company": "example"}
    )
    assert status == 200
    assert [r["tool"] for r in data["rules"]] == ["write_site_content"]


def test_revoking_something_that_was_never_granted_is_not_found(server):
    status, data = _call(
        server, "POST", "/api/v1/rules", {"tool": "write_site_content", "company": "example"}
    )
    assert status == 404 and data["error"]["code"] == "not_found"
    assert data["error"]["detail"]["tool"] == "write_site_content"


def test_a_rule_revoke_with_no_tool_is_invalid(server):
    status, data = _call(server, "POST", "/api/v1/rules", {"company": "example"})
    assert status == 400 and data["error"]["detail"]["field"] == "tool"


def test_granting_then_revoking_makes_the_gate_ask_again(server):
    """The property, rather than the two calls. A rule is worth nothing if the gate does not read it,
    and worth less than nothing if it keeps reading a revoked one."""
    from corparius.config import permissions
    from corparius.config.settings import Settings
    from corparius.tools.spec import SPEC

    store = _store(server)
    company = {"slug": "example", "agents": {"social": True}}
    tool = SPEC["draft_social_post"]

    def rule_now():
        engine = permissions.PermissionEngine.from_settings(Settings(), company, store)
        return engine.evaluate(tool, "example").rule

    store.add_approval(
        ApprovalRequest(
            id="ap1", company="example", agent="social", tool="draft_social_post", parameters={}
        )
    )
    before = rule_now()
    _call(
        server,
        "POST",
        "/api/v1/approvals",
        {"id": "ap1", "decision": "approved", "remember": "always"},
    )
    # `rule:always`, not `allow`: the engine names *why* it allowed, which is what makes a decision
    # auditable rather than merely correct. Asserted at the real value — the first version of this
    # guessed `allow` and would have passed against an engine that had stopped distinguishing them.
    assert rule_now() == "rule:always", "the standing rule was granted and the gate does not see it"
    _call(server, "POST", "/api/v1/rules", {"tool": "draft_social_post", "company": "example"})
    assert rule_now() == before, "revoked, and the gate still reads it"
    assert before != "rule:always", (
        "the fixture has to start without the rule for this to mean anything"
    )


# --- memory ---------------------------------------------------------------------


def test_all_three_memory_actions_reach_the_store(server):
    store = _store(server)
    fact = store.remember("example", "ceo", "The clinic buys in March", "seasonal")
    assert _call(server, "POST", "/api/v1/memory", {"id": fact, "action": "pin"})[0] == 200
    assert store.list_memory("example")[0]["pinned"]
    assert _call(server, "POST", "/api/v1/memory", {"id": fact, "action": "unpin"})[0] == 200
    assert not store.list_memory("example")[0]["pinned"]
    assert _call(server, "POST", "/api/v1/memory", {"id": fact, "action": "forget"})[0] == 200
    assert store.list_memory("example") == []


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"action": "pin"}, "id"),
        ({"id": "x", "action": "pin"}, "id"),
        ({"id": 1, "action": "burn"}, "action"),
    ],
)
def test_the_memory_refusals_name_the_field(server, body, field):
    status, data = _call(server, "POST", "/api/v1/memory", body)
    assert status == 400 and data["error"]["detail"]["field"] == field


def test_forgetting_a_fact_that_is_gone_is_not_found(server):
    status, data = _call(server, "POST", "/api/v1/memory", {"id": 9999, "action": "forget"})
    assert status == 404 and data["error"]["code"] == "not_found"


def test_every_memory_action_has_a_flag():
    """Both ends of the vocabulary: the service declares three actions and the parser offers three
    flags. This is the guard that makes `getattr(args, action, 0)` safe — the default would otherwise
    let a fourth action be added to `ACTIONS` with no way to reach it from a terminal, which is the
    same "reachable and never reached" shape as `write_skill` and `ask_operator`.

    And it is the shape that *was* broken here: `unpin` was in the console's vocabulary and had no
    flag, so the terminal could do two thirds of the job.
    """
    import argparse

    from corparius.app import memory as app_memory
    from corparius.cli import configure

    parser = argparse.ArgumentParser()
    configure.register(parser.add_subparsers())
    memory = next(
        action
        for action in parser._subparsers._group_actions[0].choices.items()  # type: ignore[union-attr]
        if action[0] == "memory"
    )[1]
    flags = {opt.lstrip("-") for action in memory._actions for opt in action.option_strings}
    missing = sorted(set(app_memory.ACTIONS) - flags)
    assert not missing, f"declared in ACTIONS with no flag to reach them: {missing}"


def test_the_terminal_can_now_unpin(tmp_path, monkeypatch, capsys):
    """The divergence this service closed. `corparius memory` had `--pin` and `--forget` and no
    `--unpin`, so a fact pinned by mistake from a terminal needed the browser to undo."""
    import types

    from corparius.cli import configure
    from corparius.config import cfg
    from corparius.store import Store

    company = tmp_path / "company.yaml"
    company.write_text(
        "slug: t\nname: T\noffer: {product: p}\nicp: {segment: s, pains: [x]}\nagents: {ceo: true}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    store = Store(str(tmp_path / "data"))
    try:
        fact = store.remember("t", "ceo", "A fact", "why")

        def args(**kw):
            return types.SimpleNamespace(
                **{"company": str(company), "pin": 0, "unpin": 0, "forget": 0, **kw}
            )

        configure.cmd_memory(args(pin=fact))
        assert "pinned" in capsys.readouterr().out
        assert store.list_memory("t")[0]["pinned"]

        configure.cmd_memory(args(unpin=fact))
        assert "unpinned" in capsys.readouterr().out
        assert not store.list_memory("t")[0]["pinned"]

        configure.cmd_memory(args(forget=fact))
        assert "forgotten" in capsys.readouterr().out
        assert store.list_memory("t") == []

        configure.cmd_memory(args(forget=9999))
        assert "no such memory" in capsys.readouterr().out
    finally:
        store.close()


# --- drafts ---------------------------------------------------------------------


def _draft(store, body="A post about the badge", state="draft"):
    return store.add_draft("example", "social", "linkedin", body, state=state)


def test_marking_a_draft_published_frees_the_queue(server):
    """`published` is the operator saying it went out, not corparius claiming it sent anything. What
    it does is stop the post counting against the queue, which is what lets the agent resume."""
    store = _store(server)
    draft = _draft(store, state="queued")
    before = _call(server, "GET", "/api/v1/drafts?company=example")[1]
    assert before["queued"] == 1
    status, data = _call(
        server, "POST", "/api/v1/drafts", {"id": draft, "state": "published", "company": "example"}
    )
    assert status == 200
    assert data["queued"] == 0 and data["published"] == 1


def test_the_queue_count_is_both_unpublished_states(server):
    """`draft` **and** `queued`, which is what actually gates the agent. One place computes it now;
    it was written out twice, identically, in the two draft handlers."""
    store = _store(server)
    _draft(store, "one", state="draft")
    _draft(store, "two", state="queued")
    _status, data = _call(server, "GET", "/api/v1/drafts?company=example")
    assert data["queued"] == 2, "a draft that is not queued still stops the agent writing"
    assert data["cap"] >= 1


def test_a_draft_can_be_put_back(server):
    """Marked published by mistake, and the agent's queue has to see it again — which is why
    `queued` is in the allowed set and not only the two terminal states."""
    store = _store(server)
    draft = _draft(store, state="published")
    status, data = _call(
        server, "POST", "/api/v1/drafts", {"id": draft, "state": "queued", "company": "example"}
    )
    assert status == 200 and data["queued"] == 1


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"state": "published"}, "id"),
        ({"id": "x", "state": "published"}, "id"),
        ({"id": 1, "state": "sent"}, "state"),
        ({"id": 1}, "state"),
    ],
)
def test_the_draft_refusals_name_the_field_and_the_allowed_set(server, body, field):
    """`allowed` in the detail, because a client that sent the wrong word needs the right ones and
    parsing them out of a sentence is what the envelope exists to end."""
    status, data = _call(server, "POST", "/api/v1/drafts", {**body, "company": "example"})
    assert status == 400 and data["error"]["detail"]["field"] == field
    assert set(data["error"]["detail"]["allowed"]) == {"published", "discarded", "queued"}


def test_a_draft_that_is_not_there_is_not_found(server):
    status, data = _call(
        server, "POST", "/api/v1/drafts", {"id": 9999, "state": "published", "company": "example"}
    )
    assert status == 404 and data["error"]["code"] == "not_found"


def test_both_spellings_of_the_draft_write_answer_the_same_four_keys(server):
    """The legacy route keeps the flat error string — the shipped page reads `data.error` as a string
    — and that is what a version *is*. What must not differ is the success payload, because both are
    the same operation."""
    store = _store(server)
    one, two = _draft(store, "one", state="queued"), _draft(store, "two", state="queued")
    _status, legacy = _call(
        server, "POST", "/api/drafts", {"id": one, "state": "published", "company": "example"}
    )
    _status, versioned = _call(
        server, "POST", "/api/v1/drafts", {"id": two, "state": "published", "company": "example"}
    )
    assert set(legacy) == set(versioned) == {"ok", "drafts", "queued", "published", "cap"}
    assert versioned["published"] == 2
