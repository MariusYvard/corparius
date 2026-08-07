"""Every tool call the company made, and where its drafted content came from."""

from __future__ import annotations

import json
import time

from .base import Connected, _locked


class ActionsMixin(Connected):
    @_locked
    def record_action(self, company, agent, tool, parameters, output, ok, trace=None) -> None:
        """One action, and where its drafted content came from.

        `trace` is a `kernel.records.Trace`, or None for the paths that never called a model —
        a skipped tool, a raised exception, a deterministic write. None leaves the four columns
        NULL, which reads as "not recorded" rather than "no provider answered".

        Not a keyword each caller has to remember: the executor holds the harness result at the
        moment it logs (agents.py) and is the only caller that has one. The other five pass
        nothing and mean it.
        """
        self.db.execute(
            "INSERT INTO actions"
            " (company, agent, tool, parameters, output, ok, ts, source, attempts, fell_back,"
            " errors) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                company,
                agent,
                tool,
                json.dumps(parameters),
                output,
                int(ok),
                time.time(),
                trace.source if trace else None,
                trace.attempts if trace else None,
                int(trace.fell_back) if trace else None,
                trace.errors if trace else None,
            ),
        )
        self.db.commit()

    @_locked
    def recent_outputs(self, company, tool, limit=3) -> list[str]:
        rows = self.db.execute(
            "SELECT output FROM actions WHERE company=? AND tool=? AND ok=1"
            " ORDER BY ts DESC LIMIT ?",
            (company, tool, limit),
        ).fetchall()
        return [r["output"] for r in rows]

    @_locked
    def recent_actions(self, company, limit=25) -> list[dict]:
        rows = self.db.execute(
            "SELECT agent, tool, ok, ts, substr(output,1,160) output,"
            " source, attempts, fell_back, errors FROM actions "
            "WHERE company=? ORDER BY id DESC LIMIT ?",
            (company, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def routing_health(self, company, limit=200) -> dict:
        """Which providers answered the last drafted turns, and how often the chain fell back.

        The reader that makes schema 18 mean something. `_empty_draft` says it at the moment of
        failure and only when a tool calls it; this says it about a *history*, which is the
        thing nobody could see. An operator read "Nothing usable drafted" as a broken site
        generator while groq and cerebras were both answering 429 — the pattern was in the run
        and there was nowhere to look at it.

        NULL `source` rows are excluded, not counted as failures: they are the turns that
        called no model — a skipped tool, a deterministic write — and folding them in would
        make a quiet day look like an outage.
        """
        rows = self.db.execute(
            "SELECT source, fell_back, attempts FROM actions"
            " WHERE company=? AND source IS NOT NULL AND source != ''"
            " ORDER BY id DESC LIMIT ?",
            (company, int(limit)),
        ).fetchall()
        answered: dict[str, int] = {}
        fell_back = retries = 0
        for row in rows:
            answered[row["source"]] = answered.get(row["source"], 0) + 1
            fell_back += 1 if row["fell_back"] else 0
            retries += max(0, (row["attempts"] or 1) - 1)
        return {
            "drafted": len(rows),
            "answered_by": dict(sorted(answered.items(), key=lambda kv: -kv[1])),
            "fell_back": fell_back,
            "retries": retries,
        }

    @_locked
    def count_actions_by_tool(self, company, tool) -> int:
        return self.db.execute(
            "SELECT COUNT(*) n FROM actions WHERE company=? AND tool=?", (company, tool)
        ).fetchone()["n"]

    @_locked
    def recent_failures(self, company, limit=40) -> list[str]:
        """Outputs of recent actions that did not succeed.

        The CEO reads this to notice a provider falling over instead of watching
        it happen: one real run logged twenty-odd rate limits and nothing
        anywhere reacted.
        """
        rows = self.db.execute(
            "SELECT output FROM actions WHERE company=? AND ok=0 ORDER BY ts DESC LIMIT ?",
            (company, int(limit)),
        ).fetchall()
        return [str(r["output"] or "") for r in rows]
