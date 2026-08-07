"""What was spent, in tokens and in money."""

from __future__ import annotations

import time

from .base import Connected, _locked


class TokenUsageMixin(Connected):
    @_locked
    def record_usage(self, company, agent, input_tokens, output_tokens, cost=0.0) -> None:
        self.db.execute(
            "INSERT INTO token_usage (company, agent, input_tokens, output_tokens, ts, cost)"
            " VALUES (?,?,?,?,?,?)",
            (company, agent, input_tokens, output_tokens, time.time(), float(cost or 0.0)),
        )
        self.db.commit()

    # Read helpers for the console overview. These live here rather than as raw
    # SQL in corparius/webui.py: with the connection now guarded, a caller reaching
    # into store.db directly would be an unsynchronised access to a locked
    # resource, which is exactly the interleaving _locked exists to prevent.
    @_locked
    def spend_by_agent(self, company) -> list[dict]:
        """Tokens and money side by side. `cost` is 0 for every provider that
        does not report one, so a caller showing it has to know whether any
        provider reported anything at all — see `cost_reported`."""
        rows = self.db.execute(
            "SELECT agent, COALESCE(SUM(input_tokens+output_tokens),0) t, "
            "COALESCE(SUM(cost),0) cost "
            "FROM token_usage WHERE company=? GROUP BY agent ORDER BY t DESC",
            (company,),
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def cost_reported(self, company) -> bool:
        """Whether any call for this company came back with a cost. Without it,
        a total of 0.00 is indistinguishable from a free run, and the console
        would quietly tell an operator on a paid key that they spent nothing."""
        row = self.db.execute(
            "SELECT COUNT(*) n FROM token_usage WHERE company=? AND cost > 0", (company,)
        ).fetchone()
        return row["n"] > 0
