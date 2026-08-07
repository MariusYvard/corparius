"""The measured profile of this machine, one row."""

from __future__ import annotations

import time

from .base import Connected, _locked


class MachineMixin(Connected):
    @_locked
    def save_machine(self, profile: dict) -> None:
        """Record what this machine measured. One row, replaced each time: a
        history of benchmarks would be a history of one number that does not
        drift, and the stale one is never the one to act on."""
        self.db.execute(
            "INSERT OR REPLACE INTO machine"
            " (id, cores, ram_total, ram_available, tokens_per_second, load_seconds,"
            "  placement, model, ts) VALUES (1,?,?,?,?,?,?,?,?)",
            (
                profile.get("cores"),
                profile.get("ram_total"),
                profile.get("ram_available"),
                profile.get("tokens_per_second"),
                profile.get("load_seconds"),
                profile.get("placement", ""),
                profile.get("model", ""),
                time.time(),
            ),
        )
        self.db.commit()

    @_locked
    def load_machine(self):
        """The cached profile, or None when nothing has been measured yet.

        None is a real answer the caller must handle — "not measured" is not
        "incapable", and treating it as such would silently stop routing local
        work on machines that were simply never benchmarked."""
        row = self.db.execute("SELECT * FROM machine WHERE id=1").fetchone()
        return dict(row) if row else None
