"""SQLite persistence: actions, token usage, approvals, and per-company state."""
from __future__ import annotations
import json
import os
import sqlite3
import time

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
"""

# Bump this and add a migration below whenever the schema changes in a way that
# an existing store must be brought forward through. The version is tracked in
# the database itself via `PRAGMA user_version`, so an upgrade migrates in place
# instead of relying on the operator to back up and recreate.
SCHEMA_VERSION = 1


def _migration_1(db: sqlite3.Connection) -> None:
    """Stores created before the CEO wired tasks to executable tools lack the
    tasks.tool column. Guarded so it is a no-op on fresh DBs (the column is in
    SCHEMA) and on re-runs."""
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN tool TEXT")
    except sqlite3.OperationalError:
        pass


# version -> callable(db). Applied in order for any version above the DB's own.
MIGRATIONS = {1: _migration_1}


class Store:
    def __init__(self, data_path: str):
        os.makedirs(data_path, exist_ok=True)
        try:  # the store holds API keys in the clear; keep the dir owner-only
            if os.name != "nt":
                os.chmod(data_path, 0o700)   # effective on POSIX, a no-op on Windows
        except OSError:
            pass
        self.path = os.path.join(data_path, "corparius.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        try:  # the settings table holds API keys in the clear; owner only
            os.chmod(self.path, 0o600)   # effective on POSIX, a no-op on Windows
        except OSError:
            pass
        self._migrate()

    def _migrate(self) -> None:
        """Bring the store from its recorded version up to SCHEMA_VERSION, one
        step at a time, recording progress so an interrupted upgrade resumes."""
        current = self.db.execute("PRAGMA user_version").fetchone()[0]
        for version in range(current + 1, SCHEMA_VERSION + 1):
            MIGRATIONS[version](self.db)
            self.db.execute(f"PRAGMA user_version = {int(version)}")
            self.db.commit()

    def schema_version(self) -> int:
        return self.db.execute("PRAGMA user_version").fetchone()[0]

    def record_action(self, company, agent, tool, parameters, output, ok) -> None:
        self.db.execute(
            "INSERT INTO actions (company, agent, tool, parameters, output, ok, ts)"
            " VALUES (?,?,?,?,?,?,?)",
            (company, agent, tool, json.dumps(parameters), output, int(ok), time.time()),
        )
        self.db.commit()

    def record_usage(self, company, agent, input_tokens, output_tokens) -> None:
        self.db.execute(
            "INSERT INTO token_usage (company, agent, input_tokens, output_tokens, ts)"
            " VALUES (?,?,?,?,?)",
            (company, agent, input_tokens, output_tokens, time.time()),
        )
        self.db.commit()

    def recent_outputs(self, company, tool, limit=3) -> list[str]:
        rows = self.db.execute(
            "SELECT output FROM actions WHERE company=? AND tool=? AND ok=1"
            " ORDER BY ts DESC LIMIT ?", (company, tool, limit)).fetchall()
        return [r["output"] for r in rows]

    def add_approval(self, req) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO approvals"
            " (id, company, agent, tool, parameters, status, note, ts) VALUES (?,?,?,?,?,?,?,?)",
            (req.id, req.company, req.agent, req.tool, json.dumps(req.parameters),
             req.status, req.note, req.ts),
        )
        self.db.commit()

    def find_approval(self, company, tool, parameters, status=None):
        q = "SELECT * FROM approvals WHERE company=? AND tool=? AND parameters=?"
        args = [company, tool, json.dumps(parameters)]
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY ts DESC LIMIT 1"
        row = self.db.execute(q, args).fetchone()
        return dict(row) if row else None

    def list_approvals(self, company, status="pending"):
        rows = self.db.execute(
            "SELECT * FROM approvals WHERE company=? AND status=? ORDER BY ts",
            (company, status),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_approval_status(self, approval_id, status, note="") -> bool:
        cur = self.db.execute(
            "UPDATE approvals SET status=?, note=? WHERE id=?", (status, note, approval_id)
        )
        self.db.commit()
        return cur.rowcount > 0

    def save_state(self, company, data: dict) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO state (company, data) VALUES (?,?)",
            (company, json.dumps(data)),
        )
        self.db.commit()

    def load_state(self, company) -> dict:
        row = self.db.execute("SELECT data FROM state WHERE company=?", (company,)).fetchone()
        return json.loads(row["data"]) if row else {}

    # Settings saved from the console. Global, not per company: they are the
    # second layer of app/cfg.py, under the real process environment.
    def all_settings(self) -> dict[str, str]:
        from . import secretbox
        rows = self.db.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: secretbox.decrypt_safe(r["value"]) for r in rows}

    def get_setting(self, key) -> str | None:
        from . import secretbox
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return secretbox.decrypt_safe(row["value"]) if row else None

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

    def delete_setting(self, key) -> bool:
        cur = self.db.execute("DELETE FROM settings WHERE key=?", (key,))
        self.db.commit()
        return cur.rowcount > 0

    # Outreach we sent, so a reply can be recognised as a reply. Without this
    # the company emails prospects and never learns whether anyone answered,
    # which is the one signal it exists to chase.
    def record_outreach(self, company, email, message_id="", subject="") -> None:
        self.db.execute(
            "INSERT INTO outreach (company, email, message_id, subject, ts) VALUES (?,?,?,?,?)",
            (company, (email or "").strip().lower(), message_id, subject, time.time()),
        )
        self.db.commit()

    def pending_outreach(self, company) -> dict[str, dict]:
        """Addresses we wrote to that have not answered, newest send per address."""
        rows = self.db.execute(
            "SELECT email, MAX(ts) ts, subject FROM outreach "
            "WHERE company=? AND replied_at IS NULL AND email<>'' GROUP BY email",
            (company,)).fetchall()
        return {r["email"]: dict(r) for r in rows}

    def mark_replied(self, company, email, snippet="") -> int:
        cur = self.db.execute(
            "UPDATE outreach SET replied_at=?, reply_snippet=? "
            "WHERE company=? AND email=? AND replied_at IS NULL",
            (time.time(), (snippet or "")[:400], company, (email or "").strip().lower()),
        )
        self.db.commit()
        return cur.rowcount

    def outreach_stats(self, company) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*) sent, COUNT(replied_at) replied FROM outreach WHERE company=?",
            (company,)).fetchone()
        sent, replied = row["sent"], row["replied"]
        return {"sent": sent, "replied": replied,
                "reply_rate": round(replied / sent, 3) if sent else 0.0}

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

    def add_task(self, company, title, target, priority=2, status="approved",
                 created_by="ceo", note="", tool="") -> int:
        cur = self.db.execute(
            "INSERT INTO tasks (company, title, target, priority, status, created_by, note, tool, ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (company, title, target, priority, status, created_by, note, tool, time.time()))
        self.db.commit()
        return cur.lastrowid

    def list_tasks(self, company, status=None) -> list[dict]:
        if status:
            rows = self.db.execute(
                "SELECT * FROM tasks WHERE company=? AND status=? ORDER BY priority DESC, ts",
                (company, status)).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM tasks WHERE company=? ORDER BY status, priority DESC, ts",
                (company,)).fetchall()
        return [dict(r) for r in rows]

    def claim_next_task(self, company, target):
        row = self.db.execute(
            "SELECT * FROM tasks WHERE company=? AND target=? AND status='approved'"
            " ORDER BY priority DESC, ts ASC LIMIT 1", (company, target)).fetchone()
        if row is None:
            return None
        self.db.execute("UPDATE tasks SET status='in_progress' WHERE id=?", (row["id"],))
        self.db.commit()
        return dict(row)

    def complete_task(self, task_id, note="") -> None:
        self.db.execute("UPDATE tasks SET status='done', note=? WHERE id=?", (note, task_id))
        self.db.commit()

    def set_task_status(self, task_id, status, note="") -> None:
        self.db.execute("UPDATE tasks SET status=?, note=? WHERE id=?", (status, note, task_id))
        self.db.commit()

    def update_task(self, task_id, **fields) -> None:
        allowed = {"title", "target", "priority", "note", "status", "tool"}
        items = [(k, v) for k, v in fields.items() if k in allowed]
        if not items:
            return
        sets = ", ".join(f"{k}=?" for k, _ in items)
        self.db.execute(f"UPDATE tasks SET {sets} WHERE id=?",
                        [v for _, v in items] + [task_id])
        self.db.commit()

    def wip_count(self, company, target) -> int:
        return self.db.execute(
            "SELECT COUNT(*) n FROM tasks WHERE company=? AND target=?"
            " AND status IN ('approved','in_progress')", (company, target)).fetchone()["n"]

    def flow_metrics(self, company) -> dict:
        rows = self.list_tasks(company)
        done = [t for t in rows if t["status"] == "done"]
        wip = [t for t in rows if t["status"] in ("approved", "in_progress")]
        by_target: dict = {}
        for t in wip:
            by_target[t["target"]] = by_target.get(t["target"], 0) + 1
        bottleneck = max(by_target, key=by_target.get) if by_target else None
        st = self.status(company)
        defects = self.db.execute(
            "SELECT COUNT(*) n FROM actions WHERE company=? AND ok=0", (company,)).fetchone()["n"]
        return {"throughput": len(done), "wip": len(wip), "by_target": by_target,
                "bottleneck": bottleneck, "waiting": st["pending_approvals"], "defects": defects,
                "tokens_per_completed_task": round(st["tokens"] / len(done)) if done else 0}
