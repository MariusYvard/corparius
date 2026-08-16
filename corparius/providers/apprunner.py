"""Starting, watching and stopping long-lived local processes. Rank 3.

The other half of `codeapps`, and the layer test drew the line twice. The first draft of this file
imported that module to look an app up by name — a rank-3 provider reaching into rank 4, which is the
inversion the restructuring plan names as the thing to fix rather than to declare.

So it does not know what a company app is. It takes a key, a command, a folder and a port, which are
host concepts, and the domain builds those from a manifest. The same argument `HybridRouter` makes by
taking an ordered chain instead of computing one: a supervisor that knows nothing about the thing it
supervises is a supervisor a test can drive with a two-line script.

Nothing here outlives the process that started it. A child dies with the corparius that launched it,
so what is running is a dict in memory rather than a row in the store: a row that survived a restart
would describe a process that is gone, and an operator reading "running" about nothing is worse off
than reading nothing at all.
"""

from __future__ import annotations

import atexit
import logging
import socket
import time
from pathlib import Path

from ..kernel import proc

log = logging.getLogger("corparius.apprunner")

# How long to wait for a program to open its port, and how long one may live. Six hours because a
# company runs unattended for days and a program that leaks does it slowly; twenty seconds because a
# server that has not bound by then has not started.
START_GRACE_S = 20
MAX_LIFETIME_S = 6 * 3600

_running: dict[str, proc.Started] = {}
_started_at: dict[str, float] = {}


def _stop_everything_on_the_way_out() -> None:
    """Registered with `atexit`, and it is a net rather than the plan.

    `drain_and_close` stops these on the console's clean shutdown, and that is the path an operator
    taking Ctrl+C follows. It is not the only way an interpreter ends: a `corparius run` from a
    terminal, a test process, a script, an exception nobody caught. Measured on this machine while
    building the feature — twelve leftover consoles from earlier sessions, holding eight ports
    between them, none of which had gone through a shutdown path.

    A child holding a port is worse than a stale file: the next launch cannot bind, and the operator
    has to find it in a task manager to learn why. `atexit` costs nothing and covers every ending
    except a kill, which nothing can cover.
    """
    for key in list(_running):
        stop(key)


atexit.register(_stop_everything_on_the_way_out)


def listening(port: int, timeout: float = 0.4) -> bool:
    """Is something answering on loopback at this port. Never raises."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def wait_until_up(port: int, seconds: int = START_GRACE_S, alive=None) -> bool:
    """Poll loopback until the port answers, the process dies, or the grace runs out.

    Named in `tests/test_layers.py` beside the other `time.sleep` owners, for the reason that list
    gives: this is a module waiting for its own outside world. A program whose port is not open has
    not started, and reporting success because the process object exists would hand a caller an
    address that refuses connections.

    `alive` is what stops it waiting on a corpse. A program with a syntax error is gone in a tenth of
    a second and the twenty that follow tell nobody anything — one final look after it dies, because
    a program can bind and exit and the answer is still yes.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if listening(port):
            return True
        if alive is not None and not alive():
            return listening(port)
        time.sleep(0.3)
    return False


def wait_until_free(port: int, seconds: float = 5.0) -> bool:
    """Poll until nothing answers on the port, or give up. True when it is free.

    Short, because this is only ever the tail of a stop this same process asked for: a port held by
    something else is held for good and waiting on it would be waiting for a person. Five seconds is
    the same grace `Started.stop` gives a program to write its state down.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not listening(port):
            return True
        time.sleep(0.2)
    return not listening(port)


def running(key: str) -> bool:
    live = _running.get(key)
    return bool(live and live.alive())


def pid(key: str) -> int:
    live = _running.get(key)
    return live.pid if live and live.alive() else 0


def uptime(key: str) -> int:
    if not running(key):
        return 0
    return int(time.monotonic() - _started_at.get(key, time.monotonic()))


def start(key: str, cmd: list[str], *, cwd: str, log_file: str, port: int, env: dict) -> dict:
    """Launch it and wait for its port. Returns what happened; never raises.

    Idempotent: something already answering is reported as running rather than launched a second
    time, because two processes fighting over one port is a failure that reads as the program being
    wrong.
    """
    if running(key):
        return {"ok": True, "running": True, "pid": pid(key), "started": False}
    if listening(port) and not wait_until_free(port):
        # Something else holds it. Saying so beats starting a process that exits on bind and leaving
        # an operator with a log they have to go and find.
        #
        # The wait is there because the common case is a **restart**: an app is rewritten, the old
        # process is stopped and the new one starts immediately, and a listening socket does not
        # disappear the instant its process is asked to go. Refusing on the first look reported "in
        # use by something corparius did not start" about a program corparius had just stopped —
        # which is both wrong and the most confusing sentence it could have produced.
        return {
            "ok": False,
            "running": False,
            "error": f"port {port} is already in use by something corparius did not start",
        }
    try:
        started = proc.start(cmd, cwd=cwd, log=log_file, env=env)
    except proc.ProcError as exc:
        return {"ok": False, "running": False, "error": str(exc)}
    _running[key] = started
    _started_at[key] = time.monotonic()
    if not wait_until_up(port, alive=started.alive):
        # **Three facts, because two of them were missing when this failed on a machine nobody here
        # could reach.** Every macOS job in CI reported "nothing answered within 20s" and an empty
        # log, which says only that the picture is missing — not whether the program crashed, exited
        # cleanly, or is still starting. The exit code separates those, and waiting the full grace on
        # a process that died in the first half second was the other half of the waste.
        said = tail(log_file)
        code = started.returncode()
        started.stop()
        _running.pop(key, None)
        _started_at.pop(key, None)
        gone = (
            f"it exited with {code}"
            if code is not None
            else f"it was still running after {START_GRACE_S}s"
        )
        return {
            "ok": False,
            "running": False,
            "error": (
                f"nothing answered on {port}: {gone}. {said or 'it wrote nothing at all'} "
                f"(ran {' '.join(cmd)} in {cwd})"
            ),
        }
    log.info("%s is answering on 127.0.0.1:%d (pid %d)", key, port, started.pid)
    return {"ok": True, "running": True, "pid": started.pid, "started": True}


def stop(key: str) -> dict:
    """Stop it. Reports whether there was anything to stop."""
    live = _running.pop(key, None)
    _started_at.pop(key, None)
    if live is None:
        return {"ok": True, "running": False, "stopped": False}
    return {"ok": True, "running": False, "stopped": True, "returncode": live.stop()}


def sweep(max_lifetime: int = MAX_LIFETIME_S) -> list[str]:
    """Stop what has outlived its lifetime, forget what has already died.

    The lifetime is the only real bound on a program somebody else wrote: memory cannot be capped the
    same way on all three platforms, so a leak is answered by a clock rather than by a limit an
    operator would believe everywhere and only get on one. Returns what it stopped, so a caller has
    something to say.
    """
    stopped = []
    for key, live in list(_running.items()):
        if not live.alive():
            _running.pop(key, None)
            _started_at.pop(key, None)
            continue
        age = time.monotonic() - _started_at.get(key, time.monotonic())
        if age > max_lifetime:
            live.stop()
            _running.pop(key, None)
            _started_at.pop(key, None)
            stopped.append(key)
            log.info("%s stopped after %d seconds, its lifetime", key, int(age))
    return stopped


def stop_all() -> int:
    """Every child, at shutdown. A corparius that exits leaving programs holding ports is one an
    operator has to hunt for in a task manager."""
    keys = list(_running)
    for key in keys:
        stop(key)
    return len(keys)


def tail(log_file: str | Path, limit: int = 300) -> str:
    try:
        return " ".join(Path(log_file).read_text(encoding="utf-8", errors="replace").split())[
            -limit:
        ]
    except OSError:
        return "no log was written"
