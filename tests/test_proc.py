"""The one place the package is allowed to run an external command.

Seven call sites across four modules used to spell out the same five keyword arguments to
`subprocess.run`. One of those five — `encoding="utf-8"` — was load-bearing and only one
site said why. Nothing tested it anywhere, which is how a decoding rule that had already
mangled a production run stayed one careless copy-paste away from coming back.

The child processes here are this interpreter, so these are real runs with no network, no
fixtures and no mocking: the seam being tested *is* the boundary to the operating system.
"""

import os
import subprocess
import sys

import pytest

from corparius.kernel import proc


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_output_comes_back_as_text():
    out = proc.run(_py("print('hello')"))
    assert out.ok and out.returncode == 0
    assert out.stdout.strip() == "hello"


def test_utf8_survives_a_locale_that_would_have_mangled_it():
    """The measured bug, finally pinned.

    `text=True` alone decodes with the *locale* encoding — cp1252 on Windows — while the
    Claude CLI emits utf-8 JSON. On a real run every accent in a hard-tier reply came back
    mangled and was stored that way, and the malformed bytes also produced intermittent
    "claude CLI returned non-JSON output".

    The child writes utf-8 bytes straight to the raw stream, so this asserts the decoding
    end of the wire and nothing about the child's own console settings.
    """
    out = proc.run(
        _py("import sys; sys.stdout.buffer.write('éàü — ok'.encode('utf-8'))"),
    )
    assert out.stdout == "éàü — ok"


def test_undecodable_bytes_replace_rather_than_raise():
    """`errors="replace"`, the other half of the pair. A tool that emits one bad byte must
    not take down the turn that called it — the output is still worth reading."""
    out = proc.run(_py(r"import sys; sys.stdout.buffer.write(b'ok\xff')"))
    assert out.ok and out.stdout.startswith("ok")


def test_a_non_zero_exit_is_data_not_an_exception():
    """Half the call sites treat a failure as an answer — "already exists" is success for
    `gh repo create`. Raising would force every one of them to catch immediately."""
    out = proc.run(_py("import sys; sys.exit(3)"))
    assert not out.ok and out.returncode == 3


def test_tail_prefers_stderr_but_falls_back_to_stdout():
    """A surprising number of tools report their failure on stdout. Reading only stderr
    produced empty error messages, which is worse than a long one."""
    err = proc.run(_py("import sys; sys.stderr.write('boom'); sys.exit(1)"))
    assert err.tail() == "boom"
    quiet = proc.run(_py("print('the real reason'); raise SystemExit(1)"))
    assert quiet.tail() == "the real reason"


def test_tail_is_bounded_because_it_reaches_an_operator():
    out = proc.run(_py("import sys; sys.stderr.write('x' * 5000); sys.exit(1)"))
    assert len(out.tail()) == 400
    assert len(out.tail(50)) == 50


def test_stdin_reaches_the_process():
    """How a long prompt reaches the Claude CLI: 8 000 characters pass on a Windows command
    line and 8 100 do not (ADR 0005), while stdin has no limit worth naming."""
    out = proc.run(_py("import sys; sys.stdout.write(sys.stdin.read().upper())"), stdin="quiet")
    assert out.stdout == "QUIET"


def test_a_command_that_is_not_there_is_one_exception_not_an_OSError():
    with pytest.raises(proc.ProcError) as failed:
        proc.run(["corparius-no-such-binary-8f2a", "--version"])
    assert "corparius-no-such-binary-8f2a" in str(failed.value)


def test_running_out_of_time_is_its_own_exception():
    """A subclass, not a flag, because one caller has a genuinely different answer for it:
    the Claude CLI probe tells the operator a silent CLI is probably sitting on a login
    prompt. Collapsing both into one message would throw that away."""
    with pytest.raises(proc.ProcTimeout) as failed:
        proc.run(_py("import time; time.sleep(30)"), timeout=0.5)
    assert "0.5s" in str(failed.value)
    assert isinstance(failed.value, proc.ProcError), "callers that do not care catch the base"


def test_the_cwd_is_honoured(tmp_path):
    """`_git` runs in a company folder, and getting this wrong would commit to whichever
    repository the process happened to start in."""
    out = proc.run(_py("import os; print(os.getcwd())"), cwd=str(tmp_path))
    assert out.stdout.strip() == str(tmp_path.resolve())


# --- the other half: a process that is meant to outlive the call --------------------


def _sleeper(tmp_path, seconds: int = 30) -> str:
    """A program that stays up and says so, so a test can tell running from finished."""
    script = tmp_path / "sleeper.py"
    script.write_text(
        f"import time\nprint('up', flush=True)\ntime.sleep({seconds})\n",
        encoding="utf-8",
    )
    return str(script)


def test_a_started_process_is_alive_and_stops_when_asked(tmp_path):
    """`run` waits for an answer; `start` supervises something with nothing to wait for. A company's
    own program serves requests, so the two are different jobs and this is the second one."""
    import sys

    started = proc.start(
        [sys.executable, _sleeper(tmp_path)], cwd=str(tmp_path), log=str(tmp_path / "out.log")
    )
    assert started.pid > 0
    assert started.alive() is True
    assert started.returncode() is None

    started.stop()
    assert started.alive() is False
    assert started.returncode() is not None


def test_the_output_goes_to_a_file_and_not_a_pipe(tmp_path):
    """Not a detail. A pipe nobody reads fills its buffer and the program blocks writing to it — a
    web server logging a line per request would stop dead after a few thousand, which is the kind of
    failure that looks like the program being wrong. A file has no such limit and leaves the operator
    something to read."""
    import sys
    import time

    log = tmp_path / "out.log"
    started = proc.start([sys.executable, _sleeper(tmp_path)], cwd=str(tmp_path), log=str(log))
    for _ in range(40):
        if log.is_file() and "up" in log.read_text(encoding="utf-8", errors="replace"):
            break
        time.sleep(0.1)
    started.stop()
    assert "up" in log.read_text(encoding="utf-8", errors="replace")


def test_stopping_something_already_gone_is_not_an_error(tmp_path):
    """The caller does not know whether a program exited on its own, and asking should not be how it
    finds out the hard way."""
    import sys

    started = proc.start(
        [sys.executable, "-c", "pass"], cwd=str(tmp_path), log=str(tmp_path / "x.log")
    )
    started._proc.wait(timeout=10)  # type: ignore[attr-defined]
    assert started.alive() is False
    assert started.stop() is not None  # the exit code, not an exception


def test_a_command_that_cannot_be_started_raises_the_module_s_own_error(tmp_path):
    """`ProcError`, like `run`: a caller that had to catch `OSError` would be a caller importing
    nothing useful to tell the two apart."""
    with pytest.raises(proc.ProcError):
        proc.start(
            ["definitely-not-a-program-on-this-machine"],
            cwd=str(tmp_path),
            log=str(tmp_path / "x.log"),
        )


def test_the_environment_is_replaced_rather_than_extended(tmp_path, monkeypatch):
    """The reason `env` exists at all: a caller decides exactly what a program written by a model may
    see of the machine it runs on. Extending would hand it every API key in the process."""
    import sys
    import time

    monkeypatch.setenv("A_SECRET_OF_THE_PARENT", "do-not-pass-this-on")
    script = tmp_path / "peek.py"
    script.write_text(
        "import os, json\nprint(json.dumps(sorted(os.environ)), flush=True)\n", encoding="utf-8"
    )
    log = tmp_path / "env.log"
    started = proc.start(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        log=str(log),
        env={
            "PATH": os.environ.get("PATH", ""),
            "MARKER": "1",
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        },
    )
    for _ in range(40):
        if log.is_file() and log.read_text(encoding="utf-8", errors="replace").strip():
            break
        time.sleep(0.1)
    started.stop()

    seen = log.read_text(encoding="utf-8", errors="replace")
    assert "MARKER" in seen
    assert "A_SECRET_OF_THE_PARENT" not in seen


def test_the_parent_does_not_keep_the_log_handle_open(tmp_path):
    """One handle leaked per launch, and on Windows it holds a lock on a file the operator may want
    to delete or rotate. Found because the suite treats a `ResourceWarning` as a failure; asserted
    here so it stays found."""
    import sys

    log = tmp_path / "held.log"
    started = proc.start([sys.executable, "-c", "pass"], cwd=str(tmp_path), log=str(log))
    started._proc.wait(timeout=10)  # type: ignore[attr-defined]
    started.stop()
    # If the parent still held it, this would raise PermissionError on Windows.
    log.unlink()
    assert not log.exists()


def test_stopping_a_started_that_never_ran_says_nothing_happened(tmp_path):
    """`Started` is a dataclass and a caller can hold one that never got a process — a failed launch
    that was recorded before it raised. `None` is the honest answer for "there was no exit code",
    and it is not the same as zero."""
    empty = proc.Started(pid=0, log=str(tmp_path / "x.log"))
    assert empty.alive() is False
    assert empty.returncode() is None
    assert empty.stop() is None


class _Stubborn:
    """A process that ignores being asked and has to be killed.

    A double rather than a real program, and deliberately: on Windows `terminate()` is
    `TerminateProcess`, which cannot be ignored, so the escalation below is unreachable with an
    actual child there. What is being tested is the decision — ask, wait, insist — and that is
    logic rather than an operating system behaviour.
    """

    def __init__(self, *, dies_on_kill: bool = True):
        self.terminated = self.killed = 0
        self._dies_on_kill = dies_on_kill
        self._waits = 0

    def poll(self):
        return None if self.killed == 0 else 0

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1

    def wait(self, timeout=None):
        self._waits += 1
        if self._waits == 1 or not self._dies_on_kill:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)
        return 0


def test_a_program_that_ignores_terminate_is_killed(tmp_path):
    """Terminate before kill, because a program that keeps state deserves the chance to write it
    down; kill after, because an operator pressing Stop is not asking politely twice."""
    stubborn = _Stubborn()
    started = proc.Started(pid=1, log=str(tmp_path / "x.log"), _proc=stubborn)

    assert started.stop(grace=0.01) == 0
    assert stubborn.terminated == 1 and stubborn.killed == 1


def test_a_program_that_survives_a_kill_is_reported_rather_than_waited_on(tmp_path):
    """Nothing can stop a process the OS will not kill — a wedged driver, a debugger attached. The
    honest answer is `None` and moving on, because blocking here would hang the shutdown of the
    console rather than the one program that is stuck."""
    unkillable = _Stubborn(dies_on_kill=False)
    started = proc.Started(pid=1, log=str(tmp_path / "x.log"), _proc=unkillable)

    assert started.stop(grace=0.01) is None
    assert unkillable.killed == 1
