"""The backlog: what the CEO queued and which role claims it."""

from __future__ import annotations

import time

from .base import Connected, _locked


class TasksMixin(Connected):
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
    def get_task(self, task_id) -> dict:
        """One task by id, or {}. The console edits a task by id alone, so it had
        no way to read the row it was about to approve — and approving without
        reading it is how tasks reached an agent with no tool to run."""
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else {}

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
    def roles_with_approved_work(self, company) -> set:
        """Which roles have an approved task waiting, without claiming any of it.

        The scheduler's counterpart to `claim_next_task`. A role can be *held* because the company
        has nothing for it yet — no published page for outreach, no mailbox for support — and a
        filed task is the one thing that outranks that: it is a decision somebody took, and a
        decision that silently never runs is the failure this whole gate exists to avoid, arriving
        from the other side. Read-only on purpose, because deciding who runs must not consume the
        work it is deciding about.
        """
        rows = self.db.execute(
            "SELECT DISTINCT target FROM tasks WHERE company=? AND status='approved'", (company,)
        ).fetchall()
        return {r["target"] for r in rows if r["target"]}

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
