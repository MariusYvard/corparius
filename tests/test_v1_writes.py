"""The three writes the rebuilt Overview tab needs, and what each refuses.

These moved to v1 **because a client needed them**, which is the plan's own rule: reads went first
because that is where the cost was — `/api/overview` was 48 530 bytes every five seconds — and the
writes follow when a v1 client has a decision to make. One now does.

Each is a thin call into a shared service, and that is not decoration. Deciding an approval was
implemented three times — console, terminal, MCP host — and all three did something different, the
console being the one that granted the standing rule and **never released the work parked on the
approval**. `tests/test_api_version.py` now requires both spellings of an endpoint to reach one
`app_*` function, which is what makes "the legacy path is an alias" true rather than hopeful.
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


def _approval(srv, tool="draft_social_post", approval_id="ap1"):
    _store(srv).add_approval(
        ApprovalRequest(
            id=approval_id, company="example", agent="social", tool=tool, parameters={"x": 1}
        )
    )
    return approval_id


# --- companies ------------------------------------------------------------------


def test_the_company_list_is_the_slugs_and_nothing_else(server):
    """`templates` belongs to the creation wizard, not to a list of companies. The legacy route
    carries both; the v1 one is the list, and the wizard gets its own resource when it is rebuilt."""
    status, data = _call(server, "GET", "/api/v1/companies")
    assert status == 200 and data["companies"] == ["example"]
    assert "templates" not in data


# --- approvals ------------------------------------------------------------------


def test_deciding_an_approval_reports_what_happened(server):
    """Four facts, because four things can be worth telling an operator: it landed, a rule was or
    was not granted, and some parked work moved. The old console reported only the first, which is
    how it came to look stuck."""
    approval_id = _approval(server)
    task = _store(server).add_task("example", "work held by the approval", "social")
    _store(server).park_task(task, approval_id, "approval")
    status, data = _call(
        server, "POST", "/api/v1/approvals", {"id": approval_id, "decision": "approved"}
    )
    assert status == 200 and data["ok"] is True
    assert data["released"] == 1, "an approval that unblocks nothing has not finished"
    assert data["remembered"] == "" and data["gated"] == ""
    assert _store(server).get_task(task)["status"] != "waiting"


def test_stop_asking_grants_a_standing_rule(server):
    approval_id = _approval(server)
    status, data = _call(
        server,
        "POST",
        "/api/v1/approvals",
        {"id": approval_id, "decision": "approved", "remember": "always"},
    )
    assert status == 200 and data["remembered"] == "always"
    assert [r["tool"] for r in _store(server).list_rules("example")] == ["draft_social_post"]


def test_a_tool_gated_by_name_is_reported_rather_than_silently_skipped(server):
    """The company names it in `hitl_tools`, so a standing rule would overrule the file the operator
    wrote it in. `gated` is how a console can say the button did nothing *and why* — a refusal
    nobody is told about is a button that looks broken."""
    approval_id = _approval(server, tool="send_financial_transaction")
    status, data = _call(
        server,
        "POST",
        "/api/v1/approvals",
        {"id": approval_id, "decision": "approved", "remember": "always"},
    )
    assert status == 200
    assert data["remembered"] == "" and data["gated"] == "send_financial_transaction"
    assert _store(server).list_rules("example") == []


def test_rejecting_grants_nothing_and_still_releases(server):
    """ "Always" only means anything alongside an approval. But the work parked on the question moves
    either way — it was waiting for *an answer*, not for a yes."""
    approval_id = _approval(server)
    task = _store(server).add_task("example", "held", "social")
    _store(server).park_task(task, approval_id, "approval")
    status, data = _call(
        server,
        "POST",
        "/api/v1/approvals",
        {"id": approval_id, "decision": "rejected", "remember": "always"},
    )
    assert status == 200 and data["remembered"] == ""
    assert _store(server).list_rules("example") == []
    assert data["released"] + data["refused"] >= 1


@pytest.mark.parametrize(
    ("body", "code", "status"),
    [
        ({}, "invalid", 400),
        ({"id": "ap1"}, "invalid", 400),  # no decision
        ({"id": "ap1", "decision": "maybe"}, "invalid", 400),
        ({"id": "nope", "decision": "approved"}, "not_found", 404),
    ],
)
def test_every_refusal_carries_a_code(server, body, code, status):
    """A client branches on the code. `invalid` means send something else, `not_found` means the
    list this came from is stale — different remedies, and a sentence cannot be switched on."""
    _approval(server)
    got, data = _call(server, "POST", "/api/v1/approvals", body)
    assert got == status, data
    assert data["error"]["code"] == code


def test_the_invalid_refusal_names_the_field(server):
    """`detail` is what stops a client parsing the message to work out what to fix."""
    _status, data = _call(server, "POST", "/api/v1/approvals", {"decision": "approved"})
    assert data["error"]["detail"]["field"] == "id"
    _status, data = _call(
        server, "POST", "/api/v1/approvals", {"id": _approval(server), "decision": "maybe"}
    )
    assert data["error"]["detail"]["field"] == "decision"


# --- inbox ----------------------------------------------------------------------


def test_answering_releases_the_work_that_waited(server):
    store = _store(server)
    item = store.add_inbox("example", "design", "question", "Which price?")
    task = store.add_task("example", "waiting on the answer", "social")
    store.park_task(task, item, "question")
    status, data = _call(
        server, "POST", "/api/v1/inbox", {"id": item, "answer": "49 EUR", "company": "example"}
    )
    assert status == 200 and data["released"] == 1
    assert store.get_task(task)["status"] != "waiting"


def test_a_second_answer_is_a_conflict_and_not_a_missing_item(server):
    """First responder wins. `conflict` rather than `not_found`, because a client told "already
    answered" refreshes its list where one told "no such item" would conclude something else about
    its own state."""
    store = _store(server)
    item = store.add_inbox("example", "design", "question", "Which price?")
    assert _call(server, "POST", "/api/v1/inbox", {"id": item, "company": "example"})[0] == 200
    status, data = _call(server, "POST", "/api/v1/inbox", {"id": item, "company": "example"})
    assert status == 409 and data["error"]["code"] == "conflict"
    assert data["error"]["detail"]["id"] == item


def test_an_inbox_write_with_no_id_is_invalid(server):
    status, data = _call(server, "POST", "/api/v1/inbox", {"company": "example"})
    assert status == 400 and data["error"]["code"] == "invalid"
    assert data["error"]["detail"]["field"] == "id"


# --- the terminal's own words ----------------------------------------------------


def test_the_terminal_says_which_of_the_three_things_happened(tmp_path, monkeypatch, capsys):
    """The service answers with facts; each caller phrases them. This is the terminal's phrasing,
    and it exists because a shared service must not flatten what a surface can say."""
    import types

    from corparius.cli import backlog
    from corparius.config import cfg
    from corparius.store import Store

    company = tmp_path / "company.yaml"
    company.write_text(
        "slug: t\nname: T\noffer: {product: p}\nicp: {segment: s, pains: [x]}\n"
        "agents: {ceo: true, social: true}\nhitl_tools: [send_financial_transaction]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    store = Store(str(tmp_path / "data"))
    try:
        store.add_approval(
            ApprovalRequest(
                id="a1", company="t", agent="social", tool="draft_social_post", parameters={}
            )
        )
        args = types.SimpleNamespace(company=str(company), id="a1", note="", always=True)
        backlog.cmd_decide(args, "approved")
        said = capsys.readouterr().out
        assert "a1 -> approved" in said
        assert "no longer asks for t" in said

        store.add_approval(
            ApprovalRequest(
                id="a2",
                company="t",
                agent="finance",
                tool="send_financial_transaction",
                parameters={},
            )
        )
        args = types.SimpleNamespace(company=str(company), id="a2", note="", always=True)
        backlog.cmd_decide(args, "approved")
        said = capsys.readouterr().out
        assert "gated by name" in said, "the terminal has to say the second half was refused too"
    finally:
        store.close()


def test_the_terminal_reports_an_id_that_is_not_there(tmp_path, monkeypatch, capsys):
    import types

    from corparius.cli import backlog
    from corparius.config import cfg

    company = tmp_path / "company.yaml"
    company.write_text(
        "slug: t\nname: T\noffer: {product: p}\nicp: {segment: s, pains: [x]}\n"
        "agents: {ceo: true}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    backlog.cmd_decide(
        types.SimpleNamespace(company=str(company), id="ghost", note="", always=False), "approved"
    )
    assert "approval id not found" in capsys.readouterr().out


def test_the_terminal_refuses_a_decision_that_is_not_one(tmp_path, monkeypatch, capsys):
    """`Refused` crosses the boundary as a `ValueError` with a sentence, and the terminal prints it.
    The console turns the same exception into a 400 with `invalid` — one service, two right
    answers."""
    import types

    from corparius.cli import backlog
    from corparius.config import cfg

    company = tmp_path / "company.yaml"
    company.write_text(
        "slug: t\nname: T\noffer: {product: p}\nicp: {segment: s, pains: [x]}\n"
        "agents: {ceo: true}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    backlog.cmd_decide(
        types.SimpleNamespace(company=str(company), id="x", note="", always=False), "sideways"
    )
    assert "approved or rejected" in capsys.readouterr().out
