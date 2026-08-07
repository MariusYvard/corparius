"""The providers' own description of their models, cached."""

from __future__ import annotations

import json
import time

from .base import Connected, _locked


class ModelCatalogueMixin(Connected):
    @_locked
    def save_model_catalogue(self, models: dict) -> None:
        """One row, replaced wholesale: it is a snapshot of somebody else's
        catalogue, not a log."""
        self.db.execute(
            "INSERT INTO model_catalogue (id, models, ts) VALUES (1,?,?)"
            " ON CONFLICT(id) DO UPDATE SET models=excluded.models, ts=excluded.ts",
            (json.dumps(models), time.time()),
        )
        self.db.commit()

    @_locked
    def model_catalogue(self) -> dict:
        row = self.db.execute("SELECT models FROM model_catalogue WHERE id=1").fetchone()
        if not row or not row["models"]:
            return {}
        try:
            return json.loads(row["models"])
        except json.JSONDecodeError:
            return {}

    @_locked
    def model_catalogue_ts(self) -> float:
        row = self.db.execute("SELECT ts FROM model_catalogue WHERE id=1").fetchone()
        return float(row["ts"] or 0) if row else 0.0
