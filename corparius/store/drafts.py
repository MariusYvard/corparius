"""What an agent wrote and nothing has published."""

from __future__ import annotations

import time

from .base import Connected, _locked


class DraftsMixin(Connected):
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
