"""The CEO chat can propose an action, and the operator confirms it. The LLM only
routes intent to an existing audited endpoint; it never executes on its own."""

import threading

import pytest

from app import cfg, webui
from app.config import Settings
from app.models import LLMResult, Usage

from .test_webui import _call


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = webui.build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()  # release the listening socket, not just the loop


def _model(monkeypatch, reply_json):
    # Force the router to return a scripted JSON so the harness classifies intent.
    monkeypatch.setattr(
        webui.HybridRouter,
        "generate",
        lambda self, msgs, difficulty=None, model=None, max_tokens=512: LLMResult(
            text=reply_json, usage=Usage(5, 5), model="m", provider="fake"
        ),
    )


def test_a_run_request_becomes_a_confirmable_proposal(server, monkeypatch):
    _model(monkeypatch, '{"reply": "I will run a full day.", "intent": "run_day", "ticks": 24}')
    status, d = _call(server, "POST", "/api/chat", {"company": "example", "message": "run a day"})
    assert status == 200 and d["ok"]
    p = d["proposal"]
    # It proposes; it does not run. The endpoint is the same one the button uses.
    assert p and p["intent"] == "run_day" and p["endpoint"] == "/api/run"
    assert p["body"]["ticks"] == 24 and p["needs_company"] is True
    # Nothing started: no run is in progress until the operator confirms.
    assert server.RequestHandlerClass.state.runs.get("example", {}).get("running") is not True


def test_plain_question_gets_no_proposal(server, monkeypatch):
    _model(monkeypatch, '{"reply": "The plan is steady.", "intent": "answer"}')
    status, d = _call(server, "POST", "/api/chat", {"company": "example", "message": "how are we"})
    assert d["proposal"] is None and "plan" in d["reply"].lower()


def test_use_claude_proposal_needs_no_company(server, monkeypatch):
    _model(
        monkeypatch,
        '{"reply": "I can switch you to your Claude subscription.", "intent": "use_claude"}',
    )
    status, d = _call(server, "POST", "/api/chat", {"company": "example", "message": "use claude"})
    assert d["proposal"]["endpoint"] == "/api/claude/setup"
    assert d["proposal"]["needs_company"] is False


def test_reply_is_localized_request(server, monkeypatch):
    _model(monkeypatch, '{"reply": "Bonjour, tout va bien.", "intent": "answer"}')
    status, d = _call(
        server, "POST", "/api/chat", {"company": "example", "message": "salut", "lang": "fr"}
    )
    assert d["proposal"] is None and "Bonjour" in d["reply"]
