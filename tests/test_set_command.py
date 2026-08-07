"""Writing a setting from a terminal — the first thing the console could do and the CLI could not.

The plan's argument for stage 6 in one sentence: the business logic lived in HTTP handlers, so
the console could do eleven things the command line could not. `_persist(state, values)` took a
`UiState`, and a `UiState` is a console object — that parameter was the whole barrier. Taking
`(store, env_file)` instead is what makes the service reachable, and this file is the proof that
"reachable" is not a claim.

Read in a **fresh interpreter**, deliberately. The point is not that a function returned a dict;
it is that a value written by one process is resolved by the next one, from the layer it belongs
in. A fixture asserting on the store it just wrote to would prove neither.
"""

import json
import subprocess
import sys

import pytest

from corparius.app import settings as app_settings
from corparius.kernel import dotenv
from corparius.store import Store


def _run(home, *argv):
    out = subprocess.run(
        [sys.executable, "-m", "corparius.cli", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            "CORP_HOME": str(home),
            "CORP_DATA_PATH": str(home / "data"),
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
        },
        timeout=180,
    )
    return out.returncode, out.stdout + out.stderr


def _resolved(home, keys):
    code = (
        "import json;from corparius.config import cfg;"
        f"print(json.dumps({{k: [cfg.get(k), cfg.source(k)] for k in {keys!r}}}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            "CORP_HOME": str(home),
            "CORP_DATA_PATH": str(home / "data"),
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
        },
        timeout=180,
    )
    assert out.returncode == 0, out.stderr[-600:]
    return json.loads(out.stdout.strip())


# --- the command ---------------------------------------------------------------


def test_a_setting_written_from_a_terminal_is_read_by_the_next_process(tmp_path):
    code, said = _run(tmp_path, "set", "CORP_MEMORY_TOP_K=7")
    assert code == 0, said
    assert "the store" in said, said
    got = _resolved(tmp_path, ["CORP_MEMORY_TOP_K"])
    assert got["CORP_MEMORY_TOP_K"] == ["7", "db"]


def test_a_bootstrap_key_goes_to_the_file_and_says_a_restart_is_needed(tmp_path):
    """You cannot ask the database where the database is, so these cannot live in it. An
    operator who is not told a restart is needed reads the setting as broken."""
    code, said = _run(tmp_path, "set", "CORP_UI_PORT=8999")
    assert code == 0, said
    assert ".env" in said and "restart" in said
    got = _resolved(tmp_path, ["CORP_UI_PORT"])
    assert got["CORP_UI_PORT"] == ["8999", "dotenv"]


def test_both_layers_in_one_call(tmp_path):
    """The routing is per key, not per call — which is exactly the knowledge an operator
    editing .env by hand had to carry themselves."""
    code, said = _run(tmp_path, "set", "CORP_MEMORY_TOP_K=3", "CORP_UI_PORT=8998")
    assert code == 0, said
    got = _resolved(tmp_path, ["CORP_MEMORY_TOP_K", "CORP_UI_PORT"])
    assert got["CORP_MEMORY_TOP_K"][1] == "db"
    assert got["CORP_UI_PORT"][1] == "dotenv"


def test_it_refuses_what_the_console_refuses(tmp_path):
    """Same registry, same message. A registry only one caller consults is a registry that
    drifts, and this project has the receipts."""
    code, said = _run(tmp_path, "set", "CORP_MEMORY_TOP_K=banana")
    assert code == 0
    assert "expected a whole number" in said and "banana" in said
    assert _resolved(tmp_path, ["CORP_MEMORY_TOP_K"])["CORP_MEMORY_TOP_K"][0] == ""


def test_an_unknown_key_is_named_rather_than_written(tmp_path):
    code, said = _run(tmp_path, "set", "CORP_NOT_A_SETTING=1")
    assert "unknown setting" in said and "CORP_NOT_A_SETTING" in said


def test_a_malformed_pair_says_so(tmp_path):
    code, said = _run(tmp_path, "set", "CORP_MEMORY_TOP_K")
    assert "expected KEY=value" in said


def test_clearing_lets_the_layer_below_show_through(tmp_path):
    _run(tmp_path, "set", "CORP_MEMORY_TOP_K=9")
    assert _resolved(tmp_path, ["CORP_MEMORY_TOP_K"])["CORP_MEMORY_TOP_K"] == ["9", "db"]
    code, said = _run(tmp_path, "set", "--unset", "CORP_MEMORY_TOP_K", "CORP_MEMORY_MAX=100")
    assert "cleared" in said, said
    assert _resolved(tmp_path, ["CORP_MEMORY_TOP_K"])["CORP_MEMORY_TOP_K"][1] == "default"


# --- the service, called directly ----------------------------------------------


def test_the_service_raises_the_failure_not_a_status_code(tmp_path):
    """The rule that makes it shareable. A newline in a value is refused — and refused as
    `LineBreakRefused`, which a terminal can print and the console can turn into a 400. Raising
    the console's own exception would have made the console the only possible caller."""
    store = Store(str(tmp_path / "data"))
    try:
        with pytest.raises(dotenv.LineBreakRefused):
            app_settings.persist(
                store, tmp_path / ".env", {"CORP_UI_TOKEN": "a\nCORP_UI_ALLOWED_HOSTS=evil"}
            )
        assert "evil" not in (tmp_path / ".env").read_text(encoding="utf-8")
    finally:
        store.close()


def test_the_service_takes_a_store_and_a_path_not_a_console(tmp_path):
    """Stated as a test because it is the entire reason this move happened. `UiState` in the
    signature is what kept the command line out."""
    import inspect

    params = list(inspect.signature(app_settings.persist).parameters)
    assert params[:2] == ["store", "env_file"], params


def test_shadowing_is_reported_rather_than_ignored(tmp_path, monkeypatch):
    """The process environment outranks both layers. A value written into a shadow is not an
    error, but an operator who is not told will read the setting as broken — the same honesty
    contract the console's read-only badge makes."""
    monkeypatch.setenv("CORP_MEMORY_TOP_K", "1")
    store = Store(str(tmp_path / "data"))
    try:
        meta = app_settings.persist(store, tmp_path / ".env", {"CORP_MEMORY_TOP_K": "7"})
        assert meta["shadowed"] == ["CORP_MEMORY_TOP_K"]
    finally:
        store.close()


# --- in the same process, so the coverage is real ------------------------------
#
# The subprocess tests above prove the contract that matters — a value written by one process
# is resolved by the next, from the right layer. What they cannot do is show `coverage` the
# body of `cmd_set`, because it runs somewhere else. Both are worth having: one proves the
# behaviour across a boundary, the other proves the lines were executed at all.


def _args(pairs, unset=""):
    from types import SimpleNamespace

    return SimpleNamespace(pairs=pairs, unset=unset)


def test_the_command_body_reports_both_layers(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    from corparius import cli
    from corparius.config import cfg

    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    cli.cmd_set(_args(["CORP_MEMORY_TOP_K=4", "CORP_UI_PORT=8997"]))
    said = capsys.readouterr().out
    assert "CORP_MEMORY_TOP_K = 4   -> the store" in said
    assert "CORP_UI_PORT = 8997   -> .env" in said and "restart" in said


def test_the_command_body_prints_a_refusal(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    from corparius import cli

    cli.cmd_set(_args(["CORP_MEMORY_TOP_K=nope"]))
    assert "expected a whole number" in capsys.readouterr().out


def test_the_command_body_says_when_there_is_nothing_to_do(tmp_path, monkeypatch, capsys):
    """An empty value clears, and an empty value for a key that is already unset is nothing.
    Saying so beats reporting a write that did not happen."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    from corparius import cli

    cli.cmd_set(_args(["CORP_MEMORY_TOP_K="]))
    out = capsys.readouterr().out
    assert "cleared" in out or "nothing to write" in out


def test_the_command_body_reports_a_line_break_rather_than_raising(tmp_path, monkeypatch, capsys):
    """The translation the console does with a 400, a terminal does by printing. Neither is the
    service's business, which is why the service raises the failure."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    from corparius import cli
    from corparius.config import cfg

    cfg.set_dotenv_path(tmp_path / ".env")
    cli.cmd_set(_args(["CORP_UI_TOKEN=a\nCORP_UI_ALLOWED_HOSTS=evil.example"]))
    said = capsys.readouterr().out
    assert "line break is not allowed" in said
    if (tmp_path / ".env").is_file():
        assert "evil.example" not in (tmp_path / ".env").read_text(encoding="utf-8")
