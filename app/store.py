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
"""


class Store:
    def __init__(self, data_path: str):
        os.makedirs(data_path, exist_ok=True)
        self.path = os.path.join(data_path, "corparius.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

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
        }
