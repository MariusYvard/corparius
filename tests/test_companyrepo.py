"""A company folder holds the operator's real business: config, skills, notes,
and often the names and addresses of the people it talks to. Versioning it must
never depend on one host, must never expose it publicly, and must never cost a
run that already happened.
"""

import pytest

from corparius import companyrepo
from corparius.companyrepo import GitHubProvider, LocalBareProvider
from corparius.config import cfg

needs_git = pytest.mark.skipif(not companyrepo.git_available(), reason="git is not on PATH")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An isolated writable home holding one company folder, so no test can
    reach the operator's real companies."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cfg.invalidate()
    company = tmp_path / "companies" / "acme"
    (company / "skills").mkdir(parents=True)
    (company / "company.yaml").write_text("slug: acme\n", encoding="utf-8")
    (company / "data").mkdir()
    (company / "data" / "runtime.db").write_text("binary-ish", encoding="utf-8")
    return tmp_path


def test_local_provider_is_always_available():
    """The offline fallback: if this can ever be unavailable, an operator with
    no network and no token has no way to version their company at all."""
    assert LocalBareProvider().available() is True


def test_local_comes_last_so_a_hosted_remote_wins():
    """deploy.py tries `local` first on purpose; here the operator asking for a
    company repository means a hosted one, and local is the fallback. If this
    order ever flips, provisioning would silently stop at a bare repo on the
    same disk and never reach GitHub."""
    order = companyrepo._order()
    assert order[-1] == "local"
    assert order.index("github") < order.index("local")


class _Resp:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


def test_github_asks_for_a_private_repository(monkeypatch):
    """A company folder can carry prospect names and correspondence. `private`
    must be in the request, not left to the account default."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    cfg.invalidate()
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(json or {})
        return _Resp({"private": True, "clone_url": "https://github.com/me/acme.git"})

    monkeypatch.setattr(companyrepo.requests, "post", fake_post)
    url = GitHubProvider().create("acme", "desc")
    assert seen["private"] is True
    assert url == "https://github.com/me/acme.git"


def test_github_refuses_a_repository_that_came_back_public(monkeypatch):
    """Belt and braces on the answer, not just the request. An org policy or a
    future API change could hand back a public repo, and pushing correspondence
    into it is exactly the failure this module exists to prevent."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    cfg.invalidate()
    monkeypatch.setattr(
        companyrepo.requests,
        "post",
        lambda *a, **k: _Resp({"private": False, "clone_url": "https://github.com/me/acme.git"}),
    )
    with pytest.raises(RuntimeError, match="public"):
        GitHubProvider().create("acme", "desc")


def test_github_reuses_an_existing_repository(monkeypatch):
    """Re-running provisioning must land on the same remote. Treating "already
    exists" as a failure would fall through to the next provider and scatter one
    company across two hosts."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    cfg.invalidate()
    monkeypatch.setattr(companyrepo.requests, "post", lambda *a, **k: _Resp(status=422))
    monkeypatch.setattr(companyrepo.requests, "get", lambda *a, **k: _Resp({"login": "me"}))
    assert GitHubProvider().create("acme", "desc") == "https://github.com/me/acme.git"


@needs_git
def test_ensure_repo_is_idempotent_and_never_commits_runtime_state(home):
    """`data/` is a live SQLite store. Committing it means binary churn on every
    tick and, in the framework's own store, API keys in the clear."""
    companyrepo.ensure_repo("acme")
    first = companyrepo._git(["rev-parse", "HEAD"], companyrepo.repo_dir("acme")).stdout.strip()
    companyrepo.ensure_repo("acme")
    again = companyrepo._git(["rev-parse", "HEAD"], companyrepo.repo_dir("acme")).stdout.strip()
    assert first == again

    tracked = companyrepo._git(["ls-files"], companyrepo.repo_dir("acme")).stdout
    assert "company.yaml" in tracked
    assert "data/runtime.db" not in tracked


@needs_git
def test_sync_makes_no_commit_when_nothing_changed(home):
    """An automatic commit per run must stay silent on a run that changed
    nothing, or the history that should show real edits becomes unreadable."""
    companyrepo.ensure_repo("acme")
    res = companyrepo.sync("acme", "nothing to see")
    assert res["ok"] is True
    assert res["committed"] is False


@needs_git
def test_sync_commits_locally_even_with_no_remote(home):
    """Provisioning may not have happened yet, or the network may be down. The
    work still has to be captured on disk."""
    companyrepo.ensure_repo("acme")
    (home / "companies" / "acme" / "skills" / "SKILL.md").write_text("x", encoding="utf-8")
    res = companyrepo.sync("acme", "acme: change")
    assert res["committed"] is True
    assert res["pushed"] is False
    assert res["error"] == "no remote"


@needs_git
def test_sync_never_raises_when_the_push_fails(home):
    """This runs at the end of an autonomous run. An unreachable remote must
    not turn a completed run into an exception."""
    companyrepo.ensure_repo("acme")
    companyrepo._set_remote("acme", str(home / "nowhere.git"))
    (home / "companies" / "acme" / "skills" / "SKILL.md").write_text("x", encoding="utf-8")
    res = companyrepo.sync("acme", "acme: change")
    assert res["committed"] is True
    assert res["pushed"] is False
    assert res["error"]


@needs_git
def test_provision_falls_back_to_a_local_bare_repository(home, monkeypatch):
    """With no host configured at all, provisioning still has to produce a
    working remote. This is the promise of the local provider."""
    monkeypatch.setenv("CORP_REPO_PROVIDERS", "github,local")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("CORP_GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(companyrepo.shutil, "which", lambda name: None if name == "gh" else "git")
    cfg.invalidate()
    res = companyrepo.provision_result("acme")
    assert res["ok"] is True
    assert res["provider"] == "local"
    assert companyrepo.remote_url("acme") == res["remote"]


def test_provision_reports_failure_rather_than_a_false_success(home, monkeypatch):
    """deploy.py learned this the hard way: a formatter that returns a string
    either way makes a total failure look like a success in the log."""
    monkeypatch.setenv("CORP_REPO_PROVIDERS", "gitlab")
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    cfg.invalidate()
    res = companyrepo.provision_result("acme")
    assert res["ok"] is False
    assert res["skipped"] == ["gitlab: not configured"]
    assert "no provider" in companyrepo.provision("acme")


def test_autocommit_is_off_unless_the_operator_asks(monkeypatch):
    """Pushing an operator's business to a remote is not something a framework
    gets to start doing on its own."""
    monkeypatch.delenv("CORP_REPO_AUTOCOMMIT", raising=False)
    cfg.invalidate()
    assert companyrepo.autocommit_enabled() is False
    monkeypatch.setenv("CORP_REPO_AUTOCOMMIT", "true")
    cfg.invalidate()
    assert companyrepo.autocommit_enabled() is True
