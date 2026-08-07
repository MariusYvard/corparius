"""Reads that span tables, and therefore belong to no single one."""

from __future__ import annotations

import time

from .base import Connected, _locked


class ReportsMixin(Connected):
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
