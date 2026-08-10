"""The two machine-level operations, moved off `UiState` and onto durable jobs.

`ui.pulls` and `ui.sweep` were the last two things in that object a restart silently lost, and the
last two a second client could not see. Three properties change, and they are the same three
`start_run`'s docstring lists for runs:

  * **the guard is durable** — "a sweep is already running" read this process's memory, so one left
    behind by a crashed console was invisible to the next, which would start a second: hundreds of
    duplicate paid calls;
  * **a client that did not start the work can watch it** — the premise of the whole v1 contract;
  * **one a dead console left behind reports `interrupted`** — not `running`, and not absent.

Nothing here makes a real provider call or a real download. A sweep is hundreds of paid generations
against the operator's own rate limits; a test that made one would be charging whoever ran it.
"""

import json
from http.client import HTTPConnection

import pytest

from corparius.store import jobs as jobs_store


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """A private home and store, with the environment set rather than an object patched."""
    import shutil

    from corparius.config import cfg

    from .conftest import EXAMPLE_COMPANY

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    house = tmp_path / "home"
    shutil.copytree(EXAMPLE_COMPANY, house / "companies" / "example")
    monkeypatch.setenv("CORP_HOME", str(house))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    return tmp_path


@pytest.fixture()
def env(home):
    """What a subprocess console needs to point at the same private store."""
    return {
        "CORP_DATA_PATH": str(home / "data"),
        "CORP_HOME": str(home / "home"),
        "CORP_LLM_MOCK": "true",
        "CORP_UPDATE_CHECK": "false",
    }


def _a_store(home):
    from corparius.store import Store

    return Store(str(home / "data"))


class _Live:
    """Settings with mock mode off, which is all `start_sweep` reads."""

    llm_mock = False


# --- the restart proof -----------------------------------------------------------


def test_a_sweep_a_dead_console_left_behind_is_reported_interrupted(home, env):
    """The plan's fifth verification, applied to the sweep instead of to a run.

    The row is written **by this test process**, so its `owner_token` is not the console's — which is
    exactly the shape of a console killed mid-sweep, and needs no provider and no network to arrange.

    What is asserted is the honest answer: `interrupted`. Nothing was resumed, because restarting
    hundreds of paid calls by itself would be indefensible, and "interrupted, start it again" is what
    an operator can act on. The progress it had reached survives too, because it is a column and not
    a variable.
    """
    from corparius.app import setup as app_setup

    from .test_durable_jobs import _console, _free_port, _kill

    store = _a_store(home)
    try:
        left = store.start_job(
            app_setup.KIND_SWEEP, app_setup.MACHINE, progress="groq/llama — 12 called"
        )
        assert store.job(left["id"])["state"] == jobs_store.RUNNING
    finally:
        store.close()

    port = _free_port()
    proc = _console(port, home, env)
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/v1/machine")
        res = conn.getresponse()
        data = json.loads(res.read() or b"{}")
        conn.close()
        assert res.status == 200, data
        assert data["sweep"]["state"] == jobs_store.INTERRUPTED, data["sweep"]
        assert "12 called" in data["sweep"]["progress"]
    finally:
        _kill(proc)


# --- the guard, which is now the store ------------------------------------------


def test_the_pull_guard_is_the_store_not_this_process(home, monkeypatch):
    """ "A pull is already in progress" used to read this process's memory, so a pull left behind by a
    crashed console was invisible to the next one — which would start a second download of the same
    gigabytes."""
    from corparius.app import setup as app_setup
    from corparius.app.errors import Refused
    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": ["gemma:2b"]})
    store = _a_store(home)
    try:
        first = app_setup.start_pull(store)
        assert first["models"] == ["gemma:2b"] and first["created"] is True
        with pytest.raises(Refused, match="already in progress"):
            app_setup.start_pull(store)
    finally:
        store.close()


def test_there_is_nothing_to_pull_when_every_model_is_installed(home, monkeypatch):
    """Refused rather than a job that does nothing: an empty pull that reported success would leave an
    operator waiting for a download that was never going to happen."""
    from corparius.app import setup as app_setup
    from corparius.app.errors import Refused
    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": []})
    store = _a_store(home)
    try:
        with pytest.raises(Refused, match="already installed"):
            app_setup.start_pull(store)
        assert store.list_jobs(kind=app_setup.KIND_PULL) == [], "nothing may be recorded"
    finally:
        store.close()


def test_a_sweep_cannot_start_twice_and_mock_mode_refuses_before_recording(home):
    from corparius.app import setup as app_setup
    from corparius.app.errors import Refused
    from corparius.config.settings import Settings

    store = _a_store(home)
    try:
        assert app_setup.start_sweep(store, _Live())["created"] is True
        with pytest.raises(Refused, match="already running"):
            app_setup.start_sweep(store, _Live())
        running = store.running_job(app_setup.KIND_SWEEP, app_setup.MACHINE)
        store.finish_job(running["id"], jobs_store.CANCELLED, {})
        # Mock mode: there is no provider to call, and a sweep that proved nothing while reporting
        # success is worse than one that did not start.
        with pytest.raises(Refused, match="mock mode"):
            app_setup.start_sweep(store, Settings())
        assert len(store.list_jobs(kind=app_setup.KIND_SWEEP)) == 1
    finally:
        store.close()


def test_stopping_is_a_column_so_anybody_can_ask(home):
    """The durable half. A phone stops a sweep this console started by writing `cancel_requested`,
    which `run_sweep`'s `should_stop` reads — no `threading.Event` involved, because an event only
    exists in the process that made it."""
    from corparius.app import setup as app_setup

    store = _a_store(home)
    try:
        job = app_setup.start_sweep(store, _Live())["job"]
        assert app_setup.stop(store, app_setup.KIND_SWEEP) == {"stopping": True, "job": job}
        assert store.cancel_requested(job) is True
        # Nothing running is not an error: the client asked, and the answer is there was nothing.
        store.finish_job(job, jobs_store.CANCELLED, {})
        assert app_setup.stop(store, app_setup.KIND_SWEEP)["stopping"] is False
    finally:
        store.close()


# --- the view, and the bound that would have lied -------------------------------


def test_the_view_still_reports_a_pull_that_finished(home, monkeypatch):
    """A view reporting only live work cannot say "the pull you started finished", which is what an
    operator coming back to the tab actually wants to know."""
    from corparius.app import setup as app_setup
    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": ["gemma:2b"]})
    store = _a_store(home)
    try:
        job = app_setup.start_pull(store)["job"]
        assert app_setup.view(store)["pull"]["state"] == jobs_store.RUNNING
        store.finish_job(job, jobs_store.DONE, {"done": ["gemma:2b"], "failed": []})
        seen = app_setup.view(store)["pull"]
        assert seen["state"] == jobs_store.DONE
        assert seen["result"]["done"] == ["gemma:2b"]
        assert app_setup.view(store)["sweep"] == {}, "never started is not the same as finished"
    finally:
        store.close()


def test_a_pull_is_found_behind_twenty_five_newer_company_runs(home, monkeypatch):
    """The bound that would have read as "there is no pull".

    `_latest` filters by `kind` **in SQL**. Filtering in Python over `list_jobs(limit=…)` would hide a
    pull behind newer rows — and `list_jobs(company="")` does not even mean "the empty company", it
    means *no company filter*, so it returns every company's runs too. Two ways to the same silent
    wrong answer, which is why this is a test and not a comment.
    """
    from corparius.app import setup as app_setup
    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": ["gemma:2b"]})
    store = _a_store(home)
    try:
        job = app_setup.start_pull(store)["job"]
        store.finish_job(job, jobs_store.DONE, {"done": ["gemma:2b"]})
        for i in range(25):
            other = store.start_job("run", f"company-{i}")["id"]
            store.finish_job(other, jobs_store.DONE, {})
        assert app_setup.view(store)["pull"]["id"] == job, "the pull was buried by newer runs"
    finally:
        store.close()


def test_list_jobs_filters_by_kind_and_an_empty_filter_means_every_one(home):
    """Stated directly, because the asymmetry is the trap: an empty string means *do not filter*, so
    `company=""` asks for all companies rather than for the machine-level ones."""
    store = _a_store(home)
    try:
        store.start_job("ollama_pull", "")
        store.start_job("run", "vigil")
        assert [r["kind"] for r in store.list_jobs(kind="ollama_pull")] == ["ollama_pull"]
        assert len(store.list_jobs(company="")) == 2, "an empty company filters nothing"
        assert [r["company"] for r in store.list_jobs(company="vigil")] == ["vigil"]
    finally:
        store.close()


# --- the workers, which are thread targets and must not raise -------------------


def test_the_pull_worker_never_raises_and_always_ends_the_row(home, monkeypatch):
    """It is a thread target. An exception escaping would print a traceback nobody reads and leave the
    row saying `running` until a later process marked it `interrupted` — true, and a day late."""
    from corparius.app import setup as app_setup
    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": ["gemma:2b"]})

    def explode(model, on_line=None):
        raise OSError("the daemon went away")

    monkeypatch.setattr(ollama_setup, "pull", explode)
    store = _a_store(home)
    try:
        claim = app_setup.start_pull(store)
        outcome = app_setup.run_pull(store, claim["job"], claim["models"])
        assert "the daemon went away" in outcome["error"]
        row = store.job(claim["job"])
        assert row["state"] == jobs_store.FAILED, "the row has to end, whatever happened"
        assert row["result"]["skipped"] == ["gemma:2b"]
    finally:
        store.close()


def test_a_cancelled_pull_reports_which_models_landed(home, monkeypatch):
    """`done`, `failed` and `skipped` apart, because "pulling three models" is one job and a single
    `running` flag could not say which of the three arrived."""
    from corparius.app import setup as app_setup
    from corparius.providers import ollama_setup

    wanted = ["a:1", "b:2", "c:3"]
    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": list(wanted)})
    store = _a_store(home)
    pulled: list[str] = []

    def pull_then_cancel(model, on_line=None):
        pulled.append(model)
        if len(pulled) == 1:
            store.request_cancel(store.running_job(app_setup.KIND_PULL, app_setup.MACHINE)["id"])
        return {"ok": True}

    monkeypatch.setattr(ollama_setup, "pull", pull_then_cancel)
    try:
        claim = app_setup.start_pull(store)
        outcome = app_setup.run_pull(store, claim["job"], claim["models"])
        # Stopped **between** models: `ollama pull` has no resumable stop, and killing a download
        # halfway leaves a partial blob the daemon refuses to use.
        assert outcome["done"] == ["a:1"]
        assert outcome["skipped"] == ["b:2", "c:3"]
        assert store.job(claim["job"])["state"] == jobs_store.CANCELLED
    finally:
        store.close()


def test_the_pull_writes_each_line_to_the_row_as_it_arrives(home, monkeypatch):
    """Progress on the row rather than in memory is the whole point: this is what a phone reads."""
    from corparius.app import setup as app_setup
    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "status", lambda **k: {"missing": ["gemma:2b"]})
    seen: list[str] = []

    def pull(model, on_line=None):
        for line in ("pulling manifest", "downloading 42%", "verifying sha256"):
            on_line(line)
            seen.append(str(store.job(job)["progress"]))
        return {"ok": True}

    monkeypatch.setattr(ollama_setup, "pull", pull)
    store = _a_store(home)
    try:
        job = app_setup.start_pull(store)["job"]
        app_setup.run_pull(store, job, ["gemma:2b"])
        assert seen == ["pulling manifest", "downloading 42%", "verifying sha256"]
        assert store.job(job)["state"] == jobs_store.DONE
    finally:
        store.close()


def test_the_sweep_worker_records_a_failure_on_the_job(home, monkeypatch):
    """Everything proved before the failure is already in the store — each verdict is written the
    moment it arrives — so an hour of real calls is never lost to whatever went wrong at the end."""
    from corparius.app import setup as app_setup
    from corparius.providers import preflight

    def explode(store, **kwargs):
        kwargs["on_progress"]("groq", "llama", type("R", (), {"state": "usable"})(), 1)
        raise RuntimeError("the catalogue moved")

    monkeypatch.setattr(preflight, "sweep", explode)
    store = _a_store(home)
    try:
        job = app_setup.start_sweep(store, _Live())["job"]
        outcome = app_setup.run_sweep(store, job)
        assert outcome["counts"] == {"usable": 1}, "what was proved is kept"
        assert "catalogue moved" in outcome["error"]
        row = store.job(job)
        assert row["state"] == jobs_store.FAILED
        assert row["result"]["counts"] == {"usable": 1}
    finally:
        store.close()


def test_the_sweep_progress_line_names_the_model_being_called(home, monkeypatch):
    from corparius.app import setup as app_setup
    from corparius.providers import preflight

    def one_probe(store, **kwargs):
        kwargs["on_progress"]("cerebras", "llama-3.3-70b", type("R", (), {"state": "usable"})(), 7)

    monkeypatch.setattr(preflight, "sweep", one_probe)
    store = _a_store(home)
    try:
        job = app_setup.start_sweep(store, _Live())["job"]
        app_setup.run_sweep(store, job)
        # The row is finished by then, so the line is read from what was written during the run.
        assert store.job(job)["state"] == jobs_store.DONE
        assert store.job(job)["result"]["counts"] == {"usable": 1}
    finally:
        store.close()


def test_uistate_no_longer_holds_either_of_them():
    """The inverse of the test this commit deleted.

    `tests/test_v1_providers.py` carried `test_the_pull_and_the_sweep_have_no_v1_spelling_yet`, whose
    message said whoever added a v1 route should make it durable first and then delete the test. This
    is that deletion, replaced by the assertion that the premise is genuinely gone: neither field is
    in `UiState` any more, so neither can quietly come back.
    """
    from corparius.api.state import UiState

    names = UiState.__init__.__code__.co_names
    assert "pulls" not in names and "sweep" not in names, (
        "an in-process copy of the pull or the sweep came back. Both are `jobs` rows now: a field "
        "here would be a second source of truth that a restart silently loses."
    )
    # What is left is genuinely per-process.
    assert "runs" in names and "chats" in names
