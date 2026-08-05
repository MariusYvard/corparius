"""What each module drags in behind it, measured.

An import graph tells you who depends on whom. This tells you what that *costs*, which is
the number the restructuring is actually trying to move — and it is the acceptance test
for three of its stages.

The baseline below is measured, not assumed. Two lines of it are the argument for the
whole exercise:

- **`settings_spec` pulls `requests`, `subprocess` and `ssl`.** Reading a settings registry
  loads the HTTP stack and the process spawner, because of one import on line 19 that
  exists to read `OPENAI_COMPAT_PROVIDERS` and is used nowhere else in 1 380 lines.
- **`agents` pulls `smtplib` and `imaplib`.** `agents.py` has no host concern of its own —
  it imports `tools`, and `tools` imports `deploy`, `integrations`, `mailbox` and
  `sitecheck` at module scope. Every agent turn pays for a mail client it will never use.

Each check runs in a **fresh interpreter**, because `sys.modules` is global: once anything
in a test session has imported `requests`, every later check would pass for the wrong
reason. That is also why this file cannot use fixtures to fake the answer.

Same ratchet as test_layers.py: `observed == declared`. A module that starts pulling more
fails, and a module that stops pulling something has to be struck off — otherwise the
baseline rots into folklore and stops being a measurement.
"""

import json
import subprocess
import sys

import pytest

WATCHED = ("requests", "subprocess", "sqlite3", "smtplib", "imaplib", "ssl")

# Measured on this package. The comment on each line says what should change it.
COST: dict[str, frozenset[str]] = {
    # Kernel: clean, and the rules in test_layers.py keep it that way.
    "kernel.paths": frozenset(),
    "kernel.records": frozenset(),
    "kernel.i18n": frozenset(),
    "kernel.httpkit": frozenset(),
    # Free even though it is the encryption module: `cryptography` is optional and is
    # imported inside the three functions that need it, so its absence is *reported* rather
    # than assumed. That is also why it does not appear in WATCHED.
    "kernel.crypto": frozenset(),
    "permissions": frozenset(),
    "kernel.vectors": frozenset(),
    "kernel.text": frozenset(),
    # The one module that owns `subprocess`, so of course it loads it. This line is the
    # counterpart of the OWNERS rule in test_layers.py: it should never be joined by another.
    "kernel.proc": frozenset({"subprocess"}),
    "safety": frozenset(),
    # Config: sqlite3 only, because cfg reads a settings table. Stage 2 moves that
    # connection into `config/store_layer.py`; it does not remove it, and it should not —
    # "you cannot ask the database where the database is" is why it exists.
    "cfg": frozenset({"sqlite3"}),
    "config": frozenset({"sqlite3"}),
    "store": frozenset({"sqlite3"}),
    # Stage 2 must take `requests`, `subprocess` and `ssl` off this line: reading a
    # setting has no business loading an HTTP client.
    "settings_spec": frozenset({"requests", "subprocess", "sqlite3", "ssl"}),
    # Stage 3 must take `smtplib` and `imaplib` off this line. Splitting the tool registry
    # into data (`domain/tools/spec.py`) and wiring (`registry.py`) is what does it: the
    # catalogue stops needing the adapters, and only the executor pays.
    "agents": frozenset({"requests", "subprocess", "sqlite3", "smtplib", "imaplib", "ssl"}),
    "tools": frozenset({"requests", "subprocess", "sqlite3", "smtplib", "imaplib", "ssl"}),
    # Stage 5 should take `subprocess` off this line: the Claude CLI becomes one provider
    # among others behind `kernel/proc.py`, and the router stops knowing it exists.
    "llm": frozenset({"requests", "subprocess", "sqlite3", "ssl"}),
    # Interfaces and app services legitimately reach everything. Recorded so a *rise* is
    # visible, not because it should fall.
    "doctor": frozenset({"requests", "subprocess", "sqlite3", "ssl"}),
    "orchestrator": frozenset({"requests", "subprocess", "sqlite3", "smtplib", "imaplib", "ssl"}),
    "webui": frozenset({"requests", "subprocess", "sqlite3", "smtplib", "imaplib", "ssl"}),
}

_PROBE = (
    "import sys, json, importlib;"
    "importlib.import_module('corparius.{module}');"
    "print(json.dumps(sorted(m for m in {watched!r} if m in sys.modules)))"
)


def _pulled(module: str) -> frozenset[str]:
    """Which watched modules a bare `import corparius.<module>` loads, in a clean process."""
    out = subprocess.run(
        [sys.executable, "-c", _PROBE.format(module=module, watched=WATCHED)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert out.returncode == 0, f"importing corparius.{module} failed: {out.stderr[:400]}"
    return frozenset(json.loads(out.stdout.strip()))


@pytest.mark.parametrize("module", sorted(COST))
def test_a_module_pulls_in_exactly_what_it_declares(module):
    declared = COST[module]
    pulled = _pulled(module)
    extra = sorted(pulled - declared)
    gone = sorted(declared - pulled)
    assert not extra, (
        f"importing corparius.{module} now also loads {extra}. Either that is a new "
        "coupling to remove, or the cost genuinely changed and COST should say so."
    )
    assert not gone, (
        f"corparius.{module} no longer loads {gone} — good. Strike it off COST so the "
        "baseline keeps meaning something."
    )


def test_the_kernel_costs_nothing():
    """Stated separately because it is the property that makes rank 0 safe to import from
    anywhere, and it should never need an exception.

    Rank 0 only. `permissions` and `safety` are free too and COST says so, but they are
    rank 1 and rank 4 — including them here would blur what this test is claiming.

    Derived from COST rather than listed, so a new kernel module is covered the day it
    exists instead of the day somebody remembers this line. `kernel.proc` is the single
    exception, and a declared one: it is the module that *owns* `subprocess`, which is the
    whole reason nothing else may import it.
    """
    free = [m for m in sorted(COST) if m.startswith("kernel.") and m != "kernel.proc"]
    assert len(free) >= 5, "the derivation stopped finding kernel modules"
    for module in free:
        assert _pulled(module) == frozenset(), f"corparius.{module} stopped being free"
