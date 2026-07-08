"""The safety firewall: a hard token ceiling, semantic loop detection, and a
spend-velocity circuit breaker. These run in front of every agent turn so a
divergent agent cannot burn the budget or stutter forever.
"""
from __future__ import annotations
import hashlib
import math
import time
from collections import deque


class BudgetExceeded(Exception):
    """Raised when a session would cross its token ceiling."""


class TokenBudget:
    """A hard per-session ceiling. Check before an LLM call, record after it."""

    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        self.used = 0

    def check_before(self, estimate: int = 0) -> None:
        if self.used + estimate >= self.max_tokens:
            raise BudgetExceeded(f"token budget spent: {self.used}/{self.max_tokens}")

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.used += max(0, input_tokens) + max(0, output_tokens)

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def hash_embed(text: str, dim: int = 64) -> list[float]:
    """A cheap, dependency-free, deterministic bag-of-tokens embedding. Good
    enough to catch near-duplicate outputs offline; real similarity comes from
    the embedding model when the router is live."""
    vec = [0.0] * dim
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 1.0
    return vec


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
            self.mode = self.SAFE if self.mode == self.CONSERVATIVE else self.CONSERVATIVE
        else:
            self.mode = self.NORMAL
        return self.mode

    @property
    def tripped(self) -> bool:
        return self.mode != self.NORMAL
