"""Requests waiting on a human, and the answers given."""

from __future__ import annotations

import json

from .base import Connected, _locked


class ApprovalsMixin(Connected):
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
        # The tie matters here too: two identical requests in one clock tick and this picks
        # which one a decision lands on. See `store/jobs.py:list_jobs`.
        q += " ORDER BY ts DESC, rowid DESC LIMIT 1"
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
    def decided_approvals(self, company) -> int:
        """How many approvals this company's operator has actually answered.

        The durable answer to "has a human ever decided anything here", and it exists because the
        shipped page kept that in `localStorage` — so it was lost on a new browser and invisible to a
        phone. The onboarding thread's third step is exactly this question.

        **Approvals, not tasks**, and the page's own comment says why: the company completing its own
        work is not the human deciding, so a done task must never tick that step off. Approvals are
        different — `set_approval_status` has exactly two callers and both are the operator, one
        pressing the button and one asking the CEO to in the chat ("approved in the CEO chat"). Nothing
        automatic moves an approval off `pending`.
        """
        row = self.db.execute(
            "SELECT COUNT(*) n FROM approvals WHERE company=? AND status<>'pending'", (company,)
        ).fetchone()
        return int(row["n"])

    @_locked
    def set_approval_status(self, approval_id, status, note="") -> bool:
        cur = self.db.execute(
            "UPDATE approvals SET status=?, note=? WHERE id=?", (status, note, approval_id)
        )
        self.db.commit()
        return cur.rowcount > 0
