"""The safety firewall: a hard token ceiling, semantic loop detection, and a
spend-velocity circuit breaker. These run in front of every agent turn so a
divergent agent cannot burn the budget or stutter forever.

All three are policy, and that is the whole content of this module now: `cosine` and
`hash_embed` moved to `kernel/vectors.py`, because they are arithmetic with no opinion in
them — and because keeping them here forced `store` to import a domain module for a
bag-of-tokens vector.
"""

from __future__ import annotations

import time
from collections import deque

from .kernel.vectors import cosine


class BudgetExceeded(Exception):
    """Raised when a session would cross its token ceiling."""


class TokenBudget:
    """A hard per-session ceiling. Check before an LLM call, record after it.

    Two ceilings, not one. Tokens are the ceiling that always applies, because
    every provider reports them. Money is the ceiling an operator actually cares
    about, and it only applies where a provider reports a cost — so it is opt-in
    (`max_cost=0` disables it) rather than a silent second way for a run to stop.

    **A role may have its own ceiling, and then it also has that much reserved.**
    One shared pool means the frequent role spends it and the rare one arrives to a
    closed till: design runs once every 24 ticks, support every 3, and design's turn
    is the most expensive in the company because it reads and reviews four real
    pages. Measured on a real week, 830 069 tokens against a 120 000 session
    ceiling, with support's turns landing first.

    So `reserves` is two things at once, deliberately: a ceiling for the named role
    and a floor nobody else can spend. Roles with no entry share what is left. The
    session ceiling still stops a runaway — it is raised to cover the reserves,
    because a reserve the session cannot pay for is a reserve that does nothing, and
    silently ignoring it would be the declared-but-not-honoured shape again.
    """

    def __init__(self, max_tokens: int, max_cost: float = 0.0, reserves: dict | None = None):
        self.reserves = {str(k): max(0, int(v)) for k, v in (reserves or {}).items() if int(v) > 0}
        # A reserve is a purse **in addition to** the shared budget, not a slice
        # taken out of it. The first version subtracted, and a 400 000 reserve
        # against a 120 000 session left the shared pool at zero — every other role
        # starved instantly, which is the opposite of what asking for one role to
        # have more can possibly mean. Measured the moment it ran.
        self.shared_max = max(0, max_tokens)
        self.max_tokens = self.shared_max + sum(self.reserves.values())
        self.max_cost = max(0.0, max_cost)
        self.used = 0
        self.spent = 0.0
        self.by_role: dict[str, int] = {}

    def _ledger(self, role: str) -> tuple[int, int, str]:
        """(used, ceiling, label) for whichever ledger this role spends from.

        A reserved role spends from its own purse; everybody else shares the session
        budget, which is why the shared figure subtracts what the reserved roles
        have spent — otherwise their spending would count twice.
        """
        if role in self.reserves:
            return self.by_role.get(role, 0), self.reserves[role], f"{role} budget"
        shared = self.used - sum(self.by_role.get(r, 0) for r in self.reserves)
        return max(0, shared), self.shared_max, "token budget"

    def check_before(self, estimate: int = 0, role: str = "") -> None:
        if self.used + estimate >= self.max_tokens:
            raise BudgetExceeded(f"token budget spent: {self.used}/{self.max_tokens}")
        if role or self.reserves:
            used, ceiling, label = self._ledger(role)
            if used + estimate >= ceiling:
                raise BudgetExceeded(f"{label} spent: {used}/{ceiling}")
        if self.max_cost and self.spent >= self.max_cost:
            raise BudgetExceeded(f"cost budget spent: {self.spent:.4f}/{self.max_cost:.4f}")

    def record_usage(
        self, input_tokens: int, output_tokens: int, cost: float = 0.0, role: str = ""
    ) -> None:
        total = max(0, input_tokens) + max(0, output_tokens)
        self.used += total
        self.spent += max(0.0, cost)
        if role:
            self.by_role[role] = self.by_role.get(role, 0) + total

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used)

    def remaining_for(self, role: str) -> int:
        used, ceiling, _ = self._ledger(role)
        return max(0, min(ceiling - used, self.remaining))


class LoopGuard:
    """Suspends an agent that stutters: near-identical outputs across a window,
    or the same tool called with identical parameters too many times in a row.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.95,
        window: int = 3,
        max_identical_calls: int = 2,
    ):
        self.threshold = similarity_threshold
        self.window = window
        self.max_identical_calls = max_identical_calls
        self._embeddings: deque[list[float]] = deque(maxlen=window)
        self._last_call: tuple | None = None
        self._identical_streak = 0

    def observe_output(self, embedding: list[float]) -> bool:
        """Record an output embedding. True if the last `window` outputs are all
        mutually similar past the threshold (a semantic stutter loop)."""
        self._embeddings.append(embedding)
        if len(self._embeddings) < self.window:
            return False
        pairs = list(self._embeddings)
        sims = [cosine(pairs[i], pairs[i + 1]) for i in range(len(pairs) - 1)]
        return all(s >= self.threshold for s in sims)

    def observe_tool_call(self, name: str, parameters: dict) -> bool:
        """Record a tool call. True once the same call repeats past the limit."""
        key = (name, repr(sorted(parameters.items())))
        if key == self._last_call:
            self._identical_streak += 1
        else:
            self._last_call = key
            self._identical_streak = 1
        return self._identical_streak > self.max_identical_calls


class CircuitBreaker:
    """Watches token-spend velocity over a rolling 60s window and escalates the
    operating mode NORMAL -> CONSERVATEUR -> SECURISE when it runs hot."""

    NORMAL, CONSERVATIVE, SAFE = "NORMAL", "CONSERVATEUR", "SECURISE"

    def __init__(self, tokens_per_minute_limit: int = 10000):
        self.limit = tokens_per_minute_limit
        self.mode = self.NORMAL
        self._events: deque[tuple[float, int]] = deque()

    def record(self, tokens: int, now: float | None = None) -> str:
        now = time.time() if now is None else now
        self._events.append((now, tokens))
        cutoff = now - 60.0
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
        rate = sum(t for _, t in self._events)
        if rate > self.limit:
            # Escalate, never step back down while still over the limit. The
            # previous form was `SAFE if mode == CONSERVATIVE else CONSERVATIVE`,
            # which flipped SAFE back to CONSERVATEUR on the very next call: the
            # mode an agent ended a turn in depended on whether it had spent an
            # odd or an even number of times, and a session that had already
            # earned a freeze could talk itself out of one by burning more
            # tokens. Adding one tool to a playbook was enough to move the
            # parity and stop a runaway day from freezing.
            self.mode = self.CONSERVATIVE if self.mode == self.NORMAL else self.SAFE
        else:
            self.mode = self.NORMAL
        return self.mode

    @property
    def tripped(self) -> bool:
        return self.mode != self.NORMAL
