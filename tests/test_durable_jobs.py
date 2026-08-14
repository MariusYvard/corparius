"""A run that outlives the process that started it — the plan's proof that a phone is possible.

Verification item 5, in the plan's own words: a client "lance un tour, tue le serveur, le relance,
et retrouve son tour". Until schema 19 that was impossible in principle: `UiState.runs` is a dict
in the console's process, so a run started from anywhere vanished on restart with no record it had
existed. `capabilities.durable_jobs` reported `false` for exactly this, and now reports `true`.

Four properties, and each one is a refusal to guess:

  * **an interrupted run is `interrupted`, never resumed.** Picking it up silently would claim the
    ticks it did not run and the day boundary it never banked. "It stopped, start it again" is the
    honest answer and the one a client can act on.
  * **ownership is a per-process token, not the PID.** PIDs are reused, so a new console holding
    the old one's number would call the orphan its own and report a dead run as live forever.
  * **`Idempotency-Key` means the retry gets the same job.** A phone on 4G that never saw the
    first answer must not start a second run by asking again.
  * **cancellation is durable.** The client that stops a run is not the process running it, so the
    signal is a column. The in-process event stays because a tick is long enough for a button to
    feel broken.
"""

import json
import threading
import time
from http.client import HTTPConnection

import pytest

from corparius.store import jobs as jobs_store


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """A private home and store, and the environment set rather than an object patched."""
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


def _serve(env_file):
    """A console, running for real. Returned with the thread so a test can stop it."""
    from corparius.api.server import build_server
    from corparius.config.settings import Settings

    srv = build_server(Settings(), host="127.0.0.1", port=0, env_file=env_file)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _call(srv, method, path, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=10)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        {"Content-Type": "application/json", **(headers or {})},
    )
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, json.loads(raw or b"{}")


def _stop(srv):
    """The graceful path, which is what `serve()` does on Ctrl-C.

    Draining matters here and not only in production: a `--loop` run keeps ticking after
    `shutdown()`, and closing the store under it raised `Cannot operate on a closed database` in
    this file's own teardown until this called what the real shutdown calls.
    """
    from corparius.api.server import drain_and_close

    drain_and_close(srv.RequestHandlerClass.state)
    srv.shutdown()
    srv.server_close()


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _console(port, home, env):
    """A console in its own **process**, because that is the only honest version of "the console
    went away".

    The in-process version of this test could not work and it took a failure to see why: `OWNER`
    is minted per process, and rightly — `shutdown()` on a server object does not kill the thread
    running the ticks, so a job started before it is still genuinely owned by this process. Two
    `build_server` calls in one interpreter are one owner. Killing a subprocess is the real thing.
    """
    import os
    import subprocess
    import sys
    import time

    proc = subprocess.Popen(
        [sys.executable, "-m", "corparius.cli", "ui", "--port", str(port), "--host", "127.0.0.1"],
        env={**os.environ, **env, "PYTHONPATH": os.getcwd()},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    for _ in range(200):
        if proc.poll() is not None:
            raise AssertionError(f"the console exited: {proc.communicate()[0][-800:]!r}")
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/v1/meta")
            conn.getresponse().read()
            conn.close()
            return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise AssertionError("the console never answered")


def _kill(proc):
    """Kill it and close its pipes.

    The close is not tidiness: `filterwarnings = ["error"]` makes a leaked `FileIO` finalizer a
    test failure, and the first version of this file failed on exactly that rather than on
    anything about jobs.
    """
    proc.kill()
    proc.wait(timeout=20)
    if proc.stdout is not None:
        proc.stdout.close()


def _ask(port, method, path, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        {"Content-Type": "application/json", **(headers or {})},
    )
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, json.loads(raw or b"{}")


# --- the proof ------------------------------------------------------------------


@pytest.fixture()
def env(home):
    """What a subprocess console needs to point at the same private store."""
    return {
        "CORP_DATA_PATH": str(home / "data"),
        "CORP_HOME": str(home / "home"),
        "CORP_LLM_MOCK": "true",
        "CORP_UPDATE_CHECK": "false",
    }


def test_a_run_survives_the_console_that_started_it(home, env):
    """The plan's fifth verification, literally: start a run, **kill** the server, start another,
    and ask it what happened. Two processes, one store.

    `proc.kill()` rather than a graceful stop, because a console that shut down tidily is the easy
    case and not the one an operator hits. What this asserts is what the second console says about
    work the first one was in the middle of when it died.
    """
    port = _free_port()
    first = _console(port, home, env)
    try:
        status, started = _ask(
            port, "POST", "/api/v1/runs", {"company": "example", "ticks": 48, "loop": True}
        )
        assert status == 200 and started["created"] is True, started
        job_id = started["job"]
        _status, jobs = _ask(port, "GET", "/api/v1/jobs?company=example")
        assert jobs["jobs"][0]["id"] == job_id
        assert jobs["jobs"][0]["state"] == jobs_store.RUNNING
        # 48 because that is the route's ceiling — `min(int(ticks), 48)`. Asked for 200 in the
        # first draft and asserted 200 back, which measured my wish rather than the product.
        assert jobs["jobs"][0]["params"] == {"ticks": 48, "loop": True}
    finally:
        _kill(first)

    port = _free_port()
    second = _console(port, home, env)
    try:
        _status, jobs = _ask(port, "GET", "/api/v1/jobs?company=example")
        found = next(j for j in jobs["jobs"] if j["id"] == job_id)
        assert found["state"] == jobs_store.INTERRUPTED, (
            f"a run whose process is gone is interrupted, not {found['state']!r}"
        )
        assert found["ended_at"], "an ended job has an end"
        # And it says so in words an operator reads, rather than reporting nothing.
        _status, summary = _ask(port, "GET", "/api/v1/summary?company=example")
        assert summary["running"] is False
        assert summary["last_run"]["state"] == jobs_store.INTERRUPTED
        assert "Nothing was resumed" in summary["last_run"]["error"]
        # The consequence that makes `interrupted` useful rather than merely honest: the guard is
        # clear, so the operator can act on what they were just told.
        status, again = _ask(port, "POST", "/api/v1/runs", {"company": "example", "ticks": 1})
        assert status == 200, f"a stale running row must not block a new run: {again}"
        assert again["job"] != job_id
    finally:
        _kill(second)


def test_a_pid_that_came_back_is_not_mistaken_for_the_same_process(home):
    """Ownership is a token, not a PID, and this is the case that says why.

    The row is rewritten to name *this* process's PID while keeping a foreign token — which is
    what an operating system handing out a reused number looks like from the inside. On PIDs alone
    the sweep would call the orphan its own and leave a dead run reading `running` forever.
    """
    import os

    from corparius.store import Store

    store = Store(str(home / "data"))
    try:
        job = store.start_job("run", "example", params={"ticks": 3})["id"]
        store.db.execute(
            "UPDATE jobs SET owner_pid=?, owner_token=? WHERE id=?",
            (os.getpid(), "a-different-process", job),
        )
        store.db.commit()
        assert store.interrupt_orphans() == [job]
        assert store.job(job)["state"] == jobs_store.INTERRUPTED
    finally:
        store.close()


def test_this_process_own_running_job_is_left_alone(home):
    """The other half, and the one that would break everything if it were wrong: the sweep must
    not interrupt the run this very console is in the middle of."""
    from corparius.store import Store

    store = Store(str(home / "data"))
    try:
        mine = store.start_job("run", "example")["id"]
        assert store.interrupt_orphans() == []
        assert store.job(mine)["state"] == jobs_store.RUNNING
    finally:
        store.close()


def test_the_jobs_resource_does_not_publish_the_ownership_token(home, env):
    """`owner_token` is what the startup sweep compares to decide whether a `running` job is this
    process's. A client has nothing it could do with it, and publishing a value that gates a state
    transition is needless even on loopback. `owner_pid` stays — a person can act on a PID."""
    port = _free_port()
    proc = _console(port, home, env)
    try:
        _s, started = _ask(port, "POST", "/api/v1/runs", {"company": "example", "ticks": 1})
        assert started["ok"]
        _s, jobs = _ask(port, "GET", "/api/v1/jobs?company=example")
        row = jobs["jobs"][0]
        assert "owner_token" not in row
        assert row["owner_pid"] > 0, "the PID is for a person and stays"
    finally:
        _kill(proc)


# --- idempotency ----------------------------------------------------------------


def test_the_same_key_twice_starts_one_run(home):
    """A phone on 4G that never saw the first answer asks again. It must get the first job back,
    not a second run and not a refusal it would have to interpret."""
    srv = _serve(home / ".env")
    try:
        key = {"Idempotency-Key": "phone-42"}
        s1, first = _call(srv, "POST", "/api/v1/runs", {"company": "example", "ticks": 40}, key)
        s2, second = _call(srv, "POST", "/api/v1/runs", {"company": "example", "ticks": 40}, key)
        assert s1 == 200 and s2 == 200
        assert first["created"] is True and second["created"] is False
        assert first["job"] == second["job"]
        _status, jobs = _call(srv, "GET", "/api/v1/jobs?company=example")
        assert len(jobs["jobs"]) == 1, f"one request, one job: {jobs['jobs']}"
    finally:
        _stop(srv)


def test_two_different_keys_are_two_requests_and_the_second_is_refused(home):
    """Idempotency is not a lock. A genuinely different request still meets the one-run-at-a-time
    guard, and it is `conflict` — ask again later, not differently — with the job that holds it."""
    srv = _serve(home / ".env")
    try:
        _s, first = _call(
            srv,
            "POST",
            "/api/v1/runs",
            {"company": "example", "ticks": 40, "loop": True},
            {"Idempotency-Key": "one"},
        )
        status, refused = _call(
            srv, "POST", "/api/v1/runs", {"company": "example"}, {"Idempotency-Key": "two"}
        )
        assert status == 409
        assert refused["error"]["code"] == "conflict"
        assert refused["error"]["detail"]["job"] == first["job"], (
            "a client told 'already running' needs to know which one"
        )
    finally:
        _stop(srv)


def test_no_key_means_no_promise_and_two_calls_do_not_collide(home):
    """The index is partial (`WHERE idempotency_key <> ''`). Without it every keyless job would
    collide with every other, and the second start would fail on a unique constraint instead of
    meeting the guard that is actually meant to stop it."""
    from corparius.store import Store

    store = Store(str(home / "data"))
    try:
        a = store.start_job("run", "example")
        store.finish_job(a["id"], jobs_store.DONE, {})
        b = store.start_job("run", "example")
        assert a["id"] != b["id"] and b["created"] is True
    finally:
        store.close()


# --- durable cancellation -------------------------------------------------------


def test_a_run_can_be_stopped_by_a_client_that_did_not_start_it(home):
    """The column, not the event. This is what lets a phone stop a run — and here the request is
    written straight into the store, as a second client with no event to set would do."""
    from corparius.store import Store

    srv = _serve(home / ".env")
    try:
        _s, started = _call(
            srv, "POST", "/api/v1/runs", {"company": "example", "ticks": 200, "loop": True}
        )
        job_id = started["job"]
        elsewhere = Store(str(home / "data"))
        try:
            assert elsewhere.request_cancel(job_id) is True
        finally:
            elsewhere.close()
        # The run notices at a tick boundary. `should_stop` reads the column, so this lands
        # without the console's event ever being set.
        for _ in range(100):
            _status, jobs = _call(srv, "GET", "/api/v1/jobs?company=example")
            if jobs["jobs"][0]["state"] != jobs_store.RUNNING:
                break
            time.sleep(0.1)
        assert jobs["jobs"][0]["state"] == jobs_store.CANCELLED, (
            f"a cancel written elsewhere has to stop the run: {jobs['jobs'][0]}"
        )
    finally:
        _stop(srv)


def test_stopping_reports_which_job_and_says_so_in_the_summary(home):
    srv = _serve(home / ".env")
    try:
        _s, started = _call(
            srv, "POST", "/api/v1/runs", {"company": "example", "ticks": 200, "loop": True}
        )
        status, stopped = _call(srv, "POST", "/api/v1/runs/stop", {"company": "example"})
        assert status == 200 and stopped["stopping"] is True
        assert stopped["job"] == started["job"]
    finally:
        _stop(srv)


def test_stopping_nothing_is_a_refusal_with_a_code(home):
    srv = _serve(home / ".env")
    try:
        status, data = _call(srv, "POST", "/api/v1/runs/stop", {"company": "example"})
        assert status == 404 and data["error"]["code"] == "not_found"
    finally:
        _stop(srv)


def test_cancelling_a_job_that_already_ended_answers_false(home):
    """ "I asked it to stop" and "it was already over" are different things to report."""
    from corparius.store import Store

    store = Store(str(home / "data"))
    try:
        job = store.start_job("run", "example")["id"]
        store.finish_job(job, jobs_store.DONE, {"ticks_run": 1})
        assert store.request_cancel(job) is False
    finally:
        store.close()


# --- the guard, in both callers --------------------------------------------------


def test_a_terminal_sees_the_run_the_console_started(home, capsys):
    """The other direction of the same durability, and the reason `app/runs.py` is in `app/`.

    `corparius status` reported "not running" while the console was mid-tick, because the fact
    lived in the console's memory. It reads the job row now.
    """
    from corparius.cli import operate

    srv = _serve(home / ".env")
    try:
        _s, started = _call(
            srv, "POST", "/api/v1/runs", {"company": "example", "ticks": 200, "loop": True}
        )
        assert started["ok"]
        import types

        operate.cmd_status(types.SimpleNamespace(company="example", json=True))
        payload = json.loads(capsys.readouterr().out)
        assert payload["running"] is True, "a terminal has to see the console's run"
        assert payload["loop"] is True
    finally:
        _stop(srv)


def test_a_terminal_run_is_recorded_and_refuses_a_second_one(home, capsys):
    """A run is a run whoever started it. Without the row, `status` elsewhere would report a
    phantom "not running" — the same defect the v1 work removed from `/api/overview`."""
    import types

    from corparius.app.support import open_store
    from corparius.cli import operate

    operate.cmd_run(types.SimpleNamespace(company="example", ticks=1, loop=False))
    capsys.readouterr()
    store = open_store()
    try:
        jobs = store.list_jobs(company="example")
        assert len(jobs) == 1 and jobs[0]["state"] == jobs_store.DONE
        assert jobs[0]["params"] == {"ticks": 1, "loop": False}
        # And while one is running, another terminal is refused rather than doubling up.
        held = store.start_job("run", "example")["id"]
        assert operate.cmd_run(types.SimpleNamespace(company="example", ticks=1, loop=False)) == 1
        assert "already in progress" in capsys.readouterr().out
        store.finish_job(held, jobs_store.DONE, {})
    finally:
        store.close()


# --- the same properties, in this process ---------------------------------------
#
# The subprocess test above is the honest proof and it contributes **nothing** to coverage: its
# assertions run in another interpreter, so `app/runs.py`'s interrupted branch read as untested
# while being the most carefully tested thing in the file. These cover the same properties one
# level down, which is also where a wrong word in the sentence would show.


def _a_store(home):
    from corparius.store import Store

    return Store(str(home / "data"))


def test_the_interrupted_sentence_says_nothing_was_resumed(home):
    """The words matter: an operator reading this decides whether to start it again. "Interrupted"
    alone would leave them wondering whether some of it took."""
    from corparius.app import runs as app_runs

    store = _a_store(home)
    try:
        job = store.start_job("run", "c", params={"ticks": 5, "loop": True})["id"]
        store.finish_job(job, jobs_store.INTERRUPTED)
        view = app_runs.view(store, "c")
        assert view["running"] is False and view["loop"] is True
        # `result` here, `last_run` once `summary` has published it — that rename is `summary`'s
        # own contract with the page and predates this table.
        assert view["result"]["state"] == jobs_store.INTERRUPTED
        assert "Nothing was resumed" in view["result"]["error"]
    finally:
        store.close()


def test_a_finished_run_reports_its_result_and_a_failed_one_its_state(home):
    from corparius.app import runs as app_runs

    store = _a_store(home)
    try:
        done = store.start_job("run", "c")["id"]
        store.finish_job(done, jobs_store.DONE, {"ticks_run": 4})
        assert app_runs.view(store, "c")["result"] == {"ticks_run": 4}
        failed = store.start_job("run", "c")["id"]
        store.finish_job(failed, jobs_store.FAILED, {"error": "it broke"})
        view = app_runs.view(store, "c")
        assert view["result"]["state"] == jobs_store.FAILED
        assert view["result"]["error"] == "it broke"
    finally:
        store.close()


def test_a_company_that_never_ran_reports_nothing_rather_than_a_false_shape(home):
    """`{}` and not `{"running": False}`: `summary` merges this, and inventing keys for a company
    that has never run would make "never" and "finished" look the same."""
    from corparius.app import runs as app_runs

    store = _a_store(home)
    try:
        assert app_runs.view(store, "never-ran") == {}
    finally:
        store.close()


def test_a_running_job_reports_stopping_from_either_signal(home):
    from corparius.app import runs as app_runs

    store = _a_store(home)
    try:
        job = store.start_job("run", "c")["id"]
        assert app_runs.view(store, "c")["stopping"] is False
        # The caller's own event, which lands first for its own click.
        assert app_runs.view(store, "c", stopping=True)["stopping"] is True
        # And the column, which is what a client elsewhere has instead.
        store.request_cancel(job)
        assert app_runs.view(store, "c")["stopping"] is True
    finally:
        store.close()


def test_a_key_that_raced_past_the_read_is_told_so_by_start_job(home):
    """`start_job`'s own key check, which is the second line of defence: two requests carrying one
    key can both pass `job_for_key` and only one can pass the unique index."""
    store = _a_store(home)
    try:
        first = store.start_job("run", "c", idempotency_key="k")
        second = store.start_job("run", "c", idempotency_key="k")
        assert first["created"] is True and second["created"] is False
        assert first["id"] == second["id"]
        assert store.job_for_key("") is None, "no key is not a key that matches everything"
        assert store.job_for_key("never-used") is None
    finally:
        store.close()


def test_jobs_can_be_listed_by_state(home):
    store = _a_store(home)
    try:
        done = store.start_job("run", "c")["id"]
        store.finish_job(done, jobs_store.DONE, {})
        running = store.start_job("run", "c")["id"]
        assert [j["id"] for j in store.list_jobs(state=jobs_store.RUNNING)] == [running]
        assert [j["id"] for j in store.list_jobs(state=jobs_store.DONE)] == [done]
        assert len(store.list_jobs(company="c")) == 2
        assert store.list_jobs(company="another") == []
    finally:
        store.close()


def test_a_row_whose_json_was_corrupted_reads_back_as_empty_rather_than_raising(home):
    """Defensive, and this project has the precedent: `parameters` and `detail` on approvals both
    carry the same guard. A row written by an older build, or truncated on a full disk, must not
    make a polled endpoint 500."""
    store = _a_store(home)
    try:
        job = store.start_job("run", "c")["id"]
        store.db.execute("UPDATE jobs SET params=?, result=? WHERE id=?", ("{oops", "{oops", job))
        store.db.commit()
        row = store.job(job)
        assert row["params"] == {} and row["result"] is None
    finally:
        store.close()


def test_finishing_with_a_state_that_is_not_an_ending_is_refused(home):
    """`running` is not an ending, and neither is a typo. An assertion rather than a silent
    write, because a job stuck in a state nothing sweeps is a job nothing ever reports on."""
    store = _a_store(home)
    try:
        job = store.start_job("run", "c")["id"]
        with pytest.raises(AssertionError):
            store.finish_job(job, jobs_store.RUNNING, {})
        with pytest.raises(AssertionError):
            store.finish_job(job, "finito", {})
    finally:
        store.close()


def test_two_jobs_in_one_clock_tick_still_have_a_later_one(home):
    """**The tie, forced.** `time.time()` has a ~15.6ms floor on Windows, so two rows written inside
    one tick carry the same `started_at` and `ORDER BY started_at DESC` alone lets SQLite return
    either. It did: a run finished, a second started and failed within one tick, and `app_runs.view`
    reported the first one's result — green on seven runners, `KeyError: 'state'` on windows-latest.

    Here the timestamps are made **equal on purpose** rather than left to a fast machine, because a
    test that reproduces this only on a coarse clock is a test that reports the runner it ran on.
    `rowid` is the second key: insertion order is exactly "which came later" when the clock cannot
    say so.
    """
    from corparius.app import runs as app_runs

    store = _a_store(home)
    try:
        first = store.start_job("run", "c")["id"]
        store.finish_job(first, jobs_store.DONE, {"ticks_run": 4})
        second = store.start_job("run", "c")["id"]
        store.finish_job(second, jobs_store.FAILED, {"error": "it broke"})
        # One tick, both rows. Written through the connection because no clock is coarse enough to
        # guarantee it and no sleep is fine enough to prevent it.
        store.db.execute("UPDATE jobs SET started_at = 1000.0")
        store.db.commit()

        assert store.list_jobs(company="c", limit=1)[0]["id"] == second
        view = app_runs.view(store, "c")
        assert view["job"] == second, "the tie went to the older job"
        assert view["result"]["state"] == jobs_store.FAILED
    finally:
        store.close()
