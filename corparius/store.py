"""SQLite persistence: actions, token usage, approvals, memory, and per-company state."""

from __future__ import annotations

import functools
import json
import logging
import os
import sqlite3
import threading
import time

from .safety import cosine, hash_embed

log = logging.getLogger("corparius.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, agent TEXT, tool TEXT, parameters TEXT,
    output TEXT, ok INTEGER, ts REAL
);
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, agent TEXT, input_tokens INTEGER, output_tokens INTEGER, ts REAL,
    cost REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    company TEXT, agent TEXT, tool TEXT, parameters TEXT,
    status TEXT, note TEXT, ts REAL, detail TEXT
);
CREATE TABLE IF NOT EXISTS state (
    company TEXT PRIMARY KEY, data TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, title TEXT, target TEXT, priority INTEGER,
    status TEXT, created_by TEXT, note TEXT, ts REAL, tool TEXT, why TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL,
    secret INTEGER NOT NULL DEFAULT 0, updated_at REAL
);
CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, email TEXT, message_id TEXT, subject TEXT, ts REAL,
    replied_at REAL, reply_snippet TEXT
);
CREATE INDEX IF NOT EXISTS outreach_by_email ON outreach (company, email);
CREATE TABLE IF NOT EXISTS rules (
    company TEXT, tool TEXT, scope TEXT, note TEXT, ts REAL,
    PRIMARY KEY (company, tool)
);
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, agent TEXT, fact TEXT, why TEXT, pinned INTEGER DEFAULT 0, ts REAL
);
CREATE INDEX IF NOT EXISTS memory_by_company ON memory (company, pinned, ts);
CREATE TABLE IF NOT EXISTS inbox (
    id TEXT PRIMARY KEY,
    company TEXT, agent TEXT, kind TEXT, title TEXT, body TEXT, options TEXT,
    state TEXT, resolution TEXT, resolved_at REAL, ts REAL, fix TEXT
);
CREATE INDEX IF NOT EXISTS inbox_by_company ON inbox (company, state, ts);
CREATE TABLE IF NOT EXISTS machine (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cores INTEGER, ram_total INTEGER, ram_available INTEGER,
    tokens_per_second REAL, load_seconds REAL, placement TEXT, model TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, kind TEXT, channel TEXT, body TEXT,
    state TEXT, note TEXT, ts REAL, published_at REAL
);
CREATE INDEX IF NOT EXISTS drafts_by_company ON drafts (company, state, ts);
CREATE TABLE IF NOT EXISTS model_catalogue (
    id INTEGER PRIMARY KEY CHECK (id = 1), models TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS directives (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, kind TEXT, target TEXT,
    note TEXT, active INTEGER DEFAULT 1, ts REAL
);
CREATE INDEX IF NOT EXISTS directives_by_company ON directives (company, active);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, text TEXT, why TEXT, ts REAL
);
CREATE INDEX IF NOT EXISTS decisions_by_company ON decisions (company, ts);
CREATE TABLE IF NOT EXISTS model_probes (
    provider TEXT, model TEXT, state TEXT, detail TEXT, status INTEGER, ms INTEGER, ts REAL,
    tok_s REAL, json_ok INTEGER, samples INTEGER, failures INTEGER, measured_at REAL,
    PRIMARY KEY (provider, model)
);
"""

# Bump this and add a migration below whenever the schema changes in a way that
# an existing store must be brought forward through. The version is tracked in
# the database itself via `PRAGMA user_version`, so an upgrade migrates in place
# instead of relying on the operator to back up and recreate.
SCHEMA_VERSION = 15


def _migration_1(db: sqlite3.Connection) -> None:
    """Stores created before the CEO wired tasks to executable tools lack the
    tasks.tool column. Guarded so it is a no-op on fresh DBs (the column is in
    SCHEMA) and on re-runs."""
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN tool TEXT")
    except sqlite3.OperationalError:
        pass


def _migration_2(db: sqlite3.Connection) -> None:
    """Standing permission rules ("approve, and stop asking"), added with the
    risk-classed permission engine. CREATE TABLE IF NOT EXISTS in SCHEMA already
    covers fresh stores; this exists so an upgrade in place reaches the same
    shape without the operator recreating the database."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS rules ("
        " company TEXT, tool TEXT, scope TEXT, note TEXT, ts REAL,"
        " PRIMARY KEY (company, tool))"
    )


def _migration_3(db: sqlite3.Connection) -> None:
    """Durable memory, added when three days of EOD summaries stopped being
    enough. Same guarded shape as _migration_2."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS memory ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " company TEXT, agent TEXT, fact TEXT, why TEXT, pinned INTEGER DEFAULT 0, ts REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS memory_by_company ON memory (company, pinned, ts)")


def _migration_4(db: sqlite3.Connection) -> None:
    """The typed inbox: questions an agent could not ask before, and notices a
    frozen session could not send. Same guarded shape as the two above."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS inbox ("
        " id TEXT PRIMARY KEY,"
        " company TEXT, agent TEXT, kind TEXT, title TEXT, body TEXT, options TEXT,"
        " state TEXT, resolution TEXT, resolved_at REAL, ts REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS inbox_by_company ON inbox (company, state, ts)")


def _migration_5(db: sqlite3.Connection) -> None:
    """Cost per call, added when OpenRouter turned out to report it in the usage
    block corparius was already parsing for tokens. Existing rows keep 0, which
    reads as "not reported" rather than "free"."""
    try:
        db.execute("ALTER TABLE token_usage ADD COLUMN cost REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass


def _migration_6(db: sqlite3.Connection) -> None:
    """The measured machine profile, added when the routing turned out to decide
    the trivial tier on nothing but "Ollama's port answered". One row, pinned by
    a CHECK: there is exactly one machine."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS machine ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " cores INTEGER, ram_total INTEGER, ram_available INTEGER,"
        " tokens_per_second REAL, load_seconds REAL, placement TEXT, model TEXT, ts REAL)"
    )


def _migration_7(db: sqlite3.Connection) -> None:
    """Somewhere for a draft to land.

    The social agent was the biggest line in one operator's spend — 29 065
    tokens — and `schedule_post` returned a sentence. Nothing was stored, so
    every post it wrote was gone before the next tick wrote another. A draft
    nobody can read is a draft nobody asked for.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS drafts ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " company TEXT, kind TEXT, channel TEXT, body TEXT,"
        " state TEXT, note TEXT, ts REAL, published_at REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS drafts_by_company ON drafts (company, state, ts)")


def _migration_8(db: sqlite3.Connection) -> None:
    """What the operator is actually being asked to approve.

    An approval carried `parameters`, and `parameters` carried the draft cut to
    80 characters — because the id is a hash of them, and a longer draft would
    have made the same request look like a new one every time. So approving
    `send_outreach` meant approving an email nobody could read. The full text
    goes here instead, where nothing hashes it.
    """
    try:
        db.execute("ALTER TABLE approvals ADD COLUMN detail TEXT")
    except sqlite3.OperationalError:
        pass


def _migration_9(db: sqlite3.Connection) -> None:
    """Where to go to make the notice stop.

    `scan_replies` and `triage_inbox` said "no mailbox connected" on every tick
    of every run, as a log line — true, repeated forever, and pointing at
    nothing an operator could click. A notice that names its own remedy can be
    filed once and answered once.
    """
    try:
        db.execute("ALTER TABLE inbox ADD COLUMN fix TEXT")
    except sqlite3.OperationalError:
        pass


def _migration_10(db: sqlite3.Connection) -> None:
    """What each provider's models actually did when called.

    A catalogue lists models that exist. On NVIDIA, 8 of 14 sampled catalogue
    entries answered 404 for the owner's own key. Knowing that is worth keeping:
    the previous preflight overwrote one report per run and remembered nothing
    per provider, so the same 404s were rediscovered every time.

    Keyed on (provider, model) so a later run updates a verdict instead of
    appending a second one, and so knowledge accumulates across runs.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS model_probes ("
        " provider TEXT, model TEXT, state TEXT, detail TEXT, status INTEGER, ms INTEGER,"
        " ts REAL, PRIMARY KEY (provider, model))"
    )


def _migration_11(db: sqlite3.Connection) -> None:
    """How a model performs, not just whether it answers.

    "It answered" is a poor basis for a routing decision. Measured on real
    providers: 547 tok/s on one, 10 on another, and one model in the owner's own
    fallback chain that cannot produce a JSON object at all — which an
    availability probe cannot see, and which breaks every tool that goes through
    corparius/structured.py.
    """
    for column, kind in (
        ("tok_s", "REAL"),
        ("json_ok", "INTEGER"),
        ("samples", "INTEGER"),
        ("failures", "INTEGER"),
        ("measured_at", "REAL"),
    ):
        try:
            db.execute(f"ALTER TABLE model_probes ADD COLUMN {column} {kind}")
        except sqlite3.OperationalError:
            pass


def _migration_12(db: sqlite3.Connection) -> None:
    """The provider catalogue, in its own table rather than in `settings`.

    It went in `settings` first and that was wrong twice over: 400 KB of JSON
    appeared as a row among the operator's own configuration, and it travelled
    into backups as if somebody had set it.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS model_catalogue ("
        " id INTEGER PRIMARY KEY CHECK (id = 1), models TEXT, ts REAL)"
    )
    db.execute("DELETE FROM settings WHERE key='CORP_MODEL_CATALOGUE'")


def _migration_13(db: sqlite3.Connection) -> None:
    """What the operator told the CEO, in a form the runtime can obey.

    The CEO chat read the store and wrote nothing. So an operator could say
    "too early for cold emailing, focus on the prototype", watch the CEO answer
    "I will pause the campaigns", and then watch the next tick draft another
    cold email. The chat was a conversation held over a machine that could not
    hear it, which is worse than no chat: it promised.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS directives ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, kind TEXT, target TEXT,"
        " note TEXT, active INTEGER DEFAULT 1, ts REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS directives_by_company ON directives (company, active)")


def _migration_14(db: sqlite3.Connection) -> None:
    """Decisions, kept apart from facts.

    `memory` holds what the company observed. A decision is a different animal:
    it binds the future, and it should be reread before the next one is taken.
    Mixing them is why one run produced three contradicting priorities in three
    hours.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS decisions ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, text TEXT, why TEXT, ts REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS decisions_by_company ON decisions (company, ts)")


def _migration_15(db: sqlite3.Connection) -> None:
    """Why a task exists, where a status change cannot erase it.

    `note` was carrying two jobs: the agent's reason for proposing the task, and
    the provenance of the last decision about it. Every caller of
    `set_task_status` overwrites it — "validated by CEO", "via console" — so the
    reason survived exactly until somebody acted on the task, which is the one
    moment it was needed. The operator was left with a row naming its own author
    and nothing else.
    """
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN why TEXT")
    except sqlite3.OperationalError:
        pass  # already there: fresh stores get it from SCHEMA


# version -> callable(db). Applied in order for any version above the DB's own.
MIGRATIONS = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,
    4: _migration_4,
    5: _migration_5,
    6: _migration_6,
    7: _migration_7,
    8: _migration_8,
    9: _migration_9,
    10: _migration_10,
    11: _migration_11,
    12: _migration_12,
    13: _migration_13,
    14: _migration_14,
    15: _migration_15,
}


_PUNCT = str.maketrans({c: " " for c in ".,;:!?()[]\"'`—–-"})


def _words(text: str) -> str:
    """Strip what a restatement changes and meaning does not. Without this the
    memory deduplicator compares tokens like `renew,` against `renew` and calls
    one sentence two facts."""
    return text.lower().translate(_PUNCT)


def _locked(method):
    """Serialise every statement pair against the shared connection.

    One Store is shared by the console's per-request threads and the background
    run loop. sqlite3 serialises individual C calls, but not the execute/commit
    pair each method below performs: without this, two threads land inside each
    other's implicit transaction. Measured on twelve concurrent writers, that
    raised `cannot start a transaction within a transaction` and silently kept
    414 of 3200 rows, so the lock is load-bearing, not defensive.

    RLock rather than Lock because these are genuinely re-entrant: status()
    calls list_approvals() and list_tasks(), flow_metrics() calls both status()
    and list_tasks(). A plain Lock self-deadlocks on the first status() call.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class Store:
    def __init__(self, data_path: str):
        os.makedirs(data_path, exist_ok=True)
        try:  # the store holds API keys in the clear; keep the dir owner-only
            if os.name != "nt":
                os.chmod(data_path, 0o700)  # effective on POSIX, a no-op on Windows
        except OSError:
            pass
        self._lock = threading.RLock()
        self.path = os.path.join(data_path, "corparius.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._configure()
        self.db.executescript(SCHEMA)
        self.db.commit()
        try:  # the settings table holds API keys in the clear; owner only
            os.chmod(self.path, 0o600)  # effective on POSIX, a no-op on Windows
        except OSError:
            pass
        self._migrate()

    def _configure(self) -> None:
        """Connection pragmas.

        WAL is the one that matters across connections: corparius/cfg.py opens the
        store read-only as its settings layer, and the CLI can run while the
        console is up. Under the default rollback journal a writer excludes
        readers outright, and SQLite returns BUSY immediately rather than
        invoking the busy handler when two connections try to upgrade a lock at
        once, so waiting longer does not help. WAL is recorded in the database
        header, so it is set once and persists.

        It is not available everywhere: some network filesystems refuse the
        shared-memory sidecar WAL needs. A Docker volume on an odd backend
        should degrade to the old behaviour rather than refuse to start, so the
        failure is swallowed deliberately.
        """
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")  # safe under WAL, one less fsync
        except sqlite3.Error:
            pass
        # Python's sqlite3 already applies a 5s busy timeout via connect(timeout=5.0);
        # setting it explicitly keeps that from silently changing under us.
        self.db.execute("PRAGMA busy_timeout=5000")

    @_locked
    def _migrate(self) -> None:
        """Bring the store from its recorded version up to SCHEMA_VERSION, one
        step at a time, recording progress so an interrupted upgrade resumes."""
        current = self.db.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            # An older build opening a store a newer one migrated. The loop
            # below is a no-op here, so this used to open, run and write in
            # complete silence — and silence is the one thing this store does
            # not do. It stays openable on purpose: rolling back to the
            # previous build is the recovery path when an update goes wrong,
            # and refusing would strand exactly the person who needs it. But an
            # old build writing to a column a later version repurposed is how
            # data gets quietly wrong, so it says so, and the doctor fails on it.
            log.warning(
                "this store was written by a newer corparius (schema %s, this build knows %s). "
                "Update again, or restore the backup taken before the update. Running an older "
                "build against it can write values a newer schema means differently.",
                current,
                SCHEMA_VERSION,
            )
        for version in range(current + 1, SCHEMA_VERSION + 1):
            MIGRATIONS[version](self.db)
            self.db.execute(f"PRAGMA user_version = {int(version)}")
            self.db.commit()

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @_locked
    def schema_version(self) -> int:
        return self.db.execute("PRAGMA user_version").fetchone()[0]

    @_locked
    def record_action(self, company, agent, tool, parameters, output, ok) -> None:
        self.db.execute(
            "INSERT INTO actions (company, agent, tool, parameters, output, ok, ts)"
            " VALUES (?,?,?,?,?,?,?)",
            (company, agent, tool, json.dumps(parameters), output, int(ok), time.time()),
        )
        self.db.commit()

    @_locked
    def record_usage(self, company, agent, input_tokens, output_tokens, cost=0.0) -> None:
        self.db.execute(
            "INSERT INTO token_usage (company, agent, input_tokens, output_tokens, ts, cost)"
            " VALUES (?,?,?,?,?,?)",
            (company, agent, input_tokens, output_tokens, time.time(), float(cost or 0.0)),
        )
        self.db.commit()

    @_locked
    def recent_outputs(self, company, tool, limit=3) -> list[str]:
        rows = self.db.execute(
            "SELECT output FROM actions WHERE company=? AND tool=? AND ok=1"
            " ORDER BY ts DESC LIMIT ?",
            (company, tool, limit),
        ).fetchall()
        return [r["output"] for r in rows]

    # Read helpers for the console overview. These live here rather than as raw
    # SQL in corparius/webui.py: with the connection now guarded, a caller reaching
    # into store.db directly would be an unsynchronised access to a locked
    # resource, which is exactly the interleaving _locked exists to prevent.
    @_locked
    def spend_by_agent(self, company) -> list[dict]:
        """Tokens and money side by side. `cost` is 0 for every provider that
        does not report one, so a caller showing it has to know whether any
        provider reported anything at all — see `cost_reported`."""
        rows = self.db.execute(
            "SELECT agent, COALESCE(SUM(input_tokens+output_tokens),0) t, "
            "COALESCE(SUM(cost),0) cost "
            "FROM token_usage WHERE company=? GROUP BY agent ORDER BY t DESC",
            (company,),
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def cost_reported(self, company) -> bool:
        """Whether any call for this company came back with a cost. Without it,
        a total of 0.00 is indistinguishable from a free run, and the console
        would quietly tell an operator on a paid key that they spent nothing."""
        row = self.db.execute(
            "SELECT COUNT(*) n FROM token_usage WHERE company=? AND cost > 0", (company,)
        ).fetchone()
        return row["n"] > 0

    @_locked
    def recent_actions(self, company, limit=25) -> list[dict]:
        rows = self.db.execute(
            "SELECT agent, tool, ok, ts, substr(output,1,160) output FROM actions "
            "WHERE company=? ORDER BY id DESC LIMIT ?",
            (company, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def count_actions_by_tool(self, company, tool) -> int:
        return self.db.execute(
            "SELECT COUNT(*) n FROM actions WHERE company=? AND tool=?", (company, tool)
        ).fetchone()["n"]

    @_locked
    def add_approval(self, req) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO approvals"
            " (id, company, agent, tool, parameters, status, note, ts, detail)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                req.id,
                req.company,
                req.agent,
                req.tool,
                json.dumps(req.parameters),
                req.status,
                req.note,
                req.ts,
                json.dumps(getattr(req, "detail", None) or {}, ensure_ascii=False),
            ),
        )
        self.db.commit()

    @_locked
    def find_approval(self, company, tool, parameters, status=None):
        q = "SELECT * FROM approvals WHERE company=? AND tool=? AND parameters=?"
        args = [company, tool, json.dumps(parameters)]
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY ts DESC LIMIT 1"
        row = self.db.execute(q, args).fetchone()
        return dict(row) if row else None

    @_locked
    def pending_approval_for(self, company, tool):
        """The oldest undecided request for this tool, whatever its parameters.

        Looked up before an agent drafts anything, so a company that already has
        one deploy waiting does not spend a model call producing a second
        request the operator will see as a duplicate. It never widens the gate:
        matching an approval to an execution still goes through find_approval,
        which compares parameters exactly."""
        row = self.db.execute(
            "SELECT * FROM approvals WHERE company=? AND tool=? AND status='pending'"
            " ORDER BY ts LIMIT 1",
            (company, tool),
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def get_approval(self, approval_id):
        row = self.db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        return dict(row) if row else None

    @_locked
    def list_approvals(self, company, status="pending"):
        rows = self.db.execute(
            "SELECT * FROM approvals WHERE company=? AND status=? ORDER BY ts",
            (company, status),
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def set_approval_status(self, approval_id, status, note="") -> bool:
        cur = self.db.execute(
            "UPDATE approvals SET status=?, note=? WHERE id=?", (status, note, approval_id)
        )
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def add_rule(self, company, tool, scope="always", note="") -> None:
        """A standing "stop asking me about this tool" for one company. `run`
        expires with the run that granted it, `always` persists. Re-granting
        replaces rather than duplicates, so the operator cannot end up with two
        rules disagreeing about the same tool."""
        self.db.execute(
            "INSERT OR REPLACE INTO rules (company, tool, scope, note, ts) VALUES (?,?,?,?,?)",
            (company, tool, scope, note, time.time()),
        )
        self.db.commit()

    @_locked
    def find_rule(self, company, tool) -> str:
        row = self.db.execute(
            "SELECT scope FROM rules WHERE company=? AND tool=?", (company, tool)
        ).fetchone()
        return str(row["scope"]) if row else ""

    @_locked
    def list_rules(self, company):
        rows = self.db.execute(
            "SELECT * FROM rules WHERE company=? ORDER BY tool", (company,)
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def drop_rule(self, company, tool) -> bool:
        cur = self.db.execute("DELETE FROM rules WHERE company=? AND tool=?", (company, tool))
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def clear_run_rules(self, company) -> int:
        """Called when a run ends. A run-scoped rule that outlived its run would
        be an `always` rule the operator never granted."""
        cur = self.db.execute("DELETE FROM rules WHERE company=? AND scope='run'", (company,))
        self.db.commit()
        return cur.rowcount

    @_locked
    def remember(self, company, agent, fact, why="", pinned=False, max_rows=200) -> int:
        """Write down something the company learned. Returns the row id, or 0
        when the same fact is already held.

        Deduplicated on the words, not on the string: the same observation
        restated with different word order, casing or punctuation is recognised
        and dropped, which is what an agent asked the same question every day
        actually produces. It is *not* paraphrase detection — the comparison is
        cosine over safety.hash_embed, a bag-of-tokens embedding, so "coaches
        renew" and "our coaching customers stay" are two facts as far as this is
        concerned. Catching those would need a real embedding model, and would
        risk merging two facts that only sound alike, which is worse than
        keeping one line twice.

        Reusing hash_embed is what keeps this dependency-free and offline, like
        the loop guard it was written for.
        """
        fact = str(fact).strip()
        if not fact:
            return 0
        target = hash_embed(_words(fact))
        for row in self.db.execute(
            "SELECT fact FROM memory WHERE company=?", (company,)
        ).fetchall():
            if cosine(target, hash_embed(_words(row["fact"]))) >= 0.95:
                return 0
        cur = self.db.execute(
            "INSERT INTO memory (company, agent, fact, why, pinned, ts) VALUES (?,?,?,?,?,?)",
            (company, agent, fact, str(why).strip(), 1 if pinned else 0, time.time()),
        )
        # max_rows caps the *unpinned* facts, oldest dropped first. A pinned
        # fact is the operator saying "this one stays", so it is neither counted
        # against the cap nor discarded by it — otherwise pinning enough facts
        # would silently stop the company from learning anything new.
        self.db.execute(
            "DELETE FROM memory WHERE id IN ("
            " SELECT id FROM memory WHERE company=? AND pinned=0"
            " ORDER BY ts DESC LIMIT -1 OFFSET ?)",
            (company, max(0, int(max_rows))),
        )
        self.db.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    @_locked
    def recall(self, company, query="", limit=5) -> list[dict]:
        """The facts most worth putting in front of this particular prompt.

        Pinned first, then by similarity to the query, then by recency. Ranking
        in Python over a few hundred rows rather than in SQL: the ordering is
        semantic, and pushing it into the query would mean either a vector
        extension or a LIKE that matches words instead of meaning."""
        rows = [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM memory WHERE company=? ORDER BY ts DESC", (company,)
            ).fetchall()
        ]
        if not rows:
            return []
        if query.strip():
            target = hash_embed(query)
            for row in rows:
                row["score"] = cosine(target, hash_embed(f"{row['fact']} {row['why']}"))
        else:
            for row in rows:
                row["score"] = 0.0
        rows.sort(key=lambda r: (r["pinned"], r["score"], r["ts"]), reverse=True)
        return rows[: max(0, int(limit))]

    @_locked
    def list_memory(self, company) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM memory WHERE company=? ORDER BY pinned DESC, ts DESC", (company,)
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def pin_memory(self, memory_id, pinned=True) -> bool:
        cur = self.db.execute(
            "UPDATE memory SET pinned=? WHERE id=?", (1 if pinned else 0, memory_id)
        )
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def forget(self, memory_id) -> bool:
        cur = self.db.execute("DELETE FROM memory WHERE id=?", (memory_id,))
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def add_inbox(self, company, agent, kind, title, body="", options=(), fix="") -> str:
        """File a question or a notice. Idempotent on its deterministic id, so
        re-running the tick that raised it does not raise it twice, and a
        restart between the question and the answer changes nothing.

        INSERT OR IGNORE, not OR REPLACE: replacing would reset the state of an
        item the operator had already answered.

        `fix` names where in the console this is fixed (see inbox.FIXES). It is
        what turns "no mailbox connected", repeated on every tick forever, into
        one item with a button on it.
        """
        from .inbox import PENDING, item_id

        ident = item_id(company, kind, agent, title)
        self.db.execute(
            "INSERT OR IGNORE INTO inbox"
            " (id, company, agent, kind, title, body, options, state, resolution,"
            "  resolved_at, ts, fix) VALUES (?,?,?,?,?,?,?,?,'',0,?,?)",
            (
                ident,
                company,
                agent,
                kind,
                title,
                body,
                json.dumps(list(options)),
                PENDING,
                time.time(),
                fix,
            ),
        )
        self.db.commit()
        return ident

    @_locked
    def list_inbox(self, company, state=None, kind=None) -> list[dict]:
        q = "SELECT * FROM inbox WHERE company=?"
        args: list = [company]
        if state:
            q += " AND state=?"
            args.append(state)
        if kind:
            q += " AND kind=?"
            args.append(kind)
        rows = self.db.execute(q + " ORDER BY ts DESC", args).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["options"] = json.loads(item["options"] or "[]")
            except json.JSONDecodeError:
                item["options"] = []
            # NULL on every row written before schema 9. The console reads this
            # to decide whether to draw a button, and `null` is not "".
            item["fix"] = item.get("fix") or ""
            out.append(item)
        return out

    @_locked
    def resolved_inbox(self, company, kind, title):
        """The answer to one question, or None while it is still pending.

        Matched on the title rather than on the id, because the id folds in the
        agent that asked: "which mailbox should I send from?" answered for
        outreach is answered for support too, and asking the operator the same
        thing once per role would be the failure this exists to remove."""
        from .inbox import RESOLVED

        row = self.db.execute(
            "SELECT * FROM inbox WHERE company=? AND kind=? AND title=? AND state=?"
            " ORDER BY resolved_at DESC LIMIT 1",
            (company, kind, title, RESOLVED),
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def resolve_inbox(self, item_id_, resolution="") -> bool:
        """First responder wins. A second answer to a decided item returns
        False rather than overwriting: the work that was waiting has already
        moved on the first one, and rewriting the record would leave the store
        disagreeing with what actually happened."""
        from .inbox import PENDING, RESOLVED

        cur = self.db.execute(
            "UPDATE inbox SET state=?, resolution=?, resolved_at=? WHERE id=? AND state=?",
            (RESOLVED, str(resolution), time.time(), item_id_, PENDING),
        )
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def save_machine(self, profile: dict) -> None:
        """Record what this machine measured. One row, replaced each time: a
        history of benchmarks would be a history of one number that does not
        drift, and the stale one is never the one to act on."""
        self.db.execute(
            "INSERT OR REPLACE INTO machine"
            " (id, cores, ram_total, ram_available, tokens_per_second, load_seconds,"
            "  placement, model, ts) VALUES (1,?,?,?,?,?,?,?,?)",
            (
                profile.get("cores"),
                profile.get("ram_total"),
                profile.get("ram_available"),
                profile.get("tokens_per_second"),
                profile.get("load_seconds"),
                profile.get("placement", ""),
                profile.get("model", ""),
                time.time(),
            ),
        )
        self.db.commit()

    @_locked
    def load_machine(self):
        """The cached profile, or None when nothing has been measured yet.

        None is a real answer the caller must handle — "not measured" is not
        "incapable", and treating it as such would silently stop routing local
        work on machines that were simply never benchmarked."""
        row = self.db.execute("SELECT * FROM machine WHERE id=1").fetchone()
        return dict(row) if row else None

    @_locked
    def save_state(self, company, data: dict) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO state (company, data) VALUES (?,?)",
            (company, json.dumps(data)),
        )
        self.db.commit()

    @_locked
    def load_state(self, company) -> dict:
        row = self.db.execute("SELECT data FROM state WHERE company=?", (company,)).fetchone()
        return json.loads(row["data"]) if row else {}

    # Settings saved from the console. Global, not per company: they are the
    # second layer of corparius/cfg.py, under the real process environment.
    @_locked
    def all_settings(self) -> dict[str, str]:
        from . import secretbox

        rows = self.db.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: secretbox.decrypt_safe(r["value"]) for r in rows}

    @_locked
    def get_setting(self, key) -> str | None:
        from . import secretbox

        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return secretbox.decrypt_safe(row["value"]) if row else None

    @_locked
    def set_setting(self, key, value, secret: bool = False) -> None:
        # Secret values are encrypted at rest when CORP_SECRET_KEY is set;
        # encrypt() is a no-op otherwise, so plaintext stays the default.
        if secret:
            from . import secretbox

            value = secretbox.encrypt(value)
        self.db.execute(
            "INSERT OR REPLACE INTO settings (key, value, secret, updated_at) VALUES (?,?,?,?)",
            (key, value, 1 if secret else 0, time.time()),
        )
        self.db.commit()

    @_locked
    def delete_setting(self, key) -> bool:
        cur = self.db.execute("DELETE FROM settings WHERE key=?", (key,))
        self.db.commit()
        return cur.rowcount > 0

    # Drafts an agent wrote that nothing has published yet. Kept because the
    # alternative — and what happened — is an agent spending the biggest share
    # of a company's tokens writing posts that evaporate on the next tick.
    @_locked
    def add_draft(self, company, kind, channel, body, note="", state="draft") -> int:
        cur = self.db.execute(
            "INSERT INTO drafts (company, kind, channel, body, state, note, ts)"
            " VALUES (?,?,?,?,?,?,?)",
            (company, kind, channel, body, state, note, time.time()),
        )
        self.db.commit()
        return int(cur.lastrowid or 0)

    @_locked
    def list_drafts(self, company, state: str = "", limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM drafts WHERE company=?"
        args: list = [company]
        if state:
            sql += " AND state=?"
            args.append(state)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    @_locked
    def count_drafts(self, company, state: str = "queued") -> int:
        row = self.db.execute(
            "SELECT COUNT(*) n FROM drafts WHERE company=? AND state=?", (company, state)
        ).fetchone()
        return int(row["n"])

    @_locked
    def record_probe(self, provider, model, state, detail="", status=0, ms=0) -> None:
        """Remember what one model did when it was actually called.

        UPSERT rather than INSERT: a model that was cold last week and answers
        today should end up with today's verdict, not two rows disagreeing. The
        knowledge accumulates across runs — the point of keeping it at all is
        not rediscovering the same 404s every time.
        """
        self.db.execute(
            "INSERT INTO model_probes (provider, model, state, detail, status, ms, ts)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(provider, model) DO UPDATE SET"
            " state=excluded.state, detail=excluded.detail, status=excluded.status,"
            " ms=excluded.ms, ts=excluded.ts",
            (provider, model, state, detail, int(status), int(ms), time.time()),
        )
        self.db.commit()

    @_locked
    def record_measurement(self, provider, model, tok_s, json_ok, samples, failures) -> None:
        """Attach performance to a model already proved callable.

        Kept separate from `record_probe` because the two cost different things:
        availability is one small call across a whole catalogue, performance is
        several larger ones and is only worth paying for on models a tier might
        actually be routed to.
        """
        self.db.execute(
            "INSERT INTO model_probes"
            " (provider, model, state, detail, status, ms, ts,"
            "  tok_s, json_ok, samples, failures, measured_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(provider, model) DO UPDATE SET"
            " tok_s=excluded.tok_s, json_ok=excluded.json_ok,"
            " samples=COALESCE(model_probes.samples,0)+excluded.samples,"
            " failures=COALESCE(model_probes.failures,0)+excluded.failures,"
            " measured_at=excluded.measured_at",
            (
                provider,
                model,
                "usable",
                "",
                200,
                0,
                time.time(),
                float(tok_s or 0),
                int(bool(json_ok)),
                int(samples),
                int(failures),
                time.time(),
            ),
        )
        self.db.commit()

    @_locked
    def save_model_catalogue(self, models: dict) -> None:
        """One row, replaced wholesale: it is a snapshot of somebody else's
        catalogue, not a log."""
        self.db.execute(
            "INSERT INTO model_catalogue (id, models, ts) VALUES (1,?,?)"
            " ON CONFLICT(id) DO UPDATE SET models=excluded.models, ts=excluded.ts",
            (json.dumps(models), time.time()),
        )
        self.db.commit()

    @_locked
    def model_catalogue(self) -> dict:
        row = self.db.execute("SELECT models FROM model_catalogue WHERE id=1").fetchone()
        if not row or not row["models"]:
            return {}
        try:
            return json.loads(row["models"])
        except json.JSONDecodeError:
            return {}

    @_locked
    def model_catalogue_ts(self) -> float:
        row = self.db.execute("SELECT ts FROM model_catalogue WHERE id=1").fetchone()
        return float(row["ts"] or 0) if row else 0.0

    @_locked
    def recent_failures(self, company, limit=40) -> list[str]:
        """Outputs of recent actions that did not succeed.

        The CEO reads this to notice a provider falling over instead of watching
        it happen: one real run logged twenty-odd rate limits and nothing
        anywhere reacted.
        """
        rows = self.db.execute(
            "SELECT output FROM actions WHERE company=? AND ok=0 ORDER BY ts DESC LIMIT ?",
            (company, int(limit)),
        ).fetchall()
        return [str(r["output"] or "") for r in rows]

    @_locked
    def week_summary(self, company) -> dict:
        """Seven days of arithmetic: spent against produced.

        The end-of-day summary is a paragraph a model wrote. This can be wrong,
        but it cannot flatter.
        """
        since = time.time() - 7 * 86400
        row = self.db.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END),0) bad"
            " FROM actions WHERE company=? AND ts>=?",
            (company, since),
        ).fetchone()
        # Tokens live in token_usage, not on the action row. Guessing the column
        # name cost fifteen red tests, which is the cheap way to find out.
        spent = self.db.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens),0) tok FROM token_usage"
            " WHERE company=? AND ts>=?",
            (company, since),
        ).fetchone()
        done = self.db.execute(
            "SELECT COUNT(*) n FROM tasks WHERE company=? AND status='done'", (company,)
        ).fetchone()
        return {
            "actions": int(row["n"] or 0),
            "tokens": int(spent["tok"] or 0),
            "failed": int(row["bad"] or 0),
            "done": int(done["n"] or 0),
        }

    @_locked
    def add_decision(self, company, text, why="") -> int:
        """A decision, kept apart from a fact.

        `remember` stores "customers value the privacy of the voice model" —
        an observation. "We stop cold emailing until the prototype ships" is a
        different kind of thing, and a CEO that cannot tell them apart rewrites
        its own strategy every twelve hours. One real run produced three
        contradicting "absolute priorities" in three hours.
        """
        cur = self.db.execute(
            "INSERT INTO decisions (company, text, why, ts) VALUES (?,?,?,?)",
            (company, str(text)[:400], str(why)[:400], time.time()),
        )
        self.db.commit()
        return int(cur.lastrowid or 0)

    @_locked
    def list_decisions(self, company, limit=6) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM decisions WHERE company=? ORDER BY ts DESC LIMIT ?",
            (company, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def add_directive(self, company, kind, target, note="") -> int:
        """Record a standing instruction. Replaces any live one for the same
        (kind, target): "pause social" said twice is one instruction, and the
        second saying should not leave the first to be revoked separately."""
        self.db.execute(
            "UPDATE directives SET active=0 WHERE company=? AND kind=? AND target=? AND active=1",
            (company, kind, target),
        )
        cur = self.db.execute(
            "INSERT INTO directives (company, kind, target, note, active, ts) VALUES (?,?,?,?,1,?)",
            (company, kind, target, note, time.time()),
        )
        self.db.commit()
        return int(cur.lastrowid or 0)

    @_locked
    def directives(self, company, kind="") -> list[dict]:
        q = "SELECT * FROM directives WHERE company=? AND active=1"
        args: list = [company]
        if kind:
            q += " AND kind=?"
            args.append(kind)
        return [dict(r) for r in self.db.execute(q + " ORDER BY ts DESC", args).fetchall()]

    @_locked
    def clear_directive(self, directive_id) -> bool:
        cur = self.db.execute("UPDATE directives SET active=0 WHERE id=?", (directive_id,))
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def known_probes(self, provider: str = "") -> list[dict]:
        """Everything ever proved, newest verdict per (provider, model)."""
        q = "SELECT * FROM model_probes"
        args: list = []
        if provider:
            q += " WHERE provider=?"
            args.append(provider)
        rows = self.db.execute(q + " ORDER BY provider, model", args).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def count_unpublished(self, company) -> int:
        """Everything written and not yet out: `draft` and `queued` together.

        Counting only `queued` let the operator publish the newest post — which
        is usually still in `draft`, written after the last schedule_post — and
        watch the queue not move. The agent stayed stood down and nothing they
        did released it.
        """
        row = self.db.execute(
            "SELECT COUNT(*) n FROM drafts WHERE company=? AND state IN ('draft','queued')",
            (company,),
        ).fetchone()
        return int(row["n"])

    @_locked
    def set_draft_state(self, draft_id: int, state: str, note: str = "") -> bool:
        cur = self.db.execute(
            "UPDATE drafts SET state=?, note=COALESCE(NULLIF(?,''), note),"
            " published_at=CASE WHEN ?='published' THEN ? ELSE published_at END"
            " WHERE id=?",
            (state, note, state, time.time(), draft_id),
        )
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def secret_rows(self) -> list[dict]:
        """Every stored secret, with whether it is currently ciphertext.

        The count is the honest answer to "is encryption actually on here?" —
        turning it on only affects the next write, so a store can have the
        passphrase set and still hold plaintext keys.
        """
        from . import secretbox

        rows = self.db.execute("SELECT key, value, secret FROM settings").fetchall()
        from .settings_spec import SECRETS

        out = []
        for row in rows:
            if not (row["secret"] or row["key"] in SECRETS):
                continue
            out.append(
                {
                    "key": row["key"],
                    "encrypted": secretbox.is_encrypted(row["value"] or ""),
                    "empty": not (row["value"] or ""),
                }
            )
        return out

    @_locked
    def rewrite_secrets(self, to_encrypted: bool) -> list[str]:
        """Bring every stored secret to ciphertext, or back to plaintext.

        Without this, `CORP_SECRET_KEY` only ever protected the *next* write:
        an operator who turned encryption on still had every existing key in
        the clear, and a backup still had to blank them. Which made the setting
        look like it did something it did not do yet.

        Returns the names it changed. Empty values are skipped — there is
        nothing to protect, and encrypting "" would only make it unreadable.
        """
        from . import secretbox

        changed: list[str] = []
        for row in self.secret_rows.__wrapped__(self):  # already holding the lock
            if row["empty"]:
                continue
            if row["encrypted"] == to_encrypted:
                continue
            stored = self.db.execute(
                "SELECT value FROM settings WHERE key=?", (row["key"],)
            ).fetchone()["value"]
            plain = secretbox.decrypt(stored) if secretbox.is_encrypted(stored) else stored
            value = secretbox.encrypt(plain) if to_encrypted else plain
            self.db.execute(
                "UPDATE settings SET value=?, secret=1, updated_at=? WHERE key=?",
                (value, time.time(), row["key"]),
            )
            changed.append(row["key"])
        self.db.commit()
        return changed

    # Outreach we sent, so a reply can be recognised as a reply. Without this
    # the company emails prospects and never learns whether anyone answered,
    # which is the one signal it exists to chase.
    @_locked
    def record_outreach(self, company, email, message_id="", subject="") -> None:
        self.db.execute(
            "INSERT INTO outreach (company, email, message_id, subject, ts) VALUES (?,?,?,?,?)",
            (company, (email or "").strip().lower(), message_id, subject, time.time()),
        )
        self.db.commit()

    @_locked
    def pending_outreach(self, company) -> dict[str, dict]:
        """Addresses we wrote to that have not answered, newest send per address."""
        rows = self.db.execute(
            "SELECT email, MAX(ts) ts, subject FROM outreach "
            "WHERE company=? AND replied_at IS NULL AND email<>'' GROUP BY email",
            (company,),
        ).fetchall()
        return {r["email"]: dict(r) for r in rows}

    @_locked
    def mark_replied(self, company, email, snippet="") -> int:
        cur = self.db.execute(
            "UPDATE outreach SET replied_at=?, reply_snippet=? "
            "WHERE company=? AND email=? AND replied_at IS NULL",
            (time.time(), (snippet or "")[:400], company, (email or "").strip().lower()),
        )
        self.db.commit()
        return cur.rowcount

    @_locked
    def outreach_stats(self, company) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*) sent, COUNT(replied_at) replied FROM outreach WHERE company=?",
            (company,),
        ).fetchone()
        sent, replied = row["sent"], row["replied"]
        return {
            "sent": sent,
            "replied": replied,
            "reply_rate": round(replied / sent, 3) if sent else 0.0,
        }

    @_locked
    def purge_company(self, company) -> dict[str, int]:
        """Drop everything recorded for one company. Only ever called with an
        explicit confirmation from the operator; the config itself is moved to
        companies/.trash rather than deleted."""
        removed = {}
        for table in ("actions", "token_usage", "approvals", "tasks", "state", "outreach"):
            cur = self.db.execute(f"DELETE FROM {table} WHERE company=?", (company,))
            removed[table] = cur.rowcount
        self.db.commit()
        return removed

    @_locked
    def status(self, company) -> dict:
        actions = self.db.execute(
            "SELECT COUNT(*) n FROM actions WHERE company=?", (company,)
        ).fetchone()["n"]
        by_agent = self.db.execute(
            "SELECT agent, COUNT(*) n FROM actions WHERE company=? GROUP BY agent", (company,)
        ).fetchall()
        tokens = self.db.execute(
            "SELECT COALESCE(SUM(input_tokens+output_tokens),0) t FROM token_usage WHERE company=?",
            (company,),
        ).fetchone()["t"]
        return {
            "actions": actions,
            "by_agent": {r["agent"]: r["n"] for r in by_agent},
            "tokens": tokens,
            "pending_approvals": len(self.list_approvals(company, "pending")),
            "open_tasks": len(self.list_tasks(company, "approved")),
        }

    @_locked
    def add_task(
        self,
        company,
        title,
        target,
        priority=2,
        status="approved",
        created_by="ceo",
        note="",
        tool="",
        why="",
    ) -> int:
        cur = self.db.execute(
            "INSERT INTO tasks"
            " (company, title, target, priority, status, created_by, note, tool, why, ts)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (company, title, target, priority, status, created_by, note, tool, why, time.time()),
        )
        self.db.commit()
        assert cur.lastrowid is not None  # always set after an AUTOINCREMENT insert
        return cur.lastrowid

    @_locked
    def list_tasks(self, company, status=None) -> list[dict]:
        if status:
            rows = self.db.execute(
                "SELECT * FROM tasks WHERE company=? AND status=? ORDER BY priority DESC, ts",
                (company, status),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM tasks WHERE company=? ORDER BY status, priority DESC, ts", (company,)
            ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def claim_next_task(self, company, target):
        row = self.db.execute(
            "SELECT * FROM tasks WHERE company=? AND target=? AND status='approved'"
            " ORDER BY priority DESC, ts ASC LIMIT 1",
            (company, target),
        ).fetchone()
        if row is None:
            return None
        self.db.execute("UPDATE tasks SET status='in_progress' WHERE id=?", (row["id"],))
        self.db.commit()
        return dict(row)

    @_locked
    def complete_task(self, task_id, note="") -> None:
        self.db.execute("UPDATE tasks SET status='done', note=? WHERE id=?", (note, task_id))
        self.db.commit()

    @_locked
    def set_task_status(self, task_id, status, note="") -> None:
        self.db.execute("UPDATE tasks SET status=?, note=? WHERE id=?", (status, note, task_id))
        self.db.commit()

    @_locked
    def park_task(self, task_id, blocker_id: str, kind: str = "approval") -> None:
        """Hold a task aside until a named approval is decided, or a named
        question answered.

        `waiting` is deliberately not a status claim_next_task looks at, so the
        agent that parked it moves straight on to the next task instead of
        picking the same blocked one up again every turn."""
        self.db.execute(
            "UPDATE tasks SET status='waiting', note=? WHERE id=?",
            (f"{kind}:{blocker_id}", task_id),
        )
        self.db.commit()

    @_locked
    def release_waiting_tasks(self, company) -> dict:
        """Put parked tasks back in play once the operator has answered.

        Polled rather than pushed on purpose: an approval can be decided from
        the console, the CLI or an MCP host, and a run can be restarted between
        the question and the answer. Reading the answer back is the only version
        of this that works from all of them."""
        released = 0
        refused = 0
        for task in self.db.execute(
            "SELECT id, note FROM tasks WHERE company=? AND status='waiting'", (company,)
        ).fetchall():
            note = str(task["note"] or "")
            # Two things can hold a task: an approval ("may I") and a question
            # ("what should I use"). Both park it the same way, so both have to
            # release it, or an answered question would leave its task parked
            # for good.
            if note.startswith("approval:"):
                row = self.db.execute(
                    "SELECT status FROM approvals WHERE id=?", (note[len("approval:") :],)
                ).fetchone()
            elif note.startswith("question:"):
                answered = self.db.execute(
                    "SELECT state FROM inbox WHERE id=?", (note[len("question:") :],)
                ).fetchone()
                # An answered question is a go-ahead: the operator supplied what
                # was missing, so the task returns to the queue rather than
                # being closed. There is no "refused" for a question.
                row = (
                    {"status": "approved" if answered["state"] == "resolved" else "pending"}
                    if answered
                    else None
                )
            else:
                continue
            if row is None or row["status"] == "pending":
                continue
            if row["status"] == "approved":
                self.db.execute(
                    "UPDATE tasks SET status='approved', note='approved, back in the queue'"
                    " WHERE id=?",
                    (task["id"],),
                )
                released += 1
            else:
                self.db.execute(
                    "UPDATE tasks SET status='rejected', note='refused by the operator' WHERE id=?",
                    (task["id"],),
                )
                refused += 1
        self.db.commit()
        return {"released": released, "refused": refused}

    @_locked
    def update_task(self, task_id, **fields) -> None:
        allowed = {"title", "target", "priority", "note", "status", "tool"}
        items = [(k, v) for k, v in fields.items() if k in allowed]
        if not items:
            return
        sets = ", ".join(f"{k}=?" for k, _ in items)
        self.db.execute(f"UPDATE tasks SET {sets} WHERE id=?", [v for _, v in items] + [task_id])
        self.db.commit()

    @_locked
    def wip_count(self, company, target) -> int:
        return self.db.execute(
            "SELECT COUNT(*) n FROM tasks WHERE company=? AND target=?"
            " AND status IN ('approved','in_progress')",
            (company, target),
        ).fetchone()["n"]

    @_locked
    def flow_metrics(self, company) -> dict:
        rows = self.list_tasks(company)
        done = [t for t in rows if t["status"] == "done"]
        wip = [t for t in rows if t["status"] in ("approved", "in_progress")]
        # Blocked work is counted apart from WIP rather than folded into it. It
        # is genuinely in flight, so hiding it would flatter the board; but
        # charging it against the pull limit would let four unanswered
        # approvals stop the company from starting anything else, which is the
        # opposite of what parking a task is for.
        blocked = [t for t in rows if t["status"] == "waiting"]
        by_target: dict[str, int] = {}
        for t in wip:
            by_target[t["target"]] = by_target.get(t["target"], 0) + 1
        bottleneck = max(by_target, key=by_target.__getitem__) if by_target else None
        st = self.status(company)
        defects = self.db.execute(
            "SELECT COUNT(*) n FROM actions WHERE company=? AND ok=0", (company,)
        ).fetchone()["n"]
        return {
            "throughput": len(done),
            "wip": len(wip),
            "blocked": len(blocked),
            "by_target": by_target,
            "bottleneck": bottleneck,
            "waiting": st["pending_approvals"],
            "defects": defects,
            "tokens_per_completed_task": round(st["tokens"] / len(done)) if done else 0,
        }
