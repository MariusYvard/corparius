"""The one place the package is allowed to run an external command.

Seven call sites across four modules used to spell out the same five keyword arguments to
`subprocess.run`. One of those five — `encoding="utf-8"` — was load-bearing and only one
site said why. Nothing tested it anywhere, which is how a decoding rule that had already
mangled a production run stayed one careless copy-paste away from coming back.

The child processes here are this interpreter, so these are real runs with no network, no
fixtures and no mocking: the seam being tested *is* the boundary to the operating system.
"""

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
