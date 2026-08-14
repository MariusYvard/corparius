"""Work that outlives the request that asked for it. Schema 19.

The one thing a second client most needs and could not have: `UiState.runs` is a dict in the
console's process, so a run started from a phone vanished the moment the console restarted, with
no record it had ever existed. `capabilities.durable_jobs` reported `false` for exactly this.

Three decisions here, and each one is a refusal to guess.

**An interrupted job is `interrupted`, never resumed.** At startup, a job still marked `running`
that this process does not own becomes `interrupted`. "It stopped, relaunch it" is honest;
picking it up silently would claim the ticks it did not run and the day boundary it never banked.

**Ownership is a per-process token, not the PID.** The plan said `owner_boot`, and there is no
portable boot id in the stdlib — `/proc/sys/kernel/random/boot_id` has no Windows equivalent, and
this project builds on three OSes. A PID alone is worse than nothing here: PIDs are reused, so a
new console that happened to inherit the old one's number would decide the orphan was its own and
report a dead run as live forever. `OWNER` below is a random token minted once per process, which
answers "is this mine" exactly and needs no boot id at all. `owner_pid` is kept beside it for a
person reading the table, and is never the thing compared.

**Cancellation is durable, and the in-memory `Event` stays for speed.** `cancel_requested` is a
column because the phone that stops a run is not the process running it. The console's
`should_stop` reads both: the event lands within microseconds for its own clicks, the column
within a tick for everybody else's. That parameter was already injected — `orchestrator.run`
takes `should_stop` and polls it at every tick and day boundary — so this cost one lambda.

`idempotency_key` is uniquely indexed, and the index is **partial**: `WHERE idempotency_key <> ''`,
so the twenty jobs a day started without one do not collide with each other. A phone on 4G that
retries "start a run" must not start two, and the retry gets the *same* job back rather than a
refusal it would have to interpret.
"""

from __future__ import annotations

import json
import os
import secrets
import time

from .base import Connected, _locked

# The states, and they are a closed set for the same reason the error codes are: a client
# switches on them.
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"
STATES = frozenset({RUNNING, DONE, FAILED, CANCELLED, INTERRUPTED})

# Minted once per process. Two consoles started in sequence differ here even if the operating
# system handed the second one the first one's PID.
OWNER = secrets.token_hex(8)


class JobsMixin(Connected):
    @_locked
    def start_job(
        self,
        kind: str,
        company: str = "",
        *,
        idempotency_key: str = "",
        progress: str = "",
        params: dict | None = None,
    ) -> dict:
        """Record that work has begun, and answer with the row that now represents it.

        `{"id": …, "created": bool}` rather than an id alone, because the interesting case is
        `created=False`: a retried request found its own earlier job and the caller must **not**
        start a second worker. Returning the id silently either way is how a client on a bad
        connection ends up running two.
        """
        if idempotency_key:
            row = self.db.execute(
                "SELECT id FROM jobs WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if row:
                return {"id": str(row["id"]), "created": False}
        job_id = secrets.token_hex(8)
        self.db.execute(
            "INSERT INTO jobs (id, kind, company, state, progress, params, owner_pid,"
            " owner_token, idempotency_key, started_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                kind,
                company,
                RUNNING,
                progress,
                json.dumps(params or {}),
                os.getpid(),
                OWNER,
                idempotency_key,
                time.time(),
            ),
        )
        self.db.commit()
        return {"id": job_id, "created": True}

    @_locked
    def job_for_key(self, idempotency_key: str) -> dict | None:
        """The job a key already named, if any.

        Separate from `start_job` because a caller has to be able to ask *before* deciding
        anything else. `start_run` checked its "already running" guard first and told a phone
        retrying its own request that a run was in progress — its own — which is precisely the
        situation the key exists to make harmless.
        """
        if not idempotency_key:
            return None
        row = self.db.execute(
            "SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        return _as_dict(row) if row else None

    @_locked
    def job(self, job_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _as_dict(row) if row else None

    @_locked
    def list_jobs(
        self, company: str = "", state: str = "", limit: int = 50, kind: str = ""
    ) -> list[dict]:
        """Newest first, because a client opening on the oldest job is showing the least useful
        end of the list — the same reasoning as the `done` task column.

        Every filter is opt-in: an empty string means "do not filter on this", which is why the
        machine-level jobs (`ollama_pull`, `preflight_sweep`) cannot be found by passing
        `company=""` — that asks for *all* companies, not for the empty one. They are found by
        `kind`, which is what actually distinguishes them, and `running_job` compares `company=?`
        exactly when the live one is what is wanted.

        `kind` was added when those two moved off `UiState`: filtering in Python over `limit=20`
        would have hidden a pull behind twenty newer company runs, which is the kind of bound that
        reads as "there is no pull" instead of "you did not look far enough".
        """
        where: list[str] = []
        params: list[object] = []
        if company:
            where.append("company=?")
            params.append(company)
        if kind:
            where.append("kind=?")
            params.append(kind)
        if state:
            where.append("state=?")
            params.append(state)
        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        # **`rowid` breaks the tie, and the tie is real.** `time.time()` has a ~15.6ms floor on
        # Windows, so two rows written in the same tick carry the *same* `ts` and SQLite is free to
        # return them in any order. Measured: a run finished, a second run started and failed inside
        # one tick, and the console reported the first one's result — `KeyError: 'state'` on
        # windows-latest, green on every other runner. Insertion order is exactly "which came later"
        # when the clock cannot say, so it is the honest second key rather than a coin toss.
        sql += " ORDER BY started_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_as_dict(r) for r in self.db.execute(sql, params).fetchall()]

    @_locked
    def set_job_progress(self, job_id: str, progress: str) -> bool:
        """One short line for a person. Not a percentage: a `--loop` run has no end to be a
        fraction of, and a bar that never fills is worse than a sentence that is true."""
        cur = self.db.execute(
            "UPDATE jobs SET progress=? WHERE id=? AND state=?", (progress, job_id, RUNNING)
        )
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def finish_job(self, job_id: str, state: str, result: dict | None = None) -> bool:
        assert state in STATES and state != RUNNING, f"{state!r} is not an ending"
        cur = self.db.execute(
            "UPDATE jobs SET state=?, result=?, ended_at=? WHERE id=?",
            (state, json.dumps(result or {}), time.time(), job_id),
        )
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def request_cancel(self, job_id: str) -> bool:
        """The durable half of stopping. False when there is no such job or it already ended —
        which a caller needs, because "I asked it to stop" and "it was already over" are
        different things to report.
        """
        cur = self.db.execute(
            "UPDATE jobs SET cancel_requested=1 WHERE id=? AND state=?", (job_id, RUNNING)
        )
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def cancel_requested(self, job_id: str) -> bool:
        row = self.db.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    @_locked
    def running_job(self, kind: str, company: str) -> dict | None:
        """The one job of this kind still running for this company, if any.

        The guard against a second run, and it is in the store rather than in the console's
        `UiState` for the reason this whole module exists: the console's copy of that fact does
        not survive a restart, so a run left `running` by a crashed process used to be invisible
        to the next one and a second run would start on top of it.
        """
        row = self.db.execute(
            "SELECT * FROM jobs WHERE kind=? AND company=? AND state=?"
            " ORDER BY started_at DESC, rowid DESC",  # see list_jobs on the tie
            (kind, company, RUNNING),
        ).fetchone()
        return _as_dict(row) if row else None

    @_locked
    def interrupt_orphans(self) -> list[str]:
        """Mark every `running` job this process does not own as `interrupted`. Returns the ids.

        Called once at startup. The comparison is on `owner_token`, never on the PID: see the
        module docstring for why a reused PID would make a dead run look live forever.
        """
        rows = self.db.execute(
            "SELECT id FROM jobs WHERE state=? AND owner_token<>?", (RUNNING, OWNER)
        ).fetchall()
        ids = [str(r["id"]) for r in rows]
        if ids:
            self.db.execute(
                "UPDATE jobs SET state=?, ended_at=? WHERE state=? AND owner_token<>?",
                (INTERRUPTED, time.time(), RUNNING, OWNER),
            )
            self.db.commit()
        return ids


def _as_dict(row) -> dict:
    """`result` and `params` come back as objects, not the JSON text they are stored as.

    A caller that had to `json.loads` it itself would be a caller that sometimes forgets, and the
    shape of the answer would depend on which one you asked.
    """
    out = dict(row)
    for field, empty in (("result", None), ("params", {})):
        raw = out.get(field) or ""
        try:
            out[field] = json.loads(raw) if raw else empty
        except json.JSONDecodeError:
            out[field] = empty
    out["cancel_requested"] = bool(out.get("cancel_requested"))
    return out
