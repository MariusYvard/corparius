"""Proving the mail account from a terminal, which is the machine that most needs it.

`doctor` reports whether the mail settings are *present*. On a headless box that is the
difference between believing the mail is wired and knowing it — and this project's discipline is
the second one: `integrations.smtp_check`'s own docstring says it "proves the thing works rather
than asking the operator to trust it, by making one real, minimal call".

Nothing in the CLI made that call. The console had the button.

`check` was already app-shaped — no `UiState`, no request body, no status code — so the move was
one file and one command. That is worth stating: the services that were hard to extract were
hard because of a parameter, not because of their logic.
"""

import pytest

from corparius.app import mail as app_mail


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    from corparius.config import cfg

    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    return tmp_path


# --- the service ----------------------------------------------------------------


def test_with_nothing_configured_it_says_so_rather_than_failing(home):
    """Two halves both unconfigured is not two failures, it is one thing not set up yet. An
    operator who has not started reads a stack of protocol errors as something broken."""
    out = app_mail.check()
    assert out["ok"] is False
    assert "No mail account" in out["detail"]


def test_the_two_halves_are_reported_separately(home, monkeypatch):
    """SMTP is outbound and a wrong port; IMAP is inbound and a wrong folder. They fail for
    different reasons, and "mail is broken" tells an operator which of two things to look at:
    neither."""
    monkeypatch.setattr(
        app_mail,
        "smtp_check",
        lambda to, lang="en": {"ok": True, "configured": True, "detail": "sent to a@b.c"},
    )
    monkeypatch.setattr(
        app_mail.mailbox,
        "check",
        lambda lang="en": {"ok": False, "configured": True, "detail": "IMAP refused the login"},
    )
    out = app_mail.check()
    assert out["ok"] is False, "one half failing is a failure"
    assert out["send_ok"] is True and out["read_ok"] is False
    assert "sent to a@b.c" in out["detail"] and "IMAP refused" in out["detail"]


def test_both_working_is_the_only_ok(home, monkeypatch):
    for name, target in (("smtp_check", app_mail), ("check", app_mail.mailbox)):
        monkeypatch.setattr(
            target, name, lambda *a, **k: {"ok": True, "configured": True, "detail": "fine"}
        )
    assert app_mail.check()["ok"] is True


def test_it_takes_no_console_object(home):
    """The reason this one was cheap: it never had a `UiState`. The services that were hard to
    extract were hard because of a parameter, not because of their logic."""
    import inspect

    params = list(inspect.signature(app_mail.check).parameters)
    assert params == ["to", "lang"], params


def test_the_steps_say_which_ones_corparius_cannot_check(home):
    """A step that can never turn green is worse than no state at all — installing Proton
    Bridge, reading a password off somebody else's dashboard. Those report `checkable: false`
    so a caller shows them as something to do rather than something outstanding."""
    steps = app_mail.steps()
    assert steps, "no provider steps at all"
    flat = [step for provider in steps.values() for step in provider]
    assert any(not step["checkable"] for step in flat), "nothing is marked uncheckable"
    assert all("en" in step and "fr" in step for step in flat), "both languages, as the page has"


def test_a_step_is_done_only_when_its_settings_are_there(home, monkeypatch):
    """`done` is a fact about this installation, not about the browser — the same reason the
    approval panel resolves what a tool does server-side."""
    checkable = [
        (provider, step)
        for provider, steps in app_mail.steps().items()
        for step in steps
        if step["checkable"]
    ]
    assert checkable, "no checkable step to test with"
    assert not any(step["done"] for _, step in checkable), "nothing is configured yet"


# --- the command ----------------------------------------------------------------


def test_the_command_exits_non_zero_when_the_mail_is_not_proved(home, capsys):
    from corparius import cli

    assert cli.main(["mail"]) == 1
    said = capsys.readouterr().out
    assert "No mail account" in said


def test_the_command_says_what_a_terminal_can_actually_do(home, capsys):
    """The service's copy says "below" and "above" — it was written for the settings page, and a
    terminal has no below. Rather than rewrite strings the console also shows, the command adds
    the thing a terminal can act on, which is a command that exists now."""
    from corparius import cli

    cli.main(["mail"])
    said = capsys.readouterr().out
    assert "corparius set CORP_SMTP_HOST" in said
    assert "corparius mail --steps" in said


def test_the_command_lists_the_steps_without_sending_anything(home, capsys, monkeypatch):
    """`--steps` must not spend a message. It is what an operator runs *before* having an
    account, and a check that sent one would fail for the reason they are reading it."""

    def boom(*a, **k):
        raise AssertionError("--steps sent a message")

    monkeypatch.setattr(app_mail, "smtp_check", boom)
    from corparius import cli

    assert cli.main(["mail", "--steps"]) == 0
    said = capsys.readouterr().out
    assert "gmail" in said and "[ ]" in said


def test_the_command_exits_zero_when_both_halves_work(home, capsys, monkeypatch):
    from corparius.app import mail as mod

    monkeypatch.setattr(
        mod, "check", lambda to="", lang="en": {"ok": True, "detail": "Sending: ok\nReading: ok"}
    )
    from corparius import cli

    assert cli.main(["mail"]) == 0
    assert "Sending: ok" in capsys.readouterr().out
