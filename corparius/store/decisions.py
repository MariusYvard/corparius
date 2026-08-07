"""What the CEO decided, so it can reread itself."""

from __future__ import annotations

import time

from .base import Connected, _locked


class DecisionsMixin(Connected):
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
