"""When each skill last actually reached a prompt."""

from __future__ import annotations

import time

from .base import Connected, _locked


class SkillUsageMixin(Connected):
    @_locked
    def record_skill_use(self, company, names: list[str], now: float | None = None) -> None:
        """These skills reached a prompt. One statement per skill, upserted.

        `now` is a parameter because the only thing that reads this is a decision about age —
        "nothing has used it in thirty days" — and a test of that decision must be able to say
        when, without waiting a month.
        """
        stamp = time.time() if now is None else now
        for name in names:
            self.db.execute(
                "INSERT INTO skill_usage (company, skill, uses, last_used) VALUES (?,?,1,?)"
                " ON CONFLICT(company, skill) DO UPDATE SET"
                " uses = uses + 1, last_used = excluded.last_used",
                (company, name, stamp),
            )
        self.db.commit()

    @_locked
    def skill_usage(self, company) -> dict[str, dict]:
        """{skill name: {uses, last_used}} for one company. What the curator reads."""
        rows = self.db.execute(
            "SELECT skill, uses, last_used FROM skill_usage WHERE company=?", (company,)
        ).fetchall()
        return {r["skill"]: {"uses": r["uses"], "last_used": r["last_used"]} for r in rows}

    @_locked
    def forget_skill_use(self, company, name: str) -> None:
        """Drop the usage row when the skill leaves the live folder.

        Without it, a skill written again under the same name inherits a `last_used` from
        before it was archived and the next sweep archives it immediately — a loop where the
        company keeps answering a question and keeps having the answer taken away.
        """
        self.db.execute("DELETE FROM skill_usage WHERE company=? AND skill=?", (company, name))
        self.db.commit()
