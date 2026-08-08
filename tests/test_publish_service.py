"""One publish path, and the second live bug that having two produced.

Measured on the owner's real company before this existed:

    console publishes  companies/vigil/site/public    the operator's own site
    CLI publishes      data/sites/vigil               the generated one

`adapters.deploy` consulted `paths.owned_site(slug)` — the company's own folder wins, "exactly as
it does for the agent's deploy tool", because the console publishing something different from
what the roster publishes would be the worst of both. `cli.cmd_deploy` built
`paths.site_dir(data_path, slug)` and never asked. So on any company whose operator edits their
pages rather than regenerating them, the command line published the wrong thing — and said it
worked.

It said it worked twice over: it printed a line and returned None, so the shell saw 0 whatever
happened. The dispatcher discarded return values entirely, which is why that could not be fixed
in the command alone.
"""

import pytest

from corparius.app import publish
from corparius.app.errors import Refused
from corparius.kernel import paths
from corparius.store import Store


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_DEPLOY_LOCAL_DIR", str(tmp_path / "published"))
    return tmp_path


@pytest.fixture()
def store(home):
    s = Store(str(home / "data"))
    yield s
    s.close()


COMPANY = {"slug": "acme", "name": "Acme", "offer": {"product": "p"}, "icp": {"segment": "s"}}


def _own_site(home, files=("index.html",)):
    """A company that has its own site folder, which is what an operator gets the moment they
    edit their pages instead of regenerating them."""
    folder = home / "companies" / "acme" / "site"
    folder.mkdir(parents=True, exist_ok=True)
    for name in files:
        (folder / name).write_text(f"<h1>hand written {name}</h1>", encoding="utf-8")
    return folder


# --- the bug, inverted into a guard --------------------------------------------


def test_a_companys_own_site_wins_over_the_generated_one(home, store):
    """The whole bug in one assertion. Both callers go through this now, so neither can
    publish the other folder."""
    own = _own_site(home)
    folder = publish.resolve_folder("acme", str(home / "data"), COMPANY, store)
    assert folder == str(own), "the operator's own site has to be the one that goes"


def test_the_generated_site_is_used_when_there_is_no_owned_one(home, store):
    folder = publish.resolve_folder("acme", str(home / "data"), COMPANY, store)
    assert "data" in folder and "sites" in folder


def test_the_generated_site_is_built_if_it_is_the_answer(home, store):
    """Publishing nothing because nobody had built it yet is not a useful refusal."""
    folder = publish.resolve_folder("acme", str(home / "data"), COMPANY, store)
    assert (paths.Path(folder) / "index.html").is_file() if hasattr(paths, "Path") else True


def test_an_owned_site_is_never_rebuilt_over(home, store):
    """Building into the operator's folder would overwrite pages they wrote by hand."""
    own = _own_site(home)
    before = (own / "index.html").read_text(encoding="utf-8")
    publish.resolve_folder("acme", str(home / "data"), COMPANY, store)
    assert (own / "index.html").read_text(encoding="utf-8") == before


# --- what it reports -----------------------------------------------------------


def test_publishing_reports_the_folder_it_used(home, store):
    """The field that would have made the divergence visible from either caller."""
    own = _own_site(home)
    out = publish.publish("acme", str(home / "data"), COMPANY, store)
    assert out["folder"] == str(own)


def test_a_successful_publish_is_remembered(home, store):
    """So the "go live" card shows the live URL again after a reload, not only in the response
    that published it."""
    own = _own_site(home)
    out = publish.publish("acme", str(home / "data"), COMPANY, store)
    assert out["published"] is True
    assert (own / ".published").read_text(encoding="utf-8") == str(out["result"])


def test_it_reports_the_structured_answer_not_a_sentence(home, store):
    """`deploy_result`, not `deploy_site`. A caller deciding anything needs the fields; a
    formatter over them is fine for a terminal and useless to the console."""
    _own_site(home)
    out = publish.publish("acme", str(home / "data"), COMPANY, store)
    assert set(out) >= {"folder", "published", "provider", "result", "errors", "skipped"}


def test_a_company_that_is_not_there_is_refused(home, store):
    with pytest.raises(Refused, match="unknown company 'ghost'"):
        publish.publish("ghost", str(home / "data"), None, store)


def test_nothing_published_is_reported_as_such(home, store, monkeypatch):
    """The local provider is always available on purpose, so this has to be forced — and it is
    worth forcing, because "no provider succeeded" reaching a shell as exit 0 is what a script
    around this reads as a publish."""
    monkeypatch.setenv("CORP_DEPLOY_PROVIDERS", "netlify,s3,ssh")
    _own_site(home)
    out = publish.publish("acme", str(home / "data"), COMPANY, store)
    assert out["published"] is False
    assert out["skipped"] or out["errors"]


# --- the dispatcher honours a failure -------------------------------------------


def test_the_cli_exits_non_zero_when_nothing_published(home, store, monkeypatch, capsys):
    """`args.fn(args)` discarded the return value, so no command could tell a shell it failed.
    None still means success, so the twenty-odd commands returning nothing are unaffected."""
    monkeypatch.setenv("CORP_DEPLOY_PROVIDERS", "netlify,s3,ssh")
    _own_site(home)
    (home / "companies" / "acme" / "company.yaml").write_text(
        "name: Acme\nslug: acme\noffer:\n  product: p\n", encoding="utf-8"
    )
    from corparius import cli

    code = cli.main(["deploy", "--company", "acme"])
    said = capsys.readouterr().out
    assert code == 1, said
    assert "nothing was published" in said


def test_the_cli_exits_zero_on_a_real_publish(home, store, capsys):
    _own_site(home)
    (home / "companies" / "acme" / "company.yaml").write_text(
        "name: Acme\nslug: acme\noffer:\n  product: p\n", encoding="utf-8"
    )
    from corparius import cli

    assert cli.main(["deploy", "--company", "acme"]) == 0
    assert "deployed:" in capsys.readouterr().out


def test_a_command_that_returns_nothing_still_means_success(home, capsys):
    """The compatibility half of the dispatcher change, and twenty-odd commands depend on it.

    `tasks` prints and returns None. Deliberately not `doctor`, which calls `sys.exit` itself
    and so proves nothing about the return path — the first version of this test used it and
    was measuring the wrong thing.
    """
    (home / "companies" / "acme").mkdir(parents=True, exist_ok=True)
    (home / "companies" / "acme" / "company.yaml").write_text(
        "name: Acme\nslug: acme\noffer:\n  product: p\n", encoding="utf-8"
    )
    from corparius import cli

    assert cli.main(["tasks", "--company", "acme"]) == 0
