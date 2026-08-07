"""Who was written to, and whether they replied."""

from __future__ import annotations

import time

from .base import Connected, _locked


class OutreachMixin(Connected):
    # Outreach we sent, so a reply can be recognised as a reply. Without this
    # the company emails prospects and never learns whether anyone answered,
    # which is the one signal it exists to chase.
    @_locked
    def record_outreach(self, company, email, message_id="", subject="") -> None:
        self.db.execute(
            "INSERT INTO outreach (company, email, message_id, subject, ts) VALUES (?,?,?,?,?)",
            (company, (email or "").strip().lower(), message_id, subject, time.time()),
        )
        self.db.commit()

    @_locked
    def pending_outreach(self, company) -> dict[str, dict]:
        """Addresses we wrote to that have not answered, newest send per address."""
        rows = self.db.execute(
            "SELECT email, MAX(ts) ts, subject FROM outreach "
            "WHERE company=? AND replied_at IS NULL AND email<>'' GROUP BY email",
            (company,),
        ).fetchall()
        return {r["email"]: dict(r) for r in rows}

    @_locked
    def mark_replied(self, company, email, snippet="") -> int:
        cur = self.db.execute(
            "UPDATE outreach SET replied_at=?, reply_snippet=? "
            "WHERE company=? AND email=? AND replied_at IS NULL",
            (time.time(), (snippet or "")[:400], company, (email or "").strip().lower()),
        )
        self.db.commit()
        return cur.rowcount

    @_locked
    def outreach_stats(self, company) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*) sent, COUNT(replied_at) replied FROM outreach WHERE company=?",
            (company,),
        ).fetchone()
        sent, replied = row["sent"], row["replied"]
        return {
            "sent": sent,
            "replied": replied,
            "reply_rate": round(replied / sent, 3) if sent else 0.0,
        }
