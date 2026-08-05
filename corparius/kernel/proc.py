"""Running an external command. Rank 0: pure, stdlib only.

Seven call sites across four modules spelled out the same five keyword arguments, and one of
those five carries a bug that was found the hard way. Only `llm.py` wrote down why:

    encoding="utf-8"  # `text=True` alone decodes with the locale encoding — cp1252 on
                      # Windows — and the CLI emits utf-8 JSON. Measured on a real run:
                      # every accent in a hard-tier reply came back mangled and stored that
                      # way, and the malformed bytes also produced intermittent
                      # "claude CLI returned non-JSON output".

The other six got it right by copying, which is luck rather than discipline — and luck does
not survive the seventh call site. So there is one now, and `tests/test_layers.py` forbids
`import subprocess` anywhere else in the package.

Two consequences worth stating:

  * `Completed` is this module's own type, not `subprocess.CompletedProcess`. If callers
    had to annotate with the latter they would have to import `subprocess` to do it, and
    the rule would be a rule about one line instead of about a capability.
  * Failing to *run* — not found, refused, out of time — is one exception, `ProcError`,
    subclassing RuntimeError. It is the shape callers already handle: `_git` raises
    RuntimeError on a non-zero exit, and both provider registries fall through to the next
    candidate on `Exception`. A raw `TimeoutExpired` reaching those was never handled
    differently; it just read as a different kind of accident.

A non-zero exit is **not** an exception. It is data, on `Completed`, because half these
call sites treat a failure as an answer ("already exists" is a success for `gh repo
create") and raising would force them to catch immediately.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

DEFAULT_TIMEOUT = 60


class ProcError(RuntimeError):
    """The command could not be run to completion: not on PATH, refused by the OS, or out
    of time. Distinct from a command that ran and exited non-zero, which is `Completed`."""


class ProcTimeout(ProcError):
    """Ran out of time, specifically.

    A subclass rather than a flag because one caller has a genuinely different answer for
    it: the Claude CLI probe tells the operator that a silent CLI is probably sitting on a
    login prompt and to run `claude login` once. Collapsing both into one message would have
    thrown away the only actionable thing that check says.
    """


@dataclass(frozen=True)
class Completed:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def tail(self, limit: int = 400) -> str:
        """The last of whatever the command said, stderr first.

        Every caller wanted this and four of them wrote it inline. `stdout` is the fallback
        because a surprising number of tools report their failure there — reading only
        stderr produced empty error messages, which is worse than a long one.
        """
        return (self.stderr or self.stdout or "").strip()[-limit:]


def run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    stdin: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Completed:
    """Run `cmd` and capture its output as text.

    `stdin` rather than an argv argument is how a long prompt reaches the Claude CLI — see
    ADR 0005 and `llm.ARGV_BUDGET`: 8 000 characters pass on a Windows command line and
    8 100 do not, while stdin has no limit worth naming.
    """
    try:
        out = subprocess.run(
            cmd,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            # See the module docstring: `text=True` alone decodes with the locale encoding.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcTimeout(f"{cmd[0]} did not finish within {timeout:g}s") from exc
    except OSError as exc:
        raise ProcError(f"{cmd[0]} could not be run: {exc}") from exc
    return Completed(
        args=list(cmd),
        returncode=out.returncode,
        stdout=out.stdout or "",
        stderr=out.stderr or "",
    )
