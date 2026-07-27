"""SQLite persistence: actions, token usage, approvals, memory, and per-company state."""

from __future__ import annotations

import functools
import json
import os
import sqlite3
import threading
import time

from .safety import cosine, hash_embed

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, agent TEXT, tool TEXT, parameters TEXT,
    output TEXT, ok INTEGER, ts REAL
);
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, agent TEXT, input_tokens INTEGER, output_tokens INTEGER, ts REAL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    company TEXT, agent TEXT, tool TEXT, parameters TEXT,
    status TEXT, note TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS state (
    company TEXT PRIMARY KEY, data TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, title TEXT, target TEXT, priority INTEGER,
    status TEXT, created_by TEXT, note TEXT, ts REAL, tool TEXT
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
"""

# Bump this and add a migration below whenever the schema changes in a way that
# an existing store must be brought forward through. The version is tracked in
# the database itself via `PRAGMA user_version`, so an upgrade migrates in place
# instead of relying on the operator to back up and recreate.
SCHEMA_VERSION = 3


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


# version -> callable(db). Applied in order for any version above the DB's own.
MIGRATIONS = {1: _migration_1, 2: _migration_2, 3: _migration_3}


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
    def record_usage(self, company, agent, input_tokens, output_tokens) -> None:
        self.db.execute(
            "INSERT INTO token_usage (company, agent, input_tokens, output_tokens, ts)"
            " VALUES (?,?,?,?,?)",
            (company, agent, input_tokens, output_tokens, time.time()),
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
        rows = self.db.execute(
            "SELECT agent, COALESCE(SUM(input_tokens+output_tokens),0) t "
            "FROM token_usage WHERE company=? GROUP BY agent ORDER BY t DESC",
            (company,),
        ).fetchall()
        return [dict(r) for r in rows]

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
            " (id, company, agent, tool, parameters, status, note, ts) VALUES (?,?,?,?,?,?,?,?)",
            (
                req.id,
                req.company,
                req.agent,
                req.tool,
                json.dumps(req.parameters),
                req.status,
                req.note,
                req.ts,
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
    ) -> int:
        cur = self.db.execute(
            "INSERT INTO tasks (company, title, target, priority, status, created_by, note, tool, ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (company, title, target, priority, status, created_by, note, tool, time.time()),
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
    def park_task(self, task_id, approval_id: str) -> None:
        """Hold a task aside until a named approval is decided.

        `waiting` is deliberately not a status claim_next_task looks at, so the
        agent that parked it moves straight on to the next task instead of
        picking the same blocked one up again every turn."""
        self.db.execute(
            "UPDATE tasks SET status='waiting', note=? WHERE id=?",
            (f"approval:{approval_id}", task_id),
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
            if not note.startswith("approval:"):
                continue
            row = self.db.execute(
                "SELECT status FROM approvals WHERE id=?", (note[len("approval:") :],)
            ).fetchone()
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
