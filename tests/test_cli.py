"""The CLI is the whole entry point and had no test at all: 248 lines, thirteen
commands, and the only thing exercising them was an operator typing.

main() takes argv, so every command runs in-process here - no subprocess, no
frozen binary. cli.settings is a module-level singleton captured at import, so
it is patched rather than the environment: setting CORP_DATA_PATH after import
would not move it.
"""

import json

import pytest

from app import cli
from app.config import Settings
from app.store import Store

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
    assert f"task {task_id} updated" in capsys.readouterr().out
    row = _store(cfg_path).list_tasks("t")[0]
    assert row["title"] == "renamed" and row["priority"] == 3
    assert row["status"] == "approved" and "via CLI" in row["note"]


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
    from app import backup

    cli.main(["backup", "--out", str(tmp_path / "out")])  # backup is company-wide
    out = capsys.readouterr().out
    assert "backup written" in out and backup.WARNING_EN in out


# --- approvals ------------------------------------------------------------


def test_approvals_reports_nothing_pending(cfg_path, capsys):
    cli.main(["approvals", "--company", cfg_path])
    assert "no pending approvals" in capsys.readouterr().out


def test_approve_and_reject_by_id(cfg_path, capsys):
    from app.models import ApprovalRequest

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
    monkeypatch.setattr("app.doctor.main", lambda quiet=False: 0)
    with pytest.raises(SystemExit) as exc:
        cli.main(["doctor", "--quiet"])
    assert exc.value.code == 0


def test_ui_hands_its_exit_code_back(monkeypatch):
    """serve() returns 1 when the port is taken; the CLI must not swallow it."""
    monkeypatch.setattr("app.webui.serve", lambda s, host=None, port=None: 1)
    with pytest.raises(SystemExit) as exc:
        cli.main(["ui", "--port", "8601"])
    assert exc.value.code == 1


def test_no_subcommand_is_an_error_not_a_traceback(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code != 0
