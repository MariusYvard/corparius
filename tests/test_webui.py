"""The operator console must serve the page, expose company state as JSON,
apply decisions, guard mutations with the optional token and never leak keys."""
import json
import os
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from app import webui
from app.config import Settings
from app.models import ApprovalRequest
from app.store import Store


@pytest.fixture()
def server(tmp_path, monkeypatch):
    settings = Settings()
    settings.llm_mock = True
    settings.data_path = str(tmp_path)
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    srv = webui.build_server(settings, host="127.0.0.1", port=0,
                             env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _call(srv, method, path, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=5)
    conn.request(method, path, json.dumps(body) if body is not None else None,
                 {"Content-Type": "application/json", **(headers or {})})
    res = conn.getresponse()
    data = json.loads(res.read() or b"{}") if "json" in res.getheader("Content-Type", "") else res.read()
    conn.close()
    return res.status, data


def test_serves_page_and_companies(server):
    status, page = _call(server, "GET", "/")
    assert status == 200 and b"corparius console" in page
    status, data = _call(server, "GET", "/api/companies")
    assert status == 200 and "example" in data["companies"]


def test_overview_reads_store_and_decides_approval(server):
    store = server.RequestHandlerClass.state.store()
    store.add_approval(ApprovalRequest(id="ap1", company="example", agent="finance",
                                       tool="send_financial_transaction",
                                       parameters={"amount": 10}))
    store.add_task("example", "Ship the landing page", "design", status="proposed")
    status, data = _call(server, "GET", "/api/overview?company=example")
    assert status == 200 and data["ok"]
    assert len(data["approvals"]) == 1
    assert data["tasks"]["proposed"][0]["title"] == "Ship the landing page"
    status, data = _call(server, "POST", "/api/approvals",
                         {"id": "ap1", "decision": "approved", "note": "t"})
    assert status == 200 and data["ok"]
    assert server.RequestHandlerClass.state.store().list_approvals("example", "pending") == []


def test_task_decision_updates_status(server):
    state = server.RequestHandlerClass.state
    state.store().add_task("example", "Draft outreach", "outreach", status="proposed")
    task_id = state.store().list_tasks("example", "proposed")[0]["id"]
    status, data = _call(server, "POST", "/api/tasks", {"id": task_id, "decision": "approved"})
    assert status == 200 and data["ok"]
    assert state.store().list_tasks("example", "approved")[0]["id"] == task_id


def test_providers_never_leak_keys_and_persist_env(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value")
    status, data = _call(server, "GET", "/api/providers")
    assert status == 200
    groq = next(p for p in data["providers"] if p["name"] == "groq")
    assert groq["configured"] and groq["key_set"]
    assert "gsk_secret_value" not in json.dumps(data)
    status, data = _call(server, "POST", "/api/providers",
                         {"values": {"CEREBRAS_API_KEY": "csk_new"}})
    assert status == 200 and data["ok"]
    env_file = server.RequestHandlerClass.state.env_file
    assert "CEREBRAS_API_KEY=csk_new" in env_file.read_text()
    assert os.environ["CEREBRAS_API_KEY"] == "csk_new"
    status, data = _call(server, "POST", "/api/providers",
                         {"values": {"PATH": "evil"}})
    assert status == 500 or data["ok"] is False


def test_token_guards_mutations(server, monkeypatch):
    monkeypatch.setenv("CORP_UI_TOKEN", "s3cret")
    status, data = _call(server, "POST", "/api/tasks", {"id": 1, "decision": "approved"})
    assert status == 401
    status, _ = _call(server, "GET", "/api/overview?company=example")
    assert status == 200  # reads stay open on localhost
    status, data = _call(server, "POST", "/api/chat",
                         {"company": "example", "message": "hi"},
                         headers={"X-Corp-Token": "s3cret"})
    assert status == 200 and data["ok"]


def test_ceo_chat_answers_offline_in_mock_mode(server):
    status, data = _call(server, "POST", "/api/chat",
                         {"company": "example", "message": "What is the plan?"})
    assert status == 200 and data["ok"]
    assert data["provider"] == "mock"
    assert "What is the plan?" in data["reply"]
    status, data = _call(server, "GET", "/api/chat?company=example")
    assert len(data["history"]) == 2


def test_doctor_endpoint_reports_checks(server):
    status, data = _call(server, "GET", "/api/doctor")
    assert status == 200 and data["ok"]
    names = {c["name"] for c in data["checks"]}
    assert {"python", "mode", "store", "ollama"} <= names
    assert all(c["level"] in ("ok", "warn", "fail") for c in data["checks"])


def test_company_wizard_creates_and_lists(server, tmp_path, monkeypatch):
    import app.webui as webui_mod
    monkeypatch.setattr(webui_mod, "ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    status, data = _call(server, "POST", "/api/companies",
                         {"name": "Atelier Brumaire", "product": "Handmade candles online",
                          "agents": {"coder": True}, "session_tokens": 50000})
    assert status == 200 and data["ok"] and data["slug"] == "atelier-brumaire"
    import yaml as yaml_mod
    cfg = yaml_mod.safe_load((tmp_path / "companies" / "atelier-brumaire" / "company.yaml").read_text(encoding="utf-8"))
    assert cfg["agents"]["coder"] is True and cfg["budgets"]["session_tokens"] == 50000
    status, data = _call(server, "POST", "/api/companies",
                         {"name": "Atelier Brumaire", "product": "dup"})
    assert data["ok"] is False
    status, data = _call(server, "POST", "/api/companies", {"name": "!!!", "product": "x"})
    assert data["ok"] is False
