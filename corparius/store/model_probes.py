"""What a model was measured to do, as opposed to what it claims."""

from __future__ import annotations

import time

from .base import Connected, _locked


class ModelProbesMixin(Connected):
    @_locked
    def record_probe(self, provider, model, state, detail="", status=0, ms=0) -> None:
        """Remember what one model did when it was actually called.

        UPSERT rather than INSERT: a model that was cold last week and answers
        today should end up with today's verdict, not two rows disagreeing. The
        knowledge accumulates across runs — the point of keeping it at all is
        not rediscovering the same 404s every time.
        """
        self.db.execute(
            "INSERT INTO model_probes (provider, model, state, detail, status, ms, ts)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(provider, model) DO UPDATE SET"
            " state=excluded.state, detail=excluded.detail, status=excluded.status,"
            " ms=excluded.ms, ts=excluded.ts",
            (provider, model, state, detail, int(status), int(ms), time.time()),
        )
        self.db.commit()

    @_locked
    def record_measurement(
        self, provider, model, tok_s, json_ok, samples, failures, vision_ok=None
    ) -> None:
        """Attach performance to a model already proved callable.

        Kept separate from `record_probe` because the two cost different things:
        availability is one small call across a whole catalogue, performance is
        several larger ones and is only worth paying for on models a tier might
        actually be routed to.

        `vision_ok` stays None when nobody asked, and a later measurement that did
        not ask must not erase an answer an earlier one got — hence COALESCE on
        that column alone rather than the plain overwrite the others take.
        """
        self.db.execute(
            "INSERT INTO model_probes"
            " (provider, model, state, detail, status, ms, ts,"
            "  tok_s, json_ok, samples, failures, measured_at, vision_ok)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(provider, model) DO UPDATE SET"
            " tok_s=excluded.tok_s, json_ok=excluded.json_ok,"
            " samples=COALESCE(model_probes.samples,0)+excluded.samples,"
            " failures=COALESCE(model_probes.failures,0)+excluded.failures,"
            " measured_at=excluded.measured_at,"
            " vision_ok=COALESCE(excluded.vision_ok, model_probes.vision_ok)",
            (
                provider,
                model,
                "usable",
                "",
                200,
                0,
                time.time(),
                float(tok_s or 0),
                int(bool(json_ok)),
                int(samples),
                int(failures),
                time.time(),
                None if vision_ok is None else int(bool(vision_ok)),
            ),
        )
        self.db.commit()

    @_locked
    def known_probes(self, provider: str = "") -> list[dict]:
        """Everything ever proved, newest verdict per (provider, model)."""
        q = "SELECT * FROM model_probes"
        args: list = []
        if provider:
            q += " WHERE provider=?"
            args.append(provider)
        rows = self.db.execute(q + " ORDER BY provider, model", args).fetchall()
        return [dict(r) for r in rows]
