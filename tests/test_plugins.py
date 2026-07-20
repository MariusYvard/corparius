"""The plugin loader: off by default, curated by default, and isolated. These
tests exercise a drop-in plugin under a temporary home so nothing touches the
developer's machine, and restore the global registries afterwards."""

import json

import pytest

from corparius import cfg, company, llm, plugins, tools


@pytest.fixture
def clean_registries():
    """Snapshot the global registries the loader mutates, and restore them so a
    plugin loaded in one test never leaks into another."""
    prov = dict(llm.OPENAI_COMPAT_PROVIDERS)
    tls = dict(tools.TOOLS)
    tpls = list(company.TEMPLATES)
    loaded = set(plugins._loaded)
    yield
    llm.OPENAI_COMPAT_PROVIDERS.clear()
    llm.OPENAI_COMPAT_PROVIDERS.update(prov)
    tools.TOOLS.clear()
    tools.TOOLS.update(tls)
    company.TEMPLATES[:] = tpls
    plugins._loaded.clear()
    plugins._loaded.update(loaded)


_REGISTER = """
from corparius.tools import Tool
from corparius.models import ToolResult

def register(api):
    api.register_llm_provider("dummyprov", base="http://x/v1", key_env="DUMMY_KEY")
    api.register_tool(Tool("dummy_tool", "a plugin tool",
                           effect=lambda c, d: ToolResult(ok=True, output="ok")))
    api.register_template({"id": "dummytpl", "label_en": "Dummy", "label_fr": "Bidon"})
"""

_BROKEN = """
def register(api):
    raise RuntimeError("boom")
"""


def _install(home, name, code=_REGISTER, api_version=1, disabled=False, module=None):
    module = module or f"{name}_mod"
    d = home / "plugins" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{module}.py").write_text(code, encoding="utf-8")
    (d / "corparius_plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "0.1.0",
                "api_version": api_version,
                "entrypoint": f"{module}:register",
                "kinds": ["llm", "tool", "template"],
            }
        ),
        encoding="utf-8",
    )
    if disabled:
        (d / ".disabled").write_text("", encoding="utf-8")
    return d


def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("CORP_HOME", str(tmp_path / "home"))
    cfg.invalidate()
    return tmp_path / "home"


def test_nothing_loads_by_default(clean_registries, monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _install(home, "acme-plugin", module="p_default")
    monkeypatch.delenv("CORP_PLUGINS_ENABLED", raising=False)
    cfg.invalidate()
    assert plugins.load() == []
    assert "dummyprov" not in llm.OPENAI_COMPAT_PROVIDERS


def test_unverified_skipped_without_optin(clean_registries, monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _install(home, "acme-plugin", module="p_unverified")
    monkeypatch.setenv("CORP_PLUGINS_ENABLED", "true")
    monkeypatch.delenv("CORP_PLUGINS_ALLOW_UNVERIFIED", raising=False)
    cfg.invalidate()
    assert plugins.load() == []  # not in the curated registry
    assert "dummyprov" not in llm.OPENAI_COMPAT_PROVIDERS


def test_loads_with_optin_and_registers_everything(clean_registries, monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _install(home, "acme-plugin", module="p_ok")
    monkeypatch.setenv("CORP_PLUGINS_ENABLED", "true")
    monkeypatch.setenv("CORP_PLUGINS_ALLOW_UNVERIFIED", "true")
    cfg.invalidate()
    assert plugins.load() == ["acme-plugin"]
    assert llm.OPENAI_COMPAT_PROVIDERS["dummyprov"]["key_env"] == "DUMMY_KEY"
    assert "dummy_tool" in tools.TOOLS
    assert any(t["id"] == "dummytpl" for t in company.TEMPLATES)
    # Idempotent: a second load does not double-register.
    assert plugins.load() == []


def test_disabled_marker_skips(clean_registries, monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _install(home, "acme-plugin", module="p_disabled", disabled=True)
    monkeypatch.setenv("CORP_PLUGINS_ENABLED", "true")
    monkeypatch.setenv("CORP_PLUGINS_ALLOW_UNVERIFIED", "true")
    cfg.invalidate()
    assert plugins.load() == []


def test_api_version_mismatch_skipped(clean_registries, monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _install(home, "acme-plugin", module="p_apiver", api_version=999)
    monkeypatch.setenv("CORP_PLUGINS_ENABLED", "true")
    monkeypatch.setenv("CORP_PLUGINS_ALLOW_UNVERIFIED", "true")
    cfg.invalidate()
    assert plugins.load() == []


def test_broken_plugin_is_isolated(clean_registries, monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _install(home, "good", code=_REGISTER, module="p_good")
    _install(home, "bad", code=_BROKEN, module="p_bad")
    monkeypatch.setenv("CORP_PLUGINS_ENABLED", "true")
    monkeypatch.setenv("CORP_PLUGINS_ALLOW_UNVERIFIED", "true")
    cfg.invalidate()
    loaded = plugins.load()
    assert "good" in loaded and "bad" not in loaded  # the bad one is skipped, not fatal
    assert "dummyprov" in llm.OPENAI_COMPAT_PROVIDERS


def test_allowlist_limits_which_load(clean_registries, monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _install(home, "wanted", module="p_wanted")
    _install(home, "other", module="p_other")
    monkeypatch.setenv("CORP_PLUGINS_ENABLED", "true")
    monkeypatch.setenv("CORP_PLUGINS_ALLOW_UNVERIFIED", "true")
    monkeypatch.setenv("CORP_PLUGINS", "wanted")
    cfg.invalidate()
    assert plugins.load() == ["wanted"]


# --- install / manage (no real network: _download is monkeypatched) -----------


def _tarball(name: str, members: dict[str, str] | None = None) -> bytes:
    import io
    import tarfile

    root = f"{name}-main"
    files = members or {
        "corparius_plugin.json": json.dumps(
            {"name": name, "version": "1.0.0", "api_version": 1, "entrypoint": "p:register"}
        ),
        "p.py": "def register(api):\n    pass\n",
    }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(f"{root}/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_install_from_registry_ok(monkeypatch, tmp_path):
    import hashlib

    home = _home(monkeypatch, tmp_path)
    blob = _tarball("acme")
    monkeypatch.setattr(
        plugins,
        "registry_entries",
        lambda: [
            {
                "name": "acme",
                "repo": "https://github.com/x/acme",
                "ref": "v1",
                "sha256": hashlib.sha256(blob).hexdigest(),
            }
        ],
    )
    monkeypatch.setattr(plugins, "_download", lambda url, timeout=30.0: blob)
    path = plugins.install_from_registry("acme")
    assert path == home / "plugins" / "acme"
    assert (path / "corparius_plugin.json").is_file()


def test_install_from_registry_rejects_bad_sha256(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    blob = _tarball("acme")
    monkeypatch.setattr(
        plugins,
        "registry_entries",
        lambda: [
            {"name": "acme", "repo": "https://github.com/x/acme", "ref": "v1", "sha256": "deadbeef"}
        ],
    )
    monkeypatch.setattr(plugins, "_download", lambda url, timeout=30.0: blob)
    with pytest.raises(plugins.PluginError, match="sha256 mismatch"):
        plugins.install_from_registry("acme")


def test_install_unknown_registry_name(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(plugins, "registry_entries", lambda: [])
    with pytest.raises(plugins.PluginError, match="not in the verified registry"):
        plugins.install_from_registry("nope")


def test_safe_extract_rejects_traversal(tmp_path):
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in ("acme-main/corparius_plugin.json", "../escape.py"):  # 2nd escapes dest
            data = b"x"
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    with pytest.raises(plugins.PluginError):
        plugins._safe_extract(buf.getvalue(), tmp_path / "out")


def test_install_from_url_requires_optin(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    monkeypatch.delenv("CORP_PLUGINS_ALLOW_UNVERIFIED", raising=False)
    cfg.invalidate()
    with pytest.raises(plugins.PluginError, match="CORP_PLUGINS_ALLOW_UNVERIFIED"):
        plugins.install_from_url("http://x/a.tar.gz", "a")


def test_enable_disable_remove(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _install(home, "acme", module="p_mng")
    plugins.set_enabled("acme", False)
    assert (home / "plugins" / "acme" / ".disabled").exists()
    plugins.set_enabled("acme", True)
    assert not (home / "plugins" / "acme" / ".disabled").exists()
    plugins.remove("acme")
    assert not (home / "plugins" / "acme").exists()
    with pytest.raises(plugins.PluginError):
        plugins.remove("acme")
