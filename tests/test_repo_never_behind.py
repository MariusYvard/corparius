"""The copy that fell behind, and why sending the operator to a terminal was the wrong answer.

Reported from a real install, and the two sides were **both corparius**:

```text
    local   vigil: automatic commit after 6 tick(s)   documents/written/{competitor-scan,
                                                      design-brief,end-of-day}.md
    remote  vigil: automatic commit after 3 tick(s)   documents/written/end-of-day.md
```

Sequential runs, not simultaneous ones, colliding on the end-of-day summary the CEO rewrites daily.
`sync` pushed at the end of a day and nothing ever fetched at the start, so the second run wrote its
day on a stale base and then had two rewritten copies of one generated document to reconcile. The
notice ended with `Resolve it by hand: git pull --rebase in C:\\...` — a product asking somebody who
chose a console to open a terminal and arbitrate between two things they had not written.

Three changes, in the order that matters:

1. **Refresh before working.** The fix for the class rather than the occurrence: a day written on top
   of what the remote already has is an ordinary edit with one parent, and there is nothing to
   reconcile at the end.
2. **Corparius settles what it wrote itself.** `documents/written/` is the one directory it alone
   writes, so choosing a side there is choosing between two of its own outputs.
3. **A choice, in the console, for anything else.** `company.yaml` is the operator's, and picking a
   version for them would overwrite a decision made on another machine — so the decision comes back,
   and only the decision. The fetching, the rebasing and the push stay corparius's job.

The `-X` flag is inverted from how it reads and is measured rather than remembered: during a rebase
"ours" is the branch being replayed *onto* (the remote) and "theirs" is the commit being replayed
(this machine's). Reading it the other way round would discard the run that just finished.
"""

import pathlib
import subprocess

import pytest

from corparius.config import cfg
from corparius.providers import companyrepo

needs_git = pytest.mark.skipif(not companyrepo.git_available(), reason="git is not on PATH")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cfg.invalidate()
    company = tmp_path / "companies" / "acme"
    company.mkdir(parents=True)
    (company / "company.yaml").write_text("slug: acme\n", encoding="utf-8")
    return tmp_path


def _origin(tmp_path):
    """A company with a real remote, both on disk. No network: the defect is entirely about what git
    does with two histories, so a bare repository beside it reproduces it exactly."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    path = companyrepo.ensure_repo("acme")
    companyrepo._git(["remote", "add", "origin", str(bare)], path)
    written = pathlib.Path(path) / "documents" / "written"
    written.mkdir(parents=True, exist_ok=True)
    (written / "end-of-day.md").write_text("day zero\n", encoding="utf-8")
    companyrepo._git(["add", "."], path)
    companyrepo._git(["commit", "-q", "-m", "base"], path)
    companyrepo._git(["push", "-q", "origin", "main"], path)
    return pathlib.Path(path), bare


def _remote_writes(tmp_path, bare, relative: str, text: str, label: str = "remote run"):
    """Another machine ran a day and pushed. A second clone rather than a fake."""
    other = tmp_path / f"other-{relative.replace('/', '-')}"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)
    target = other / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    companyrepo._git(["add", "."], str(other))
    companyrepo._git(["commit", "-q", "-m", label], str(other))
    companyrepo._git(["push", "-q", "origin", "main"], str(other))


# --- 1. get current before working ------------------------------------------------


@needs_git
def test_refreshing_first_is_what_stops_the_conflict_happening(home, tmp_path):
    """The whole class, removed rather than handled. The remote moved and this copy has not written
    its day yet, so bringing it up to date now means the day lands on top and the push at the end has
    nothing to reconcile."""
    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "documents/written/end-of-day.md", "remote day\n")

    out = companyrepo.refresh("acme")
    assert out["ok"] is True and out["updated"] is True, out
    assert (path / "documents" / "written" / "end-of-day.md").read_text(encoding="utf-8") == (
        "remote day\n"
    )

    (path / "documents" / "written" / "end-of-day.md").write_text("local day\n", encoding="utf-8")
    done = companyrepo.sync("acme", "acme: automatic commit after 6 tick(s)")
    assert done["pushed"] is True, done
    assert done.get("recovered") is not True, "it still had to recover from a divergence"


@needs_git
def test_a_refresh_on_a_copy_already_current_changes_nothing(home, tmp_path):
    """Runs happen every few hours and most find nothing. `updated` has to distinguish "brought up to
    date" from "was already", or the log says something happened on every launch and stops being
    read."""
    _origin(tmp_path)
    out = companyrepo.refresh("acme")
    assert out["ok"] is True and out["updated"] is False, out


@needs_git
def test_a_refresh_never_touches_uncommitted_work(home, tmp_path):
    """A backup step is not allowed to move an operator's files around underneath them. A rebase
    would autostash and replay them — a correct git operation, and the wrong thing to do unattended
    at the start of a day."""
    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "documents/written/end-of-day.md", "remote day\n")
    (path / "company.yaml").write_text("slug: acme\nname: half typed\n", encoding="utf-8")

    out = companyrepo.refresh("acme")
    assert out["updated"] is False and "uncommitted" in out["error"]
    assert "half typed" in (path / "company.yaml").read_text(encoding="utf-8")


# --- 2. what corparius wrote, corparius settles -----------------------------------


@needs_git
def test_two_generated_summaries_are_reconciled_without_anyone_being_asked(home, tmp_path):
    """The occurrence itself. `documents.write` puts every agent's output under
    `documents/written/` and an operator's upload lands in the folder root instead, so both versions
    here are corparius's own and choosing between them is not the operator's decision to make."""
    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "documents/written/end-of-day.md", "the remote's summary\n")
    (path / "documents" / "written" / "end-of-day.md").write_text(
        "the summary this run wrote\n", encoding="utf-8"
    )

    done = companyrepo.sync("acme", "acme: automatic commit after 6 tick(s)")
    assert done["pushed"] is True, done
    assert done["recovered"] is True
    assert "end-of-day.md" in done.get("note", ""), "a silent resolution is an unreadable one"
    assert (path / "documents" / "written" / "end-of-day.md").read_text(encoding="utf-8") == (
        "the summary this run wrote\n"
    ), "the finished run lost to the older one; the -X flag is the wrong way round"


@needs_git
def test_the_version_that_lost_is_still_in_the_history(home, tmp_path):
    """Archive, never erase — the rule the skill curator already follows. What makes an automatic
    resolution acceptable is that it supersedes rather than deletes, and the report names the file so
    an operator who wants the other version knows there is one to want."""
    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "documents/written/end-of-day.md", "the remote's summary\n")
    (path / "documents" / "written" / "end-of-day.md").write_text("this run's\n", encoding="utf-8")
    companyrepo.sync("acme", "acme: automatic commit after 6 tick(s)")

    log = companyrepo._git(["log", "--oneline", "--all"], str(path)).stdout
    assert "remote run" in log, "the other machine's commit was dropped from history"
    older = companyrepo._git(
        ["show", "HEAD~1:documents/written/end-of-day.md"], str(path), check=False
    )
    assert "the remote's summary" in older.stdout


# --- 3. the operator's own files: a choice, and never a terminal ------------------


@needs_git
def test_a_conflict_the_operator_wrote_is_not_decided_for_them(home, tmp_path):
    """The line the automatic path stops at. Two versions of `company.yaml` are two decisions a
    person made, and picking one silently would overwrite a configuration change from another
    machine — which is the one thing worse than an unpushed commit."""
    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "company.yaml", "slug: acme\nname: From the other machine\n")
    (path / "company.yaml").write_text("slug: acme\nname: From this machine\n", encoding="utf-8")

    done = companyrepo.sync("acme", "acme: automatic commit after 6 tick(s)")
    assert done["pushed"] is False
    assert "company.yaml" in done["error"], done["error"]
    assert "From this machine" in (path / "company.yaml").read_text(encoding="utf-8")


@needs_git
def test_the_conflicting_files_can_be_listed_without_changing_anything(home, tmp_path):
    """What the console puts in front of the operator. A choice that said "some files conflict"
    would be a choice made blind, and asking has to be free of side effects: this runs while a notice
    is being written, not while anything is being decided."""
    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "company.yaml", "slug: acme\nname: other\n")
    (path / "company.yaml").write_text("slug: acme\nname: mine\n", encoding="utf-8")
    companyrepo.sync("acme", "acme: automatic commit after 6 tick(s)")

    before = companyrepo._git(["rev-parse", "HEAD"], str(path)).stdout.strip()
    assert companyrepo.conflicting_paths("acme") == ["company.yaml"]
    assert companyrepo._git(["rev-parse", "HEAD"], str(path)).stdout.strip() == before
    assert companyrepo.dirty("acme") is False


@needs_git
@pytest.mark.parametrize(
    ("keep", "expected"),
    [("mine", "name: mine\n"), ("theirs", "name: other\n")],
)
def test_the_operator_settles_it_from_the_console_and_git_is_never_typed(
    home, tmp_path, keep, expected
):
    """The point of the whole change. They choose which version of their own file survives; corparius
    does the fetching, the rebasing, the strategy flag and the push.

    Both directions are asserted because the `-X` flag is inverted during a rebase, so a single
    parametrisation would pass while doing the opposite of what was asked half the time.
    """
    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "company.yaml", "slug: acme\nname: other\n")
    (path / "company.yaml").write_text("slug: acme\nname: mine\n", encoding="utf-8")
    companyrepo.sync("acme", "acme: automatic commit after 6 tick(s)")

    out = companyrepo.resolve("acme", keep=keep)
    assert out["ok"] is True and out["pushed"] is True, out
    assert (path / "company.yaml").read_text(encoding="utf-8").endswith(expected)
    # And it is actually on the remote, which is the only thing the operator cared about.
    assert (
        companyrepo._git(["rev-list", "--count", "HEAD...origin/main"], str(path)).stdout.strip()
        == "0"
    )


@needs_git
def test_an_unknown_choice_is_refused_rather_than_guessed(home, tmp_path):
    """This endpoint is reachable from a browser and its argument decides which version of a file
    survives. A value it does not understand must not fall through to a default."""
    _origin(tmp_path)
    out = companyrepo.resolve("acme", keep="whichever")
    assert out["ok"] is False and "whichever" in out["error"]


@needs_git
def test_the_repository_is_left_usable_when_it_gives_up(home, tmp_path):
    """Leaving a folder mid-rebase would be worse than the unpushed commit it was trying to fix: the
    next run would find a detached head and fail in a way nobody could read."""
    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "company.yaml", "slug: acme\nname: other\n")
    (path / "company.yaml").write_text("slug: acme\nname: mine\n", encoding="utf-8")
    companyrepo.sync("acme", "acme: automatic commit after 6 tick(s)")

    assert companyrepo.dirty("acme") is False, "left with a half-applied rebase"
    head = companyrepo._git(["symbolic-ref", "--short", "HEAD"], str(path), check=False)
    assert head.stdout.strip() == "main", "left on a detached head"


# --- and the sentence that started it --------------------------------------------


def test_no_notice_tells_the_operator_to_run_git():
    """The message this whole file exists to delete. `tests/test_inbox_remedy.py` already forbids a
    notice naming a terminal command in general; this names the one that shipped, because a rule with
    no example of what it caught is a rule nobody reconsiders when it starts failing."""
    source = pathlib.Path("corparius/orchestrator.py").read_text(encoding="utf-8")
    notice = source[source.index("REPO_BEHIND") : source.index("def _repo_clashes")]
    assert "git pull" not in notice
    assert "--rebase" not in notice


# --- the two callers, which the console reaches and the suite did not ---------------


@needs_git
def test_a_run_brings_the_copy_up_to_date_before_it_starts(home, tmp_path, monkeypatch):
    """`Runtime.run` calls this first, and that call is the fix for the class. Asserted through the
    orchestrator rather than on `refresh` alone: the wiring is the part that was missing, and a
    provider function nothing calls is the shape this codebase keeps finding in itself."""
    from corparius.orchestrator import Runtime

    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "documents/written/end-of-day.md", "remote day\n")
    monkeypatch.setenv("CORP_REPO_AUTOCOMMIT", "true")
    from corparius.config import cfg as cfg_mod

    cfg_mod.invalidate()

    runtime = Runtime.__new__(Runtime)
    runtime._refresh_repo("acme")

    assert (path / "documents" / "written" / "end-of-day.md").read_text(encoding="utf-8") == (
        "remote day\n"
    )


def test_a_repository_that_cannot_be_reached_never_stops_a_day(home, monkeypatch):
    """Same silence rule as the commit at the other end of the run. A backup step is not allowed to
    be the reason a company does no work, so this reports at info and carries on — including when
    the provider raises something nobody predicted."""
    from corparius.orchestrator import Runtime
    from corparius.providers import companyrepo as repo_mod

    monkeypatch.setenv("CORP_REPO_AUTOCOMMIT", "true")
    from corparius.config import cfg as cfg_mod

    cfg_mod.invalidate()
    monkeypatch.setattr(
        repo_mod, "refresh", lambda slug: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    runtime = Runtime.__new__(Runtime)
    runtime._refresh_repo("acme")  # must not raise


def test_no_autocommit_means_no_fetch_at_all(home, monkeypatch):
    """An operator who never asked for versioning must not have their folder touched, and must not
    pay a network round trip at the start of every run for a feature they turned off."""
    from corparius.orchestrator import Runtime
    from corparius.providers import companyrepo as repo_mod

    monkeypatch.setenv("CORP_REPO_AUTOCOMMIT", "false")
    from corparius.config import cfg as cfg_mod

    cfg_mod.invalidate()
    monkeypatch.setattr(
        repo_mod, "refresh", lambda slug: pytest.fail("a repository was fetched anyway")
    )
    Runtime.__new__(Runtime)._refresh_repo("acme")


@needs_git
def test_the_notice_lists_the_files_the_operator_is_being_asked_about(home, tmp_path):
    """A choice that said "some files conflict" would be a choice made blind. `_repo_clashes` is
    what puts the names in front of them, and it must never be the reason a notice fails to be
    written: a list it could not produce costs the notice a button, not its existence."""
    from corparius.orchestrator import Runtime

    path, bare = _origin(tmp_path)
    _remote_writes(tmp_path, bare, "company.yaml", "slug: acme\nname: other\n")
    (path / "company.yaml").write_text("slug: acme\nname: mine\n", encoding="utf-8")
    companyrepo.sync("acme", "acme: automatic commit after 6 tick(s)")

    runtime = Runtime.__new__(Runtime)
    assert runtime._repo_clashes("acme") == ["company.yaml"]


def test_listing_the_clashes_never_takes_the_notice_down(home, monkeypatch):
    from corparius.orchestrator import Runtime
    from corparius.providers import companyrepo as repo_mod

    monkeypatch.setattr(
        repo_mod, "conflicting_paths", lambda slug: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert Runtime.__new__(Runtime)._repo_clashes("acme") == []
