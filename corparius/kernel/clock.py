"""Waiting, in one place. Rank 0: stdlib only.

The same argument as `kernel/proc.py`, and the plan makes it explicitly for that one: **one wrapper so
the layer test can forbid the primitive everywhere else.** `proc.run()` exists so `subprocess` can be
banned outside it; this exists so `time.sleep` can be.

There was exactly one call left in the domain, and it is load-bearing rather than sloppy:
`orchestrator.run` waits a second at the **day boundary** of a `--loop` run. A day whose every role is
paused completes in milliseconds, so without a floor a long-lived loop spins at full speed doing
nothing. Deleting it to satisfy the rule would have traded an architecture violation for a busy loop,
which is the wrong trade and the reason this module exists instead.

Patching one function is also what makes a `--loop` test possible: `tests/test_orchestrator.py` can
replace `pace` and a two-day run stops taking two seconds. That was the second cost of the primitive
being spread out — the first being that nothing could forbid it.
"""

from __future__ import annotations

import time

# The floor between simulated days in a `--loop` run. One second, which is nothing against a real day
# of agent turns and everything against a day that produces no work at all.
DAY_PACE = 1.0


def pace(seconds: float = DAY_PACE) -> None:
    """Wait, and be the only place in the package that does.

    Named `pace` rather than `sleep` because that is what the one caller wants: a floor on how fast a
    loop may go round, not a delay for its own sake. A function called `sleep` invites being used as
    one — a retry backoff, a poll interval — and both of those belong to whoever owns the retry or the
    poll, not to a helper.
    """
    time.sleep(max(0.0, float(seconds)))
