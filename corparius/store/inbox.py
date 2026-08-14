"""Typed notices and questions an agent could not otherwise ask."""

from __future__ import annotations

import json
import time

from .base import Connected, _locked


class InboxMixin(Connected):
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
        from ..inbox import PENDING, item_id

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
        from ..inbox import RESOLVED

        row = self.db.execute(
            "SELECT * FROM inbox WHERE company=? AND kind=? AND title=? AND state=?"
            " ORDER BY resolved_at DESC, rowid DESC LIMIT 1",  # see store/jobs.py on the tie
            (company, kind, title, RESOLVED),
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def resolve_inbox(self, item_id_, resolution="") -> bool:
        """First responder wins. A second answer to a decided item returns
        False rather than overwriting: the work that was waiting has already
        moved on the first one, and rewriting the record would leave the store
        disagreeing with what actually happened."""
        from ..inbox import PENDING, RESOLVED

        cur = self.db.execute(
            "UPDATE inbox SET state=?, resolution=?, resolved_at=? WHERE id=? AND state=?",
            (RESOLVED, str(resolution), time.time(), item_id_, PENDING),
        )
        self.db.commit()
        return cur.rowcount > 0
