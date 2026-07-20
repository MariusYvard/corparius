"""`corparius plugin ...` had no test. It is the command that downloads and runs
third-party code, so the refusal paths matter more than the happy ones: an
unverified install that silently succeeded would be the whole curation model
failing quietly.

Everything runs under a temporary CORP_HOME, so no plugin is ever written to the
developer's real plugin directory.
"""
import json

import pytest

from app import cfg, cli, plugins


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CORP_PLUGINS_ENABLED", "true")
    monkeypatch.delenv("CORP_PLUGINS_ALLOW_UNVERIFIED", raising=False)
    cfg.invalidate()
    return tmp_path / "home"


def _install(home, name="acme-plugin", disabled=False):
    d = home / "plugins" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "acme_mod.py").write_text("def register(api):\n    pass\n", encoding="utf-8")
    (d / "corparius_plugin.json").write_text(json.dumps({
        "name": name, "version": "0.1.0", "api_version": 1,
        "entrypoint": "acme_mod:register", "kinds": ["tool"],
        "description": "an example",
    }), encoding="utf-8")
    if disabled:
        (d / ".disabled").write_text("", encoding="utf-8")
    return d


def test_list_says_none_when_nothing_is_installed(home, capsys):
    cli.main(["plugin", "list"])
    assert "installed: none" in capsys.readouterr().out


def test_list_warns_when_plugins_are_off(home, monkeypatch, capsys):
    monkeypatch.setenv("CORP_PLUGINS_ENABLED", "false")
    cfg.invalidate()
    cli.main(["plugin", "list"])
    assert "plugins are OFF" in capsys.readouterr().out


def test_list_marks_uncurated_plugins_as_unverified(home, capsys):
    """The registry is an allow-list; anything outside it is code the operator
    audited themselves, and the listing has to say so in as many words."""
    _install(home)
    cli.main(["plugin", "list"])
    out = capsys.readouterr().out
    assert "acme-plugin" in out and "UNVERIFIED" in out


def test_list_marks_a_disabled_plugin(home, capsys):
    _install(home, disabled=True)
    cli.main(["plugin", "list"])
    assert "disabled" in capsys.readouterr().out


def test_info_on_an_unknown_plugin_exits(home):
    with pytest.raises(SystemExit) as exc:
        cli.main(["plugin", "info", "nope"])
    assert "unknown plugin" in str(exc.value)


def test_info_reports_an_installed_plugin(home, capsys):
    _install(home)
    cli.main(["plugin", "info", "acme-plugin"])
    out = capsys.readouterr().out
    assert "installed: v0.1.0" in out and "UNVERIFIED" in out


def test_disable_then_enable_round_trips(home, capsys):
    path = _install(home)
    cli.main(["plugin", "disable", "acme-plugin"])
    assert "disabled 'acme-plugin'" in capsys.readouterr().out
    assert (path / ".disabled").exists()
    cli.main(["plugin", "enable", "acme-plugin"])
    assert "enabled 'acme-plugin'" in capsys.readouterr().out
    assert not (path / ".disabled").exists()


def test_enabling_an_unknown_plugin_exits(home):
    with pytest.raises(SystemExit) as exc:
        cli.main(["plugin", "enable", "nope"])
    assert "error:" in str(exc.value)


def test_remove_deletes_the_directory(home, capsys):
    path = _install(home)
    cli.main(["plugin", "remove", "acme-plugin"])
    assert "removed 'acme-plugin'" in capsys.readouterr().out
    assert not path.exists()


def test_removing_an_unknown_plugin_exits(home):
    with pytest.raises(SystemExit) as exc:
        cli.main(["plugin", "remove", "nope"])
    assert "error:" in str(exc.value)


def test_installing_off_registry_is_refused(home):
    """The curated path: a name that is not in plugins/registry.json cannot be
    installed, whatever the operator types."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["plugin", "install", "not-in-the-registry"])
    assert "error:" in str(exc.value)


def test_unverified_url_install_is_refused_without_the_optin(home, capsys):
    """--url runs code nobody audited. It must stay behind
    CORP_PLUGINS_ALLOW_UNVERIFIED, and it must say so out loud first."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["plugin", "install", "evil", "--url", "https://example.invalid/x.tar.gz"])
    assert "error:" in str(exc.value)
    assert "UNVERIFIED" in capsys.readouterr().out


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",       # urlopen honours this and reads a local file
    "http://example.invalid/x.tar.gz",
    "ftp://example.invalid/x.tar.gz",
    "/tmp/x.tar.gz",            # no scheme at all
])
def test_download_refuses_anything_but_https(home, monkeypatch, url):
    """urlopen happily opens file:// and ftp://, so without a scheme check
    `plugin install --url file:///etc/passwd` reads a local file and hands it to
    the extractor. Asserted at _download so both install paths are covered."""
    monkeypatch.setenv("CORP_PLUGINS_ALLOW_UNVERIFIED", "true")
    cfg.invalidate()
    with pytest.raises(plugins.PluginError, match="https"):
        plugins.install_from_url(url, "evil")


def test_download_refuses_an_oversized_archive(home, monkeypatch):
    """The read happens before the sha256 check, so a wrong or hostile URL could
    otherwise stream until the process dies and never reach the verification
    that would have rejected it."""
    class _Resp:
        def read(self, n=-1):
            return b"x" * n if n and n > 0 else b"x" * (plugins.MAX_ARCHIVE_BYTES + 1)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    with pytest.raises(plugins.PluginError, match="larger than"):
        plugins._download("https://example.invalid/x.tar.gz")


def test_extraction_refuses_an_interpreter_without_the_data_filter(tmp_path, monkeypatch):
    """tarfile's `filter=` was backported to 3.10.12 and 3.11.4, so the fallback
    branch is unreachable on any supported Python - which is exactly why it has
    to be driven directly rather than left to a CI leg that cannot reach it.
    The old behaviour was to extract without the filter; it now refuses."""
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("pkg/file.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))

    def _no_filter(self, *args, **kwargs):
        raise TypeError("extractall() got an unexpected keyword argument 'filter'")

    monkeypatch.setattr(tarfile.TarFile, "extractall", _no_filter)
    with pytest.raises(plugins.PluginError, match="too old"):
        plugins._safe_extract(buf.getvalue(), tmp_path / "dest")
