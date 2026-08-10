"""The four endpoints over the two long operations, at the wire.

`GET /api/v1/machine` is the read a client polls while one runs — and the name is a correction: it was
`/api/v1/setup` until `test_mutating_routes_are_exactly_the_post_routes` failed on it. That test
forbids a non-public GET whose path ends in `/delete`, `/stop`, `/pull` or `/setup`, because
`POST /api/claude/setup` is why `/setup` reads as a write. The heuristic was right — a read named after
an action defeats the one check keeping writes behind POST.

Nothing here calls a provider or downloads a model. A sweep is hundreds of paid generations against the
operator's own rate limits.
"""

import json
import shutil
import threading
from http.client import HTTPConnection

import pytest

from corparius.store import jobs as jobs_store


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


# --- the read --------------------------------------------------------------------


def test_the_machine_read_answers_both_operations_and_what_is_proved(server):
    status, data = _call(server, "GET", "/api/v1/machine")
    assert status == 200
    assert data["pull"] == {} and data["sweep"] == {}, "never started is not the same as finished"
    assert set(data) >= {"pull", "sweep", "known", "tally", "usable_by_provider", "oldest_days"}
    assert data["known"] == 0 and data["worth_rechecking"] == 0


def test_the_machine_read_reports_a_running_job_with_its_progress(server):
    from corparius.app import setup as app_setup

    _store(server).start_job(app_setup.KIND_PULL, app_setup.MACHINE, progress="gemma:2b: 42%")
    _status, data = _call(server, "GET", "/api/v1/machine")
    assert data["pull"]["state"] == jobs_store.RUNNING
    assert data["pull"]["progress"] == "gemma:2b: 42%"


def test_a_verdict_ages_and_the_read_says_how_old(server):
    """A verdict is a measurement and measurements age. Reported so nobody reads a six-month-old
    `blocked` as current fact."""
    import time

    from corparius.providers import preflight

    store = _store(server)
    preflight.remember(store, [preflight.Probe("groq", "a", state=preflight.USABLE, status=200)])
    store.db.execute("UPDATE model_probes SET ts=?", (time.time() - 40 * 86400,))
    store.db.commit()
    _status, data = _call(server, "GET", "/api/v1/machine")
    assert data["known"] == 1
    assert data["tally"] == {preflight.USABLE: 1}
    assert data["oldest_days"] >= 39
    assert data["usable_by_provider"]["groq"] == 1


# --- the pull --------------------------------------------------------------------


def test_starting_a_pull_records_a_job_and_names_the_models(server, monkeypatch):
    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": ["gemma:2b"]})
    monkeypatch.setattr(ollama_setup, "pull", lambda m, on_line=None: {"ok": True})
    status, data = _call(server, "POST", "/api/v1/ollama/pull", {"models": []})
    assert status == 200
    assert data["models"] == ["gemma:2b"] and data["created"] is True
    assert data["job"], "a client needs the id to follow it"


def test_a_pull_with_nothing_missing_is_a_conflict(server, monkeypatch):
    """`conflict`, not `invalid`: the request is well formed and the machine is in a state where there
    is nothing to do. A client shows "everything installed", not "you sent something wrong"."""
    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": []})
    status, data = _call(server, "POST", "/api/v1/ollama/pull", {})
    assert status == 409 and data["error"]["code"] == "conflict"
    assert "already installed" in data["error"]["message"]


def test_a_second_pull_is_refused_by_the_row_not_by_memory(server, monkeypatch):
    from corparius.app import setup as app_setup
    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": ["gemma:2b"]})
    _store(server).start_job(app_setup.KIND_PULL, app_setup.MACHINE)
    status, data = _call(server, "POST", "/api/v1/ollama/pull", {})
    assert status == 409 and "already in progress" in data["error"]["message"]


def test_stopping_a_pull_writes_the_column(server, monkeypatch):
    from corparius.app import setup as app_setup

    job = _store(server).start_job(app_setup.KIND_PULL, app_setup.MACHINE)["id"]
    status, data = _call(server, "POST", "/api/v1/ollama/pull/stop", {})
    assert status == 200 and data["stopping"] is True and data["job"] == job
    assert _store(server).cancel_requested(job) is True


def test_stopping_a_pull_that_is_not_running_is_not_an_error(server):
    """The client asked; the answer is that there was nothing. A 404 here would make a stop button
    that raced a finishing job look broken."""
    status, data = _call(server, "POST", "/api/v1/ollama/pull/stop", {})
    assert status == 200 and data["stopping"] is False and data["job"] == ""


# --- the sweep -------------------------------------------------------------------


def test_the_estimate_makes_no_calls_and_answers_the_number(server, monkeypatch):
    """The number goes in front of the operator first: NVIDIA alone advertises 102 models, and
    "check everything" is their money and their rate limits."""
    from corparius.providers import preflight

    monkeypatch.setattr(
        preflight, "estimate", lambda timeout=8: {"providers": {"groq": 12, "ovh": 3}, "total": 15}
    )
    status, data = _call(server, "POST", "/api/v1/preflight/sweep", {"estimate": True})
    assert status == 200
    assert data["total"] == 15 and set(data["providers"]) == {"groq", "ovh"}
    # And nothing was recorded: pricing is not starting.
    assert _call(server, "GET", "/api/v1/machine")[1]["sweep"] == {}


def test_a_sweep_in_mock_mode_is_a_conflict(server):
    status, data = _call(server, "POST", "/api/v1/preflight/sweep", {})
    assert status == 409 and data["error"]["code"] == "conflict"
    assert "mock mode" in data["error"]["message"]


def test_stopping_a_sweep_goes_through_the_column(server):
    from corparius.app import setup as app_setup

    job = _store(server).start_job(app_setup.KIND_SWEEP, app_setup.MACHINE)["id"]
    status, data = _call(server, "POST", "/api/v1/preflight/sweep", {"stop": True})
    assert status == 200 and data["stopping"] is True and data["job"] == job
    assert _store(server).cancel_requested(job) is True


def test_a_sweep_starts_when_a_provider_could_answer(server, monkeypatch):
    """Started, recorded, and the worker left to a thread. The probing itself is replaced: a real one
    is hundreds of paid generations."""
    from corparius.config import cfg
    from corparius.providers import preflight

    monkeypatch.setenv("CORP_LLM_MOCK", "false")
    cfg.invalidate()
    monkeypatch.setattr(preflight, "sweep", lambda store, **kwargs: None)
    status, data = _call(server, "POST", "/api/v1/preflight/sweep", {"limit": 3})
    assert status == 200 and data["created"] is True and data["job"]
    # The row exists whatever the thread has done by now: the claim is synchronous, the work is not.
    assert _store(server).job(data["job"])["params"]["limit"] == 3


def test_the_legacy_sweep_read_maps_the_row_into_the_page_shape(server):
    """The shipped page reads `sweep.running` and `sweep.provider`. Mapped from the row rather than
    changing the page — that is what a version is."""
    from corparius.app import setup as app_setup

    _store(server).start_job(
        app_setup.KIND_SWEEP, app_setup.MACHINE, progress="groq/llama — 4 called"
    )
    status, data = _call(server, "GET", "/api/preflight/sweep")
    assert status == 200
    assert data["sweep"]["running"] is True
    assert "4 called" in data["sweep"]["provider"]
    assert data["sweep"]["state"] == jobs_store.RUNNING


def test_the_legacy_ollama_read_reports_the_pull_from_the_row(server):
    """It read `ctx.state.pulls`, so a console restarted mid-download reported no pull at all."""
    from corparius.app import setup as app_setup

    _store(server).start_job(app_setup.KIND_PULL, app_setup.MACHINE, progress="downloading 71%")
    status, data = _call(server, "GET", "/api/ollama")
    assert status == 200
    assert data["result"]["pulling"] is True
    assert data["result"]["detail"] == "downloading 71%"
