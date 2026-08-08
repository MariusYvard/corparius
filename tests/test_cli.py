"""The CLI is the whole entry point and had no test at all: 248 lines, thirteen
commands, and the only thing exercising them was an operator typing.

main() takes argv, so every command runs in-process here - no subprocess, no
frozen binary. cli.settings is a module-level singleton captured at import, so
it is patched rather than the environment: setting CORP_DATA_PATH after import
would not move it.
"""

import json
import sys
from pathlib import Path

import pytest

from corparius import cli
from corparius.config.settings import Settings
from corparius.store import Store

COMPANY = """
slug: t
name: T
offer: {product: p, price_eur: 9}
icp: {segment: seg, channels: [linkedin], pains: [pain]}
agents: {ceo: true, social: true, finance: true, ads: false, coder: false}
budgets: {session_tokens: 20000, tokens_per_minute: 20000}
hitl_tools: [send_financial_transaction]
"""


@pytest.fixture()
def cfg_path(tmp_path, monkeypatch):
    """A company file plus a data path the CLI's captured settings point at."""
    path = tmp_path / "company.yaml"
    path.write_text(COMPANY, encoding="utf-8")
    settings = Settings()
    settings.data_path = str(tmp_path / "data")
    settings.llm_mock = True
    monkeypatch.setattr(cli, "settings", settings)
    return str(path)


def _store(cfg_path):
    return Store(str(__import__("pathlib").Path(cfg_path).parent / "data"))


# --- config resolution ----------------------------------------------------


def test_a_missing_company_exits_with_a_message(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["status", "--company", "definitely-not-a-company"])
    assert "not found" in str(exc.value)


def test_malformed_yaml_exits_with_a_message(tmp_path, monkeypatch):
    bad = tmp_path / "company.yaml"
    bad.write_text("just a string, not a mapping", encoding="utf-8")
    settings = Settings()
    settings.data_path = str(tmp_path / "data")
    monkeypatch.setattr(cli, "settings", settings)
    with pytest.raises(SystemExit) as exc:
        cli.main(["status", "--company", str(bad)])
    assert "expected a mapping" in str(exc.value)


# --- commands -------------------------------------------------------------


def test_init_seeds_the_clock(cfg_path, capsys):
    cli.main(["init", "--company", cfg_path])
    out = capsys.readouterr().out
    assert "initialised T (t)" in out and "ceo" in out
    assert _store(cfg_path).load_state("t")["tick"] == 0


def test_run_reports_json(cfg_path, capsys):
    cli.main(["init", "--company", cfg_path])
    capsys.readouterr()
    cli.main(["run", "--company", cfg_path, "--ticks", "4"])
    result = json.loads(capsys.readouterr().out)
    assert result["ticks_run"] == 4
    assert _store(cfg_path).status("t")["actions"] > 0


def test_status_reports_the_clock_and_the_work(cfg_path, capsys):
    cli.main(["init", "--company", cfg_path])
    cli.main(["run", "--company", cfg_path, "--ticks", "2"])
    capsys.readouterr()
    cli.main(["status", "--company", cfg_path])
    out = capsys.readouterr().out
    assert "== T (t) ==" in out and "clock: tick" in out and "actions:" in out


def test_tasks_says_so_when_empty(cfg_path, capsys):
    cli.main(["tasks", "--company", cfg_path])
    assert "no tasks" in capsys.readouterr().out


def test_task_edit_and_approve(cfg_path, capsys):
    task_id = _store(cfg_path).add_task("t", "a task", "social", status="proposed")
    cli.main(
        [
            "task",
            "--company",
            cfg_path,
            "--id",
            str(task_id),
            "--title",
            "renamed",
            "--priority",
            "3",
            "--approve",
        ]
    )
    said = capsys.readouterr().out
    assert f"task {task_id}" in said and "approved" in said
    # It names what changed now, rather than saying "updated" whatever happened.
    assert "title" in said and "priority" in said
    row = _store(cfg_path).list_tasks("t")[0]
    assert row["title"] == "renamed" and row["priority"] == 3
    assert row["status"] == "approved" and "via CLI" in row["note"]
    # The assertion this test was missing, and the bug it would have caught: approving from
    # the command line went straight to `store.update_task`, so it skipped `executable_fields`
    # and left the task with no tool. It then closed "done (no tool mapped)" having done
    # nothing, the condition survived, and the agent proposed the same work again.
    assert row["tool"] == "draft_social_post", "approval must leave the task executable"


def test_task_reject(cfg_path, capsys):
    task_id = _store(cfg_path).add_task("t", "a task", "social", status="proposed")
    cli.main(["task", "--company", cfg_path, "--id", str(task_id), "--reject"])
    assert _store(cfg_path).list_tasks("t")[0]["status"] == "rejected"


def test_tasks_lists_what_was_added(cfg_path, capsys):
    _store(cfg_path).add_task("t", "ship it", "design", tool="build_sales_site")
    cli.main(["tasks", "--company", cfg_path])
    out = capsys.readouterr().out
    assert "ship it" in out and "build_sales_site" in out and "design" in out


def test_board_prints_every_column(cfg_path, capsys):
    _store(cfg_path).add_task("t", "a", "social", status="done")
    cli.main(["board", "--company", cfg_path])
    out = capsys.readouterr().out
    for column in ("proposed", "approved", "in_progress", "done", "rejected"):
        assert column in out


def test_flow_reports_metrics(cfg_path, capsys):
    _store(cfg_path).add_task("t", "a", "social", status="done")
    cli.main(["flow", "--company", cfg_path])
    out = capsys.readouterr().out
    assert "throughput(done): 1" in out and "waste:" in out


def test_site_builds(cfg_path, capsys):
    cli.main(["site", "--company", cfg_path, "--headline", "Hire faster"])
    out = capsys.readouterr().out
    assert "sales site built" in out
    assert "Hire faster" in (
        __import__("pathlib").Path(out.split(": ", 1)[1].strip()).read_text(encoding="utf-8")
    )


def test_deploy_builds_the_site_if_missing(cfg_path, capsys):
    cli.main(["deploy", "--company", cfg_path])
    assert "deployed: local" in capsys.readouterr().out


def test_backup_prints_the_plaintext_warning(cfg_path, tmp_path, capsys):
    """The zip carries the console's API keys in the clear, so the CLI has to
    say so every time rather than only in the docs."""
    from corparius import backup

    cli.main(["backup", "--out", str(tmp_path / "out")])  # backup is company-wide
    out = capsys.readouterr().out
    assert "backup written" in out and backup.WARNING_EN in out


# --- approvals ------------------------------------------------------------


def test_approvals_reports_nothing_pending(cfg_path, capsys):
    cli.main(["approvals", "--company", cfg_path])
    assert "no pending approvals" in capsys.readouterr().out


def test_approve_and_reject_by_id(cfg_path, capsys):
    from corparius.kernel.records import ApprovalRequest

    store = _store(cfg_path)
    store.add_approval(
        ApprovalRequest(
            id="pay-1",
            company="t",
            agent="finance",
            tool="send_financial_transaction",
            parameters={"amount": 12},
            ts=1.0,
        )
    )
    cli.main(["approvals", "--company", cfg_path])
    assert "pay-1" in capsys.readouterr().out

    cli.main(["approve", "--company", cfg_path, "--id", "pay-1", "--note", "fine"])
    assert "pay-1 -> approved" in capsys.readouterr().out
    assert (
        _store(cfg_path).find_approval("t", "send_financial_transaction", {"amount": 12})["status"]
        == "approved"
    )

    cli.main(["reject", "--company", cfg_path, "--id", "pay-1"])
    assert "pay-1 -> rejected" in capsys.readouterr().out


def test_an_unknown_approval_id_is_reported_not_silent(cfg_path, capsys):
    cli.main(["approve", "--company", cfg_path, "--id", "nope"])
    assert "not found" in capsys.readouterr().out


# --- commands that exit ---------------------------------------------------


def test_doctor_exits_with_its_own_status(cfg_path, monkeypatch):
    monkeypatch.setattr("corparius.doctor.main", lambda quiet=False: 0)
    with pytest.raises(SystemExit) as exc:
        cli.main(["doctor", "--quiet"])
    assert exc.value.code == 0


def test_ui_hands_its_exit_code_back(monkeypatch):
    """serve() returns 1 when the port is taken; the CLI must not swallow it.

    The patch names `corparius.api.serve`, not `corparius.api.server.serve`, and the difference
    is not cosmetic: `cmd_ui` does `from .api import serve`, which resolves the attribute on the
    package. Aimed one module too deep during the split, this test passed anyway — the real
    `serve` ran and returned 1 because port 8600 happened to be in use. A green test measuring
    nothing, which is the shape this suite exists to refuse.
    """
    monkeypatch.setattr("corparius.api.serve", lambda s, host=None, port=None: 1)
    with pytest.raises(SystemExit) as exc:
        cli.main(["ui", "--port", "8601"])
    assert exc.value.code == 1


def test_no_subcommand_is_an_error_not_a_traceback(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code != 0


def test_bench_measures_prints_and_caches(tmp_path, monkeypatch, capsys):
    from corparius.providers import hardware

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(
        hardware, "installed_models", lambda **k: [{"name": "gemma:2b", "size": 1_680_000_000}]
    )
    monkeypatch.setattr(
        hardware,
        "measure",
        lambda model, **k: {
            "ok": True,
            "model": model,
            "tokens_per_second": 8.6,
            "load_seconds": 6.9,
            "placement": "cpu",
            "detail": "",
        },
    )
    cli.main(["bench"])
    out = capsys.readouterr().out
    assert "8.6 tokens/s" in out and "CPU" in out
    assert "512-token draft" in out, "the arithmetic, not just the threshold"
    assert Store(str(tmp_path)).load_machine()["tokens_per_second"] == 8.6


def test_bench_json_carries_the_verdict_not_only_the_numbers(tmp_path, monkeypatch, capsys):
    """A script that re-derives "fast enough" from tokens_per_second will derive
    it differently from the router, and then the two disagree."""
    from corparius.providers import hardware

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(hardware, "installed_models", lambda **k: [{"name": "m", "size": 1}])
    monkeypatch.setattr(
        hardware,
        "measure",
        lambda model, **k: {
            "ok": True,
            "model": model,
            "tokens_per_second": 40.0,
            "load_seconds": 1.0,
            "placement": "gpu",
            "detail": "",
        },
    )
    cli.main(["bench", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["tokens_per_second"] == 40.0 and data["local_model"] == "m"
    assert "40.0 tokens/s" in data["reason"]


def test_bench_exits_nonzero_when_there_is_nothing_to_measure(monkeypatch, capsys):
    from corparius.providers import hardware

    monkeypatch.setattr(hardware, "installed_models", lambda **k: [])
    with pytest.raises(SystemExit) as exc:
        cli.main(["bench"])
    assert exc.value.code == 1
    assert "Nothing to measure" in capsys.readouterr().out


# --- corparius skills ------------------------------------------------------
def test_skills_list_names_what_rides_on_every_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    shared = tmp_path / "skills" / "house-voice"
    shared.mkdir(parents=True)
    (shared / "SKILL.md").write_text(
        "---\nname: house-voice\ndescription: how we write\n---\nShort sentences.",
        encoding="utf-8",
    )
    cli.main(["skills", "list"])
    out = capsys.readouterr().out
    assert "house-voice" in out and "EVERY TOOL" in out
    assert "ride on EVERY prompt" in out


def test_skills_import_refuses_a_tool_that_does_not_exist(tmp_path, monkeypatch, capsys):
    """A skill naming a missing tool is parsed and then never applies. Letting
    --tools write one would hand the operator a file that does nothing."""
    src = tmp_path / "incoming"
    src.mkdir()
    (src / "SKILL.md").write_text("---\nname: x\ndescription: d\n---\nbody", encoding="utf-8")
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    with pytest.raises(SystemExit):
        cli.main(["skills", "import", str(src), "--tools", "not_a_tool"])
    assert not (tmp_path / "skills" / "x").exists(), "a refusal must not have written first"


def test_skills_import_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    src = tmp_path / "incoming"
    src.mkdir()
    (src / "SKILL.md").write_text(
        "---\nname: draft-response\ndescription: d\n---\nbody", encoding="utf-8"
    )
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cli.main(["skills", "import", str(src), "--dry-run"])
    out = capsys.readouterr().out
    assert "would write" in out and "draft_support_reply" in out
    assert not (tmp_path / "skills" / "draft-response").exists()


def test_skills_import_says_loudly_when_nothing_here_does_that_job(tmp_path, monkeypatch, capsys):
    src = tmp_path / "incoming"
    src.mkdir()
    (src / "SKILL.md").write_text(
        "---\nname: sox-testing\ndescription: d\n---\nbody", encoding="utf-8"
    )
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cli.main(["skills", "import", str(src)])
    out = capsys.readouterr().out
    assert "NO allowed-tools" in out and "every turn" in out
    written = (tmp_path / "skills" / "sox-testing" / "SKILL.md").read_text(encoding="utf-8")
    assert "allowed-tools:\n" in written, "no scope must be invented"


def test_skills_install_starter_lands_scoped_and_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cli.main(["skills", "install", "starter"])
    first = capsys.readouterr().out
    # Counted from what is actually shipped, not a literal that has to be edited
    # every time a skill is added. What matters is that install lands all of
    # them, not that the number is any particular value.
    shipped = len(list(Path("packaging/skill-pack-starter/skills").glob("*/SKILL.md")))
    assert f"{shipped} skill(s)" in first
    cli.main(["skills", "list"])
    listed = capsys.readouterr().out
    assert "EVERY TOOL" not in listed, "a shipped skill must never be unscoped"
    assert "ride on EVERY prompt" not in listed

    # Run twice: an operator who edited one must not lose it to a reinstall.
    edited = tmp_path / "skills" / "social-cadence" / "SKILL.md"
    edited.write_text("---\nname: social-cadence\nallowed-tools: schedule_post\n---\nmine\n")
    cli.main(["skills", "install", "starter"])
    assert "kept your own social-cadence" in capsys.readouterr().out
    assert edited.read_text().endswith("mine\n")


def test_skills_install_refuses_a_pack_that_does_not_ship(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    with pytest.raises(SystemExit):
        cli.main(["skills", "install", "nope"])


# --- corparius apps --------------------------------------------------------
def _seed_app(home, name="faq", **over):
    import yaml

    d = home / "companies" / "t" / "apps"
    d.mkdir(parents=True, exist_ok=True)
    body = {"name": name, "system": "Answer questions.", "tier": "trivial", **over}
    (d / f"{name}.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")


def test_apps_list_shows_the_ceilings_and_flags_a_missing_origin_list(
    tmp_path, monkeypatch, capsys
):
    """An app with no origins cannot be called from a browser at all, which is
    the safe default and the one most likely to look like a bug later."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    _seed_app(tmp_path, daily_tokens=20000, rate_per_minute=6)
    cli.main(["apps", "list", "--company", "t"])
    out = capsys.readouterr().out
    assert "faq" in out and "20000 tok/day" in out and "NO origin list" in out


def test_apps_list_says_where_to_write_one_when_there_are_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cli.main(["apps", "list", "--company", "t"])
    assert "companies/t/apps/" in capsys.readouterr().out


def test_apps_run_prints_the_answer_and_what_it_spent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    _seed_app(tmp_path)
    cli.main(["apps", "run", "faq", "--company", "t", "--input", "how much?"])
    out = capsys.readouterr().out
    assert "how much?" in out, "mock mode echoes, which is enough to prove the wiring"
    assert "/50000 today" in out, "the day's ceiling has to be visible while trying it"


def test_apps_run_refuses_past_the_daily_ceiling_without_calling_a_model(
    tmp_path, monkeypatch, capsys
):
    """The ceiling has to hold before the call, not after: refusing afterwards
    would already have spent the tokens it was there to protect."""
    from corparius import apps as apps_mod

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    _seed_app(tmp_path, daily_tokens=100)

    def explode(*a, **k):
        raise AssertionError("the model was called past the ceiling")

    monkeypatch.setattr(apps_mod, "run", explode)
    Store(str(tmp_path / "data")).record_usage("t", "app:faq", 90, 20)
    with pytest.raises(SystemExit) as exc:
        cli.main(["apps", "run", "faq", "--company", "t", "--input", "hi"])
    assert "110/100" in str(exc.value)


def test_apps_key_says_it_is_not_a_secret(tmp_path, monkeypatch, capsys):
    """A key a web page sends is readable in the inspector. Printing it without
    saying so would sell it as protection it does not provide."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    _seed_app(tmp_path)
    cli.main(["apps", "key", "faq", "--company", "t"])
    out = capsys.readouterr().out
    assert "CORP_APP_KEY_T_FAQ=" in out
    assert "NOT a secret" in out and "origin list" in out


def test_apps_commands_need_a_company(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    with pytest.raises(SystemExit):
        cli.main(["apps", "list"])


# --- the frozen binary is also the CLI -------------------------------------
def test_the_frozen_launcher_hands_a_subcommand_to_the_cli(monkeypatch, tmp_path):
    """It looked at argv for exactly one string, `--no-browser`, and served the
    console whatever else was there. So `corparius doctor` started the console,
    and every command the docs tell an operator to run did not exist for anyone
    who downloaded the binary — which is the install path the README puts
    first. The starter skill pack even rides inside the executable, with
    nothing able to ask for it.
    """
    import sys as _sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    try:
        import launcher
    finally:
        sys.path.pop(0)

    seen = {}
    monkeypatch.setattr(launcher, "_prepare_home", lambda: None)
    monkeypatch.setattr("corparius.cli.main", lambda argv: seen.setdefault("argv", argv))
    monkeypatch.setattr(_sys, "argv", ["corparius", "skills", "list"])
    assert launcher.main() == 0
    assert seen["argv"] == ["skills", "list"]


def test_the_frozen_launcher_answers_help_instead_of_opening_a_browser(monkeypatch, tmp_path):
    """Found by building the binary and running it, not by reading the code.
    `corparius.exe --help` fell into "only flags serves the console", so asking
    what the program can do launched a browser — and on this machine it then
    failed on a port already in use and printed an error about ports to someone
    who had asked for help.

    `--no-browser` stays a console flag, because that is what it is for.
    """
    import sys as _sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    try:
        import launcher
    finally:
        sys.path.pop(0)

    monkeypatch.setattr(launcher, "_prepare_home", lambda: None)
    seen: list[list[str]] = []
    monkeypatch.setattr("corparius.cli.main", seen.append)
    for flag in ("--help", "-h", "--version"):
        monkeypatch.setattr(_sys, "argv", ["corparius", flag])
        assert launcher.main() == 0, flag
    assert seen == [["--help"], ["-h"], ["--version"]]

    # ...and the console flag still opens the console: it must reach serve(),
    # never the CLI.
    reached = {}
    monkeypatch.setattr(launcher, "_announce_update", lambda: None)
    monkeypatch.setattr("corparius.doctor.main", lambda quiet=False: None)
    monkeypatch.setattr("corparius.api.serve", lambda *a, **k: reached.setdefault("ui", True))
    monkeypatch.setattr("corparius.cli.main", lambda argv: pytest.fail(f"CLI got {argv}"))
    monkeypatch.setattr(_sys, "argv", ["corparius", "--no-browser"])
    launcher.main()
    assert reached.get("ui")


def test_the_frozen_launcher_still_serves_the_console_with_no_command(monkeypatch):
    """No argument, or only flags: the turnkey path the binary exists for."""
    import sys as _sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    try:
        import launcher
    finally:
        sys.path.pop(0)

    served = {}
    monkeypatch.setattr(launcher, "_prepare_home", lambda: None)
    monkeypatch.setattr(launcher, "_announce_update", lambda: None)
    monkeypatch.setattr("corparius.doctor.main", lambda quiet=False: 0)
    monkeypatch.setattr("corparius.api.serve", lambda s: served.setdefault("served", True) or 0)

    def explode(argv):
        raise AssertionError("a bare launch went to the CLI")

    monkeypatch.setattr("corparius.cli.main", explode)
    for argv in (["corparius"], ["corparius", "--no-browser"]):
        served.clear()
        monkeypatch.setattr(_sys, "argv", argv)
        launcher.main()
        assert served.get("served"), argv


def test_the_frozen_launcher_survives_a_codepage_that_cannot_encode_its_output(monkeypatch):
    """A frozen build writes stdout in the machine's ANSI encoding, and the
    bootloader starts Python before PYTHONUTF8 or PYTHONIOENCODING could change
    that — both were verified ignored. Every character corparius prints encodes
    on a Western Windows, but the em dash and the accented French strings do
    not exist in a Cyrillic codepage: a redirected `doctor --lang fr` would die
    with UnicodeEncodeError instead of printing.
    """
    import io

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    try:
        import launcher
    finally:
        sys.path.pop(0)

    hostile = io.TextIOWrapper(io.BytesIO(), encoding="cp1251", errors="strict")
    monkeypatch.setattr(sys, "stdout", hostile)
    monkeypatch.setattr(sys, "stderr", hostile)
    with pytest.raises(UnicodeEncodeError):
        print("faq — réponse", file=hostile)
    launcher._never_crash_on_a_character()
    print("faq — réponse", file=hostile)  # no raise: the point of the guard
    hostile.flush()


def test_hardening_the_streams_never_raises_on_something_that_is_not_a_stream(monkeypatch):
    """It runs first, before anything else, so it has to be the one line that
    cannot be the reason a launch fails."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    try:
        import launcher
    finally:
        sys.path.pop(0)

    monkeypatch.setattr(sys, "stdout", object())
    monkeypatch.setattr(sys, "stderr", None)
    launcher._never_crash_on_a_character()
