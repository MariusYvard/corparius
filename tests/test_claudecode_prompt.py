"""The prompt goes to the CLI on stdin, not on the command line.

Measured on the installed CLI (2.1.220) on Windows: an 8000-character prompt on
argv reaches the model, 8100 fails with `claude CLI exited 1: La ligne de
commande est trop longue`. The CLI npm installs is `claude.CMD`, so every call
goes through cmd.exe, which truncates the whole command line at 8191 characters.

That is not a corner case. A company with documents (up to 6000 characters of
extracted text) and skills passes it on the design agent's first turn, and the
failure arrived as a plain provider error — so the router did what it does with
a provider that is down: it fell through to the next step. On a real run that
step was a free model that cannot produce JSON, `write_site_content` returned
"no JSON object in the reply", and the site was never rewritten. The operator
had pinned Opus to the design role and Opus never once ran.

Nothing in the log said any of that. The same 25 268-character prompt on stdin
returns rc 0, also measured. These tests hold the shape that makes it true.
"""

import subprocess

import pytest

from corparius import llm


class _Run:
    """Stands in for subprocess.run and records how it was called."""

    def __init__(self, stdout='{"result": "ok", "usage": {}}'):
        self.stdout = stdout
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, self.stdout, "")

    @property
    def cmd(self):
        return self.calls[-1][0]

    @property
    def kw(self):
        return self.calls[-1][1]


@pytest.fixture
def run(monkeypatch):
    r = _Run()
    monkeypatch.setattr(subprocess, "run", r)
    monkeypatch.setattr("corparius.claudecli.resolve", lambda: "claude.CMD")
    return r


def test_the_prompt_travels_on_stdin(run):
    llm.ClaudeCodeProvider().generate([{"role": "user", "content": "write the site"}], "opus")
    assert run.kw["input"] == "write the site", "the prompt must be handed over on stdin"
    assert "write the site" not in " ".join(run.cmd), "the prompt must not be on the command line"


def test_a_prompt_far_past_the_command_line_limit_is_not_on_the_command_line(run):
    """8100 characters on argv is the measured failure. This is three times that."""
    prompt = "Contexte du document Vigil. " * 900  # 25 200 characters
    llm.ClaudeCodeProvider().generate([{"role": "user", "content": prompt}], "opus")
    assert run.kw["input"] == prompt
    assert llm._argv_chars(run.cmd) < 200, (
        f"the command line is {llm._argv_chars(run.cmd)} characters; only flags belong there"
    )


def test_the_system_prompt_stays_a_system_prompt_while_it_fits(run):
    llm.ClaudeCodeProvider().generate(
        [{"role": "system", "content": "you are terse"}, {"role": "user", "content": "hi"}],
        "opus",
    )
    assert "--append-system-prompt" in run.cmd
    assert "you are terse" in run.cmd
    assert run.kw["input"] == "hi"


def test_a_system_prompt_too_long_for_argv_is_folded_in_rather_than_dropped(run, monkeypatch):
    """A call that silently loses the company's skills and house rules answers
    confidently in the wrong voice. Folding it into the prompt keeps it."""
    monkeypatch.setattr(llm.ClaudeCodeProvider, "ARGV_BUDGET", 200)
    system = "promesse clinique: " * 100  # 1900 characters, past the fake budget
    llm.ClaudeCodeProvider().generate(
        [{"role": "system", "content": system}, {"role": "user", "content": "write the site"}],
        "opus",
    )
    assert "--append-system-prompt" not in run.cmd, "it cannot fit, so it must not be there"
    assert system in run.kw["input"], "and it must not be lost either"
    assert "write the site" in run.kw["input"]


def test_the_windows_budget_is_under_the_cmd_exe_limit():
    """cmd.exe truncates at 8191 characters and the CLI is a .CMD on Windows.
    A budget at or above that is a budget that does not guard anything."""
    assert 0 < llm.ClaudeCodeProvider.ARGV_BUDGET < 8191 or llm.os.name != "nt"


def test_a_failing_cli_still_reports_what_it_said(run, monkeypatch):
    """The message that named this bug — "La ligne de commande est trop longue" —
    only ever reached the log because the CLI's own stderr is carried through."""

    def boom(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "La ligne de commande est trop longue.")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(llm.ProviderError) as exc:
        llm.ClaudeCodeProvider().generate([{"role": "user", "content": "x"}], "opus")
    assert "trop longue" in str(exc.value)
