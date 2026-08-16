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

import os
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


@dataclass
class Started:
    """A process that is still running, and the file its output is going into.

    Deliberately not a `Popen`. Returning one would put `subprocess` types in the signature of
    every caller and make the rule this module exists for a rule about one import instead of about
    a capability — the same argument `Completed` is here for.
    """

    pid: int
    log: str
    _proc: object = None

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None  # type: ignore[attr-defined]

    def returncode(self) -> int | None:
        """None while it runs, the exit code once it has stopped."""
        return None if self._proc is None else self._proc.poll()  # type: ignore[attr-defined]

    def stop(self, grace: float = 5.0) -> int | None:
        """Ask it to stop, then insist. Returns the exit code, or None if it was already gone.

        Terminate before kill because a program that keeps state deserves the chance to write it
        down, and `grace` seconds is long enough for a web server to finish a request and short
        enough that an operator pressing Stop does not wait on a program that is not listening.
        """
        if self._proc is None:
            return None
        proc = self._proc
        if proc.poll() is not None:  # type: ignore[attr-defined]
            return proc.poll()  # type: ignore[attr-defined]
        proc.terminate()  # type: ignore[attr-defined]
        try:
            return proc.wait(timeout=grace)  # type: ignore[attr-defined]
        except subprocess.TimeoutExpired:
            proc.kill()  # type: ignore[attr-defined]
            try:
                return proc.wait(timeout=grace)  # type: ignore[attr-defined]
            except subprocess.TimeoutExpired:
                return None


def start(cmd: list[str], *, cwd: str | None = None, log: str, env: dict | None = None) -> Started:
    """Launch `cmd` and leave it running, with its output going to `log`.

    The other half of this module, and a different job from `run`: that one waits for an answer,
    this one supervises something that is meant to outlive the call. A company's own application is
    a program that serves requests, so there is nothing to wait for.

    **Output to a file rather than a pipe**, and it is not a detail. A pipe nobody reads fills its
    buffer and the program blocks writing to it — a web server that logs a line per request would
    stop dead after a few thousand of them, which is the kind of failure that looks like the program
    being wrong. A file has no such limit and gives the operator something to read afterwards.

    `env` replaces rather than extends when given, so a caller can decide exactly what a program
    written by a model is allowed to see of the machine it runs on.
    """
    handle = open(log, "a", encoding="utf-8", errors="replace")  # noqa: SIM115 - owned by the child
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=env,
            # Its own group, so stopping it stops what it spawned. A dev server that forks a
            # reloader is the normal case, and terminating only the parent leaves the child holding
            # the port — which then looks like a program that would not die.
            start_new_session=(os.name != "nt"),
            # `getattr`, because the constant only exists on Windows. The conditional expression
            # never evaluates it elsewhere at runtime, but mypy checks the attribute regardless and
            # `--platform linux` is one of the two invocations CI runs — which is how this was found,
            # having passed the default and the win32 pass here.
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except OSError as exc:
        handle.close()
        raise ProcError(f"{cmd[0]} could not be started: {exc}") from exc
    finally:
        # **Ours, closed; the child has its own.** `Popen` duplicates the descriptor into the child,
        # so keeping this one open leaks a handle per launch — and on Windows it holds a lock on a
        # file the operator may want to delete or rotate. The suite treats a `ResourceWarning` as a
        # failure, which is how this was found rather than lived with.
        handle.close()
    return Started(pid=proc.pid, log=str(log), _proc=proc)
