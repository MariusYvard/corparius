"""A company's repository keeps itself up to date, and says when it cannot.

Measured on the owner's install: nine local commits, none on the remote. One commit had
been pushed from elsewhere, the histories diverged, and every automatic push since had
been rejected as a non-fast-forward — **eight runs in a row, in silence**. `sync`
returned `pushed: False` with the reason in a dict, the orchestrator passed the dict up,
and nothing anywhere read it. A repository that quietly stopped being a backup.

These tests use real git repositories on disk, with a bare one as the remote. A stubbed
git would not have caught the thing that went wrong, because what went wrong was git's
own answer to a real divergence.
"""

import shutil
import subprocess

import pytest

from corparius import companyrepo


def _git(args, cwd):
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _commit(path, name, text, message):
    (path / name).write_text(text, encoding="utf-8")
    _git(["add", "."], path)
    _git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message], path)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """A company repo with a bare remote, and a second clone to move the remote from."""
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    remote = tmp_path / "remote.git"
    _git(["init", "--bare", "-b", "main", str(remote)], tmp_path)

    companies = tmp_path / "companies"
    work = companies / "c"
    work.mkdir(parents=True)
    _git(["init", "-b", "main"], work)
    _git(["config", "user.name", "t"], work)
    _git(["config", "user.email", "t@t"], work)
    _commit(work, "company.yaml", "slug: c\nname: C\n", "first")
    _git(["remote", "add", "origin", str(remote)], work)
    _git(["push", "-u", "origin", "main"], work)

    other = tmp_path / "other"
    _git(["clone", str(remote), str(other)], tmp_path)
    _git(["config", "user.name", "o"], other)
    _git(
        [
            "config",
            "user.email",
            "o@o",
        ],
        other,
    )

    monkeypatch.setattr(companyrepo.paths, "companies_dir", lambda: companies)
    return work, other


def test_a_clean_push_reports_itself(repos):
    work, _ = repos
    (work / "note.md").write_text("a", encoding="utf-8")
    res = companyrepo.sync("c", "work")
    assert res["committed"] and res["pushed"] and not res["recovered"]
    assert res["error"] == ""


def test_nothing_to_commit_is_not_a_failure(repos):
    res = companyrepo.sync("c", "work")
    assert res["ok"] and not res["committed"] and not res["pushed"]


def test_a_remote_that_moved_is_rebased_onto_and_pushed(repos):
    """The one failure worth recovering from without asking: the remote moved, the
    local moved, and both sides are wanted. This is exactly the state the owner's
    repository sat in for eight runs."""
    work, other = repos
    _commit(other, "from-elsewhere.md", "b", "elsewhere")
    _git(["push"], other)

    (work / "local.md").write_text("c", encoding="utf-8")
    res = companyrepo.sync("c", "local work")
    assert res["pushed"] is True, res["error"]
    assert res["recovered"] is True, "it should have said it had to recover"
    # Both sides survived.
    assert (work / "from-elsewhere.md").is_file() and (work / "local.md").is_file()
    log = _git(["log", "--oneline"], work).stdout
    assert "elsewhere" in log and "local work" in log


def test_a_real_conflict_is_reported_and_the_repo_left_usable(repos):
    """Leaving a repository mid-rebase would be worse than the unpushed commits it was
    trying to fix: the next run finds a detached head and fails unreadably."""
    work, other = repos
    _commit(other, "company.yaml", "slug: c\nname: Elsewhere\n", "theirs")
    _git(["push"], other)

    (work / "company.yaml").write_text("slug: c\nname: Ours\n", encoding="utf-8")
    res = companyrepo.sync("c", "ours")
    assert res["committed"] is True and res["pushed"] is False
    assert "conflicts" in res["error"] and "git pull --rebase" in res["error"]
    # No rebase in progress, and our own commit is still here.
    assert not (work / ".git" / "rebase-merge").exists()
    assert not (work / ".git" / "rebase-apply").exists()
    assert _git(["status", "--porcelain"], work).stdout.strip() == ""
    assert "Ours" in (work / "company.yaml").read_text(encoding="utf-8")


def test_a_dirty_folder_does_not_block_its_own_backup(repos):
    """`--autostash`: a run that left the folder dirty must still get its work off this
    machine."""
    work, other = repos
    _commit(other, "from-elsewhere.md", "b", "elsewhere")
    _git(["push"], other)
    (work / "tracked.md").write_text("committed", encoding="utf-8")
    companyrepo.sync("c", "first")
    (work / "tracked.md").write_text("changed after the commit", encoding="utf-8")
    (work / "another.md").write_text("new", encoding="utf-8")
    res = companyrepo.sync("c", "second")
    assert res["pushed"] is True, res["error"]


def test_an_authentication_failure_is_not_mistaken_for_a_divergence():
    """Rebasing would do nothing about a credential problem, and trying it would hide
    the real reason behind a second, more confusing one."""
    assert companyrepo._diverged("! [rejected] main -> main (non-fast-forward)")
    assert companyrepo._diverged("Updates were rejected because the remote contains work")
    assert not companyrepo._diverged("fatal: could not read Username for 'https://github.com'")
    assert not companyrepo._diverged("fatal: repository not found")


def test_no_remote_is_stated_rather_than_reported_as_a_push(repos, monkeypatch):
    work, _ = repos
    _git(["remote", "remove", "origin"], work)
    (work / "note.md").write_text("a", encoding="utf-8")
    res = companyrepo.sync("c", "work")
    assert res["committed"] and not res["pushed"] and res["error"] == "no remote"


def test_a_failed_push_reaches_the_operator(tmp_path, monkeypatch):
    """The half that was missing entirely. Eight runs reported it only in a value the
    caller discarded."""
    from corparius import companyrepo as repo_mod
    from corparius import orchestrator
    from corparius.config import Settings
    from corparius.store import Store

    monkeypatch.setattr(repo_mod, "autocommit_enabled", lambda: True)
    monkeypatch.setattr(
        repo_mod,
        "sync",
        lambda slug, msg: {
            "ok": True,
            "committed": True,
            "pushed": False,
            "error": "non-fast-forward",
            "recovered": False,
        },
    )
    s = Settings()
    s.data_path = str(tmp_path)
    store = Store(s.data_path)
    try:
        runtime = orchestrator.Runtime(s, store)
        runtime._autocommit("c", 24)
        titles = [i["title"] for i in store.list_inbox("c", "pending")]
        assert "The company repository is behind" in titles, titles
    finally:
        store.close()
