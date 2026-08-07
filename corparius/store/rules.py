"""Standing permissions: approve, and stop asking."""

from __future__ import annotations

import time

from .base import Connected, _locked


class RulesMixin(Connected):
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
