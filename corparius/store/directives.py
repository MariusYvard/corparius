"""What the operator told the company to stop or start doing."""

from __future__ import annotations

import time

from .base import Connected, _locked


class DirectivesMixin(Connected):
    @_locked
    def add_directive(self, company, kind, target, note="") -> int:
        """Record a standing instruction. Replaces any live one for the same
        (kind, target): "pause social" said twice is one instruction, and the
        second saying should not leave the first to be revoked separately."""
        self.db.execute(
            "UPDATE directives SET active=0 WHERE company=? AND kind=? AND target=? AND active=1",
            (company, kind, target),
        )
        cur = self.db.execute(
            "INSERT INTO directives (company, kind, target, note, active, ts) VALUES (?,?,?,?,1,?)",
            (company, kind, target, note, time.time()),
        )
        self.db.commit()
        return int(cur.lastrowid or 0)

    @_locked
    def directives(self, company, kind="") -> list[dict]:
        q = "SELECT * FROM directives WHERE company=? AND active=1"
        args: list = [company]
        if kind:
            q += " AND kind=?"
            args.append(kind)
        return [dict(r) for r in self.db.execute(q + " ORDER BY ts DESC", args).fetchall()]

    @_locked
    def clear_directive(self, directive_id) -> bool:
        cur = self.db.execute("UPDATE directives SET active=0 WHERE id=?", (directive_id,))
        self.db.commit()
        return cur.rowcount > 0
