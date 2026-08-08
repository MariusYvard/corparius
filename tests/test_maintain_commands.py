"""The two commands that destroy something, and what they do before they do it.

Stage 7's per-file coverage ratchet is what asked for this file. `cli.py` measured 52% whole,
which said nothing about *which* half; split into eight groups, `cli/maintain.py` came out at
**25.9%** — the lowest in the package, for the two commands that replace the running binary and
replace the companies and the store. The plan named this exactly: "le total peut rester beau
pendant qu'un module extrait tombe à 40%".

The modules underneath are tested (`test_backup.py`, `test_selfupdate.py`). What was not tested
is the **command**: the order it does things in, what it refuses, and what a shell sees. Three
properties, and each one has a way of being wrong that a passing module test cannot catch:

  1. **A refusal exits non-zero.** `corparius deploy` printed "no provider succeeded" and exited
     0 for months, because `args.fn(args)` discarded the return value. A script wrapping
     `update` or `restore` reads the exit code, not the prose.
  2. **The prompt comes after the report and before the write.** An operator confirms a restore
     having read what the archive holds; asking first and printing after would be a confirmation
     of nothing.
  3. **Answering no calls nothing.** Not "rolls back" — never starts. Asserted by making the
     destructive function fail the test if it is reached at all.
"""

import types

import pytest

from corparius import backup, selfupdate, update_check
from corparius.cli import maintain


def _args(**kw):
    kw.setdefault("yes", False)
    return types.SimpleNamespace(**kw)


def _never(name):
    def boom(*a, **k):
        raise AssertionError(f"{name} was called and must not have been")

    return boom


# --- update ---------------------------------------------------------------------


def test_update_refuses_where_it_cannot_work_and_says_what_to_do(monkeypatch, capsys):
    """From source or Docker there is no binary to replace. Measured: that is this checkout, so
    the reason below is the real one an operator would read."""
    monkeypatch.setattr(selfupdate, "apply", _never("selfupdate.apply"))
    with pytest.raises(SystemExit) as exc:
        maintain.cmd_update(_args())
    said = str(exc.value)
    assert "cannot update here" in said
    assert "git pull" in said or "docker pull" in said, "a refusal has to name the way out"


def test_update_says_the_check_is_off_rather_than_asking_github_anyway(monkeypatch, capsys):
    """`CORP_UPDATE_CHECK` is off by default and that is a decision, not a failure: this build
    does not contact GitHub unless told to. So the message names the setting."""
    monkeypatch.setattr(selfupdate, "why_not", lambda: "")
    monkeypatch.setattr(update_check, "check", lambda: {"enabled": False, "current": "0.3.3"})
    monkeypatch.setattr(selfupdate, "apply", _never("selfupdate.apply"))
    with pytest.raises(SystemExit) as exc:
        maintain.cmd_update(_args())
    assert exc.value.code == 1
    assert "CORP_UPDATE_CHECK" in capsys.readouterr().out


def test_update_reports_an_unreachable_github_as_a_refusal(monkeypatch):
    monkeypatch.setattr(selfupdate, "why_not", lambda: "")
    monkeypatch.setattr(update_check, "check", lambda: {"enabled": True, "reachable": False})
    monkeypatch.setattr(selfupdate, "apply", _never("selfupdate.apply"))
    with pytest.raises(SystemExit) as exc:
        maintain.cmd_update(_args())
    assert "could not reach GitHub" in str(exc.value)


def test_update_on_the_newest_release_downloads_nothing_and_succeeds(monkeypatch, capsys):
    """Exit 0, because nothing is wrong. The distinction matters to a cron job that runs this."""
    monkeypatch.setattr(selfupdate, "why_not", lambda: "")
    monkeypatch.setattr(
        update_check,
        "check",
        lambda: {"enabled": True, "reachable": True, "update_available": False, "current": "0.3.3"},
    )
    monkeypatch.setattr(selfupdate, "apply", _never("selfupdate.apply"))
    assert maintain.cmd_update(_args()) is None
    assert "already on the newest release (0.3.3)" in capsys.readouterr().out


def _an_update_is_waiting(monkeypatch):
    monkeypatch.setattr(selfupdate, "why_not", lambda: "")
    monkeypatch.setattr(
        update_check,
        "check",
        lambda: {
            "enabled": True,
            "reachable": True,
            "update_available": True,
            "current": "0.3.3",
            "latest": "0.4.0",
        },
    )


def test_update_declined_at_the_prompt_replaces_nothing(monkeypatch, capsys):
    """The property, not the prose: `apply` fails the test if it is reached."""
    _an_update_is_waiting(monkeypatch)
    monkeypatch.setattr(selfupdate, "apply", _never("selfupdate.apply"))
    monkeypatch.setattr("builtins.input", lambda _="": "n")
    with pytest.raises(SystemExit) as exc:
        maintain.cmd_update(_args())
    assert "nothing was changed" in str(exc.value)
    out = capsys.readouterr().out
    assert "0.3.3 -> 0.4.0" in out, "it has to say what it is about to do before asking"
    assert "not touched" in out, "and that companies and settings are not in the swap"


def test_update_with_yes_asks_nothing_and_reports_all_three_paths(monkeypatch, capsys):
    """`--yes` is for scripts, so the prompt must not be reachable — `input` fails the test.

    Three paths in the report and each answers a different question: what is installed now,
    where the store backup went, and where the build that was running is kept. The last one is
    how an operator goes back, so omitting it would make the rollback undiscoverable.
    """
    _an_update_is_waiting(monkeypatch)
    monkeypatch.setattr("builtins.input", _never("input"))
    monkeypatch.setattr(
        selfupdate,
        "apply",
        lambda tag: {
            "installed": "0.4.0",
            "path": "/opt/corparius",
            "backup": "/backups/b.zip",
            "previous": "/opt/corparius.old",
        },
    )
    assert maintain.cmd_update(_args(yes=True)) is None
    out = capsys.readouterr().out
    assert "installed 0.4.0 at /opt/corparius" in out
    assert "/backups/b.zip" in out
    assert "/opt/corparius.old" in out


def test_update_passes_the_tag_the_check_named(monkeypatch, capsys):
    """`v` + the version. A mismatch here downloads the wrong release, or none."""
    _an_update_is_waiting(monkeypatch)
    seen = {}
    monkeypatch.setattr("builtins.input", lambda _="": "y")
    monkeypatch.setattr(
        selfupdate,
        "apply",
        lambda tag: (
            seen.setdefault("tag", tag)
            and {"installed": "0.4.0", "path": "p", "backup": "", "previous": "q"}
        ),
    )
    maintain.cmd_update(_args())
    assert seen["tag"] == "v0.4.0"


def test_update_turns_an_update_error_into_a_sentence(monkeypatch):
    """`UpdateError` is documented as "a refusal an operator can act on, in one sentence". A
    traceback out of a binary swap is the worst moment for one."""
    _an_update_is_waiting(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _="": "y")

    def refuse(_tag):
        raise selfupdate.UpdateError("the checksum did not match")

    monkeypatch.setattr(selfupdate, "apply", refuse)
    with pytest.raises(SystemExit) as exc:
        maintain.cmd_update(_args())
    assert str(exc.value) == "the checksum did not match"


# --- restore --------------------------------------------------------------------


def test_restore_refuses_a_bad_archive_before_touching_anything(monkeypatch, tmp_path):
    """`backup.inspect`'s own docstring is the reason: an archive that is not a corparius backup
    "must be refused while the operator still has theirs"."""

    def refuse(_archive):
        raise backup.RestoreError("not a corparius backup")

    monkeypatch.setattr(backup, "inspect", refuse)
    monkeypatch.setattr(backup, "restore", _never("backup.restore"))
    with pytest.raises(SystemExit) as exc:
        maintain.cmd_restore(_args(archive=str(tmp_path / "x.zip")))
    assert str(exc.value) == "not a corparius backup"


def _an_archive(monkeypatch, companies=("vigil", "example")):
    monkeypatch.setattr(
        backup,
        "inspect",
        lambda _a: {"companies": list(companies), "has_store": True, "has_env": False},
    )


def test_restore_reports_what_the_archive_holds_before_it_asks(monkeypatch, tmp_path, capsys):
    """The order is the whole value of the prompt. An operator says yes to *this* archive —
    two companies and a store — not to the idea of restoring."""
    _an_archive(monkeypatch)
    monkeypatch.setattr(backup, "restore", _never("backup.restore"))
    asked = {}

    def prompt(_=""):
        asked["out"] = capsys.readouterr().out
        return "n"

    monkeypatch.setattr("builtins.input", prompt)
    with pytest.raises(SystemExit) as exc:
        maintain.cmd_restore(_args(archive=str(tmp_path / "b.zip")))
    assert "nothing was changed" in str(exc.value)
    shown = asked["out"]
    assert "vigil" in shown and "example" in shown
    assert "store     : yes" in shown and ".env      : no" in shown
    assert "replaces those companies and the store" in shown


def test_restore_with_yes_asks_nothing(monkeypatch, tmp_path, capsys):
    _an_archive(monkeypatch, companies=("vigil",))
    monkeypatch.setattr("builtins.input", _never("input"))
    monkeypatch.setattr(
        backup,
        "restore",
        lambda _a, _p: {"replaced": ["vigil", "store"], "safety_backup": "/s/b.zip", "blanked": []},
    )
    maintain.cmd_restore(_args(archive=str(tmp_path / "b.zip"), yes=True))
    out = capsys.readouterr().out
    assert "restored: vigil, store" in out
    assert "what it replaced: /s/b.zip" in out


def test_restore_names_the_keys_that_have_to_be_entered_again(monkeypatch, tmp_path, capsys):
    """A backup taken without `--with-secrets` blanks the keys. That is not an error, and the
    command's own docstring says why it still has to be said: "discovering it at the next tick
    would be"."""
    _an_archive(monkeypatch, companies=("vigil",))
    monkeypatch.setattr(
        backup,
        "restore",
        lambda _a, _p: {
            "replaced": ["vigil"],
            "safety_backup": "",
            "blanked": ["GROQ_API_KEY", "STRIPE_API_KEY"],
        },
    )
    maintain.cmd_restore(_args(archive=str(tmp_path / "b.zip"), yes=True))
    out = capsys.readouterr().out
    assert "have to be entered again" in out
    assert "GROQ_API_KEY" in out and "STRIPE_API_KEY" in out


def test_restore_turns_a_failure_mid_way_into_a_sentence(monkeypatch, tmp_path):
    _an_archive(monkeypatch)

    def refuse(_a, _p):
        raise backup.RestoreError("the store in that archive will not open")

    monkeypatch.setattr(backup, "restore", refuse)
    with pytest.raises(SystemExit) as exc:
        maintain.cmd_restore(_args(archive=str(tmp_path / "b.zip"), yes=True))
    assert str(exc.value) == "the store in that archive will not open"


def test_restore_reads_the_data_path_when_it_runs(monkeypatch, tmp_path):
    """Not the import-time snapshot. `cli.py` held one and eight group modules read it, so
    `CORP_DATA_PATH` set by a test — or by an operator's own env — moved nothing. Stage 7
    replaced every use with `Settings()`; this is the assertion that says so for the one
    command whose data path decides what gets overwritten.
    """
    from corparius.config import cfg

    _an_archive(monkeypatch, companies=("vigil",))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "elsewhere"))
    cfg.invalidate()
    seen = {}
    monkeypatch.setattr(
        backup,
        "restore",
        lambda _a, path: (
            seen.setdefault("path", path) and {"replaced": [], "safety_backup": "", "blanked": []}
        ),
    )
    maintain.cmd_restore(_args(archive=str(tmp_path / "b.zip"), yes=True))
    assert str(tmp_path / "elsewhere") in seen["path"]
