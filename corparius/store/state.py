"""Per-company loop state: which tick it is on."""

from __future__ import annotations

import json

from .base import Connected, _locked


class StateMixin(Connected):
    @_locked
    def save_state(self, company, data: dict) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO state (company, data) VALUES (?,?)",
            (company, json.dumps(data)),
        )
        self.db.commit()

    @_locked
    def load_state(self, company) -> dict:
        row = self.db.execute("SELECT data FROM state WHERE company=?", (company,)).fetchone()
        return json.loads(row["data"]) if row else {}
