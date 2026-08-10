"""Long work on the machine's model infrastructure, recorded where a restart cannot lose it. Rank 5.

Two operations, and they are here together because they share the only property that matters about
them: **they take minutes and they are not company work.** Pulling a model is gigabytes; sweeping every
configured provider is hundreds of real generations on the operator's own account and rate limits.

## Why they moved

Both tracked progress in `UiState` — `ui.pulls` and `ui.sweep`, dicts in this process. Three
consequences, all of them measured against how a run behaves now that `jobs` exists:

  * **A restart lost them.** The console comes back with `{"running": False}` and no record that
    anything was ever started, so an operator who restarted mid-pull cannot tell an interrupted
    download from one that never began.
  * **A second client could not see them.** The plan's premise for the whole v1 contract is that a
    phone consults a core it did not start. `ui.sweep` is not consultable; a phone that pressed
    "check everything" and lost its connection had no way back to it.
  * **The guard was per-process.** "A sweep is already running" read this process's memory, so a
    sweep left behind by a crashed console was invisible to the next one, which would happily start a
    second — hundreds of duplicate paid calls.

That is exactly the list `start_run`'s docstring gives for runs, one layer down. Schema 19 already
built the table; these two were simply not moved yet, and `tests/test_v1_providers.py` had a test
failing on purpose until they were.

## The shape, and the one thing it does differently from runs

**The worker body lives here, not in the caller.** `adapters.start_run` keeps its thread *and* its
work, so `cli/operate.cmd_run` had to write the guard, the row and the finish a second time — 25 lines
of near-duplicate that only agree because somebody checked. Here `run_pull` and `run_sweep` are
synchronous functions taking a store and a job id: the console runs them in a thread, a terminal could
run them in the foreground, and neither has to know how the other reports.

Nothing here starts a thread. Rank 5 owns the work and the bookkeeping; the caller owns concurrency.
"""

from __future__ import annotations

import logging

from ..store import jobs as jobs_store
from .errors import Refused

# One kind per operation, and neither is company-scoped: a model on disk and a proven provider key
# belong to the installation, not to one company. `jobs.company` stays `''` for both, which is what
# `running_job(kind, "")` then asks about.
KIND_PULL = "ollama_pull"
KIND_SWEEP = "preflight_sweep"

log = logging.getLogger("corparius.app.setup")

MACHINE = ""  # the empty slug, spelled out so the intent is not read as an oversight


def start_pull(store, models: list | None = None) -> dict:
    """Claim the right to pull, and record it. Does not pull.

    Returns the job row plus the resolved model list. Raises `Refused` when there is nothing to pull
    or one is already running — the failure, not a status code, so the console can turn it into a 409
    and a terminal can print it.

    The models are resolved **here** rather than in the caller: "pull what is missing" is the
    interesting request, and an empty list meaning "everything missing" is a decision that must not be
    made twice differently.
    """
    from ..providers import ollama_setup

    wanted = [str(m).strip() for m in (models or []) if str(m).strip()]
    if not wanted:
        wanted = list(ollama_setup.status()["missing"])
    if not wanted:
        raise Refused("every model your tiers need is already installed")
    already = store.running_job(KIND_PULL, MACHINE)
    if already:
        raise Refused("a pull is already in progress")
    started = store.start_job(
        KIND_PULL,
        MACHINE,
        progress="starting",
        params={"models": wanted},
    )
    return {"job": started["id"], "created": started["created"], "models": wanted}


def run_pull(store, job_id: str, models: list[str]) -> dict:
    """Pull each model, writing progress to the row as it goes. Synchronous.

    One row per pull rather than one per model, because "pulling three models" is one thing an
    operator asked for. `done` and `failed` accumulate in the result so a client that reconnects
    learns which of the three landed — the distinction a single `running` flag could not carry.

    A cancel is honoured **between** models, not inside one: `ollama pull` has no resumable stop, and
    killing a download halfway leaves a partial blob the daemon will refuse to use. Stopping after the
    current model is the honest granularity, and saying so beats a stop button that appears immediate
    and is not.
    """
    from ..providers import ollama_setup

    done: list[str] = []
    failed: list[str] = []
    error = ""
    try:
        for model in models:
            if store.cancel_requested(job_id):
                break
            store.set_job_progress(job_id, f"{model}: starting")
            result = ollama_setup.pull(
                model, on_line=lambda line: store.set_job_progress(job_id, line)
            )
            (done if result["ok"] else failed).append(model)
    except Exception as exc:  # noqa: BLE001 - see below: the row must end, whatever happened
        log.exception("ollama pull failed")
        error = str(exc)
    # `dict[str, object]`, because `error` is a string among lists. Inferred from the literal it
    # would be `dict[str, list[str]]` and the assignment below would not type — mypy said so.
    outcome: dict[str, object] = {
        "done": done,
        "failed": failed,
        "skipped": [m for m in models if m not in done + failed],
    }
    if error:
        outcome["error"] = error
    # **The row must end, and this function must not raise.** It is a thread target: an exception
    # escaping it would print a traceback nobody reads and leave the row saying `running` until some
    # later process marked it `interrupted` — true, and a day late. Recording the failure on the job is
    # what "a background worker must not die silently" actually requires.
    state = jobs_store.FAILED if error else _ending(store, job_id)
    store.finish_job(job_id, state, outcome)
    return outcome


def start_sweep(store, settings, limit: int = 0, timeout: int = 0) -> dict:
    """Claim the right to sweep, and record what was asked.

    `Refused` in mock mode, because there is no provider to call and a sweep that proved nothing while
    reporting success is worse than one that did not start.
    """
    from ..providers import preflight

    if settings.llm_mock:
        raise Refused("mock mode is on, so there is no provider to call")
    already = store.running_job(KIND_SWEEP, MACHINE)
    if already:
        raise Refused("a sweep is already running")
    started = store.start_job(
        KIND_SWEEP,
        MACHINE,
        progress="starting",
        params={"limit": int(limit), "timeout": int(timeout or preflight.TIMEOUT)},
    )
    return {"job": started["id"], "created": started["created"]}


def run_sweep(store, job_id: str, limit: int = 0, timeout: int = 0) -> dict:
    """Probe every configured model once, writing progress to the row. Synchronous.

    **Everything proved before a failure is already kept.** Each verdict is written to the store the
    moment it arrives, so an hour of real calls is never lost to whatever went wrong at the end — and
    that is why the `except` here records the failure on the job rather than discarding the run.

    The counts accumulate in memory and are written once at the end, because a count is only ever read
    whole; the *progress line* is what a client watching wants, and that is one short string per probe
    rather than a growing dict serialised on every call.
    """
    from ..providers import preflight

    counts: dict[str, int] = {}

    def note(provider, model, result, done):
        counts[result.state] = counts.get(result.state, 0) + 1
        store.set_job_progress(job_id, f"{provider}/{model} — {done} called")

    try:
        preflight.sweep(
            store,
            limit=int(limit),
            timeout=int(timeout or preflight.TIMEOUT),
            on_progress=note,
            should_stop=lambda: store.cancel_requested(job_id),
        )
    except Exception as exc:  # noqa: BLE001 - the row must end; this is a thread target
        log.exception("preflight sweep failed")
        outcome = {"counts": counts, "error": str(exc)}
        store.finish_job(job_id, jobs_store.FAILED, outcome)
        return outcome
    store.finish_job(job_id, _ending(store, job_id), {"counts": counts})
    return {"counts": counts}


def _ending(store, job_id: str) -> str:
    """`cancelled` when somebody asked, `done` otherwise.

    One place, because getting it backwards is silent: a sweep the operator stopped and that reports
    `done` claims coverage it does not have, and one that finished and reports `cancelled` sends them
    to run it again for nothing.
    """
    return jobs_store.CANCELLED if store.cancel_requested(job_id) else jobs_store.DONE


def stop(store, kind: str) -> dict:
    """Ask the running job of this kind to stop. Durable, so anybody can ask.

    `cancel_requested` is a column, not an event, which is what lets a phone stop a sweep this console
    started — the same mechanism the plan names for runs, and the reason `should_stop` above reads the
    store rather than a `threading.Event`.
    """
    job = store.running_job(kind, MACHINE)
    if not job:
        return {"stopping": False, "job": ""}
    store.request_cancel(job["id"])
    return {"stopping": True, "job": job["id"]}


def view(store) -> dict:
    """What each operation is doing, read from the rows.

    `interrupted` is a state a client will actually see: a console killed mid-sweep leaves a `running`
    row that the next process marks on startup. Reporting it beats both silence and a resume — nothing
    was resumed, and claiming otherwise would be a lie about what happened.
    """
    return {
        "pull": _latest(store, KIND_PULL),
        "sweep": _latest(store, KIND_SWEEP),
    }


def _latest(store, kind: str) -> dict:
    """The running job of this kind, or the last one to end. `{}` when there has never been one.

    Newest-first rather than "the running one, else nothing": an operator coming back to the tab wants
    to know that the pull they started finished, which a view that only reports live work cannot say.

    Filtered by `kind` in SQL, not in Python. `list_jobs(company=MACHINE)` would have been wrong twice
    over: an empty company means *no filter* there, so it returns every company's runs too, and a
    `limit` applied before the filter hides a pull behind twenty newer ones. That reads as "there is no
    pull" rather than "you did not look far enough", which is the failure mode this project keeps
    finding in bounded reads.
    """
    rows = store.list_jobs(kind=kind, limit=5)
    running = next((r for r in rows if r["state"] == jobs_store.RUNNING), None)
    return running or (rows[0] if rows else {})
