"""What is running, from the store rather than from a process's memory. Rank 5.

`app/overview.summary` takes the run as a parameter, and that one line — `state.runs.get(slug)` —
was what stopped a terminal from seeing it. Stage 6 made it a parameter; this makes there be
something durable to pass.

The shape is unchanged (`running`, `loop`, `last_run`, `stopping`), so the console's page and
`corparius status` read what they always read. What changed is where it comes from: a row in
`jobs` that outlives the process. A console restarted mid-run now says `interrupted` instead of
saying nothing, and a terminal can see a run the console started — which is the same capability
in the other direction and the reason this is in `app/` and not in `api/adapters.py`.

**One fact, one home.** The tick count is not here: it is in `state`, where the run itself writes
it, and duplicating it into `jobs.progress` would be two copies of one number waiting to
disagree. `progress` carries a short line for a person — "starting", "stopping" — and the clock
comes from the clock.
"""

from __future__ import annotations

from ..store import jobs as jobs_store

KIND = "run"


def view(store, slug: str, stopping: bool = False) -> dict:
    """The four fields `summary` reports about the run, or an empty dict if there was never one.

    `stopping` is passed in rather than read: it is true the moment a cancel is *requested*, and
    the request may be a column (somebody else asked) or an in-process event (this console's own
    click, which lands microseconds earlier). The caller knows which it has.
    """
    running = store.running_job(KIND, slug)
    if running:
        return {
            "running": True,
            "loop": bool((running.get("params") or {}).get("loop")),
            "result": None,
            "job": running["id"],
            # Either signal counts. The column is what makes a phone able to stop a run it did
            # not start; the event is what makes the console's own button feel instant.
            "stopping": stopping or bool(running.get("cancel_requested")),
        }
    recent = store.list_jobs(company=slug, limit=1)
    if not recent or recent[0]["kind"] != KIND:
        return {}
    last = recent[0]
    return {
        "running": False,
        "loop": bool((last.get("params") or {}).get("loop")),
        # An interrupted run has no result, and that is the honest answer rather than an empty
        # one: it says the work stopped without finishing, where `{}` would read as "it finished
        # and did nothing". The page shows the state; a client switches on it.
        "result": last.get("result") if last["state"] == jobs_store.DONE else _ended(last),
        "job": last["id"],
        "stopping": False,
    }


def _ended(job: dict) -> dict:
    """What to report for a run that stopped without completing.

    `interrupted` is the one this whole table exists for: the process that was running it went
    away. Saying so is the plan's own rule — "interrompu, relance-le" is honest and a silent
    resume is a lie about what happened.
    """
    if job["state"] == jobs_store.INTERRUPTED:
        return {
            "state": job["state"],
            "error": "The console stopped while this run was in progress. Nothing was resumed; "
            "start it again when you are ready.",
        }
    # Cancelled and failed both carry whatever the worker managed to record, alongside the state
    # a client switches on. Written as one branch because it is one: the first version had two
    # identical ones, which reads as a distinction that does not exist.
    return {"state": job["state"], **(job.get("result") or {})}
